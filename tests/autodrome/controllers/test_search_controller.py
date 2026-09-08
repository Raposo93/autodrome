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
            track_count=11,
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
        self.assertEqual(result["releases"][0]["track_count"], 11)
        self.assertNotIn("tracks", result["releases"][0])
        controller.metadata_service.get_cover_art.assert_not_awaited()

    async def test_selected_release_returns_full_details(self):
        metadata_service = MagicMock()
        metadata_service.get_release = AsyncMock(
            return_value=Release(
                release_id="release-1",
                title="Album",
                date="2020",
                artist="Artist",
                cover_url="https://archive.test/small.jpg",
                tracks=[],
            )
        )
        controller = SearchController(
            http_client=MagicMock(),
            metadata_service=metadata_service,
        )

        with self.assertLogs("autodrome", level="INFO") as logs:
            details = await controller.get_release_details("release-1")

        self.assertEqual(details["id"], "release-1")
        self.assertEqual(details["track_count"], 0)
        self.assertEqual(details["tracks"], [])
        metadata_service.get_release.assert_awaited_once_with("release-1")
        self.assertTrue(
            any("details fetched in" in entry for entry in logs.output)
        )


if __name__ == "__main__":
    unittest.main()
