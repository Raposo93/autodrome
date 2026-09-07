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


if __name__ == "__main__":
    unittest.main()
