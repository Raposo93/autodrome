import asyncio
import tempfile
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from autodrome.yt_downloader import (
    PlaylistDownloadError,
    TrackDownloadError,
    YTDownloader,
)
from tests.fixtures import generated_playlist, playlist_from_hell


class TestYTDownloader(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.downloader = YTDownloader()

    async def test_download_playlist_downloads_track_urls_sequentially(self):
        self.downloader.get_playlist_track_urls = AsyncMock(
            return_value=[
                "https://youtube.test/watch?v=first",
                "https://youtube.test/watch?v=second",
            ]
        )
        self.downloader._download_track_blocking = MagicMock()
        self.downloader._check_downloaded_files = AsyncMock()

        with patch(
            "autodrome.yt_downloader.asyncio.to_thread", new_callable=AsyncMock
        ) as to_thread, tempfile.TemporaryDirectory() as destination:
            to_thread.side_effect = lambda function, *args: function(*args)
            playlist_url = "https://youtube.com/playlist?list=123"

            await self.downloader.download_playlist(playlist_url, destination, total=2)

        self.downloader.get_playlist_track_urls.assert_awaited_once_with(playlist_url)
        calls = self.downloader._download_track_blocking.call_args_list
        self.assertEqual(
            [call.args[0] for call in calls],
            [
                "https://youtube.test/watch?v=first",
                "https://youtube.test/watch?v=second",
            ],
        )
        self.assertEqual([call.args[2] for call in calls], [1, 2])
        self.downloader._check_downloaded_files.assert_awaited_once()

    async def test_download_track_is_reusable_and_owns_its_retries(self):
        downloader = YTDownloader(track_download_attempts=2)
        downloader._download_track_blocking = MagicMock(
            side_effect=[RuntimeError("temporary"), None]
        )
        hook = MagicMock()

        with patch(
            "autodrome.yt_downloader.asyncio.to_thread", new_callable=AsyncMock
        ) as to_thread, tempfile.TemporaryDirectory() as destination:
            to_thread.side_effect = lambda function, *args: function(*args)

            await downloader.download_track(
                "https://youtube.test/track", destination, 7, hook
            )

        self.assertEqual(downloader._download_track_blocking.call_count, 2)
        self.assertEqual(
            downloader._download_track_blocking.call_args.args[2],
            7,
        )

    async def test_manifest_mismatch_aborts_before_any_download(self):
        for urls, total in [(["first"], 2), (["first", "second"], 1), ([], 2)]:
            with self.subTest(urls=urls, total=total):
                self.downloader.get_playlist_track_urls = AsyncMock(return_value=urls)
                self.downloader.download_track = AsyncMock()
                self.downloader._check_downloaded_files = AsyncMock()
                with self.assertRaisesRegex(
                    RuntimeError, f"expected {total} tracks, extractable {len(urls)}"
                ):
                    await self.downloader.download_playlist("playlist", "unused", total)
                self.downloader.download_track.assert_not_awaited()
                self.downloader._check_downloaded_files.assert_not_awaited()

    @patch("autodrome.yt_downloader.YoutubeDL")
    async def test_playlist_from_hell_keeps_identity_and_fails_preflight(
        self, youtube_dl
    ):
        fixture = playlist_from_hell()
        extractor = MagicMock()
        extractor.extract_info.return_value = fixture["playlist"]
        youtube_dl.return_value.__enter__.return_value = extractor

        manifest = self.downloader._extract_manifest("fixture://playlist-from-hell")

        expected = fixture["expected"]
        self.assertEqual(manifest["unavailable"], 3)
        self.assertEqual(
            [track["id"] for track in manifest["tracks"]],
            expected["extractable_ids"],
        )
        self.assertEqual(
            [track["position"] for track in manifest["tracks"]],
            [
                position
                for position in range(1, len(fixture["playlist"]["entries"]) + 1)
                if position not in expected["unavailable_positions"]
            ],
        )
        self.assertNotEqual(manifest["tracks"][1]["id"], manifest["tracks"][2]["id"])
        self.assertEqual(manifest["tracks"][1]["title"], manifest["tracks"][2]["title"])

        self.downloader._extract_manifest = MagicMock(return_value=manifest)
        with patch(
            "autodrome.yt_downloader.asyncio.to_thread", new_callable=AsyncMock
        ) as to_thread:
            to_thread.side_effect = lambda function, *args: function(*args)
            with self.assertRaisesRegex(RuntimeError, "unavailable or unextractable"):
                await self.downloader.get_playlist_manifest(
                    "fixture://playlist-from-hell"
                )

        self.assertEqual(self.downloader._manifests, {})

    @patch("autodrome.yt_downloader.YoutubeDL")
    def test_generated_playlist_boundaries_keep_numeric_identity(self, youtube_dl):
        extractor = MagicMock()
        youtube_dl.return_value.__enter__.return_value = extractor

        for track_count in (99, 100, 101):
            with self.subTest(track_count=track_count):
                extractor.extract_info.return_value = generated_playlist(track_count)
                manifest = self.downloader._extract_manifest(
                    f"fixture://generated/{track_count}"
                )

                self.assertEqual(manifest["track_count"], track_count)
                self.assertEqual(manifest["unavailable"], 0)
                for position, track in enumerate(manifest["tracks"], start=1):
                    self.assertEqual(track["position"], position)
                    self.assertEqual(track["id"], f"audio-{position:03d}")
                    self.assertTrue(track["url"].endswith(track["id"]))

    async def test_unknown_total_downloads_extracted_manifest(self):
        self.downloader.get_playlist_track_urls = AsyncMock(return_value=["first"])
        self.downloader.download_track = AsyncMock()
        self.downloader._check_downloaded_files = AsyncMock()
        await self.downloader.download_playlist("playlist", "unused")
        self.downloader.download_track.assert_awaited_once()
        self.downloader._check_downloaded_files.assert_awaited_once_with("unused")

    async def test_download_track_reports_stable_failure_context(self):
        downloader = YTDownloader(track_download_attempts=1)
        downloader._download_track_blocking = MagicMock(
            side_effect=RuntimeError("unavailable")
        )

        with patch(
            "autodrome.yt_downloader.asyncio.to_thread", new_callable=AsyncMock
        ) as to_thread, tempfile.TemporaryDirectory() as destination:
            to_thread.side_effect = lambda function, *args: function(*args)

            with self.assertRaises(TrackDownloadError) as raised:
                await downloader.download_track(
                    "https://youtube.test/track", destination, 7, MagicMock()
                )

        self.assertEqual(raised.exception.index, 7)
        self.assertEqual(raised.exception.url, "https://youtube.test/track")
        self.assertEqual(raised.exception.reason, "unavailable")

    def test_download_concurrency_accepts_only_one_through_four(self):
        for concurrency in (1, 2, 4):
            with self.subTest(concurrency=concurrency):
                self.assertEqual(
                    YTDownloader(download_concurrency=concurrency).download_concurrency,
                    concurrency,
                )
        for concurrency in (0, 5, 1.5, True):
            with self.subTest(concurrency=concurrency):
                with self.assertRaisesRegex(ValueError, "between 1 and 4"):
                    YTDownloader(download_concurrency=concurrency)

    async def test_configured_concurrency_is_an_effective_limit(self):
        track_urls = [f"track-{index}" for index in range(1, 6)]
        for concurrency in (1, 2, 4):
            with self.subTest(concurrency=concurrency):
                downloader = YTDownloader(download_concurrency=concurrency)
                downloader.get_playlist_track_urls = AsyncMock(
                    return_value=track_urls
                )
                downloader._check_downloaded_files = AsyncMock()
                active = 0
                max_active = 0
                started_indices = []
                limit_reached = asyncio.Event()
                release = asyncio.Event()

                async def download_track(url, dest, index, hook):
                    nonlocal active, max_active
                    active += 1
                    max_active = max(max_active, active)
                    started_indices.append(index)
                    if active == concurrency:
                        limit_reached.set()
                    await release.wait()
                    active -= 1

                downloader.download_track = AsyncMock(side_effect=download_track)
                operation = asyncio.create_task(
                    downloader.download_playlist("playlist", "unused", total=5)
                )
                await asyncio.wait_for(limit_reached.wait(), timeout=1)
                await asyncio.sleep(0)

                self.assertEqual(max_active, concurrency)
                self.assertEqual(started_indices, list(range(1, concurrency + 1)))
                release.set()
                await asyncio.wait_for(operation, timeout=1)
                self.assertEqual(
                    [call.args[2] for call in downloader.download_track.await_args_list],
                    [1, 2, 3, 4, 5],
                )

    async def test_parallel_completion_reports_original_indices_in_finish_order(self):
        downloader = YTDownloader(download_concurrency=3)
        downloader.get_playlist_track_urls = AsyncMock(
            return_value=["first", "second", "third"]
        )
        downloader._check_downloaded_files = AsyncMock()
        releases = {index: asyncio.Event() for index in (1, 2, 3)}
        reported = {index: asyncio.Event() for index in (1, 2, 3)}
        all_started = asyncio.Event()
        started = []
        progress_events = []

        async def download_track(url, dest, index, hook):
            started.append(index)
            if len(started) == 3:
                all_started.set()
            await releases[index].wait()

        async def progress(phase, current, total, completed):
            progress_events.append((phase, current, total, completed))
            if phase == "downloading" and completed:
                reported[current].set()

        downloader.download_track = AsyncMock(side_effect=download_track)
        operation = asyncio.create_task(
            downloader.download_playlist(
                "playlist",
                "unused",
                total=3,
                progress=progress,
            )
        )
        await asyncio.wait_for(all_started.wait(), timeout=1)
        for index in (3, 1, 2):
            releases[index].set()
            await asyncio.wait_for(reported[index].wait(), timeout=1)
        await asyncio.wait_for(operation, timeout=1)

        completion_events = [
            (current, completed)
            for phase, current, total, completed in progress_events
            if phase == "downloading" and completed
        ]
        self.assertEqual(completion_events, [(3, 1), (1, 2), (2, 3)])

    async def test_parallel_failures_are_aggregated_after_started_tracks_finish(self):
        downloader = YTDownloader(download_concurrency=3)
        downloader.get_playlist_track_urls = AsyncMock(
            return_value=["first", "second", "third"]
        )
        downloader._check_downloaded_files = AsyncMock()
        successful_track_started = asyncio.Event()
        release_successful_track = asyncio.Event()
        failures_ready = asyncio.Event()
        failure_count = 0

        async def download_track(url, dest, index, hook):
            nonlocal failure_count
            if index in {1, 3}:
                failure_count += 1
                if failure_count == 2:
                    failures_ready.set()
                raise TrackDownloadError(index, url, f"failure-{index}")
            successful_track_started.set()
            await release_successful_track.wait()

        downloader.download_track = AsyncMock(side_effect=download_track)
        operation = asyncio.create_task(
            downloader.download_playlist("playlist", "unused", total=3)
        )
        await asyncio.wait_for(successful_track_started.wait(), timeout=1)
        await asyncio.wait_for(failures_ready.wait(), timeout=1)
        self.assertFalse(operation.done())

        release_successful_track.set()
        with self.assertRaises(PlaylistDownloadError) as raised:
            await asyncio.wait_for(operation, timeout=1)

        self.assertEqual(
            raised.exception.failures,
            [(1, "first", "failure-1"), (3, "third", "failure-3")],
        )
        downloader._check_downloaded_files.assert_not_awaited()

    async def test_parallel_tracks_keep_independent_retries(self):
        downloader = YTDownloader(
            track_download_attempts=2,
            download_concurrency=2,
        )
        downloader.get_playlist_track_urls = AsyncMock(
            return_value=["first", "second"]
        )
        downloader._check_downloaded_files = AsyncMock()
        attempts = {1: 0, 2: 0}

        def blocking(url, dest, index, hook):
            attempts[index] += 1
            if index == 1 and attempts[index] == 1:
                raise RuntimeError("temporary")

        downloader._download_track_blocking = MagicMock(side_effect=blocking)
        with patch(
            "autodrome.yt_downloader.asyncio.to_thread",
            new_callable=AsyncMock,
        ) as to_thread:
            to_thread.side_effect = lambda function, *args: function(*args)
            await downloader.download_playlist("playlist", "unused", total=2)

        self.assertEqual(attempts, {1: 2, 2: 1})

    @patch("autodrome.yt_downloader.YoutubeDL")
    def test_extract_track_urls_uses_playlist_metadata(self, youtube_dl):
        extractor = MagicMock()
        extractor.extract_info.return_value = {
            "entries": [
                {"id": "first", "webpage_url": "https://youtube.test/first"},
                {"id": "second"},
                None,
            ]
        }
        youtube_dl.return_value.__enter__.return_value = extractor

        urls = self.downloader._extract_track_urls(
            "https://youtube.com/playlist?list=123"
        )

        self.assertEqual(
            urls,
            [
                "https://youtube.test/first",
                "https://www.youtube.com/watch?v=second",
            ],
        )
        extractor.extract_info.assert_called_once_with(
            "https://youtube.com/playlist?list=123", download=False
        )

    @patch("autodrome.yt_downloader.YoutubeDL")
    def test_download_track_uses_stable_index_and_single_url(self, youtube_dl):
        downloader = MagicMock()
        youtube_dl.return_value.__enter__.return_value = downloader
        hook = MagicMock()

        with tempfile.TemporaryDirectory() as destination:
            self.downloader._download_track_blocking(
                "https://youtube.test/first", destination, 3, hook
            )

        options = youtube_dl.call_args.args[0]
        self.assertTrue(options["outtmpl"].endswith("03 - %(title)s.%(ext)s"))
        self.assertTrue(options["noplaylist"])
        downloader.download.assert_called_once_with(["https://youtube.test/first"])

    async def test_download_playlist_rejects_playlist_without_tracks(self):
        self.downloader.get_playlist_track_urls = AsyncMock(return_value=[])

        with tempfile.TemporaryDirectory() as destination:
            with self.assertRaisesRegex(RuntimeError, "does not contain"):
                await self.downloader.download_playlist(
                    "https://youtube.com/playlist?list=empty", destination
                )

    async def test_track_failure_does_not_stop_later_downloads(self):
        self.downloader = YTDownloader(track_download_attempts=1)
        self.downloader.get_playlist_track_urls = AsyncMock(
            return_value=[
                "https://youtube.test/unavailable",
                "https://youtube.test/available",
            ]
        )
        self.downloader._download_track_blocking = MagicMock(
            side_effect=[RuntimeError("video unavailable"), None]
        )
        self.downloader._check_downloaded_files = AsyncMock()

        with patch(
            "autodrome.yt_downloader.asyncio.to_thread", new_callable=AsyncMock
        ) as to_thread, tempfile.TemporaryDirectory() as destination:
            to_thread.side_effect = lambda function, *args: function(*args)

            with self.assertRaises(PlaylistDownloadError) as context:
                await self.downloader.download_playlist(
                    "https://youtube.com/playlist?list=123", destination
                )

        calls = self.downloader._download_track_blocking.call_args_list
        self.assertEqual(
            [call.args[0] for call in calls],
            [
                "https://youtube.test/unavailable",
                "https://youtube.test/available",
            ],
        )
        self.assertEqual(
            context.exception.failures,
            [(1, "https://youtube.test/unavailable", "video unavailable")],
        )
        self.assertIn("track 1", str(context.exception))
        self.downloader._check_downloaded_files.assert_not_awaited()

    async def test_transient_track_failure_is_retried(self):
        self.downloader = YTDownloader(track_download_attempts=2)
        self.downloader.get_playlist_track_urls = AsyncMock(
            return_value=["https://youtube.test/transient"]
        )
        self.downloader._download_track_blocking = MagicMock(
            side_effect=[RuntimeError("temporary failure"), None]
        )
        self.downloader._check_downloaded_files = AsyncMock()

        with patch(
            "autodrome.yt_downloader.asyncio.to_thread", new_callable=AsyncMock
        ) as to_thread, tempfile.TemporaryDirectory() as destination:
            to_thread.side_effect = lambda function, *args: function(*args)

            await self.downloader.download_playlist(
                "https://youtube.com/playlist?list=123", destination
            )

        self.assertEqual(self.downloader._download_track_blocking.call_count, 2)
        self.downloader._check_downloaded_files.assert_awaited_once_with(destination)


if __name__ == "__main__":
    unittest.main()

class TestPlaylistPreflight(unittest.IsolatedAsyncioTestCase):
    async def test_preflight_reused_for_download_but_expired_manifest_refetched(self):
        downloader = YTDownloader()
        downloader._extract_manifest = MagicMock(return_value={
            "tracks": [{"url": "track", "title": "Title", "position": 1}],
            "track_count": 1, "unavailable": 0,
        })
        downloader.download_track = AsyncMock()
        downloader._check_downloaded_files = AsyncMock()
        await downloader.get_playlist_manifest("playlist", 1)
        downloader.download_track.assert_not_awaited()
        await downloader.download_playlist("playlist", "unused", 1)
        downloader._extract_manifest.assert_called_once()
        downloader.download_track.assert_awaited_once()
        downloader.manifest_ttl_seconds = 0
        await downloader.get_playlist_manifest("playlist", 1)
        self.assertEqual(downloader._extract_manifest.call_count, 2)

    async def test_invalid_preflight_is_not_cached_or_downloaded(self):
        for unavailable, total in [(0, 2), (1, 1)]:
            downloader = YTDownloader()
            downloader._extract_manifest = MagicMock(return_value={
                "tracks": [{"url": "track"}], "track_count": 1, "unavailable": unavailable,
            })
            with self.assertRaises(RuntimeError):
                await downloader.get_playlist_manifest("playlist", total)
            self.assertEqual(downloader._manifests, {})

    async def test_extractor_failure_is_not_cached(self):
        downloader = YTDownloader()
        downloader._extract_manifest = MagicMock(side_effect=RuntimeError("yt-dlp failed"))
        with self.assertRaisesRegex(RuntimeError, "yt-dlp failed"):
            await downloader.get_playlist_manifest("playlist")
        self.assertEqual(downloader._manifests, {})

class TestDownloadShutdown(unittest.IsolatedAsyncioTestCase):
    async def test_shutdown_drains_blocking_audio_operation_without_retry(self):
        import threading
        downloader = YTDownloader()
        started = threading.Event()
        released = threading.Event()
        ended = threading.Event()

        def blocking(url, dest, index, hook):
            started.set()
            try:
                released.wait(2)
                hook({'status': 'downloading'})
            finally:
                ended.set()

        downloader._download_track_blocking = MagicMock(side_effect=blocking)
        task = asyncio.create_task(downloader.download_track('video', 'unused', 1, MagicMock()))
        try:
            await asyncio.to_thread(started.wait, 2)
            task.cancel()
            await asyncio.sleep(0)
            self.assertFalse(task.done())
            released.set()
            with self.assertRaises(asyncio.CancelledError):
                await task
            self.assertTrue(ended.is_set())
            downloader._download_track_blocking.assert_called_once()
        finally:
            released.set()

    async def test_playlist_shutdown_cancels_waiters_and_drains_active_tracks(self):
        downloader = YTDownloader(download_concurrency=2)
        downloader.get_playlist_track_urls = AsyncMock(
            return_value=["first", "second", "third"]
        )
        downloader._check_downloaded_files = AsyncMock()
        active_started = asyncio.Event()
        all_cancelled = asyncio.Event()
        release_cleanup = asyncio.Event()
        started = []
        cancelled = []
        drained = []

        async def download_track(url, dest, index, hook):
            started.append(index)
            if len(started) == 2:
                active_started.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                cancelled.append(index)
                if len(cancelled) == 2:
                    all_cancelled.set()
                await release_cleanup.wait()
                drained.append(index)
                raise

        downloader.download_track = AsyncMock(side_effect=download_track)
        operation = asyncio.create_task(
            downloader.download_playlist("playlist", "unused", total=3)
        )
        await asyncio.wait_for(active_started.wait(), timeout=1)
        operation.cancel()
        await asyncio.wait_for(all_cancelled.wait(), timeout=1)

        self.assertFalse(operation.done())
        self.assertEqual(started, [1, 2])
        release_cleanup.set()
        with self.assertRaises(asyncio.CancelledError):
            await asyncio.wait_for(operation, timeout=1)
        self.assertEqual(set(drained), {1, 2})
        downloader._check_downloaded_files.assert_not_awaited()

class TestTrackProgress(unittest.IsolatedAsyncioTestCase):
    async def test_retries_report_only_one_completed_track(self):
        downloader = YTDownloader()
        downloader.get_playlist_track_urls = AsyncMock(return_value=['first', 'second'])
        downloader._download_track_blocking = MagicMock(side_effect=[RuntimeError('retry'), None, None])
        downloader._check_downloaded_files = AsyncMock()
        progress = AsyncMock()
        await downloader.download_playlist('playlist', 'unused', 2, progress=progress)
        events = [call.args for call in progress.call_args_list]
        self.assertEqual(events, [
            ('manifest', None, None, None),
            ('downloading', 1, 2, 0), ('downloading', 1, 2, 1),
            ('downloading', 2, 2, 1), ('downloading', 2, 2, 2),
        ])
