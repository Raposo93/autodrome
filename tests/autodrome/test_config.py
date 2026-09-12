import os
import unittest
from unittest.mock import patch

from autodrome.config import Config, ConfigurationError


REQUIRED_ENV = {
    "GOOGLE_API_KEY": "test-key",
    "CONTACT_EMAIL": "admin@example.test",
    "VERSION": "autodrome/test",
    "LIBRARY_PATH": "/tmp/autodrome-library",
}


class TestConfig(unittest.TestCase):
    def build_config(self, values):
        with patch("autodrome.config.load_dotenv"), patch.dict(
            os.environ, values, clear=True
        ):
            return Config()

    def test_loopback_and_closed_cors_are_defaults(self):
        settings = self.build_config(REQUIRED_ENV)

        settings.validate()

        self.assertEqual(settings.api_host, "127.0.0.1")
        self.assertFalse(settings.requires_api_token)
        self.assertEqual(settings.cors_origins, [])
        self.assertEqual(settings.max_embedded_cover_bytes, 1024 * 1024)
        self.assertTrue(settings.optimize_oversized_covers)
        self.assertEqual(settings.max_embedded_cover_width, 1600)
        self.assertEqual(settings.max_embedded_cover_height, 1600)
        self.assertEqual(settings.max_cover_source_pixels, 40_000_000)
        self.assertEqual(settings.max_cover_upload_bytes, 10 * 1024 * 1024)
        self.assertEqual(settings.cover_storage_path, "covers/selected")
        self.assertEqual(settings.download_concurrency, 1)
        self.assertIsNone(settings.yt_dlp_deno_path)
        self.assertFalse(settings.redis_enabled)
        self.assertIsNone(settings.log_file)
        self.assertEqual(settings.log_max_bytes, 10 * 1024 * 1024)
        self.assertEqual(settings.log_backup_count, 3)

    def test_rotating_log_file_options_are_explicit(self):
        settings = self.build_config({
            **REQUIRED_ENV,
            "LOG_FILE": "/tmp/autodrome-test.log",
            "LOG_MAX_BYTES": "4096",
            "LOG_BACKUP_COUNT": "2",
        })

        self.assertEqual(settings.log_file, "/tmp/autodrome-test.log")
        self.assertEqual(settings.log_max_bytes, 4096)
        self.assertEqual(settings.log_backup_count, 2)

    def test_installed_package_version_is_the_default(self):
        with patch(
            "autodrome.config.default_runtime_version",
            return_value="autodrome/0.2.0",
        ):
            settings = self.build_config(
                {key: value for key, value in REQUIRED_ENV.items() if key != "VERSION"}
            )

        self.assertEqual(settings.version, "autodrome/0.2.0")
        settings.validate()

    def test_musicbrainz_policy_defaults_and_overrides(self):
        settings = self.build_config(REQUIRED_ENV)
        self.assertEqual(settings.musicbrainz_timeout_seconds, 20)
        self.assertEqual(settings.musicbrainz_max_attempts, 3)
        self.assertEqual(settings.musicbrainz_retry_base_seconds, 1)
        settings = self.build_config({
            **REQUIRED_ENV, "MUSICBRAINZ_TIMEOUT_SECONDS": "30.5",
            "MUSICBRAINZ_MAX_ATTEMPTS": "1", "MUSICBRAINZ_RETRY_BASE_SECONDS": "0",
        })
        self.assertEqual(settings.musicbrainz_timeout_seconds, 30.5)
        self.assertEqual(settings.musicbrainz_max_attempts, 1)
        self.assertEqual(settings.musicbrainz_retry_base_seconds, 0)

    def test_invalid_musicbrainz_policy_is_rejected(self):
        for name, values in {
            "MUSICBRAINZ_TIMEOUT_SECONDS": ["0", "-1", "nan", "inf", "bad"],
            "MUSICBRAINZ_MAX_ATTEMPTS": ["0", "-1", "1.5", "bad"],
            "MUSICBRAINZ_RETRY_BASE_SECONDS": ["-1", "nan", "inf", "bad"],
        }.items():
            for value in values:
                with self.subTest(name=name, value=value):
                    with self.assertRaisesRegex(ConfigurationError, name):
                        self.build_config({**REQUIRED_ENV, name: value})

    def test_redis_can_be_enabled_explicitly(self):
        settings = self.build_config({**REQUIRED_ENV, "REDIS_ENABLED": "true"})

        self.assertTrue(settings.redis_enabled)

    def test_cover_optimization_can_be_disabled(self):
        settings = self.build_config(
            {**REQUIRED_ENV, "OPTIMIZE_OVERSIZED_COVERS": "false"}
        )

        self.assertFalse(settings.optimize_oversized_covers)

    def test_cover_storage_path_can_be_configured(self):
        settings = self.build_config(
            {**REQUIRED_ENV, "COVER_STORAGE_PATH": "/var/lib/autodrome/covers"}
        )

        self.assertEqual(
            settings.cover_storage_path,
            "/var/lib/autodrome/covers",
        )

    def test_limited_track_download_concurrency_can_be_configured(self):
        for concurrency in (1, 2, 4):
            with self.subTest(concurrency=concurrency):
                settings = self.build_config(
                    {
                        **REQUIRED_ENV,
                        "DOWNLOAD_CONCURRENCY": str(concurrency),
                    }
                )
                self.assertEqual(settings.download_concurrency, concurrency)

    def test_track_download_concurrency_outside_supported_range_is_rejected(self):
        for concurrency in ("0", "5", "1.5", "many"):
            with self.subTest(concurrency=concurrency):
                with self.assertRaisesRegex(
                    ConfigurationError,
                    "DOWNLOAD_CONCURRENCY",
                ):
                    self.build_config(
                        {
                            **REQUIRED_ENV,
                            "DOWNLOAD_CONCURRENCY": concurrency,
                        }
                    )

    def test_explicit_deno_path_is_trimmed(self):
        settings = self.build_config(
            {**REQUIRED_ENV, "YT_DLP_DENO_PATH": "  /opt/deno/bin/deno  "}
        )

        self.assertEqual(settings.yt_dlp_deno_path, "/opt/deno/bin/deno")

    def test_missing_critical_configuration_is_actionable(self):
        with patch("autodrome.config.default_runtime_version", return_value=None):
            settings = self.build_config({})

        with self.assertRaisesRegex(
            ConfigurationError,
            "GOOGLE_API_KEY, CONTACT_EMAIL, VERSION",
        ):
            settings.validate()

    def test_external_host_requires_long_token(self):
        settings = self.build_config({**REQUIRED_ENV, "API_HOST": "0.0.0.0"})

        with self.assertRaisesRegex(ConfigurationError, "API_TOKEN"):
            settings.validate()

        settings = self.build_config(
            {
                **REQUIRED_ENV,
                "API_HOST": "0.0.0.0",
                "API_TOKEN": "a" * 32,
            }
        )
        settings.validate()

    def test_api_host_rejects_urls(self):
        settings = self.build_config(
            {**REQUIRED_ENV, "API_HOST": "https://example.test"}
        )

        with self.assertRaisesRegex(ConfigurationError, "API_HOST"):
            settings.validate()

    def test_cors_origins_are_explicit_and_validated(self):
        settings = self.build_config(
            {
                **REQUIRED_ENV,
                "CORS_ORIGINS": "http://localhost:5173,https://music.example.test",
            }
        )

        settings.validate()

        self.assertEqual(
            settings.cors_origins,
            ["http://localhost:5173", "https://music.example.test"],
        )

        wildcard = self.build_config({**REQUIRED_ENV, "CORS_ORIGINS": "*"})
        with self.assertRaisesRegex(ConfigurationError, "Invalid CORS origin"):
            wildcard.validate()


if __name__ == "__main__":
    unittest.main()
