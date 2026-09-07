import unittest
from unittest.mock import AsyncMock, MagicMock

from autodrome.models.playlist import Playlist
from autodrome.yt_api import YTApi


class TestYTApi(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.http_client = MagicMock()
        self.http_client.get = AsyncMock()
        self.api = YTApi(self.http_client)

    async def test_search_playlist_returns_playlists(self):
        search_response = {
            "items": [
                {
                    "id": {
                        "kind": "youtube#playlist",
                        "playlistId": "PL123",
                    },
                    "snippet": {
                        "title": "Test Playlist",
                        "channelTitle": "Test Channel",
                        "thumbnails": {
                            "medium": {"url": "http://image.url/thumbnail.jpg"}
                        },
                    },
                }
            ]
        }
        count_response = {
            "items": [{"contentDetails": {"itemCount": 42}}]
        }
        self.http_client.get.side_effect = [search_response, count_response]

        results = await self.api.search_playlist("test query")

        self.assertEqual(len(results), 1)
        playlist = results[0]
        self.assertIsInstance(playlist, Playlist)
        self.assertEqual(playlist.id, "PL123")
        self.assertEqual(playlist.title, "Test Playlist")
        self.assertEqual(playlist.channel, "Test Channel")
        self.assertEqual(playlist.thumbnail, "http://image.url/thumbnail.jpg")
        self.assertEqual(playlist.track_count, 42)
        self.assertEqual(
            playlist.url, "https://www.youtube.com/playlist?list=PL123"
        )

    async def test_search_playlist_handles_empty_response(self):
        self.http_client.get.return_value = {}

        results = await self.api.search_playlist("empty")

        self.assertEqual(results, [])

    async def test_search_playlist_handles_missing_playlist_id(self):
        self.http_client.get.return_value = {
            "items": [
                {
                    "id": {"kind": "youtube#playlist"},
                    "snippet": {"title": "No ID", "channelTitle": "Channel"},
                }
            ]
        }

        results = await self.api.search_playlist("missing id")

        self.assertEqual(results, [])

    async def test_get_track_count_propagates_upstream_error(self):
        self.http_client.get.side_effect = Exception("API error")

        with self.assertRaisesRegex(Exception, "API error"):
            await self.api._get_track_count("any_id")


if __name__ == "__main__":
    unittest.main()
