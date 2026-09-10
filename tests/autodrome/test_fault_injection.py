import asyncio
import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp

from autodrome.controllers.downloader_controller import DownloaderController
from autodrome.http_client_async import AsyncHttpClient, UpstreamServiceError
from autodrome.models.release import Release
from autodrome.models.track import Track
from autodrome.services.download_queue import DownloadQueueManager
from autodrome.yt_downloader import (
    PlaylistDownloadError,
    TrackDownloadError,
    YTDownloader,
)
from tests.fault_injection import FaultInjector, ScriptedCall


PAYLOAD = {
    "playlist_url": "https://example.test/playlist",
    "artist": "Artist",
    "album": "Album",
    "release_id": "release-1",
    "track_count": 1,
}


def response_context(response):
    context = MagicMock()
    context.__aenter__ = AsyncMock(return_value=response)
    context.__aexit__ = AsyncMock(return_value=None)
    return context


def http_response(status=200, payload=None):
    response = MagicMock()
    if status >= 400:
        response.raise_for_status.side_effect = aiohttp.ClientResponseError(
            request_info=MagicMock(),
            history=(),
            status=status,
            message="injected upstream response",
        )
    response.json = AsyncMock(return_value=payload or {"status": "ok"})
    return response


class TestFaultHelpers(unittest.TestCase):
    def test_named_faults_replay_the_same_point_and_history(self):
        histories = []
        for _ in range(2):
            faults = FaultInjector(
                "repeatable-write",
                {"queue.persist.running": {2: OSError}},
            )
            faults.hit("queue.persist.running")
            with self.assertRaisesRegex(
                OSError,
                "repeatable-write.*queue.persist.running.*hit 2",
            ):
                faults.hit("queue.persist.running")
            faults.hit("queue.persist.running")
            faults.assert_complete()
            histories.append(faults.history)

        self.assertEqual(histories[0], histories[1])


