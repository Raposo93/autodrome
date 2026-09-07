import unittest
from unittest.mock import AsyncMock, patch

from httpx import ASGITransport, AsyncClient

from app import app, conf


class TestApiAuthentication(unittest.IsolatedAsyncioTestCase):
    async def test_external_api_rejects_missing_token(self):
        with patch.object(conf, "api_host", "0.0.0.0"), patch.object(
            conf, "api_token", "a" * 32
        ):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                response = await client.get("/api/search/", params={"artist": "A"})

        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.headers["www-authenticate"], "Bearer")

    async def test_external_api_accepts_valid_bearer_token(self):
        app.state.search_controller = AsyncMock()
        app.state.search_controller.search.return_value = {
            "playlists": [],
            "releases": [],
        }
        with patch.object(conf, "api_host", "0.0.0.0"), patch.object(
            conf, "api_token", "a" * 32
        ):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                response = await client.get(
                    "/api/search/",
                    params={"artist": "Artist"},
                    headers={"Authorization": f"Bearer {'a' * 32}"},
                )

        self.assertEqual(response.status_code, 200)

    async def test_unconfigured_cors_origin_is_not_allowed(self):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.options(
                "/api/search/",
                headers={
                    "Origin": "https://untrusted.example.test",
                    "Access-Control-Request-Method": "GET",
                },
            )

        self.assertNotIn("access-control-allow-origin", response.headers)


if __name__ == "__main__":
    unittest.main()
