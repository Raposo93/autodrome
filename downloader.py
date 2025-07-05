import subprocess
from logger import logger
from contextlib import contextmanager
from tempfile import TemporaryDirectory
import os

class Downloader:

    def create_temp_folder(self):
        return TemporaryDirectory()

    def download_playlist(self, url, dest):
        logger.info(f"Downloading playlist to: {dest}")
        cmd = [
            "yt-dlp",
            "--extract-audio",
            "--audio-format", "mp3",
            "--audio-quality", "4",  # media-alta (aprox 165 kbps)
            "--output", os.path.join(dest, "%(playlist_index)02d - %(title)s.%(ext)s"),
            url
        ]
        try:
            subprocess.run(cmd, check=True)
            logger.info("Playlist download completed successfully.")
        except subprocess.CalledProcessError as e:
            logger.error(f"yt-dlp failed: {e}")
            raise