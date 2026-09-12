import unittest
from unittest.mock import AsyncMock, MagicMock, patch

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

    async def test_system_status_requires_token_on_external_host(self):
        app.state.system_status = AsyncMock()
        with patch.object(conf, "api_host", "0.0.0.0"), patch.object(
            conf, "api_token", "a" * 32
        ):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                response = await client.get("/api/status/")

        self.assertEqual(response.status_code, 401)
        app.state.system_status.snapshot.assert_not_awaited()

    async def test_history_mutations_require_token_on_external_host(self):
        app.state.queue_manager = AsyncMock()
        with patch.object(conf, "api_host", "0.0.0.0"), patch.object(conf, "api_token", "a" * 32):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                for method, path in (
                    ("delete", "/api/download/history"),
                    ("delete", "/api/download/jobs/job"),
                    ("post", "/api/download/jobs/job/retry"),
                ):
                    response = await getattr(client, method)(path)
                    self.assertEqual(response.status_code, 401)
        app.state.queue_manager.clear_history.assert_not_awaited()
        app.state.queue_manager.delete_job.assert_not_awaited()
        app.state.queue_manager.retry_job.assert_not_awaited()

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

    async def test_websocket_ticket_requires_http_authentication(self):
        ticket_store = MagicMock()
        app.state.websocket_ticket_store = ticket_store
        with patch.object(conf, "api_host", "0.0.0.0"), patch.object(
            conf, "api_token", "a" * 32
        ):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                response = await client.post("/api/auth/ws-ticket")

        self.assertEqual(response.status_code, 401)
        ticket_store.issue.assert_not_called()

    async def test_authenticated_client_can_request_websocket_ticket(self):
        ticket_store = MagicMock()
        ticket_store.issue.return_value = "ephemeral-ticket"
        ticket_store.ttl_seconds = 45
        app.state.websocket_ticket_store = ticket_store
        with patch.object(conf, "api_host", "0.0.0.0"), patch.object(
            conf, "api_token", "a" * 32
        ):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                response = await client.post(
                    "/api/auth/ws-ticket",
                    headers={"Authorization": f"Bearer {'a' * 32}"},
                )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.headers["cache-control"], "no-store")
        self.assertEqual(
            response.json(),
            {"ticket": "ephemeral-ticket", "expires_in": 45},
        )
        ticket_store.issue.assert_called_once_with()

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
