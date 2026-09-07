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

        with self.assertLogs(level="WARNING") as logs:
            self.assertIsNone(cache.get_release("release-1"))
            cache.set_release("release-1", {"title": "Album"})

        self.assertTrue(any("Could not retrieve" in entry for entry in logs.output))
        self.assertTrue(any("Could not save" in entry for entry in logs.output))


if __name__ == "__main__":
    unittest.main()
