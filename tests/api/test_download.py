import unittest
from unittest.mock import AsyncMock, MagicMock

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from api.download import album_destination, download, download_router
from autodrome.models.requests import AlbumDestinationRequest, DownloadRequest


class TestDownloadEndpoint(unittest.IsolatedAsyncioTestCase):
    async def test_enqueue_response_contains_job_id(self):
        request = MagicMock()
        payload = DownloadRequest(
            playlist_url="https://www.youtube.com/playlist?list=PL1234567890",
            artist="Artist",
            album="Album",
            release_id="12345678-1234-1234-1234-123456789abc",
            track_count=1,
        )
        request.app.state.queue_manager.enqueue = AsyncMock(return_value="job-1")

        response = await download(payload, request)

        self.assertEqual(response, {"status": "queued", "job_id": "job-1"})

    async def test_destination_preflight_uses_organizer_result(self):
        request = MagicMock()
        request.app.state.downloader_controller.organizer.inspect_album_destination.return_value = {
            "state": "exists",
            "exists": True,
            "artist": "Artist",
            "album": "Album",
            "relative_path": "Artist/Album",
            "mp3_count": 2,
            "file_count": 3,
        }

        response = await album_destination(
            AlbumDestinationRequest(artist="Artist", album="Album"),
            request,
        )

        self.assertTrue(response["exists"])
        request.app.state.downloader_controller.organizer.inspect_album_destination.assert_called_once_with(
            "Artist", "Album"
        )

    async def test_queue_routes_delegate_and_return_results(self):
        app = FastAPI()
        app.include_router(download_router, prefix="/api/download")
        app.state.queue_manager = AsyncMock()
        app.state.queue_manager.clear_history.return_value = 3
        app.state.queue_manager.retry_job.return_value = "new-job"
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.delete("/api/download/history")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json(), {"removed": 3})
            response = await client.delete("/api/download/jobs/old-job")
            self.assertEqual(response.status_code, 200)
            app.state.queue_manager.delete_job.assert_awaited_once_with("old-job")
            response = await client.post("/api/download/jobs/queued-job/cancel")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(
                response.json(),
                {"status": "cancelled", "job_id": "queued-job"},
            )
            app.state.queue_manager.cancel_job.assert_awaited_once_with("queued-job")
            response = await client.post("/api/download/jobs/old-job/retry")
            self.assertEqual(response.status_code, 202)
            self.assertEqual(response.json(), {"status": "queued", "job_id": "new-job"})
            app.state.queue_manager.retry_job.assert_awaited_once_with("old-job")

    async def test_queue_routes_translate_rejections_and_persistence_errors(self):
        app = FastAPI()
        app.include_router(download_router, prefix="/api/download")
        app.state.queue_manager = AsyncMock()
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            for method, path, operation in (
                ("delete", "/api/download/jobs/job", "delete_job"),
                ("post", "/api/download/jobs/job/cancel", "cancel_job"),
                ("post", "/api/download/jobs/job/retry", "retry_job"),
                ("delete", "/api/download/history", "clear_history"),
            ):
                for error, expected in ((KeyError("missing"), 404), (ValueError("Active job"), 409), (OSError("private path"), 503)):
                    getattr(app.state.queue_manager, operation).side_effect = error
                    response = await getattr(client, method)(path)
                    self.assertEqual(response.status_code, expected)
                    self.assertNotIn("private path", response.text)

    def test_route_uses_http_202(self):
        route = next(route for route in download_router.routes if route.path == "/")

        self.assertEqual(route.status_code, 202)

    async def test_invalid_payload_returns_4xx_without_enqueue(self):
        app = FastAPI()
        app.include_router(download_router, prefix="/api/download")
        app.state.queue_manager = MagicMock()

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.post(
                "/api/download/",
                json={
                    "playlist_url": "http://127.0.0.1/private",
                    "artist": "..",
                    "album": "",
                    "release_id": "not-a-release-id",
                },
            )

        self.assertEqual(response.status_code, 422)
        app.state.queue_manager.enqueue.assert_not_called()


if __name__ == "__main__":
    unittest.main()
