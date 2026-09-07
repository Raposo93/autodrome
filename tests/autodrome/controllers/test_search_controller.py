import unittest
from unittest.mock import AsyncMock, MagicMock

from autodrome.controllers.search_controller import SearchController
from autodrome.models.release import Release


class TestSearchController(unittest.IsolatedAsyncioTestCase):
    async def test_search_returns_remote_thumbnail_without_downloading_cover(self):
        controller = SearchController(http_client=MagicMock())
        controller.yt_api.search_playlist = AsyncMock(return_value=[])
        release = Release(
            release_id="release-1",
            title="Album",
            date="2020",
            artist="Artist",
            cover_url="https://archive.test/small.jpg",
            tracks=[],
        )
        controller.metadata_service.search_releases = AsyncMock(
            return_value=[release]
        )
        controller.metadata_service.get_cover_art = AsyncMock()

        result = await controller.search("Artist", "Album")

        self.assertEqual(
            result["releases"][0]["cover_url"],
            "https://archive.test/small.jpg",
        )
        controller.metadata_service.get_cover_art.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
