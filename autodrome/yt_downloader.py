import asyncio
import os
import threading
import time
from pathlib import Path
from typing import Callable, List, Optional, Tuple

from yt_dlp import YoutubeDL

from autodrome.config import MAX_DOWNLOAD_CONCURRENCY
from autodrome.logger import logger
from autodrome.models.progress import report_progress, ProgressCallback


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
        if (
            not isinstance(download_concurrency, int)
            or isinstance(download_concurrency, bool)
            or not 1 <= download_concurrency <= MAX_DOWNLOAD_CONCURRENCY
        ):
            raise ValueError(
                "download_concurrency must be between 1 and "
                f"{MAX_DOWNLOAD_CONCURRENCY}"
            )
        self._manifests = {}
        self.manifest_ttl_seconds = 120
        self.track_download_attempts = track_download_attempts
        self.download_concurrency = download_concurrency

    async def download_playlist(
        self,
        url: str,
        dest: str,
        total: Optional[int] = None,
        manifest=None,
        progress: Optional[ProgressCallback] = None,
    ) -> None:
        logger.debug("playlist_download_started destination=%s", dest)

        await report_progress(progress, "manifest")
        if manifest is not None:
            if manifest.get("unavailable"):
                raise RuntimeError("Playlist contains unavailable entries")
            track_urls = [track["url"] for track in manifest["tracks"]]
        else:
            track_urls = await self.get_playlist_track_urls(url)
        self.validate_manifest(track_urls, total)

        hook = self._build_progress_hook(total or len(track_urls))
        failures = await self._download_tracks(
            track_urls,
            dest,
            hook,
            progress,
        )

        if failures:
            raise PlaylistDownloadError(failures)

        await self._check_downloaded_files(dest)

    async def _download_tracks(
        self,
        track_urls: List[str],
        dest: str,
        hook: Callable,
        progress: Optional[ProgressCallback],
    ) -> List[Tuple[int, str, str]]:
        semaphore = asyncio.Semaphore(self.download_concurrency)
        progress_lock = asyncio.Lock()
        completed = 0

        async def update_progress(index: int, *, finished: bool = False) -> None:
            nonlocal completed
            async with progress_lock:
                if finished:
                    completed += 1
                await report_progress(
                    progress,
                    "downloading",
                    index,
                    len(track_urls),
                    completed,
                )

        async def download_one(index: int, track_url: str):
            async with semaphore:
                await update_progress(index)
                try:
                    await self.download_track(track_url, dest, index, hook)
                except TrackDownloadError as error:
                    return (error.index, error.url, error.reason)
                await update_progress(index, finished=True)
                return None

        tasks = [
            asyncio.create_task(download_one(index, track_url))
            for index, track_url in enumerate(track_urls, start=1)
        ]
        try:
            results = await asyncio.gather(*tasks)
        except (asyncio.CancelledError, Exception):
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            raise

        return [failure for failure in results if failure is not None]

    @staticmethod
    def validate_manifest(track_urls, total=None):
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

    async def get_playlist_manifest(self, url: str, total=None):
        cached = self._manifests.get(url)
        if cached and time.monotonic() - cached[0] < self.manifest_ttl_seconds:
            manifest = cached[1]
        else:
            manifest = await asyncio.to_thread(self._extract_manifest, url)
            if manifest["unavailable"]:
                raise RuntimeError("Playlist contains unavailable or unextractable entries")
            self.validate_manifest(manifest["tracks"], total)
            if len(self._manifests) >= 16:
                self._manifests.pop(next(iter(self._manifests)))
            self._manifests[url] = (time.monotonic(), manifest)
        self.validate_manifest(manifest["tracks"], total)
        return manifest

    async def get_playlist_track_urls(self, url: str) -> List[str]:
        manifest = await self.get_playlist_manifest(url)
        return [track["url"] for track in manifest["tracks"]]

    async def download_track(
        self,
        url: str,
        dest: str,
        index: int,
        hook: Callable,
    ) -> None:
        stopping = threading.Event()

        def cancellable_hook(data):
            if stopping.is_set():
                raise RuntimeError("Download stopped during shutdown")
            hook(data)

        for attempt in range(1, self.track_download_attempts + 1):
            operation = asyncio.create_task(asyncio.to_thread(
                self._download_track_blocking, url, dest, index, cancellable_hook
            ))
            try:
                await asyncio.shield(operation)
                return
            except asyncio.CancelledError:
                stopping.set()
                # A cancelled to_thread await does not stop its thread. Drain it
                # before allowing the job/staging lifecycle to finish.
                try:
                    await operation
                except Exception:
                    pass
                raise
            except Exception as e:
                if attempt == self.track_download_attempts:
                    raise TrackDownloadError(index, url, str(e)) from e
                logger.warning(
                    "track_download_retry track=%s attempt=%s/%s reason=%s",
                    index,
                    attempt + 1,
                    self.track_download_attempts,
                    type(e).__name__,
                )

    def _extract_track_urls(self, url: str) -> List[str]:
        return [track["url"] for track in self._extract_manifest(url)["tracks"]]

    def _extract_manifest(self, url: str):
        options = {
            "extract_flat": "in_playlist",
            "skip_download": True,
            "quiet": True,
            "no_warnings": True,
        }
        with YoutubeDL(options) as ydl:
            playlist = ydl.extract_info(url, download=False)

        tracks = []
        unavailable = 0
        for position, entry in enumerate(playlist.get("entries") or [], 1):
            if not entry or entry.get("availability") in {"private", "premium_only", "subscriber_only", "needs_auth"} or entry.get("title") in {"[Private video]", "[Deleted video]"}:
                unavailable += 1
                continue
            track_url = entry.get("webpage_url") or entry.get("original_url")
            if not track_url and entry.get("id"):
                track_url = f"https://www.youtube.com/watch?v={entry['id']}"
            if not track_url:
                track_url = entry.get("url")
            if track_url:
                tracks.append({"position": position, "id": entry.get("id"), "url": track_url, "title": entry.get("title") or f"Track {position}"})
            else:
                unavailable += 1

        return {"tracks": tracks, "track_count": len(tracks), "unavailable": unavailable}

    def _download_track_blocking(
        self,
        url: str,
        dest: str,
        index: int,
        hook: Callable,
    ) -> None:
        logger.debug("track_download_started track=%s", index)

        ydl_opts = self._build_ydl_opts(Path(dest), hook, index)

        with YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])

        logger.debug("track_download_completed track=%s", index)

    async def _check_downloaded_files(self, folder: str) -> None:
        files = os.listdir(folder)

        downloaded = [
            file
            for file in files
            if file.lower().endswith((".mp3", ".m4a", ".opus"))
        ]
        logger.debug("playlist_files_verified audio_files=%s", len(downloaded))

        if not downloaded:
            raise RuntimeError(
                "[YTDownloader] No se han descargado archivos de audio. "
                "Revisa la URL o la configuración."
            )

    def _build_ydl_opts(self, dest: Path, hook: Callable, index: int) -> dict:
        return {
            'socket_timeout': 20,
            'format': 'bestaudio/best',
            'postprocessors': [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '192',
            }],
            'outtmpl': str(dest / f'{index:02d} - %(title)s.%(ext)s'),
            'progress_hooks': [hook],
            'quiet': True,
            'no_warnings': True,
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
                    logger.debug(msg)
                elif (
                    d.get("status") == "downloading"
                    and last_log_msg != "beginning download"
                ):
                    logger.debug("track_transfer_started")
                    last_log_msg = "beginning download"

        return hook
