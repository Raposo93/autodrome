import asyncio
import os
from yt_dlp import YoutubeDL
from autodrome.logger import logger
from tempfile import TemporaryDirectory
from pathlib import Path
from typing import Callable, Optional

class YTDownloader:
    def __init__(self):
        pass

    def create_temp_folder(self) -> TemporaryDirectory:
        return TemporaryDirectory()

    async def download_playlist(self, url: str, dest: str, total: Optional[int] = None) -> None:
        logger.debug(f"[YTDownloader] Starting download_playlist: {url} to {dest}")
        print(f"[YTDownloader] Descargando: {url} en {dest}")
        
        await asyncio.to_thread(self._download_blocking, url, dest, total)
        await self._check_downloaded_files(dest)

    def _download_blocking(self, url: str, dest: str, total: Optional[int] = None) -> None:
        logger.info(f"[YTDownloader] Downloading playlist to: {dest}")
        print(f"[YTDownloader] Lanzando descarga yt-dlp: {url}")

        hook = self._build_progress_hook(total)
        ydl_opts = self._build_ydl_opts(Path(dest), hook)

        with YoutubeDL(ydl_opts) as ydl:
            try:
                ydl.download([url])
            except Exception as e:
                logger.error(f"[YTDownloader] Error downloading playlist: {e}")
                raise

        logger.info("[YTDownloader] Playlist download completed successfully.")
        print("[YTDownloader] Descarga completada sin errores")

    async def _check_downloaded_files(self, folder: str) -> None:
        print(f"[YTDownloader] Comprobando archivos descargados en: {folder}")

        files = os.listdir(folder)

        downloaded = [f for f in files if f.lower().endswith((".mp3", ".m4a", ".opus"))]
        logger.info(f"[YTDownloader] Archivos de audio descargados: {downloaded}")

        if not downloaded:
            raise RuntimeError("[YTDownloader] No se han descargado archivos de audio. Revisa la URL o la configuración.")

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
            'quiet': False,
            'no_warnings': False,
            'ignoreerrors': False,
        }

    def _build_progress_hook(self, total: Optional[int]) -> Callable:
        completed = 0
        last_log_msg = None

        def hook(d):
            nonlocal completed, last_log_msg
            if d.get('status') == 'finished':
                completed += 1
                msg = f"[YTDownloader] Downloaded {completed} of {total}" if total else f"[YTDownloader] Downloaded {completed}"
                logger.info(msg)
                print(msg)
            elif d.get('status') == 'downloading' and last_log_msg != "beginning download":
                logger.info("[YTDownloader] Beginning download")
                print("[YTDownloader] Comenzando descarga")
                last_log_msg = "beginning download"

        return hook

    async def _download_with_subprocess(self, url: str, dest: str) -> None:
        args = [
            "yt-dlp",
            "-f", "bestaudio/best",
            "--extract-audio",
            "--audio-format", "mp3",
            "--audio-quality", "192K",
            "-o", f"{dest}/%(playlist_index)02d - %(title)s.%(ext)s",
            url
        ]
        logger.info(f"[YTDownloader] Starting yt-dlp subprocess with args: {args}")
        print(f"[YTDownloader] Subprocess yt-dlp: {' '.join(args)}")

        process = await asyncio.create_subprocess_exec(
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        stdout, stderr = await process.communicate()

        if stdout:
            decoded = stdout.decode(errors='ignore')
            logger.debug(f"[YTDownloader] yt-dlp stdout: {decoded}")
            print(decoded)
        if stderr:
            decoded = stderr.decode(errors='ignore')
            logger.error(f"[YTDownloader] yt-dlp stderr: {decoded}")
            print(decoded)

        if process.returncode != 0:
            raise RuntimeError(f"[YTDownloader] yt-dlp subprocess failed with return code {process.returncode}")
