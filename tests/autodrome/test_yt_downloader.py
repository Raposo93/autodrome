import tempfile
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from autodrome.yt_downloader import YTDownloader


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
        self.assertEqual([call.args[0] for call in calls], [
            "https://youtube.test/watch?v=first",
            "https://youtube.test/watch?v=second",
        ])
        self.assertEqual([call.args[2] for call in calls], [1, 2])
        self.downloader._check_downloaded_files.assert_awaited_once()

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


if __name__ == "__main__":
    unittest.main()
