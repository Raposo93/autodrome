import asyncio
import json
import os
import tempfile
import unittest
from unittest.mock import ANY, AsyncMock, MagicMock, patch

from autodrome.models.download_job import DownloadJob
from autodrome.services.cover_selection import CoverSelectionService
from autodrome.services.download_queue import DownloadQueueManager


PAYLOAD = {
    "playlist_url": "https://example.test/playlist",
    "artist": "Artist",
    "album": "Album",
    "release_id": "release-1",
    "track_count": 1,
}


class TestDownloadQueueManager(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp_directory = tempfile.TemporaryDirectory()
        self.state_path = os.path.join(self.temp_directory.name, "queue.json")
        self.downloader = AsyncMock()
        self.websocket_manager = AsyncMock()
        self.manager = DownloadQueueManager(
            self.downloader,
            self.websocket_manager,
            self.state_path,
        )

    async def asyncTearDown(self):
        await self.manager.stop()
        self.temp_directory.cleanup()

    async def test_success_transitions_are_persisted_and_broadcast(self):
        self.manager.start()

        job_id = await self.manager.enqueue(PAYLOAD)
        await asyncio.wait_for(self.manager.queue.join(), timeout=1)

        job = self.manager.snapshot()[0]
        self.assertEqual(job["job_id"], job_id)
        self.assertEqual(job["status"], "succeeded")
        self.assertIsNone(job["error"])
        self.downloader.download_and_tag.assert_awaited_once_with(
            progress=ANY,
            playlist_url=PAYLOAD["playlist_url"],
            artist=PAYLOAD["artist"],
            album=PAYLOAD["album"],
            release_id=PAYLOAD["release_id"],
            track_count=1,
        )
        broadcast_statuses = [
            call.args[0][0]["status"]
            for call in self.websocket_manager.broadcast.await_args_list
        ]
        self.assertEqual(broadcast_statuses, ["queued", "running", "succeeded"])

        with open(self.state_path, "r", encoding="utf-8") as state_file:
            persisted = json.load(state_file)
        self.assertEqual(persisted["jobs"][0]["status"], "succeeded")

    async def test_failure_stores_error_and_removes_running_state(self):
        self.downloader.download_and_tag.side_effect = RuntimeError("download failed")
        self.manager.start()

        job_id = await self.manager.enqueue(PAYLOAD)
        await asyncio.wait_for(self.manager.queue.join(), timeout=1)

        job = self.manager.snapshot()[0]
        self.assertEqual(job["job_id"], job_id)
        self.assertEqual(job["status"], "failed")
        self.assertEqual(job["error"], "download failed")
        final_broadcast = self.websocket_manager.broadcast.await_args_list[-1]
        self.assertEqual(final_broadcast.args[0][0]["status"], "failed")
        self.assertEqual(final_broadcast.args[0][0]["error"], "download failed")

    async def test_duplicate_payloads_are_independent_jobs(self):
        self.manager.start()

        first_job_id = await self.manager.enqueue(PAYLOAD)
        second_job_id = await self.manager.enqueue(PAYLOAD)
        await asyncio.wait_for(self.manager.queue.join(), timeout=1)

        self.assertNotEqual(first_job_id, second_job_id)
        jobs = self.manager.snapshot()
        self.assertEqual([job["status"] for job in jobs], ["succeeded", "succeeded"])
        self.assertEqual(self.downloader.download_and_tag.await_count, 2)

    async def test_start_creates_only_one_worker(self):
        first_task = self.manager.start()
        second_task = self.manager.start()

        self.assertIs(first_task, second_task)

    async def test_queued_job_resumes_once_after_restart(self):
        job_id = await self.manager.enqueue(PAYLOAD)
        restarted_downloader = AsyncMock()
        restarted_websocket = AsyncMock()
        restarted_manager = DownloadQueueManager(
            restarted_downloader,
            restarted_websocket,
            self.state_path,
        )
        try:
            restarted_manager.start()
            await asyncio.wait_for(restarted_manager.queue.join(), timeout=1)

            self.assertEqual(restarted_manager.snapshot()[0]["job_id"], job_id)
            self.assertEqual(restarted_manager.snapshot()[0]["status"], "succeeded")
            restarted_downloader.download_and_tag.assert_awaited_once()
        finally:
            await restarted_manager.stop()

    async def test_queued_job_can_be_cancelled_durably_and_is_skipped(self):
        job_id = await self.manager.enqueue(PAYLOAD)
        self.websocket_manager.broadcast.reset_mock()

        await self.manager.cancel_job(job_id)

        self.assertEqual(self.manager.snapshot()[0]["status"], "cancelled")
        self.assertEqual(self.persisted_jobs()[0]["status"], "cancelled")
        self.websocket_manager.broadcast.assert_awaited_once_with(
            self.manager.snapshot()
        )

        self.manager.start()
        await asyncio.wait_for(self.manager.queue.join(), timeout=1)
        self.downloader.download_and_tag.assert_not_awaited()

    async def test_cancelled_job_remains_terminal_after_restart(self):
        job_id = await self.manager.enqueue(PAYLOAD)
        await self.manager.cancel_job(job_id)
        restarted_downloader = AsyncMock()
        restarted_manager = DownloadQueueManager(
            restarted_downloader,
            AsyncMock(),
            self.state_path,
        )
        try:
            self.assertTrue(restarted_manager.queue.empty())
            self.assertEqual(
                restarted_manager.snapshot()[0]["status"], "cancelled"
            )
            restarted_manager.start()
            await asyncio.wait_for(restarted_manager.queue.join(), timeout=1)
            restarted_downloader.download_and_tag.assert_not_awaited()
        finally:
            await restarted_manager.stop()

    async def test_cancel_rejects_job_that_already_started(self):
        started = asyncio.Event()
        finish = asyncio.Event()

        async def download(**kwargs):
            started.set()
            await finish.wait()

        self.downloader.download_and_tag.side_effect = download
        self.manager.start()
        job_id = await self.manager.enqueue(PAYLOAD)
        await asyncio.wait_for(started.wait(), timeout=1)

        with self.assertRaisesRegex(ValueError, "Only queued jobs"):
            await self.manager.cancel_job(job_id)

        self.assertEqual(self.manager.snapshot()[0]["status"], "running")
        self.assertEqual(self.persisted_jobs()[0]["status"], "running")
        finish.set()
        await asyncio.wait_for(self.manager.queue.join(), timeout=1)

    async def test_cancel_persistence_failure_restores_queued_job(self):
        job_id = await self.manager.enqueue(PAYLOAD)
        self.websocket_manager.broadcast.reset_mock()

        with patch(
            "autodrome.services.download_queue.os.replace",
            side_effect=OSError("disk full"),
        ):
            with self.assertRaisesRegex(OSError, "disk full"):
                await self.manager.cancel_job(job_id)

        self.assertEqual(self.manager.snapshot()[0]["status"], "queued")
        self.assertEqual(self.persisted_jobs()[0]["status"], "queued")
        self.websocket_manager.broadcast.assert_not_awaited()
        self.manager.start()
        await asyncio.wait_for(self.manager.queue.join(), timeout=1)
        self.downloader.download_and_tag.assert_awaited_once()

    async def test_worker_continues_after_cancelled_job_is_cleared(self):
        first_started = asyncio.Event()
        finish_first = asyncio.Event()
        downloaded_albums = []

        async def download(album, **kwargs):
            downloaded_albums.append(album)
            if album == "First":
                first_started.set()
                await finish_first.wait()

        self.downloader.download_and_tag.side_effect = download
        first_id = await self.manager.enqueue({**PAYLOAD, "album": "First"})
        self.manager.start()
        await asyncio.wait_for(first_started.wait(), timeout=1)
        cancelled_id = await self.manager.enqueue({**PAYLOAD, "album": "Cancelled"})
        third_id = await self.manager.enqueue({**PAYLOAD, "album": "Third"})
        await self.manager.cancel_job(cancelled_id)
        self.assertEqual(await self.manager.clear_history(), 1)

        finish_first.set()
        await asyncio.wait_for(self.manager.queue.join(), timeout=1)

        self.assertEqual(downloaded_albums, ["First", "Third"])
        self.assertEqual(self.manager._jobs[first_id].status, "succeeded")
        self.assertNotIn(cancelled_id, self.manager._jobs)
        self.assertEqual(self.manager._jobs[third_id].status, "succeeded")

    async def test_running_job_becomes_interrupted_after_restart(self):
        job = DownloadJob.create(PAYLOAD)
        job.transition("running")
        with open(self.state_path, "w", encoding="utf-8") as state_file:
            json.dump({"version": 1, "jobs": [job.to_storage_dict()]}, state_file)

        restarted_downloader = AsyncMock()
        restarted_manager = DownloadQueueManager(
            restarted_downloader,
            AsyncMock(),
            self.state_path,
        )
        try:
            restarted_manager.start()
            await asyncio.sleep(0)

            recovered = restarted_manager.snapshot()[0]
            self.assertEqual(recovered["status"], "interrupted")
            self.assertIn("restarted", recovered["error"])
            restarted_downloader.download_and_tag.assert_not_awaited()
        finally:
            await restarted_manager.stop()

    async def test_terminal_jobs_are_preserved_without_rerunning(self):
        succeeded_job = DownloadJob.create(PAYLOAD)
        succeeded_job.transition("succeeded")
        failed_job = DownloadJob.create(PAYLOAD)
        failed_job.transition("failed", "original failure")
        with open(self.state_path, "w", encoding="utf-8") as state_file:
            json.dump(
                {
                    "version": 1,
                    "jobs": [
                        succeeded_job.to_storage_dict(),
                        failed_job.to_storage_dict(),
                    ],
                },
                state_file,
            )

        restarted_downloader = AsyncMock()
        restarted_manager = DownloadQueueManager(
            restarted_downloader,
            AsyncMock(),
            self.state_path,
        )
        try:
            restarted_manager.start()
            await asyncio.sleep(0)

            recovered = restarted_manager.snapshot()
            self.assertEqual(
                [job["status"] for job in recovered], ["succeeded", "failed"]
            )
            self.assertEqual(recovered[1]["error"], "original failure")
            restarted_downloader.download_and_tag.assert_not_awaited()
        finally:
            await restarted_manager.stop()

    def seed_history(self):
        jobs = {}
        for status in (
            "queued",
            "running",
            "succeeded",
            "failed",
            "interrupted",
            "cancelled",
        ):
            job = DownloadJob.create(PAYLOAD)
            job.transition(status, "original failure" if status == "failed" else None)
            self.manager._jobs[job.job_id] = job
            jobs[status] = job
        self.manager._persist_state()
        return jobs

    def persisted_jobs(self):
        with open(self.state_path, encoding="utf-8") as state_file:
            return json.load(state_file)["jobs"]

    async def test_clear_removes_only_terminal_jobs_and_persists_snapshot(self):
        jobs = self.seed_history()
        removed = await self.manager.clear_history()
        self.assertEqual(removed, 4)
        self.assertEqual(
            [job["job_id"] for job in self.manager.snapshot()],
            [jobs["queued"].job_id, jobs["running"].job_id],
        )
        self.assertEqual([job["status"] for job in self.persisted_jobs()], ["queued", "running"])
        self.websocket_manager.broadcast.assert_awaited_once_with(self.manager.snapshot())
        self.assertEqual(await self.manager.clear_history(), 0)

    async def test_delete_each_terminal_status_persists_and_survives_restart(self):
        jobs = self.seed_history()
        for status in ("succeeded", "failed", "interrupted", "cancelled"):
            job_id = jobs[status].job_id
            await self.manager.delete_job(job_id)
            self.assertNotIn(job_id, [j["job_id"] for j in self.persisted_jobs()])
            self.websocket_manager.broadcast.assert_awaited_with(self.manager.snapshot())
        restored = DownloadQueueManager(AsyncMock(), AsyncMock(), self.state_path)
        self.assertEqual(len(restored.snapshot()), 2)
        self.assertEqual([j["status"] for j in restored.snapshot()], ["queued", "interrupted"])

    async def test_retry_retains_original_and_reuses_payload_in_new_job(self):
        jobs = self.seed_history()
        for status in ("failed", "interrupted"):
            source = jobs[status]
            original = source.to_storage_dict()
            retry_id = await self.manager.retry_job(source.job_id)
            retry = self.manager._jobs[retry_id]
            self.assertNotEqual(retry_id, source.job_id)
            self.assertEqual(retry.payload, source.payload)
            self.assertIsNot(retry.payload, source.payload)
            self.assertEqual(retry.status, "queued")
            self.assertEqual(retry.retry_of, source.job_id)
            self.assertEqual(source.to_storage_dict(), original)
            self.assertIn(retry.to_storage_dict(), self.persisted_jobs())
            self.websocket_manager.broadcast.assert_awaited_with(self.manager.snapshot())
            with self.assertRaisesRegex(ValueError, "active retry"):
                await self.manager.retry_job(source.job_id)
        self.assertEqual(self.manager.queue.qsize(), 2)

    async def test_retried_payload_is_executed_once_after_restart(self):
        original = DownloadJob.create(PAYLOAD)
        original.transition("failed", "original failure")
        self.manager._jobs[original.job_id] = original
        self.manager._persist_state()
        retry_id = await self.manager.retry_job(original.job_id)
        restored = DownloadQueueManager(self.downloader, AsyncMock(), self.state_path)
        try:
            with self.assertRaisesRegex(ValueError, "active retry"):
                await restored.retry_job(original.job_id)
            restored.start()
            await asyncio.wait_for(restored.queue.join(), timeout=1)
            self.downloader.download_and_tag.assert_awaited_once_with(**PAYLOAD, progress=ANY)
            self.assertEqual(restored._jobs[retry_id].status, "succeeded")
            self.assertEqual(restored._jobs[retry_id].retry_of, original.job_id)
            self.assertEqual(restored._jobs[original.job_id].error, "original failure")
        finally:
            await restored.stop()

    async def test_active_jobs_reject_delete_and_retry_without_changes(self):
        jobs = self.seed_history()
        before = self.persisted_jobs()
        for status in ("queued", "running"):
            with self.assertRaisesRegex(ValueError, "finished jobs"):
                await self.manager.delete_job(jobs[status].job_id)
            with self.assertRaisesRegex(ValueError, "failed or interrupted"):
                await self.manager.retry_job(jobs[status].job_id)
        for status in ("succeeded", "cancelled"):
            with self.assertRaises(ValueError):
                await self.manager.retry_job(jobs[status].job_id)
        for action in (self.manager.delete_job, self.manager.retry_job):
            with self.assertRaises(KeyError):
                await action("missing")
        self.assertEqual(before, self.persisted_jobs())
        self.websocket_manager.broadcast.assert_not_awaited()

    async def test_persistence_failure_rolls_back_history_operations(self):
        jobs = self.seed_history()
        before = self.manager.snapshot()
        stored_before = self.persisted_jobs()
        actions = [
            lambda: self.manager.clear_history(),
            lambda: self.manager.delete_job(jobs["failed"].job_id),
            lambda: self.manager.retry_job(jobs["failed"].job_id),
        ]
        for action in actions:
            with patch("autodrome.services.download_queue.os.replace", side_effect=OSError("disk full")):
                with self.assertRaises(OSError):
                    await action()
            self.assertEqual(self.manager.snapshot(), before)
            self.assertEqual(self.persisted_jobs(), stored_before)
            self.assertTrue(self.manager.queue.empty())
            self.websocket_manager.broadcast.assert_not_awaited()
            self.assertEqual(os.listdir(self.temp_directory.name), ["queue.json"])

    async def test_clearing_history_during_download_preserves_active_work(self):
        started = asyncio.Event()
        finish = asyncio.Event()

        async def download(**kwargs):
            started.set()
            await finish.wait()

        finished = DownloadJob.create(PAYLOAD)
        finished.transition("failed", "old failure")
        self.manager._jobs[finished.job_id] = finished
        self.downloader.download_and_tag.side_effect = download
        self.manager.start()
        active_id = await self.manager.enqueue(PAYLOAD)
        await asyncio.wait_for(started.wait(), timeout=1)
        queued_id = await self.manager.enqueue(PAYLOAD)
        self.assertEqual(await self.manager.clear_history(), 1)
        self.assertEqual([j["job_id"] for j in self.manager.snapshot()], [active_id, queued_id])
        finish.set()
        await asyncio.wait_for(self.manager.queue.join(), timeout=1)
        self.assertEqual([j["status"] for j in self.manager.snapshot()], ["succeeded", "succeeded"])

    async def test_stop_marks_active_job_interrupted(self):
        download_started = asyncio.Event()

        async def wait_forever(**kwargs):
            download_started.set()
            await asyncio.Event().wait()

        self.downloader.download_and_tag.side_effect = wait_forever
        self.manager.start()
        await self.manager.enqueue(PAYLOAD)
        await asyncio.wait_for(download_started.wait(), timeout=1)

        await self.manager.stop()

        job = self.manager.snapshot()[0]
        self.assertEqual(job["status"], "interrupted")
        self.assertIn("stopped", job["error"])


if __name__ == "__main__":
    unittest.main()

class TestStorageRecovery(unittest.IsolatedAsyncioTestCase):
    setUp = TestDownloadQueueManager.setUp
    asyncTearDown = TestDownloadQueueManager.asyncTearDown
    persisted_jobs = TestDownloadQueueManager.persisted_jobs

    async def test_worker_retries_state_without_repeating_download(self):
        for target in ("running", "succeeded", "failed"):
            with self.subTest(target=target):
                await self.manager.stop()
                self.manager = DownloadQueueManager(
                    AsyncMock(), AsyncMock(), self.state_path + target
                )
                self.manager.STORAGE_RETRY_SECONDS = 0.001
                if target == "failed":
                    self.manager.downloader.download_and_tag.side_effect = RuntimeError("provider failed")
                first = await self.manager.enqueue(PAYLOAD)
                await self.manager.enqueue(PAYLOAD)
                persist = self.manager._persist_state
                broken = True
                attempted = asyncio.Event()

                def save():
                    if broken and self.manager._jobs[first].status == target:
                        attempted.set()
                        raise OSError("disk full")
                    persist()

                with patch.object(self.manager, "_persist_state", side_effect=save):
                    self.manager.start()
                    await asyncio.wait_for(attempted.wait(), 1)
                    self.assertFalse(self.manager.worker_task.done())
                    self.assertIn("disk full", self.manager.storage_error)
                    self.assertEqual(self.manager.queue.qsize(), 1)
                    with open(self.manager.state_path) as stream:
                        saved = json.load(stream)["jobs"]
                    self.assertEqual(saved[0]["status"], "queued" if target == "running" else "running")
                    self.assertEqual(saved[1]["status"], "queued")
                    self.assertEqual(self.manager.downloader.download_and_tag.await_count,
                                     0 if target == "running" else 1)
                    with self.assertRaisesRegex(OSError, "processing paused"):
                        await self.manager.enqueue(PAYLOAD)
                    broken = False
                    await asyncio.wait_for(self.manager.queue.join(), 1)
                self.assertIsNone(self.manager.storage_error)
                self.assertFalse(self.manager.worker_task.done())
                self.assertEqual(self.manager.downloader.download_and_tag.await_count, 2)
                with open(self.manager.state_path) as stream:
                    saved = json.load(stream)["jobs"]
                self.assertEqual([job["status"] for job in saved],
                                 ["failed", "failed"] if target == "failed" else ["succeeded", "succeeded"])
                if target == "failed":
                    self.assertEqual(saved[0]["error"], "provider failed")

    async def test_shutdown_storage_failure_leaves_uncertain_job_for_restart(self):
        started = asyncio.Event()

        async def download(**kwargs):
            started.set()
            await asyncio.Event().wait()

        self.downloader.download_and_tag.side_effect = download
        await self.manager.enqueue(PAYLOAD)
        self.manager.start()
        await asyncio.wait_for(started.wait(), 1)
        with patch.object(self.manager, "_persist_state", side_effect=OSError("disk full")):
            await asyncio.wait_for(self.manager.stop(), 1)
        self.assertIn("interrupted", self.manager.storage_error)
        self.assertEqual(self.persisted_jobs()[0]["status"], "running")
        restored = DownloadQueueManager(AsyncMock(), AsyncMock(), self.state_path)
        self.assertEqual(restored.snapshot()[0]["status"], "interrupted")
        self.assertTrue(restored.queue.empty())

class TestManualQueue(unittest.IsolatedAsyncioTestCase):
    async def test_manual_decision_survives_retry_and_restart(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, 'queue.json')
            payload = {**PAYLOAD, 'release_id': None, 'metadata_mode': 'manual',
                       'manual_confirmed': True, 'artist': 'Final Artist', 'album': 'Final Album'}
            manager = DownloadQueueManager(AsyncMock(), AsyncMock(), path)
            original = await manager.enqueue(payload)
            await manager._transition(manager._jobs[original], 'failed', 'temporary error')
            retry = await manager.retry_job(original)
            downloader = AsyncMock()
            restored = DownloadQueueManager(downloader, AsyncMock(), path)
            try:
                restored.start()
                await asyncio.wait_for(restored.queue.join(), 1)
                downloader.download_and_tag.assert_awaited_once_with(**payload, progress=ANY)
                self.assertEqual(restored._jobs[retry].payload, payload)
                self.assertEqual(restored._jobs[original].status, 'failed')
            finally:
                await restored.stop()


class TestCoverChoiceQueue(unittest.IsolatedAsyncioTestCase):
    async def test_alternative_cover_choice_survives_retry_and_restart(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "queue.json")
            payload = {
                **PAYLOAD,
                "cover_source": "youtube_thumbnail",
                "cover_id": "12345678-1234-1234-1234-123456789abc",
                "cover_url": "https://i.ytimg.com/vi/video/mqdefault.jpg",
            }
            manager = DownloadQueueManager(AsyncMock(), AsyncMock(), path)
            original = await manager.enqueue(payload)
            await manager._transition(
                manager._jobs[original], "failed", "temporary error"
            )
            retry = await manager.retry_job(original)
            downloader = AsyncMock()
            restored = DownloadQueueManager(downloader, AsyncMock(), path)
            try:
                restored.start()
                await asyncio.wait_for(restored.queue.join(), 1)
                downloader.download_and_tag.assert_awaited_once_with(
                    **payload, progress=ANY
                )
                self.assertEqual(restored._jobs[retry].payload, payload)
            finally:
                await restored.stop()

    async def test_startup_cleanup_preserves_every_recoverable_cover(self):
        with tempfile.TemporaryDirectory() as directory:
            now = 100_000
            state_path = os.path.join(directory, "queue.json")
            cover_directory = os.path.join(directory, "covers")
            os.mkdir(cover_directory)
            jobs = []
            cover_paths = {}
            for index, status in enumerate(
                ("queued", "running", "failed", "interrupted", "succeeded", "cancelled")
            ):
                cover_id = f"{index + 1:08d}-1234-1234-1234-123456789abc"
                job = DownloadJob.create({
                    **PAYLOAD,
                    "cover_source": "manual_upload",
                    "cover_id": cover_id,
                })
                job.transition(status)
                jobs.append(job)
                cover_path = os.path.join(cover_directory, f"{cover_id}.cover")
                with open(cover_path, "wb") as cover_file:
                    cover_file.write(status.encode())
                os.utime(cover_path, (now - 10, now - 10))
                cover_paths[status] = cover_path
            with open(state_path, "w", encoding="utf-8") as state_file:
                json.dump(
                    {"version": 1, "jobs": [job.to_storage_dict() for job in jobs]},
                    state_file,
                )
            selection = CoverSelectionService(
                http_client=AsyncMock(),
                embedder=MagicMock(),
                storage_dir=cover_directory,
                orphan_ttl_seconds=1,
                clock=lambda: now,
            )

            manager = DownloadQueueManager(
                AsyncMock(),
                AsyncMock(),
                state_path,
                cover_selection=selection,
            )

            for status in ("queued", "running", "failed", "interrupted"):
                self.assertTrue(os.path.exists(cover_paths[status]), status)
            for status in ("succeeded", "cancelled"):
                self.assertFalse(os.path.exists(cover_paths[status]), status)
            recovered_running = next(
                job for job in manager.snapshot()
                if job["cover_id"] == jobs[1].payload["cover_id"]
            )
            self.assertEqual(recovered_running["status"], "interrupted")

    async def test_cover_is_deleted_only_after_last_reference_stops_needing_it(self):
        with tempfile.TemporaryDirectory() as directory:
            state_path = os.path.join(directory, "queue.json")
            cover_directory = os.path.join(directory, "covers")
            os.mkdir(cover_directory)
            cover_id = "12345678-1234-1234-1234-123456789abc"
            cover_path = os.path.join(cover_directory, f"{cover_id}.cover")
            with open(cover_path, "wb") as cover_file:
                cover_file.write(b"shared bytes")
            selection = CoverSelectionService(
                http_client=AsyncMock(),
                embedder=MagicMock(),
                storage_dir=cover_directory,
            )
            manager = DownloadQueueManager(
                AsyncMock(), AsyncMock(), state_path, cover_selection=selection
            )
            payload = {
                **PAYLOAD,
                "cover_source": "manual_upload",
                "cover_id": cover_id,
            }
            first_id = await manager.enqueue(payload)
            second_id = await manager.enqueue(payload)

            await manager._transition(manager._jobs[first_id], "succeeded")
            self.assertTrue(os.path.exists(cover_path))

            await manager.cancel_job(second_id)
            self.assertFalse(os.path.exists(cover_path))

    async def test_failed_cover_survives_retry_and_restart_with_same_bytes(self):
        with tempfile.TemporaryDirectory() as directory:
            state_path = os.path.join(directory, "queue.json")
            cover_directory = os.path.join(directory, "covers")
            os.mkdir(cover_directory)
            cover_id = "12345678-1234-1234-1234-123456789abc"
            cover_path = os.path.join(cover_directory, f"{cover_id}.cover")
            original_bytes = b"exact prepared cover bytes"
            with open(cover_path, "wb") as cover_file:
                cover_file.write(original_bytes)
            selection = CoverSelectionService(
                http_client=AsyncMock(),
                embedder=MagicMock(),
                storage_dir=cover_directory,
            )
            manager = DownloadQueueManager(
                AsyncMock(), AsyncMock(), state_path, cover_selection=selection
            )
            payload = {
                **PAYLOAD,
                "cover_source": "manual_upload",
                "cover_id": cover_id,
            }
            original_id = await manager.enqueue(payload)
            await manager._transition(
                manager._jobs[original_id], "failed", "temporary failure"
            )
            retry_id = await manager.retry_job(original_id)

            restored = DownloadQueueManager(
                AsyncMock(), AsyncMock(), state_path, cover_selection=selection
            )

            self.assertEqual(restored._jobs[retry_id].payload["cover_id"], cover_id)
            with open(cover_path, "rb") as cover_file:
                self.assertEqual(cover_file.read(), original_bytes)

    async def test_cleanup_failure_does_not_change_persisted_success(self):
        with tempfile.TemporaryDirectory() as directory:
            state_path = os.path.join(directory, "queue.json")
            cover_selection = MagicMock()
            cover_selection.delete_unreferenced.side_effect = PermissionError(
                "read only"
            )
            manager = DownloadQueueManager(
                AsyncMock(),
                AsyncMock(),
                state_path,
                cover_selection=cover_selection,
            )
            payload = {
                **PAYLOAD,
                "cover_source": "manual_upload",
                "cover_id": "12345678-1234-1234-1234-123456789abc",
            }
            job_id = await manager.enqueue(payload)

            await manager._transition(manager._jobs[job_id], "succeeded")

            self.assertEqual(manager._jobs[job_id].status, "succeeded")
            with open(state_path, encoding="utf-8") as state_file:
                self.assertEqual(json.load(state_file)["jobs"][0]["status"], "succeeded")

    async def test_cover_is_not_released_when_terminal_state_cannot_persist(self):
        with tempfile.TemporaryDirectory() as directory:
            state_path = os.path.join(directory, "queue.json")
            cover_selection = MagicMock()
            manager = DownloadQueueManager(
                AsyncMock(),
                AsyncMock(),
                state_path,
                cover_selection=cover_selection,
            )
            payload = {
                **PAYLOAD,
                "cover_source": "manual_upload",
                "cover_id": "12345678-1234-1234-1234-123456789abc",
            }
            job_id = await manager.enqueue(payload)
            cover_selection.reset_mock()

            with patch.object(
                manager,
                "_persist_state",
                side_effect=OSError("disk full"),
            ):
                with self.assertRaisesRegex(OSError, "disk full"):
                    await manager._transition(manager._jobs[job_id], "succeeded")

            self.assertEqual(manager._jobs[job_id].status, "queued")
            cover_selection.delete_unreferenced.assert_not_called()

    async def test_deleting_retryable_history_releases_its_cover(self):
        with tempfile.TemporaryDirectory() as directory:
            state_path = os.path.join(directory, "queue.json")
            cover_directory = os.path.join(directory, "covers")
            os.mkdir(cover_directory)
            cover_id = "12345678-1234-1234-1234-123456789abc"
            cover_path = os.path.join(cover_directory, f"{cover_id}.cover")
            with open(cover_path, "wb") as cover_file:
                cover_file.write(b"cover")
            selection = CoverSelectionService(
                http_client=AsyncMock(),
                embedder=MagicMock(),
                storage_dir=cover_directory,
            )
            manager = DownloadQueueManager(
                AsyncMock(), AsyncMock(), state_path, cover_selection=selection
            )
            payload = {**PAYLOAD, "cover_id": cover_id}
            job_id = await manager.enqueue(payload)
            await manager._transition(manager._jobs[job_id], "failed", "failure")

            await manager.delete_job(job_id)

            self.assertFalse(os.path.exists(cover_path))

class TestQueueProgress(unittest.IsolatedAsyncioTestCase):
    setUp = TestDownloadQueueManager.setUp
    asyncTearDown = TestDownloadQueueManager.asyncTearDown
    persisted_jobs = TestDownloadQueueManager.persisted_jobs

    async def test_progress_is_visible_to_reconnections_and_persisted_on_failure(self):
        active = asyncio.Event()
        finish = asyncio.Event()

        async def download(progress, **kwargs):
            await progress('downloading', 1, 2, 0)
            active.set()
            await finish.wait()
            await progress('validating', None, None, None)
            raise RuntimeError('invalid tags')

        self.downloader.download_and_tag.side_effect = download
        await self.manager.enqueue(PAYLOAD)
        self.manager.start()
        await asyncio.wait_for(active.wait(), 1)
        self.assertEqual(self.manager.snapshot()[0]['progress']['current'], 1)
        finish.set()
        await asyncio.wait_for(self.manager.queue.join(), 1)
        self.assertEqual(self.persisted_jobs()[0]['progress']['phase'], 'validating')
        self.assertEqual(self.persisted_jobs()[0]['status'], 'failed')
        restored = DownloadQueueManager(AsyncMock(), AsyncMock(), self.state_path)
        self.assertEqual(restored.snapshot()[0]['progress']['phase'], 'validating')