class TestQueueFaultInjection(unittest.IsolatedAsyncioTestCase):
    async def test_running_persist_failure_blocks_download_until_state_is_durable(self):
        with tempfile.TemporaryDirectory() as directory:
            state_path = os.path.join(directory, "queue.json")
            downloader = AsyncMock()
            manager = DownloadQueueManager(downloader, AsyncMock(), state_path)
            manager.STORAGE_RETRY_SECONDS = 37
            first_job = await manager.enqueue(PAYLOAD)
            await manager.enqueue({**PAYLOAD, "album": "Second"})
            persist_state = manager._persist_state
            retry_waiting = asyncio.Event()
            allow_retry = asyncio.Event()
            faults = FaultInjector(
                "initial-running-transition",
                {"queue.persist.running": {1: OSError}},
            )

            def persist_with_fault():
                if manager._jobs[first_job].status == "running":
                    faults.hit("queue.persist.running")
                persist_state()

            async def controlled_retry(delay):
                self.assertEqual(delay, 37)
                retry_waiting.set()
                await allow_retry.wait()

            try:
                with (
                    patch.object(
                        manager,
                        "_persist_state",
                        side_effect=persist_with_fault,
                    ),
                    patch(
                        "autodrome.services.download_queue.asyncio.sleep",
                        side_effect=controlled_retry,
                    ),
                ):
                    manager.start()
                    await asyncio.wait_for(retry_waiting.wait(), timeout=1)

                    downloader.download_and_tag.assert_not_awaited()
                    self.assertFalse(manager.worker_task.done())
                    self.assertEqual(manager.queue.qsize(), 1)
                    self.assertIn("queue.persist.running", manager.storage_error)
                    with open(state_path, encoding="utf-8") as state_file:
                        jobs = json.load(state_file)["jobs"]
                    self.assertEqual([job["status"] for job in jobs], ["queued", "queued"])
                    with self.assertRaisesRegex(OSError, "processing paused"):
                        await manager.enqueue({**PAYLOAD, "album": "Blocked"})

                    allow_retry.set()
                    await asyncio.wait_for(manager.queue.join(), timeout=1)

                faults.assert_complete()
                self.assertIsNone(manager.storage_error)
                self.assertEqual(downloader.download_and_tag.await_count, 2)
                self.assertEqual(
                    [job["status"] for job in manager.snapshot()],
                    ["succeeded", "succeeded"],
                )
            finally:
                allow_retry.set()
                await manager.stop()

    async def test_published_album_is_not_repeated_after_final_state_write_fails(self):
        with tempfile.TemporaryDirectory() as directory:
            state_path = os.path.join(directory, "queue.json")
            published_album = Path(directory) / "library" / "Artist" / "Album"
            downloader = AsyncMock()

            async def publish_album(**kwargs):
                if published_album.exists():
                    raise AssertionError("published album would be overwritten")
                published_album.mkdir(parents=True)
                (published_album / "complete.marker").write_text(
                    "complete", encoding="utf-8"
                )

            downloader.download_and_tag.side_effect = publish_album
            manager = DownloadQueueManager(downloader, AsyncMock(), state_path)
            job_id = await manager.enqueue(PAYLOAD)
            persist_state = manager._persist_state
            retry_waiting = asyncio.Event()
            faults = FaultInjector(
                "published-before-succeeded-write",
                {"queue.persist.succeeded": {1: OSError}},
            )

            def persist_with_fault():
                if manager._jobs[job_id].status == "succeeded":
                    faults.hit("queue.persist.succeeded")
                persist_state()

            async def hold_storage_retry(delay):
                retry_waiting.set()
                await asyncio.Event().wait()

            with (
                patch.object(
                    manager,
                    "_persist_state",
                    side_effect=persist_with_fault,
                ),
                patch(
                    "autodrome.services.download_queue.asyncio.sleep",
                    side_effect=hold_storage_retry,
                ),
            ):
                manager.start()
                await asyncio.wait_for(retry_waiting.wait(), timeout=1)
                self.assertTrue((published_album / "complete.marker").is_file())
                downloader.download_and_tag.assert_awaited_once()
                with open(state_path, encoding="utf-8") as state_file:
                    persisted = json.load(state_file)["jobs"][0]
                self.assertEqual(persisted["status"], "running")
                self.assertIn("queue.persist.succeeded", manager.storage_error)
                await manager.stop()

            faults.assert_complete()
            restarted_downloader = AsyncMock()
            restarted = DownloadQueueManager(
                restarted_downloader,
                AsyncMock(),
                state_path,
            )
            try:
                self.assertEqual(restarted.snapshot()[0]["status"], "interrupted")
                self.assertTrue(restarted.queue.empty())
                restarted.start()
                await asyncio.sleep(0)
                restarted_downloader.download_and_tag.assert_not_awaited()
                self.assertEqual(
                    (published_album / "complete.marker").read_text(encoding="utf-8"),
                    "complete",
                )
            finally:
                await restarted.stop()

    async def test_queue_replace_fault_rolls_back_without_temp_or_phantom_job(self):
        for run in range(2):
            with self.subTest(run=run), tempfile.TemporaryDirectory() as directory:
                manager = DownloadQueueManager(
                    AsyncMock(),
                    AsyncMock(),
                    os.path.join(directory, "queue.json"),
                )
                real_replace = os.replace
                faults = FaultInjector(
                    "atomic-queue-replace",
                    {"queue.persist.os_replace": {1: OSError}},
                )

                def replace_with_fault(source, destination):
                    faults.hit("queue.persist.os_replace")
                    real_replace(source, destination)

                with patch(
                    "autodrome.services.download_queue.os.replace",
                    side_effect=replace_with_fault,
                ):
                    with self.assertRaisesRegex(
                        OSError,
                        "atomic-queue-replace.*queue.persist.os_replace",
                    ):
                        await manager.enqueue(PAYLOAD)

                faults.assert_complete()
                self.assertEqual(manager.snapshot(), [])
                self.assertTrue(manager.queue.empty())
                self.assertEqual(os.listdir(directory), [])


