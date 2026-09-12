import json
import unittest
from unittest.mock import MagicMock

from autodrome.services.redis_cache import NullCache, RedisCache


class TestNullCache(unittest.TestCase):
    def test_disabled_cache_is_a_silent_noop(self):
        cache = NullCache()

        with self.assertNoLogs("autodrome", level="WARNING"):
            self.assertIsNone(cache.get_release("release-1"))
            cache.set_release("release-1", {"title": "Album"})


class TestRedisCache(unittest.TestCase):
    def test_available_redis_reads_and_writes_releases(self):
        client = MagicMock()
        client.get.return_value = json.dumps({"title": "Album"})
        cache = RedisCache(client=client)

        self.assertEqual(cache.get_release("release-1"), {"title": "Album"})
        cache.set_release("release-1", {"title": "Album"})

        client.get.assert_called_once_with("release:release-1")
        client.set.assert_called_once_with(
            "release:release-1",
            json.dumps({"title": "Album"}),
        )

    def test_inaccessible_redis_behaves_as_cache_miss(self):
        client = MagicMock()
        client.get.side_effect = ConnectionError("Redis is down")
        client.set.side_effect = ConnectionError("Redis is down")
        cache = RedisCache(client=client)

        with self.assertLogs("autodrome", level="DEBUG") as logs:
            self.assertIsNone(cache.get_release("release-1"))
            self.assertIsNone(cache.get_release("release-1"))
            cache.set_release("release-1", {"title": "Album"})

        warning_entries = [entry for entry in logs.output if "WARNING" in entry]
        debug_entries = [entry for entry in logs.output if "DEBUG" in entry]
        self.assertEqual(len(warning_entries), 1)
        self.assertIn("redis_unavailable", warning_entries[0])
        self.assertIn("reason=connection_failed", warning_entries[0])
        self.assertEqual(len(debug_entries), 2)

    def test_redis_recovery_is_logged_once(self):
        client = MagicMock()
        client.get.side_effect = [ConnectionError("down"), None, None]
        cache = RedisCache(client=client)

        with self.assertLogs("autodrome", level="INFO") as logs:
            self.assertIsNone(cache.get_release("release-1"))
            self.assertIsNone(cache.get_release("release-1"))
            self.assertIsNone(cache.get_release("release-1"))

        self.assertEqual(
            sum("redis_unavailable" in entry for entry in logs.output),
            1,
        )
        self.assertEqual(
            sum("redis_recovered" in entry for entry in logs.output),
            1,
        )

    def test_ping_reports_client_availability(self):
        client = MagicMock()
        client.ping.return_value = True

        self.assertTrue(RedisCache(client=client).ping())
        self.assertFalse(NullCache().ping())


if __name__ == "__main__":
    unittest.main()
