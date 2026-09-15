import unittest
from unittest.mock import AsyncMock, MagicMock

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from api.publications import publication_router


class TestPublicationEndpoints(unittest.IsolatedAsyncioTestCase):
    async def test_history_detail_and_recreate_delegate_without_enqueuing(self):
        app = FastAPI()
        app.include_router(publication_router, prefix="/api/publications")
        controller = MagicMock()
        controller.list_publications.return_value = [{"publication_id": "pub-1"}]
        controller.get_publication.return_value = {"publication_id": "pub-1", "files": []}
        controller.recreate_review = AsyncMock(return_value={"enqueued": False})
        app.state.publication_controller = controller

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            assert (await client.get("/api/publications/")).json() == [{"publication_id": "pub-1"}]
            assert (await client.get("/api/publications/pub-1")).json()["files"] == []
            recreate = await client.post("/api/publications/pub-1/recreate")
            assert recreate.status_code == 200
            assert recreate.json() == {"enqueued": False}
        controller.recreate_review.assert_awaited_once_with("pub-1")

    async def test_missing_publication_is_404(self):
        app = FastAPI()
        app.include_router(publication_router, prefix="/api/publications")
        controller = MagicMock()
        controller.get_publication.side_effect = KeyError("missing")
        controller.recreate_review = AsyncMock(side_effect=KeyError("missing"))
        app.state.publication_controller = controller
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            assert (await client.get("/api/publications/missing")).status_code == 404
            assert (await client.post("/api/publications/missing/recreate")).status_code == 404
