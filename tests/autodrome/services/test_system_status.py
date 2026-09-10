import errno
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from autodrome.services.system_status import SystemStatusService


class FakeRedisCache:
    def __init__(self):
        self.available = False
        self.error = None
        self.calls = 0

    def ping(self):
        self.calls += 1
        if self.error:
            raise self.error
        return self.available


class TestSystemStatusService(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        root = Path(self.temporary.name)
        self.library = root / "library"
        self.staging = root / "staging"
        self.library.mkdir()
        self.staging.mkdir()
        self.state_path = root / "queue.json"
        self.state_path.write_text('{"version": 1, "jobs": []}', encoding="utf-8")
        self.settings = SimpleNamespace(
            version="autodrome/test",
            library_path=str(self.library),
            staging_path=str(self.staging),
            google_api_key="private-youtube-key",
            redis_enabled=False,
        )
        self.http_client = MagicMock()

        async def provider_response(url, **kwargs):
            if url == SystemStatusService.YOUTUBE_DISCOVERY_URL:
                return {"id": "youtube:v3"}
            return {"artists": []}

        self.http_client.get = AsyncMock(side_effect=provider_response)
        self.redis_cache = FakeRedisCache()
        self.queue_manager = MagicMock()
        self.queue_manager.state_path = str(self.state_path)
        self.queue_manager.storage_error = None
        self.queue_manager.worker_task = MagicMock()
        self.queue_manager.worker_task.done.return_value = False
        self.queue_manager.snapshot.return_value = []
        self.ffmpeg_version = AsyncMock(return_value="ffmpeg version test")

    def tearDown(self):
        self.temporary.cleanup()

    def service(self):
        return SystemStatusService(
            settings=self.settings,
            http_client=self.http_client,
            redis_cache=self.redis_cache,
            queue_manager=self.queue_manager,
            ffmpeg_version=self.ffmpeg_version,
        )

    async def test_snapshot_reports_available_components_without_touching_queue_state(self):
        before = self.state_path.read_bytes()
        with patch.dict(os.environ, {"AUTODROME_COMMIT": "abcdef123456"}):
            result = await self.service().snapshot()

        self.assertEqual(result["version"], "autodrome/test")
        self.assertEqual(result["commit"], "abcdef123456")
        self.assertEqual(result["components"]["library"]["status"], "ok")
        self.assertGreaterEqual(result["components"]["library"]["free_bytes"], 0)
        self.assertEqual(result["components"]["staging"]["status"], "ok")
        self.assertEqual(result["components"]["queue_storage"]["status"], "ok")
        self.assertEqual(result["components"]["ffmpeg"]["message"], "ffmpeg version test")
        self.assertEqual(result["components"]["youtube"]["status"], "ok")
        self.assertEqual(result["components"]["musicbrainz"]["status"], "ok")
        self.assertEqual(result["components"]["redis"]["status"], "disabled")
        self.assertEqual(result["components"]["worker"]["state"], "idle")
        self.assertIsNone(result["storage_error"])
        self.assertEqual(self.state_path.read_bytes(), before)
        self.assertEqual(
            sorted(path.name for path in self.state_path.parent.iterdir()),
            ["library", "queue.json", "staging"],
        )
        self.assertEqual(self.redis_cache.calls, 0)
        self.assertEqual(self.http_client.get.await_count, 2)
        self.http_client.get.assert_any_await(
            SystemStatusService.YOUTUBE_DISCOVERY_URL,
            params={"fields": "id"},
            timeout=SystemStatusService.PROBE_TIMEOUT_SECONDS,
            provider="YouTube",
            context="checking service availability",
        )

    async def test_external_failures_are_reported_independently(self):
        self.ffmpeg_version.side_effect = FileNotFoundError()
        self.http_client.get.side_effect = RuntimeError("contact@example.test secret")
        self.settings.redis_enabled = True
        self.redis_cache.error = ConnectionError("redis://secret")

        result = await self.service().snapshot()

        components = result["components"]
        self.assertEqual(components["ffmpeg"]["status"], "error")
        self.assertEqual(components["youtube"]["status"], "error")
        self.assertTrue(components["youtube"]["configured"])
        self.assertEqual(components["musicbrainz"]["status"], "warning")
        self.assertEqual(components["redis"]["status"], "error")
        self.assertEqual(components["library"]["status"], "ok")
        self.assertNotIn("secret", str(result))

    async def test_youtube_not_configured_is_distinct_from_unreachable(self):
        self.settings.google_api_key = None

        result = await self.service().snapshot()

        youtube = result["components"]["youtube"]
        self.assertEqual(youtube["status"], "error")
        self.assertIn("not configured", youtube["message"])
        requested_urls = [
            call.args[0] for call in self.http_client.get.await_args_list
        ]
        self.assertNotIn(SystemStatusService.YOUTUBE_DISCOVERY_URL, requested_urls)

    async def test_unexpected_youtube_discovery_response_is_not_reported_as_ok(self):
        async def provider_response(url, **kwargs):
            if url == SystemStatusService.YOUTUBE_DISCOVERY_URL:
                return {"id": "another-api:v1"}
            return {"artists": []}

        self.http_client.get.side_effect = provider_response

        result = await self.service().snapshot()

        self.assertEqual(result["components"]["youtube"]["status"], "error")

    async def test_redis_enabled_and_reachable_is_ok(self):
        self.settings.redis_enabled = True
        self.redis_cache.available = True

        result = await self.service().snapshot()

        self.assertEqual(result["components"]["redis"]["status"], "ok")
        self.assertEqual(self.redis_cache.calls, 1)

    async def test_filesystem_failures_do_not_expose_paths(self):
        service = self.service()
        with patch(
            "autodrome.services.system_status.shutil.disk_usage",
            side_effect=PermissionError(errno.EACCES, "denied", str(self.library)),
        ):
            directory = service._check_directory(str(self.library))
        with patch(
            "autodrome.services.system_status.tempfile.mkstemp",
            side_effect=OSError(errno.ENOSPC, "full", str(self.state_path)),
        ):
            queue = service._check_queue_storage()

        self.assertEqual(directory["status"], "error")
        self.assertIn("Permission denied", directory["message"])
        self.assertNotIn(str(self.library), str(directory))
        self.assertEqual(queue["status"], "error")
        self.assertIn("No space", queue["message"])
        self.assertNotIn(str(self.state_path), str(queue))

    async def test_missing_directory_and_stopped_worker_are_visible(self):
        self.settings.staging_path = str(Path(self.temporary.name) / "missing")
        self.queue_manager.worker_task = None

        result = await self.service().snapshot()

        self.assertEqual(result["components"]["staging"]["status"], "warning")
        self.assertEqual(result["components"]["worker"]["state"], "error")

    async def test_worker_running_and_storage_pause_states(self):
        self.queue_manager.snapshot.return_value = [{"status": "running"}]
        running = await self.service().snapshot()
        self.assertEqual(running["components"]["worker"]["state"], "running")

        self.queue_manager.storage_error = (
            f"failed writing {self.state_path}: private-youtube-key"
        )
        paused = await self.service().snapshot()
        self.assertEqual(paused["components"]["worker"]["state"], "paused")
        self.assertNotIn(str(self.state_path), str(paused))
        self.assertNotIn("private-youtube-key", str(paused))
        self.assertIn("retry automatically", paused["storage_error"])
