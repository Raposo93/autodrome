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
            "items": [{"id": "PL123", "contentDetails": {"itemCount": 42}}]
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

    async def test_text_is_decoded_once_at_provider_boundary(self):
        cases = [
            ('A &quot;live&quot; &amp; B', 'A "live" & B'),
            ("L&#39;été &apos;26 &#x1F3B5;", "L'été '26 🎵"),
            ("Björk — 日本語 🎵 & café", "Björk — 日本語 🎵 & café"),
            ("Literal &amp;quot; and &amp;amp;", "Literal &quot; and &amp;"),
            ("Notes &notebook &notit; &unknown;", "Notes &notebook &notit; &unknown;"),
        ]
        for raw, expected in cases:
            with self.subTest(raw=raw):
                self.http_client.get.side_effect = [
                    {"items": [{
                        "id": {"kind": "youtube#playlist", "playlistId": "PL123"},
                        "snippet": {"title": raw, "channelTitle": raw},
                    }]},
                    {"items": [{"id": "PL123", "contentDetails": {"itemCount": 1}}]},
                ]
                playlist, = await self.api.search_playlist("query")
                self.assertEqual(playlist.title, expected)
                self.assertEqual(playlist.channel, expected)

    async def test_search_playlist_handles_empty_response(self):
        self.http_client.get.return_value = {}

        results = await self.api.search_playlist("empty")

        self.assertEqual(results, [])
        self.http_client.get.assert_awaited_once()

    async def test_ten_playlists_use_one_details_request_and_match_by_id(self):
        ids = [f"PL{i}" for i in range(10)]
        for returned_ids in [list(reversed(ids)), ["PL8", "PL2"], []]:
            with self.subTest(returned_ids=returned_ids):
                self.http_client.get.reset_mock()
                self.http_client.get.side_effect = [
                    {"items": [
                        {"id": {"kind": "youtube#playlist", "playlistId": pid}}
                        for pid in ids
                    ]},
                    {"items": [
                        {"id": pid, "contentDetails": {"itemCount": int(pid[2:])}}
                        for pid in returned_ids
                    ]},
                ]
                results = await self.api.search_playlist("album")
                self.assertEqual([p.id for p in results], ids)
                self.assertEqual(
                    [p.track_count for p in results],
                    [i if pid in returned_ids else None for i, pid in enumerate(ids)],
                )
                self.assertEqual(self.http_client.get.await_count, 2)
                details = self.http_client.get.call_args
                self.assertTrue(details.args[0].endswith("/playlists"))
                self.assertEqual(details.kwargs["params"]["id"], ",".join(ids))
                self.assertEqual(details.kwargs["params"]["maxResults"], 50)

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
            await self.api._get_track_counts(["any_id"])


if __name__ == "__main__":
    unittest.main()
