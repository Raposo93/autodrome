import tempfile
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from autodrome.yt_downloader import YTDownloader


class TestYTDownloader(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.downloader = YTDownloader()

    @patch("autodrome.yt_downloader.YoutubeDL")
    async def test_download_playlist_calls_yt_dlp_with_url(self, youtube_dl):
        downloader = MagicMock()
        youtube_dl.return_value.__enter__.return_value = downloader
        self.downloader._check_downloaded_files = AsyncMock()

        with patch(
            "autodrome.yt_downloader.asyncio.to_thread", new_callable=AsyncMock
        ) as to_thread, tempfile.TemporaryDirectory() as destination:
            to_thread.side_effect = lambda function, *args: function(*args)
            url = "https://youtube.com/playlist?list=123"

            await self.downloader.download_playlist(url, destination, total=3)

        downloader.download.assert_called_once_with([url])
        self.downloader._check_downloaded_files.assert_awaited_once()

    @patch("autodrome.yt_downloader.YoutubeDL")
    async def test_download_playlist_handles_exception(self, youtube_dl):
        downloader = MagicMock()
        downloader.download.side_effect = Exception("Fake error")
        youtube_dl.return_value.__enter__.return_value = downloader

        with patch(
            "autodrome.yt_downloader.asyncio.to_thread", new_callable=AsyncMock
        ) as to_thread, tempfile.TemporaryDirectory() as destination:
            to_thread.side_effect = lambda function, *args: function(*args)
            with self.assertRaisesRegex(Exception, "Fake error"):
                await self.downloader.download_playlist(
                    "https://youtube.com/playlist?list=123",
                    destination,
                )


if __name__ == "__main__":
    unittest.main()
