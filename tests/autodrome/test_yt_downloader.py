import os
import shutil
import tempfile
import unittest
from unittest.mock import patch, MagicMock
from autodrome.yt_downloader import YTDownloader

class TestYTDownloader(unittest.TestCase):
    def setUp(self):
        self.downloader = YTDownloader()

    def test_create_temp_folder_removes_folder_after_success(self):
        with self.downloader.create_temp_folder() as folder:
            self.assertTrue(os.path.isdir(folder))

        self.assertFalse(os.path.exists(folder))

    def test_create_temp_folder_preserves_files_after_failure(self):
        folder = None
        try:
            with self.assertRaisesRegex(RuntimeError, "tagging failed"):
                with self.downloader.create_temp_folder() as folder:
                    with open(os.path.join(folder, "downloaded.mp3"), "wb") as file:
                        file.write(b"ID3")
                    raise RuntimeError("tagging failed")

            self.assertTrue(os.path.isfile(os.path.join(folder, "downloaded.mp3")))
        finally:
            if folder and os.path.exists(folder):
                shutil.rmtree(folder)

    @patch("autodrome.yt_downloader.YoutubeDL")
    def test_download_playlist_calls_yt_dlp_with_url(self, mock_yt_dlp):
        mock_dl_instance = MagicMock()
        mock_yt_dlp.return_value.__enter__.return_value = mock_dl_instance

        dest = tempfile.mkdtemp()
        url = "https://youtube.com/playlist?list=123"

        self.downloader.download_playlist(url, dest, total=3)

        mock_dl_instance.download.assert_called_once_with([url])

    @patch("autodrome.yt_downloader.YoutubeDL")
    def test_download_playlist_handles_exception(self, mock_yt_dlp):
        mock_dl_instance = MagicMock()
        mock_dl_instance.download.side_effect = Exception("Fake error")
        mock_yt_dlp.return_value.__enter__.return_value = mock_dl_instance

        dest = tempfile.mkdtemp()
        url = "https://youtube.com/playlist?list=123"

        with self.assertRaises(Exception) as context:
            self.downloader.download_playlist(url, dest)

        self.assertIn("Fake error", str(context.exception))

if __name__ == "__main__":
    unittest.main()
