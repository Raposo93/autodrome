import asyncio
import json
import os
import tempfile
import time
from typing import Dict, List, Optional

from autodrome.controllers.downloader_controller import DownloaderController
from autodrome.logger import logger, safe_log_text
from autodrome.models.download_job import (
    DownloadJob,
    RETRYABLE_STATUSES,
    TERMINAL_STATUSES,
)
from autodrome.services.cover_selection import CoverSelectionService


class DownloadQueueManager:
    STORAGE_RETRY_SECONDS = 5
    REQUIRED_KEYS = {"playlist_url", "artist", "album", "release_id"}

    def __init__(
        self,
        downloader: DownloaderController,
        websocket_manager,
        state_path: str,
        cover_selection: Optional[CoverSelectionService] = None,
    ) -> None:
        self.queue: asyncio.Queue[str] = asyncio.Queue()
        self.downloader = downloader
        self.websocket_manager = websocket_manager
        self.state_path = os.path.abspath(state_path)
        self.cover_selection = cover_selection
        self.worker_task: Optional[asyncio.Task] = None
        self.storage_error: Optional[str] = None
        self._storage_failure_started_at: Optional[float] = None
        self._storage_retry_failures = 0
        self._recovered_running_jobs = 0
        self._snapshot_lock = asyncio.Lock()
        self._jobs: Dict[str, DownloadJob] = {}
        self._load_state()
        if self.cover_selection is not None:
            self.cover_selection.set_protected_cover_ids_provider(
                self.protected_cover_ids
            )
            self._cleanup_expired_covers()
        logger.info(
            "queue_started loaded=%s queued=%s interrupted=%s",
            len(self._jobs),
            sum(job.status == "queued" for job in self._jobs.values()),
            self._recovered_running_jobs,
        )

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
        logger.info(
            "job_enqueued job_id=%s mode=%s",
            job.job_id,
            payload.get("metadata_mode", "musicbrainz"),
        )
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

    async def cancel_job(self, job_id: str) -> None:
        job = self._get_job(job_id)
        if job.status != "queued":
            raise ValueError("Only queued jobs can be cancelled")
        await self._transition(job, "cancelled")
        logger.info("job_cancelled job_id=%s", job_id)

    async def retry_job(self, job_id: str) -> str:
        job = self._get_job(job_id)
        if job.status not in RETRYABLE_STATUSES:
            raise ValueError("Only failed or interrupted jobs can be retried")
        if any(
            candidate.retry_of == job_id and candidate.status in {"queued", "running"}
            for candidate in self._jobs.values()
        ):
            raise ValueError("This job already has an active retry")
        retry_id = await self.enqueue(job.payload, retry_of=job_id)
        logger.info("job_retry_created job_id=%s retry_of=%s", retry_id, job_id)
        return retry_id

    def _get_job(self, job_id: str) -> DownloadJob:
        if job_id not in self._jobs:
            raise KeyError("Download job not found")
        return self._jobs[job_id]

    async def _remove_jobs(self, job_ids: set[str]) -> None:
        previous_jobs = self._jobs
        removed_cover_ids = {
            job.payload.get("cover_id")
            for job_id, job in previous_jobs.items()
            if job_id in job_ids and job.payload.get("cover_id")
        }
        self._jobs = {
            job_id: job for job_id, job in previous_jobs.items() if job_id not in job_ids
        }
        try:
            self._persist_state()
        except Exception:
            self._jobs = previous_jobs
            raise
        self._delete_unreferenced_covers(removed_cover_ids)
        await self._broadcast_snapshot()

    def snapshot(self) -> List[Dict]:
        return [job.to_dict() for job in self._jobs.values()]

    def protected_cover_ids(self) -> set[str]:
        return {
            str(cover_id)
            for job in self._jobs.values()
            if (
                job.status not in TERMINAL_STATUSES
                or job.status in RETRYABLE_STATUSES
            )
            and (cover_id := job.payload.get("cover_id"))
        }

    async def _worker(self) -> None:
        logger.debug("queue_worker_started")
        while True:
            job_id = None
            job = None
            try:
                job_id = await self.queue.get()
                job = self._jobs.get(job_id)
                if job is None or job.status != "queued":
                    continue

                await self._save_worker_transition(job, "running")
                payload = job.payload
                concurrency = getattr(self.downloader, "download_concurrency", None)
                if not isinstance(concurrency, int):
                    concurrency = getattr(
                        getattr(self.downloader, "downloader", None),
                        "download_concurrency",
                        "unknown",
                    )
                logger.info(
                    "job_started job_id=%s tracks=%s concurrency=%s",
                    job_id,
                    payload.get("track_count", "unknown"),
                    concurrency,
                )

                async def progress(phase, current, total, completed):
                    previous_phase = (job.progress or {}).get("phase")
                    job.progress = {"phase": phase, "current": current,
                                    "total": total, "completed": completed}
                    if previous_phase != phase:
                        await self._save_worker_transition(job, job.status)
                    else:
                        await self._broadcast_snapshot()

                try:
                    await self.downloader.download_and_tag(
                        progress=progress,
                        playlist_url=payload["playlist_url"],
                        artist=payload["artist"],
                        album=payload["album"],
                        release_id=payload["release_id"],
                        track_count=payload.get("track_count"),
                        **{
                            key: payload[key]
                            for key in ("cover_source", "cover_id", "cover_url")
                            if key in payload
                        },
                        **({"metadata_mode": "manual", "manual_confirmed": payload.get("manual_confirmed", False)}
                           if payload.get("metadata_mode") == "manual" else {}),
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
                    await self._save_worker_transition(job, "failed", str(error))
                    phase = (job.progress or {}).get("phase", "unknown")
                    logger.error(
                        "job_failed job_id=%s phase=%s reason=%s",
                        job_id,
                        phase,
                        safe_log_text(error),
                    )
                else:
                    await self._save_worker_transition(job, "succeeded")
                    logger.info("job_succeeded job_id=%s", job_id)
            finally:
                if job_id is not None:
                    self.queue.task_done()

    def processing_status(self) -> Dict:
        return {"type": "queue_processing", "paused": self.storage_error is not None,
                "error": self.storage_error}

    async def _report_storage_error(self, job, status, error) -> None:
        message = (
            f"Queue processing paused: could not save {status} for job {job.job_id}: "
            f"{error}. Fix queue storage; saving will retry automatically."
        )
        if self.storage_error is None:
            self.storage_error = message
            self._storage_failure_started_at = time.monotonic()
            self._storage_retry_failures = 0
            logger.error(
                "queue_storage_paused job_id=%s transition=%s reason=%s",
                job.job_id,
                status,
                safe_log_text(error),
            )
            await self.websocket_manager.broadcast(self.processing_status())
        else:
            self._storage_retry_failures += 1
            logger.debug(
                "queue_storage_retry_failed job_id=%s transition=%s attempt=%s",
                job.job_id,
                status,
                self._storage_retry_failures,
            )

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
                    downtime = (
                        time.monotonic() - self._storage_failure_started_at
                        if self._storage_failure_started_at is not None
                        else 0
                    )
                    self.storage_error = None
                    logger.info(
                        "queue_storage_recovered downtime_s=%.2f retries=%s",
                        downtime,
                        self._storage_retry_failures,
                    )
                    self._storage_failure_started_at = None
                    self._storage_retry_failures = 0
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
        cover_id = job.payload.get("cover_id")
        if cover_id:
            self._delete_unreferenced_covers({cover_id})
        await self._broadcast_snapshot()

    def _cleanup_expired_covers(self) -> None:
        if self.cover_selection is None:
            return
        try:
            self.cover_selection.cleanup_expired(self.protected_cover_ids())
        except Exception as error:
            logger.warning(
                "prepared_cover_cleanup_failed reason=%s",
                safe_log_text(error),
            )

    def _delete_unreferenced_covers(self, cover_ids: set[str]) -> None:
        if self.cover_selection is None or not cover_ids:
            return
        try:
            self.cover_selection.delete_unreferenced(
                cover_ids,
                self.protected_cover_ids(),
            )
        except Exception as error:
            logger.warning(
                "prepared_cover_delete_failed reason=%s",
                safe_log_text(error),
            )

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
                self._recovered_running_jobs += 1
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
