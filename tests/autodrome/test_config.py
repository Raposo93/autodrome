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
        self.assertEqual(settings.download_concurrency, 1)
        self.assertFalse(settings.redis_enabled)

    def test_redis_can_be_enabled_explicitly(self):
        settings = self.build_config({**REQUIRED_ENV, "REDIS_ENABLED": "true"})

        self.assertTrue(settings.redis_enabled)

    def test_cover_optimization_can_be_disabled(self):
        settings = self.build_config(
            {**REQUIRED_ENV, "OPTIMIZE_OVERSIZED_COVERS": "false"}
        )

        self.assertFalse(settings.optimize_oversized_covers)

    def test_parallel_download_configuration_is_rejected_for_now(self):
        with self.assertRaisesRegex(ConfigurationError, "DOWNLOAD_CONCURRENCY"):
            self.build_config({**REQUIRED_ENV, "DOWNLOAD_CONCURRENCY": "2"})

    def test_missing_critical_configuration_is_actionable(self):
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
