import tempfile
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from autodrome.yt_downloader import (
    PlaylistDownloadError,
    TrackDownloadError,
    YTDownloader,
)


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

    def test_parallel_downloads_are_not_enabled_by_configuration_stub(self):
        with self.assertRaisesRegex(ValueError, "must remain 1"):
            YTDownloader(download_concurrency=2)

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
