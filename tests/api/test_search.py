import unittest
from unittest.mock import AsyncMock, MagicMock

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from api.search import search_router
from autodrome.http_client_async import UpstreamServiceError


class TestSearchEndpoint(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.app = FastAPI()
        self.app.include_router(search_router, prefix="/api/search")
        self.app.state.search_controller = MagicMock()
        self.app.state.search_controller.search = AsyncMock(
            return_value={"playlists": [], "releases": []}
        )
        self.app.state.search_controller.get_release_details = AsyncMock(
            return_value={
                "id": "12345678-1234-1234-1234-123456789abc",
                "title": "Album",
                "date": "2020",
                "artist": "Artist",
                "cover_url": None,
                "tracks": [],
            }
        )

    async def test_valid_query_is_normalized(self):
        async with AsyncClient(
            transport=ASGITransport(app=self.app), base_url="http://test"
        ) as client:
            response = await client.get(
                "/api/search/", params={"artist": "  Artist  "}
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"playlists": [], "releases": []})
        self.app.state.search_controller.search.assert_awaited_once_with("Artist", "")

    async def test_empty_query_returns_4xx_without_searching(self):
        async with AsyncClient(
            transport=ASGITransport(app=self.app), base_url="http://test"
        ) as client:
            response = await client.get("/api/search/")

        self.assertEqual(response.status_code, 422)
        self.app.state.search_controller.search.assert_not_awaited()

    async def test_upstream_failure_returns_provider_and_bad_gateway(self):
        self.app.state.search_controller.search.side_effect = UpstreamServiceError(
            provider="MusicBrainz",
            context="searching releases",
            reason="request timed out",
            attempts=3,
        )

        async with AsyncClient(
            transport=ASGITransport(app=self.app), base_url="http://test"
        ) as client:
            response = await client.get(
                "/api/search/", params={"artist": "Artist"}
            )

        self.assertEqual(response.status_code, 502)
        self.assertEqual(response.json()["provider"], "MusicBrainz")
        self.assertEqual(
            response.json()["error"],
            "MusicBrainz failed while searching releases: request timed out "
            "after 3 attempts",
        )

    async def test_release_details_load_one_selected_release(self):
        release_id = "12345678-1234-1234-1234-123456789abc"

        async with AsyncClient(
            transport=ASGITransport(app=self.app), base_url="http://test"
        ) as client:
            response = await client.get(f"/api/search/releases/{release_id}")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["tracks"], [])
        self.app.state.search_controller.get_release_details.assert_awaited_once_with(
            release_id
        )

    async def test_release_details_reject_invalid_release_id(self):
        async with AsyncClient(
            transport=ASGITransport(app=self.app), base_url="http://test"
        ) as client:
            response = await client.get("/api/search/releases/not-a-uuid")

        self.assertEqual(response.status_code, 422)
        self.app.state.search_controller.get_release_details.assert_not_awaited()

    async def test_release_details_surface_upstream_failure(self):
        release_id = "12345678-1234-1234-1234-123456789abc"
        self.app.state.search_controller.get_release_details.side_effect = (
            UpstreamServiceError(
                provider="MusicBrainz",
                context=f"loading release {release_id}",
                reason="request timed out",
                attempts=3,
            )
        )

        async with AsyncClient(
            transport=ASGITransport(app=self.app), base_url="http://test"
        ) as client:
            response = await client.get(f"/api/search/releases/{release_id}")

        self.assertEqual(response.status_code, 502)
        self.assertEqual(response.json()["provider"], "MusicBrainz")
        self.assertIn(f"loading release {release_id}", response.json()["error"])


if __name__ == "__main__":
    unittest.main()
