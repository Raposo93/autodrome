import os
import logging
import math
from urllib.parse import urlsplit
from typing import Optional

from dotenv import load_dotenv
from autodrome.logger import configure_logging
from autodrome.version import default_runtime_version


MAX_DOWNLOAD_CONCURRENCY = 4


class ConfigurationError(RuntimeError):
    pass


class Config:
    def __init__(self):
        load_dotenv()
        self.google_api_key = os.getenv("GOOGLE_API_KEY")
        self.contact_email = os.getenv("CONTACT_EMAIL")
        self.version = os.getenv("VERSION") or default_runtime_version()
        self.user_agent = f"{self.version} ({self.contact_email})"
        self.library_path = os.getenv("LIBRARY_PATH", "library")
        self.staging_path = os.getenv(
            "STAGING_PATH",
            os.path.join(self.library_path, ".autodrome-staging"),
        )
        self.minimum_staging_free_bytes = self._read_int(
            "MIN_STAGING_FREE_BYTES", 1024 * 1024 * 1024, minimum=0
        )
        self.preserve_failed_staging = self._read_bool(
            "PRESERVE_FAILED_STAGING", True
        )
        self.max_embedded_cover_bytes = self._read_int(
            "MAX_EMBEDDED_COVER_BYTES", 1024 * 1024, minimum=1
        )
        self.optimize_oversized_covers = self._read_bool(
            "OPTIMIZE_OVERSIZED_COVERS", True
        )
        self.max_embedded_cover_width = self._read_int(
            "MAX_EMBEDDED_COVER_WIDTH", 1600, minimum=1
        )
        self.max_embedded_cover_height = self._read_int(
            "MAX_EMBEDDED_COVER_HEIGHT", 1600, minimum=1
        )
        self.max_cover_source_pixels = self._read_int(
            "MAX_COVER_SOURCE_PIXELS", 40_000_000, minimum=1
        )
        self.max_cover_upload_bytes = self._read_int(
            "MAX_COVER_UPLOAD_BYTES", 10 * 1024 * 1024, minimum=1
        )
        self.cover_storage_path = os.getenv(
            "COVER_STORAGE_PATH", os.path.join("covers", "selected")
        )
        self.queue_state_path = os.getenv(
            "QUEUE_STATE_PATH",
            os.path.join(self.library_path, ".autodrome-queue.json"),
        )
        self.download_concurrency = self._read_int(
            "DOWNLOAD_CONCURRENCY",
            1,
            minimum=1,
            maximum=MAX_DOWNLOAD_CONCURRENCY,
        )
        self.yt_dlp_deno_path = os.getenv("YT_DLP_DENO_PATH", "").strip() or None
        self.musicbrainz_timeout_seconds = self._read_float(
            "MUSICBRAINZ_TIMEOUT_SECONDS", 20, minimum=0, exclusive=True
        )
        self.musicbrainz_max_attempts = self._read_int(
            "MUSICBRAINZ_MAX_ATTEMPTS", 3, minimum=1
        )
        self.musicbrainz_retry_base_seconds = self._read_float(
            "MUSICBRAINZ_RETRY_BASE_SECONDS", 1, minimum=0
        )
        self.redis_enabled = self._read_bool("REDIS_ENABLED", False)
        self.api_host = os.getenv("API_HOST", "127.0.0.1").strip()
        self.api_port = self._read_int("API_PORT", 5000, minimum=1, maximum=65535)
        self.api_token = os.getenv("API_TOKEN")
        self.cors_origins = [
            origin.strip()
            for origin in os.getenv("CORS_ORIGINS", "").split(",")
            if origin.strip()
        ]

        log_level_str = os.getenv("LOG_LEVEL", "INFO").upper()
        self.log_level = getattr(logging, log_level_str, logging.INFO)
        self.log_file = os.getenv("LOG_FILE", "").strip() or None
        self.log_max_bytes = self._read_int(
            "LOG_MAX_BYTES", 10 * 1024 * 1024, minimum=1
        )
        self.log_backup_count = self._read_int(
            "LOG_BACKUP_COUNT", 3, minimum=1
        )
        configure_logging(
            self.log_level,
            log_file=self.log_file,
            max_bytes=self.log_max_bytes,
            backup_count=self.log_backup_count,
        )

    @property
    def requires_api_token(self) -> bool:
        return self.api_host.lower() not in {"127.0.0.1", "::1", "localhost"}

    def validate(self) -> None:
        required_values = {
            "GOOGLE_API_KEY": self.google_api_key,
            "CONTACT_EMAIL": self.contact_email,
            "VERSION": self.version,
            "LIBRARY_PATH": self.library_path,
        }
        missing = [name for name, value in required_values.items() if not value]
        if missing:
            raise ConfigurationError(
                f"Missing required configuration: {', '.join(missing)}"
            )

        if (
            not self.api_host
            or any(character.isspace() for character in self.api_host)
            or "/" in self.api_host
        ):
            raise ConfigurationError("API_HOST must be a hostname or IP address")

        if self.requires_api_token and (
            self.api_token is None
            or self.api_token.strip() != self.api_token
            or len(self.api_token) < 32
        ):
            raise ConfigurationError(
                "API_TOKEN must contain at least 32 characters when API_HOST "
                "is not loopback"
            )

        for origin in self.cors_origins:
            try:
                parsed = urlsplit(origin)
                hostname = parsed.hostname
                parsed.port
            except ValueError as e:
                raise ConfigurationError(f"Invalid CORS origin: {origin}") from e
            if (
                origin == "*"
                or parsed.scheme not in {"http", "https"}
                or not hostname
                or parsed.username
                or parsed.password
                or parsed.path not in {"", "/"}
                or parsed.query
                or parsed.fragment
            ):
                raise ConfigurationError(f"Invalid CORS origin: {origin}")

    @staticmethod
    def _read_int(
        name: str,
        default: int,
        minimum: int,
        maximum: Optional[int] = None,
    ) -> int:
        raw_value = os.getenv(name, str(default))
        try:
            value = int(raw_value)
        except ValueError as e:
            raise ConfigurationError(f"{name} must be an integer") from e
        if value < minimum or (maximum is not None and value > maximum):
            expected = (
                f"between {minimum} and {maximum}"
                if maximum is not None
                else f"at least {minimum}"
            )
            raise ConfigurationError(f"{name} must be {expected}")
        return value

    @staticmethod
    def _read_float(
        name: str, default: float, minimum: float, exclusive: bool = False
    ) -> float:
        try:
            value = float(os.getenv(name, str(default)))
        except ValueError as e:
            raise ConfigurationError(f"{name} must be a number") from e
        if not math.isfinite(value) or value < minimum or (exclusive and value == minimum):
            comparison = "greater than" if exclusive else "at least"
            raise ConfigurationError(f"{name} must be finite and {comparison} {minimum}")
        return value

    @staticmethod
    def _read_bool(name: str, default: bool) -> bool:
        raw_value = os.getenv(name, str(default)).lower()
        if raw_value in {"1", "true", "yes", "on"}:
            return True
        if raw_value in {"0", "false", "no", "off"}:
            return False
        raise ConfigurationError(f"{name} must be true or false")
