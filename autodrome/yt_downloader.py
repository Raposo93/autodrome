import asyncio
import os
import threading
import time
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
    ) -> None:
        logger.debug(f"[YTDownloader] Starting download_playlist: {url} to {dest}")
        print(f"[YTDownloader] Descargando: {url} en {dest}")

        if manifest is not None:
            if manifest.get("unavailable"):
                raise RuntimeError("Playlist contains unavailable entries")
            track_urls = [track["url"] for track in manifest["tracks"]]
        else:
            track_urls = await self.get_playlist_track_urls(url)
        self.validate_manifest(track_urls, total)

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
                logger.warning(
                    f"[YTDownloader] Track {index} attempt {attempt} of "
                    f"{self.track_download_attempts} failed: {e}"
                )
                if attempt == self.track_download_attempts:
                    raise TrackDownloadError(index, url, str(e)) from e

    def _extract_track_urls(self, url: str) -> List[str]:
        return [track["url"] for track in self._extract_manifest(url)["tracks"]]

    def _extract_manifest(self, url: str):
        options = {
            "extract_flat": "in_playlist",
            "skip_download": True,
            "quiet": True,
            "no_warnings": False,
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
            'socket_timeout': 20,
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
