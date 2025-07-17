from yt_dlp import YoutubeDL
from autodrome.logger import logger
from tempfile import TemporaryDirectory
from pathlib import Path
from typing import Callable, Optional

class YTDownloader:
    def __init__(self):
        pass  # Sin estado interno innecesario

    def create_temp_folder(self) -> TemporaryDirectory:
        return TemporaryDirectory()

    def download_playlist(self, url: str, dest: str, total: Optional[int] = None) -> None:
        logger.info(f"Downloading playlist to: {dest}")
        logger.debug(f"Total expected: {total}")

        hook = self._build_progress_hook(total)
        ydl_opts = self._build_ydl_opts(Path(dest), hook)

        with YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])

        logger.info("Playlist download completed successfully.")

    def _build_ydl_opts(self, dest: Path, hook: Callable) -> dict:
        return {
            'format': 'bestaudio/best',
            'postprocessors': [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '192',
            }],
            'outtmpl': str(dest / '%(playlist_index)02d - %(title)s.%(ext)s'),
            'progress_hooks': [hook],
            'quiet': True,
            'no_warnings': True,
            'ignoreerrors': True,
            }

    def _build_progress_hook(self, total: Optional[int]) -> Callable:
        completed = 0
        last_log_msg = None

        def hook(d):
            nonlocal completed, last_log_msg
            if d.get('status') == 'finished':
                completed += 1
                msg = f"Downloaded {completed} of {total}" if total else f"Downloaded {completed}"
                logger.info(msg)
            elif d.get('status') == 'downloading' and last_log_msg != "beginning download":
                logger.info("beginning download")
                last_log_msg = "beginning download"

        return hook
