import unittest
from unittest.mock import AsyncMock, MagicMock

from api.download import download, download_router


class TestDownloadEndpoint(unittest.IsolatedAsyncioTestCase):
    async def test_enqueue_response_contains_job_id(self):
        request = MagicMock()
        request.json = AsyncMock(
            return_value={
                "playlist_url": "https://example.test/playlist",
                "artist": "Artist",
                "album": "Album",
                "release_id": "release-1",
                "track_count": 1,
            }
        )
        request.app.state.queue_manager.enqueue = AsyncMock(return_value="job-1")

        response = await download(request)

        self.assertEqual(response, {"status": "queued", "job_id": "job-1"})

    def test_route_uses_http_202(self):
        route = next(route for route in download_router.routes if route.path == "/")

        self.assertEqual(route.status_code, 202)


if __name__ == "__main__":
    unittest.main()
