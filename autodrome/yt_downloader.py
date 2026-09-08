import asyncio
import os
import threading
from pathlib import Path
from typing import Callable, List, Optional, Tuple

from yt_dlp import YoutubeDL

from autodrome.logger import logger


class PlaylistDownloadError(RuntimeError):
    def __init__(self, failures: List[Tuple[int, str, str]]) -> None:
        self.failures = failures
        details = "; ".join(
            f"track {index} ({url}): {error}"
            for index, url, error in failures
        )
        super().__init__(
            f"Failed to download {len(failures)} playlist track(s): {details}"
        )


class TrackDownloadError(RuntimeError):
    def __init__(self, index: int, url: str, reason: str) -> None:
        self.index = index
        self.url = url
        self.reason = reason
        super().__init__(f"Track {index} failed: {reason}")


class YTDownloader:
    def __init__(
        self,
        track_download_attempts: int = 2,
        download_concurrency: int = 1,
    ):
        if track_download_attempts < 1:
            raise ValueError("track_download_attempts must be at least 1")
        if download_concurrency != 1:
            raise ValueError(
                "download_concurrency must remain 1 until parallel publication "
                "is supported"
            )
        self.track_download_attempts = track_download_attempts
        self.download_concurrency = download_concurrency

    async def download_playlist(
        self,
        url: str,
        dest: str,
        total: Optional[int] = None,
    ) -> None:
        logger.debug(f"[YTDownloader] Starting download_playlist: {url} to {dest}")
        print(f"[YTDownloader] Descargando: {url} en {dest}")

        track_urls = await self.get_playlist_track_urls(url)
        if total is not None and len(track_urls) != total:
            raise RuntimeError(
                f"[YTDownloader] Playlist manifest mismatch: expected {total} "
                f"tracks, extractable {len(track_urls)}. The current manifest "
                "does not match the known count; entries may be unavailable."
            )
        if not track_urls:
            raise RuntimeError(
                "[YTDownloader] The playlist does not contain downloadable tracks"
            )

        hook = self._build_progress_hook(total or len(track_urls))
        failures = []
        for index, track_url in enumerate(track_urls, start=1):
            try:
                await self.download_track(track_url, dest, index, hook)
            except TrackDownloadError as e:
                failures.append((e.index, e.url, e.reason))

        if failures:
            raise PlaylistDownloadError(failures)

        await self._check_downloaded_files(dest)

    async def get_playlist_track_urls(self, url: str) -> List[str]:
        return await asyncio.to_thread(self._extract_track_urls, url)

    async def download_track(
        self,
        url: str,
        dest: str,
        index: int,
        hook: Callable,
    ) -> None:
        for attempt in range(1, self.track_download_attempts + 1):
            try:
                await asyncio.to_thread(
                    self._download_track_blocking,
                    url,
                    dest,
                    index,
                    hook,
                )
                return
            except Exception as e:
                logger.warning(
                    f"[YTDownloader] Track {index} attempt {attempt} of "
                    f"{self.track_download_attempts} failed: {e}"
                )
                if attempt == self.track_download_attempts:
                    raise TrackDownloadError(index, url, str(e)) from e

    def _extract_track_urls(self, url: str) -> List[str]:
        options = {
            "extract_flat": "in_playlist",
            "skip_download": True,
            "quiet": True,
            "no_warnings": False,
        }
        with YoutubeDL(options) as ydl:
            playlist = ydl.extract_info(url, download=False)

        track_urls = []
        for entry in playlist.get("entries") or []:
            if not entry:
                continue
            track_url = entry.get("webpage_url") or entry.get("original_url")
            if not track_url and entry.get("id"):
                track_url = f"https://www.youtube.com/watch?v={entry['id']}"
            if not track_url:
                track_url = entry.get("url")
            if track_url:
                track_urls.append(track_url)

        logger.info(f"[YTDownloader] Extracted {len(track_urls)} playlist track URLs")
        return track_urls

    def _download_track_blocking(
        self,
        url: str,
        dest: str,
        index: int,
        hook: Callable,
    ) -> None:
        logger.info(f"[YTDownloader] Downloading track {index} to: {dest}")
        print(f"[YTDownloader] Lanzando descarga yt-dlp: {url}")

        ydl_opts = self._build_ydl_opts(Path(dest), hook, index)

        with YoutubeDL(ydl_opts) as ydl:
            try:
                ydl.download([url])
            except Exception as e:
                logger.error(f"[YTDownloader] Error downloading track {index}: {e}")
                raise

        logger.info(f"[YTDownloader] Track {index} download completed successfully")

    async def _check_downloaded_files(self, folder: str) -> None:
        print(f"[YTDownloader] Comprobando archivos descargados en: {folder}")

        files = os.listdir(folder)

        downloaded = [
            file
            for file in files
            if file.lower().endswith((".mp3", ".m4a", ".opus"))
        ]
        logger.info(f"[YTDownloader] Archivos de audio descargados: {downloaded}")

        if not downloaded:
            raise RuntimeError(
                "[YTDownloader] No se han descargado archivos de audio. "
                "Revisa la URL o la configuración."
            )

    def _build_ydl_opts(self, dest: Path, hook: Callable, index: int) -> dict:
        return {
            'format': 'bestaudio/best',
            'postprocessors': [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '192',
            }],
            'outtmpl': str(dest / f'{index:02d} - %(title)s.%(ext)s'),
            'progress_hooks': [hook],
            'quiet': False,
            'no_warnings': False,
            'ignoreerrors': False,
            'noplaylist': True,
        }

    def _build_progress_hook(self, total: Optional[int]) -> Callable:
        completed = 0
        last_log_msg = None
        progress_lock = threading.Lock()

        def hook(d):
            nonlocal completed, last_log_msg
            with progress_lock:
                if d.get("status") == "finished":
                    completed += 1
                    msg = (
                        f"[YTDownloader] Downloaded {completed} of {total}"
                        if total
                        else f"[YTDownloader] Downloaded {completed}"
                    )
                    logger.info(msg)
                    print(msg)
                elif (
                    d.get("status") == "downloading"
                    and last_log_msg != "beginning download"
                ):
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
