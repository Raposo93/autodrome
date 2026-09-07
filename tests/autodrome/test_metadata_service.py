import unittest
from unittest.mock import AsyncMock, MagicMock

from autodrome.metadata_service import MetadataService
from autodrome.models.release import Release


class TestMetadataService(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.http_client = MagicMock()
        self.http_client.get = AsyncMock()
        self.service = MetadataService(http_client=self.http_client)
        self.service.redis_cache = MagicMock()

    async def test_search_releases_returns_correct_releases(self):
        self.http_client.get.return_value = {
            "releases": [
                {
                    "id": "release1",
                    "title": "Test Album",
                    "date": "2020-01-01",
                    "artist-credit": [{"name": "Test Artist"}],
                }
            ]
        }
        self.service.redis_cache.get_release.return_value = None
        self.service._get_tracks = AsyncMock(return_value=[])
        self.service._get_cover_url = AsyncMock(return_value=None)

        releases = await self.service.search_releases("Test Artist", "Test Album")

        self.assertEqual(len(releases), 1)
        release = releases[0]
        self.assertIsInstance(release, Release)
        self.assertEqual(release.id, "release1")
        self.assertEqual(release.title, "Test Album")
        self.assertEqual(release.date, "2020-01-01")
        self.assertEqual(release.artist, "Test Artist")
        self.assertEqual(release.tracks, [])
        self.service._get_tracks.assert_awaited_once_with("release1")
        self.service.redis_cache.set_release.assert_called_once()

    async def test_search_releases_handles_empty_response(self):
        self.http_client.get.return_value = {}

        releases = await self.service.search_releases(None, None)

        self.assertEqual(releases, [])


if __name__ == "__main__":
    unittest.main()
