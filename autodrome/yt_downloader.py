from yt_dlp import YoutubeDL
from autodrome.logger import logger
from tempfile import TemporaryDirectory
import os

class YTDownloader:
    def __init__(self):
        self.total = None
        self._completed = 0
        self._last_log_msg = None

    def create_temp_folder(self):
        return TemporaryDirectory()

    def download_playlist(self, url, dest, total=None):
        logger.info(f"Downloading playlist to: {dest}")
        logger.debug(f"total: {total}")
        self._completed = 0

        def hook(d):
            if d.get('status') == 'finished':
                self._completed += 1
                msg = f"Downloaded {self._completed} of {total}" if total else f"Downloaded {self._completed}"
                logger.info(msg)

            elif d.get('status') == 'downloading':
                idx = d.get('_download_index', 0) + 1
                msg = f"Downloading item {idx} of {total}" if total else f"Downloading item {idx}"
                if msg != self._last_log_msg:
                    logger.info(msg)
                    self._last_log_msg = msg

                    
        ydl_opts = {
            'format': 'bestaudio/best',
            'postprocessors': [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '192',
            }],
            'outtmpl': os.path.join(dest, '%(playlist_index)02d - %(title)s.%(ext)s'),
            'progress_hooks': [hook],
            'quiet': True,
            'no_warnings': True,
        }

        try:
            with YoutubeDL(ydl_opts) as ydl:
                ydl.download([url])
            logger.info("Playlist download completed successfully.")
        except Exception as e:
            logger.error(f"yt-dlp failed: {e}")
            raise