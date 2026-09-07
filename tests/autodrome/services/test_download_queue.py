import asyncio
import json
import os
import tempfile
import unittest
from unittest.mock import AsyncMock

from autodrome.models.download_job import DownloadJob
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
