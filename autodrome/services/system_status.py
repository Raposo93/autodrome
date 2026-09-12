import asyncio
import errno
import os
import shutil
import tempfile
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, Optional

from autodrome.services.ytdlp_runtime import (
    DENO_MINIMUM_VERSION_TEXT,
    UnsupportedDenoVersion,
    read_deno_version,
)


Component = Dict[str, Any]


class SystemStatusService:
    """Collect bounded, read-mostly diagnostics without making them health gates."""

    PROBE_TIMEOUT_SECONDS = 5
    YOUTUBE_DISCOVERY_URL = (
        "https://www.googleapis.com/discovery/v1/apis/youtube/v3/rest"
    )
    MUSICBRAINZ_PROBE_URL = "https://musicbrainz.org/ws/2/artist/"

    def __init__(
        self,
        *,
        settings,
        http_client,
        redis_cache,
        queue_manager,
        ffmpeg_version: Optional[Callable[[], Awaitable[str]]] = None,
        deno_version: Optional[Callable[[], Awaitable[str]]] = None,
        yt_dlp_versions: Optional[Callable[[], tuple[str, Optional[str]]]] = None,
    ) -> None:
        self.settings = settings
        self.http_client = http_client
        self.redis_cache = redis_cache
        self.queue_manager = queue_manager
        self._ffmpeg_version = ffmpeg_version or self._read_ffmpeg_version
        self._deno_version = deno_version or self._read_deno_version
        self._yt_dlp_versions = yt_dlp_versions or self._read_yt_dlp_versions

    async def snapshot(self) -> Dict[str, Any]:
        ffmpeg, js_runtime, youtube, musicbrainz, redis = await asyncio.gather(
            self._check_ffmpeg(),
            self._check_js_runtime(),
            self._check_youtube(),
            self._check_musicbrainz(),
            self._check_redis(),
        )
        storage_error = self._sanitized_storage_error()
        return {
            "version": self.settings.version or "unknown",
            "commit": self._build_commit(),
            "components": {
                "library": self._safe_sync_check(
                    lambda: self._check_directory(self.settings.library_path),
                    "Library diagnostic failed.",
                ),
                "staging": self._safe_sync_check(
                    lambda: self._check_directory(self.settings.staging_path),
                    "Staging diagnostic failed.",
                ),
                "queue_storage": self._safe_sync_check(
                    self._check_queue_storage,
                    "Queue storage diagnostic failed.",
                ),
                "ffmpeg": ffmpeg,
                "yt_dlp": self._safe_sync_check(
                    self._check_yt_dlp,
                    "yt-dlp diagnostic failed.",
                ),
                "js_runtime": js_runtime,
                "youtube": youtube,
                "musicbrainz": musicbrainz,
                "redis": redis,
                "worker": self._safe_sync_check(
                    self._check_worker,
                    "Worker diagnostic failed.",
                ),
            },
            "storage_error": storage_error,
        }

    def _check_directory(self, path: str) -> Component:
        directory = Path(path).absolute()
        try:
            if not directory.exists():
                return self._component(
                    "warning",
                    "Directory has not been created yet.",
                    writable=False,
                )
            if not directory.is_dir():
                return self._component(
                    "error",
                    "Configured location is not a directory.",
                    writable=False,
                )
            free_bytes = shutil.disk_usage(directory).free
            writable = os.access(directory, os.W_OK | os.X_OK)
        except OSError as error:
            return self._component(
                "error",
                self._filesystem_error_message(error),
                writable=False,
            )

        return self._component(
            "ok" if writable else "error",
            "Writable." if writable else "Directory is not writable.",
            writable=writable,
            free_bytes=free_bytes,
        )

    def _check_queue_storage(self) -> Component:
        state_path = Path(self.queue_manager.state_path).absolute()
        state_directory = state_path.parent
        descriptor = None
        probe_path = None
        failure = None

        try:
            if not state_directory.is_dir():
                return self._component(
                    "error",
                    "Queue state directory does not exist.",
                    writable=False,
                )
            descriptor, probe_path = tempfile.mkstemp(
                prefix=".autodrome-status-",
                suffix=".tmp",
                dir=state_directory,
            )
            os.write(descriptor, b"autodrome-status\n")
            os.fsync(descriptor)
        except OSError as error:
            failure = error
        finally:
            if descriptor is not None:
                try:
                    os.close(descriptor)
                except OSError as error:
                    failure = failure or error
            if probe_path is not None:
                try:
                    os.unlink(probe_path)
                except OSError as error:
                    failure = failure or error

        if failure is not None:
            return self._component(
                "error",
                self._filesystem_error_message(failure),
                writable=False,
            )
        return self._component(
            "ok",
            "A durable state write can be staged safely.",
            writable=True,
        )

    async def _check_ffmpeg(self) -> Component:
        try:
            version = await asyncio.wait_for(
                self._ffmpeg_version(),
                timeout=self.PROBE_TIMEOUT_SECONDS,
            )
        except FileNotFoundError:
            return self._component("error", "ffmpeg is not installed or executable.")
        except asyncio.TimeoutError:
            return self._component("error", "ffmpeg version check timed out.")
        except Exception:
            return self._component("error", "ffmpeg version check failed.")
        return self._component("ok", version)

    def _check_yt_dlp(self) -> Component:
        try:
            yt_dlp_version, ejs_version = self._yt_dlp_versions()
        except PackageNotFoundError:
            return self._component("error", "yt-dlp is not installed.")
        if ejs_version is None:
            return self._component(
                "warning",
                f"yt-dlp {yt_dlp_version}; EJS support is missing. "
                "Reinstall Autodrome's Python dependencies.",
            )
        return self._component(
            "ok",
            f"yt-dlp {yt_dlp_version} · EJS {ejs_version}",
        )

    async def _check_js_runtime(self) -> Component:
        try:
            runtime_version = await asyncio.wait_for(
                self._deno_version(),
                timeout=self.PROBE_TIMEOUT_SECONDS,
            )
        except FileNotFoundError:
            return self._component(
                "warning",
                "No supported JavaScript runtime is available. Install Deno "
                f"{DENO_MINIMUM_VERSION_TEXT} or newer for the service user.",
            )
        except UnsupportedDenoVersion as error:
            return self._component(
                "warning",
                f"deno {error.version} is too old; install Deno "
                f"{DENO_MINIMUM_VERSION_TEXT} or newer.",
            )
        except asyncio.TimeoutError:
            return self._component("warning", "Deno version check timed out.")
        except Exception:
            return self._component("warning", "Deno version check failed.")
        return self._component("ok", runtime_version)

    async def _check_youtube(self) -> Component:
        if not self.settings.google_api_key:
            return self._component("error", "YouTube API key is not configured.")
        try:
            response = await asyncio.wait_for(
                self.http_client.get(
                    self.YOUTUBE_DISCOVERY_URL,
                    params={"fields": "id"},
                    timeout=self.PROBE_TIMEOUT_SECONDS,
                    provider="YouTube",
                    context="checking service availability",
                ),
                timeout=self.PROBE_TIMEOUT_SECONDS,
            )
            if not isinstance(response, dict) or response.get("id") != "youtube:v3":
                raise ValueError("invalid YouTube discovery response")
        except Exception:
            return self._component(
                "error",
                "Configured, but the YouTube API endpoint is not reachable.",
                configured=True,
            )
        return self._component(
            "ok",
            "Configured and reachable.",
            configured=True,
        )

    async def _check_musicbrainz(self) -> Component:
        try:
            response = await asyncio.wait_for(
                self.http_client.get(
                    self.MUSICBRAINZ_PROBE_URL,
                    params={
                        "query": "artist:autodrome-diagnostic-probe",
                        "fmt": "json",
                        "limit": 1,
                    },
                    timeout=self.PROBE_TIMEOUT_SECONDS,
                    provider="MusicBrainz",
                    context="checking service availability",
                ),
                timeout=self.PROBE_TIMEOUT_SECONDS,
            )
            if not isinstance(response, dict) or not isinstance(
                response.get("artists"), list
            ):
                raise ValueError("invalid diagnostic response")
        except Exception:
            return self._component(
                "warning",
                "MusicBrainz is temporarily unreachable; manual mode remains available.",
            )
        return self._component("ok", "Reachable.")

    async def _check_redis(self) -> Component:
        if not self.settings.redis_enabled:
            return self._component("disabled", "Optional cache is disabled.")
        try:
            # RedisCache configures bounded socket connect/read timeouts.
            available = self.redis_cache.ping()
        except Exception:
            available = False
        if not available:
            return self._component(
                "error",
                "Redis cache is enabled but unavailable; primary workflows remain usable.",
            )
        return self._component("ok", "Optional cache is reachable.")

    def _check_worker(self) -> Component:
        if self.queue_manager.storage_error:
            return self._component(
                "error",
                "Processing is paused while queue state persistence recovers.",
                state="paused",
            )

        worker_task = self.queue_manager.worker_task
        if worker_task is None or worker_task.done():
            return self._component(
                "error",
                "Queue worker is not running.",
                state="error",
            )

        statuses = {job.get("status") for job in self.queue_manager.snapshot()}
        if "running" in statuses:
            return self._component(
                "ok",
                "A download is running.",
                state="running",
            )
        if "queued" in statuses:
            return self._component(
                "ok",
                "Worker is operational with downloads waiting.",
                state="busy",
            )
        return self._component("ok", "Worker is idle.", state="idle")

    def _sanitized_storage_error(self) -> Optional[str]:
        if not self.queue_manager.storage_error:
            return None
        return (
            "Queue persistence is unavailable; processing is paused and the "
            "state write will retry automatically."
        )

    async def _read_ffmpeg_version(self) -> str:
        executable = shutil.which("ffmpeg")
        if executable is None:
            raise FileNotFoundError("ffmpeg")
        process = await asyncio.create_subprocess_exec(
            executable,
            "-version",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        try:
            output, _ = await process.communicate()
        except BaseException:
            if process.returncode is None:
                process.kill()
                await process.wait()
            raise
        if process.returncode != 0:
            raise RuntimeError("ffmpeg exited unsuccessfully")
        first_line = output.decode("utf-8", errors="replace").splitlines()[0:1]
        if not first_line:
            raise RuntimeError("ffmpeg returned no version")
        return first_line[0][:200]

    async def _read_deno_version(self) -> str:
        return await read_deno_version(
            self.settings.yt_dlp_deno_path,
            timeout=self.PROBE_TIMEOUT_SECONDS,
        )

    @staticmethod
    def _read_yt_dlp_versions() -> tuple[str, Optional[str]]:
        yt_dlp_version = version("yt-dlp")
        try:
            ejs_version = version("yt-dlp-ejs")
        except PackageNotFoundError:
            ejs_version = None
        return yt_dlp_version, ejs_version

    @staticmethod
    def _build_commit() -> Optional[str]:
        for variable in ("AUTODROME_COMMIT", "GIT_COMMIT"):
            value = os.getenv(variable, "").strip().lower()
            if 7 <= len(value) <= 40 and all(
                character in "0123456789abcdef" for character in value
            ):
                return value
        return None

    @staticmethod
    def _filesystem_error_message(error: OSError) -> str:
        if isinstance(error, PermissionError) or error.errno in {errno.EACCES, errno.EPERM}:
            return "Permission denied while checking filesystem access."
        if error.errno == errno.ENOSPC:
            return "No space is available for a safe state write."
        if error.errno == errno.EROFS:
            return "Filesystem is read-only."
        return "Filesystem check failed."

    def _safe_sync_check(
        self,
        check: Callable[[], Component],
        failure_message: str,
    ) -> Component:
        try:
            return check()
        except Exception:
            return self._component("error", failure_message)

    @staticmethod
    def _component(status: str, message: str, **details: Any) -> Component:
        return {"status": status, "message": message, **details}