class TestDownloadFaultInjection(unittest.IsolatedAsyncioTestCase):
    async def test_track_four_failure_never_reaches_album_publication(self):
        failures = []
        for _ in range(2):
            with tempfile.TemporaryDirectory() as staging_directory:
                faults = FaultInjector(
                    "stable-track-four",
                    {"download.track.4": {1: RuntimeError}},
                )
                downloader = YTDownloader(track_download_attempts=1)
                track_urls = [
                    f"https://youtube.test/track-{index}"
                    for index in range(1, 6)
                ]
                downloader.get_playlist_track_urls = AsyncMock(return_value=track_urls)
                downloader._check_downloaded_files = AsyncMock()

                async def download_track(url, destination, index, hook):
                    try:
                        faults.hit(f"download.track.{index}")
                    except RuntimeError as error:
                        raise TrackDownloadError(index, url, str(error)) from error

                downloader.download_track = AsyncMock(side_effect=download_track)
                organizer = MagicMock()
                organizer.create_staging_folder.return_value.__enter__.return_value = (
                    staging_directory
                )
                metadata = MagicMock()
                metadata.get_release = AsyncMock(
                    return_value=Release(
                        release_id="release-1",
                        title="Album",
                        date="2026",
                        artist="Artist",
                        cover_url=None,
                        tracks=[
                            Track(index, f"Track {index}")
                            for index in range(1, 6)
                        ],
                    )
                )
                metadata.get_cover_art = AsyncMock(return_value=None)
                controller = DownloaderController(downloader, organizer, metadata)

                with self.assertRaises(PlaylistDownloadError) as raised:
                    await controller.download_and_tag(
                        playlist_url="https://example.test/playlist",
                        artist="Artist",
                        album="Album",
                        release_id="release-1",
                        track_count=5,
                    )

                faults.assert_complete()
                failures.append(raised.exception.failures)
                self.assertEqual(
                    [
                        call.args[2]
                        for call in downloader.download_track.await_args_list
                    ],
                    [1, 2, 3, 4, 5],
                )
                downloader._check_downloaded_files.assert_not_awaited()
                metadata.get_cover_art.assert_not_awaited()
                organizer.tag_and_rename.assert_not_called()
                organizer.validate_album.assert_not_called()
                organizer.move_to_library.assert_not_called()

        self.assertEqual(failures[0], failures[1])
        self.assertEqual(failures[0][0][:2], (4, "https://youtube.test/track-4"))
        self.assertIn("stable-track-four", failures[0][0][2])


class TestMusicBrainzFaultSequences(unittest.IsolatedAsyncioTestCase):
    def client_for(self, sequence):
        session = MagicMock()
        session.get.side_effect = sequence
        now = [0.0]
        delays = []

        async def controlled_sleep(delay):
            delays.append(delay)
            now[0] += delay

        client = AsyncHttpClient(
            session=session,
            clock=lambda: now[0],
            sleep=controlled_sleep,
            settings=SimpleNamespace(
                musicbrainz_timeout_seconds=10,
                musicbrainz_max_attempts=3,
                musicbrainz_retry_base_seconds=0.25,
            ),
        )
        return client, delays

    async def test_429_429_ok_sequence_is_exact_and_repeatable(self):
        observed = []
        for _ in range(2):
            sequence = ScriptedCall(
                "musicbrainz-rate-limit-recovery",
                "musicbrainz.request",
                [
                    response_context(http_response(429)),
                    response_context(http_response(429)),
                    response_context(http_response(payload={"releases": []})),
                ],
            )
            client, delays = self.client_for(sequence)

            result = await client.get(
                "https://musicbrainz.org/ws/2/release/",
                context="searching releases",
            )

            sequence.assert_complete()
            observed.append((result, delays))

        self.assertEqual(observed[0], observed[1])
        self.assertEqual(observed[0][0], {"releases": []})
        self.assertEqual(observed[0][1], [0.25, 0.75, 0.5, 0.5])

    async def test_timeouts_exhaust_the_exact_script(self):
        sequence = ScriptedCall(
            "musicbrainz-timeout",
            "musicbrainz.request",
            [asyncio.TimeoutError(), asyncio.TimeoutError(), asyncio.TimeoutError()],
        )
        client, _ = self.client_for(sequence)

        with self.assertRaises(UpstreamServiceError) as raised:
            await client.get(
                "https://musicbrainz.org/ws/2/release/release-1",
                context="loading release release-1",
            )

        sequence.assert_complete()
        self.assertEqual(raised.exception.reason, "request timed out")
        self.assertEqual(raised.exception.attempts, 3)

    async def test_definitive_error_stops_without_consuming_extra_outcomes(self):
        sequence = ScriptedCall(
            "musicbrainz-definitive-error",
            "musicbrainz.request",
            [response_context(http_response(400))],
        )
        client, delays = self.client_for(sequence)

        with self.assertRaises(UpstreamServiceError) as raised:
            await client.get(
                "https://musicbrainz.org/ws/2/release/release-1",
                context="loading release release-1",
            )

        sequence.assert_complete()
        self.assertEqual(raised.exception.status, 400)
        self.assertEqual(raised.exception.attempts, 1)
        self.assertEqual(delays, [])
