import asyncio
import json
import os
import tempfile
from typing import Dict, List, Optional

from autodrome.controllers.downloader_controller import DownloaderController
from autodrome.logger import logger
from autodrome.models.download_job import DownloadJob, TERMINAL_STATUSES, RETRYABLE_STATUSES


class DownloadQueueManager:
    STORAGE_RETRY_SECONDS = 5
    REQUIRED_KEYS = {"playlist_url", "artist", "album", "release_id"}

    def __init__(
        self,
        downloader: DownloaderController,
        websocket_manager,
        state_path: str,
    ) -> None:
        self.queue: asyncio.Queue[str] = asyncio.Queue()
        self.downloader = downloader
        self.websocket_manager = websocket_manager
        self.state_path = os.path.abspath(state_path)
        self.worker_task: Optional[asyncio.Task] = None
        self.storage_error: Optional[str] = None
        self._snapshot_lock = asyncio.Lock()
        self._jobs: Dict[str, DownloadJob] = {}
        self._load_state()

    def start(self) -> asyncio.Task:
        if self.worker_task is None or self.worker_task.done():
            self.worker_task = asyncio.create_task(self._worker())
        return self.worker_task

    async def stop(self) -> None:
        if self.worker_task is None:
            return

        if not self.worker_task.done():
            self.worker_task.cancel()
            try:
                await self.worker_task
            except asyncio.CancelledError:
                pass
        self.worker_task = None

    async def enqueue(self, payload: Dict, *, retry_of: Optional[str] = None) -> str:
        if self.storage_error:
            raise OSError(self.storage_error)
        if missing := self.REQUIRED_KEYS - payload.keys():
            raise ValueError(f"Payload is missing required keys: {sorted(missing)}")

        job = DownloadJob.create(payload)
        job.retry_of = retry_of
        self._jobs[job.job_id] = job
        try:
            self._persist_state()
        except Exception:
            del self._jobs[job.job_id]
            raise
        self.queue.put_nowait(job.job_id)
        await self._broadcast_snapshot()
        logger.info(f"Playlist enqueued as job {job.job_id}: {payload.get('album')}")
        return job.job_id

    async def clear_history(self) -> int:
        job_ids = {
            job.job_id for job in self._jobs.values()
            if job.status in TERMINAL_STATUSES
        }
        await self._remove_jobs(job_ids)
        return len(job_ids)

    async def delete_job(self, job_id: str) -> None:
        job = self._get_job(job_id)
        if job.status not in TERMINAL_STATUSES:
            raise ValueError("Only finished jobs can be deleted")
        await self._remove_jobs({job_id})

    async def retry_job(self, job_id: str) -> str:
        job = self._get_job(job_id)
        if job.status not in RETRYABLE_STATUSES:
            raise ValueError("Only failed or interrupted jobs can be retried")
        if any(
            candidate.retry_of == job_id and candidate.status in {"queued", "running"}
            for candidate in self._jobs.values()
        ):
            raise ValueError("This job already has an active retry")
        return await self.enqueue(job.payload, retry_of=job_id)

    def _get_job(self, job_id: str) -> DownloadJob:
        if job_id not in self._jobs:
            raise KeyError("Download job not found")
        return self._jobs[job_id]

    async def _remove_jobs(self, job_ids: set[str]) -> None:
        previous_jobs = self._jobs
        self._jobs = {
            job_id: job for job_id, job in previous_jobs.items() if job_id not in job_ids
        }
        try:
            self._persist_state()
        except Exception:
            self._jobs = previous_jobs
            raise
        await self._broadcast_snapshot()

    def snapshot(self) -> List[Dict]:
        return [job.to_dict() for job in self._jobs.values()]

    async def _worker(self) -> None:
        logger.info("DownloadQueueManager: worker started")
        while True:
            job_id = None
            job = None
            try:
                job_id = await self.queue.get()
                job = self._jobs[job_id]
                if job.status != "queued":
                    continue

                await self._save_worker_transition(job, "running")
                payload = job.payload
                try:
                    await self.downloader.download_and_tag(
                        playlist_url=payload["playlist_url"],
                        artist=payload["artist"],
                        album=payload["album"],
                        release_id=payload["release_id"],
                        track_count=payload.get("track_count"),
                    )
                except asyncio.CancelledError:
                    # Shutdown must not wait indefinitely for broken storage.
                    try:
                        await self._transition(
                            job, "interrupted", "Worker stopped before the download completed"
                        )
                    except OSError as error:
                        await self._report_storage_error(job, "interrupted", str(error))
                    raise
                except Exception as error:
                    logger.error(f"Error processing download job {job_id}: {error}")
                    await self._save_worker_transition(job, "failed", str(error))
                else:
                    await self._save_worker_transition(job, "succeeded")
                    logger.info(f"Completed download job {job_id}")
            finally:
                if job_id is not None:
                    self.queue.task_done()

    def processing_status(self) -> Dict:
        return {"type": "queue_processing", "paused": self.storage_error is not None,
                "error": self.storage_error}

    async def _report_storage_error(self, job, status, error) -> None:
        self.storage_error = (
            f"Queue processing paused: could not save {status} for job {job.job_id}: "
            f"{error}. Fix queue storage; saving will retry automatically."
        )
        logger.error(self.storage_error)
        await self.websocket_manager.broadcast(self.processing_status())

    async def _save_worker_transition(self, job, status, error=None) -> None:
        # Retry only this state write, never the download that preceded it.
        while True:
            try:
                await self._transition(job, status, error)
            except OSError as storage_error:
                await self._report_storage_error(job, status, str(storage_error))
                await asyncio.sleep(self.STORAGE_RETRY_SECONDS)
            else:
                if self.storage_error is not None:
                    self.storage_error = None
                    await self.websocket_manager.broadcast(self.processing_status())
                return

    async def _transition(
        self,
        job: DownloadJob,
        status: str,
        error: Optional[str] = None,
    ) -> None:
        previous_state = (job.status, job.updated_at, job.error)
        job.transition(status, error)
        try:
            self._persist_state()
        except Exception:
            job.status, job.updated_at, job.error = previous_state
            raise
        await self._broadcast_snapshot()

    async def _broadcast_snapshot(self) -> None:
        async with self._snapshot_lock:
            await self.websocket_manager.broadcast(self.snapshot())

    def _load_state(self) -> None:
        if not os.path.exists(self.state_path):
            return

        try:
            with open(self.state_path, "r", encoding="utf-8") as state_file:
                data = json.load(state_file)
            if data.get("version") != 1:
                raise ValueError(f"Unsupported queue state version: {data.get('version')}")
            stored_jobs = data["jobs"]
            if not isinstance(stored_jobs, list):
                raise ValueError("Persisted queue jobs must be a list")
        except Exception as e:
            raise RuntimeError(
                f"Could not load download queue state from {self.state_path}"
            ) from e

        recovered_running_job = False
        for stored_job in stored_jobs:
            job = DownloadJob.from_dict(stored_job)
            if job.job_id in self._jobs:
                raise ValueError(f"Duplicate persisted job ID: {job.job_id}")

            if job.status == "running":
                job.transition(
                    "interrupted",
                    "Application restarted before the download completed",
                )
                recovered_running_job = True
            elif job.status == "queued":
                self.queue.put_nowait(job.job_id)

            self._jobs[job.job_id] = job

        if recovered_running_job:
            self._persist_state()

    def _persist_state(self) -> None:
        state_directory = os.path.dirname(self.state_path)
        os.makedirs(state_directory, exist_ok=True)
        descriptor, temp_path = tempfile.mkstemp(
            prefix=".autodrome-queue-",
            suffix=".tmp",
            dir=state_directory,
        )
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as state_file:
                json.dump(
                    {
                        "version": 1,
                        "jobs": [
                            job.to_storage_dict() for job in self._jobs.values()
                        ],
                    },
                    state_file,
                    indent=2,
                )
                state_file.flush()
                os.fsync(state_file.fileno())
            os.replace(temp_path, self.state_path)
        except Exception:
            if os.path.exists(temp_path):
                os.unlink(temp_path)
            raise
