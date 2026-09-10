import unittest
from unittest.mock import AsyncMock, MagicMock

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from api.status import status_router, system_status


class TestSystemStatusEndpoint(unittest.IsolatedAsyncioTestCase):
    async def test_endpoint_delegates_to_diagnostic_service(self):
        report = {
            "version": "autodrome/test",
            "commit": None,
            "components": {"worker": {"status": "ok", "message": "Idle"}},
            "storage_error": None,
        }
        app = FastAPI()
        app.include_router(status_router, prefix="/api/status")
        app.state.system_status = AsyncMock()
        app.state.system_status.snapshot.return_value = report

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.get("/api/status/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), report)
        app.state.system_status.snapshot.assert_awaited_once_with()

    async def test_route_function_returns_partial_report(self):
        request = MagicMock()
        request.app.state.system_status.snapshot = AsyncMock(
            return_value={
                "components": {
                    "youtube": {"status": "error"},
                    "library": {"status": "ok"},
                }
            }
        )

        result = await system_status(request)

        self.assertEqual(result["components"]["youtube"]["status"], "error")
        self.assertEqual(result["components"]["library"]["status"], "ok")
