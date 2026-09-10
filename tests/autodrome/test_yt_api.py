import unittest
from unittest.mock import AsyncMock, MagicMock

from autodrome.http_client_async import UpstreamServiceError
from autodrome.models.playlist import Playlist
from autodrome.yt_api import YTApi


def search_page(playlist_ids, next_page_token=None):
    data = {
        "items": [
            {
                "id": {
                    "kind": "youtube#playlist",
                    "playlistId": playlist_id,
                }
            }
            for playlist_id in playlist_ids
        ]
    }
    if next_page_token is not None:
        data["nextPageToken"] = next_page_token
    return data


def playlist_details(track_counts):
    return {
        "items": [
            {
                "id": playlist_id,
                "contentDetails": {"itemCount": track_count},
            }
            for playlist_id, track_count in track_counts.items()
        ]
    }


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
        search_request = self.http_client.get.await_args_list[0]
        self.assertEqual(search_request.kwargs["params"]["maxResults"], 10)

    async def test_search_playlist_uses_requested_limit(self):
        for limit in (1, 23, 50):
            with self.subTest(limit=limit):
                self.http_client.get.reset_mock()
                self.http_client.get.return_value = {"items": []}

                await self.api.search_playlist("test query", limit=limit)

                search_request = self.http_client.get.await_args
                self.assertEqual(
                    search_request.kwargs["params"]["maxResults"], limit
                )

    async def test_disabled_filter_does_not_follow_next_page(self):
        self.http_client.get.side_effect = [
            search_page(["PL1"], next_page_token="next"),
            playlist_details({"PL1": 40}),
        ]

        results = await self.api.search_playlist("album", limit=10)

        self.assertEqual([playlist.id for playlist in results], ["PL1"])
        self.assertEqual(self.http_client.get.await_count, 2)

    async def test_filter_excludes_only_known_counts_above_maximum(self):
        self.http_client.get.side_effect = [
            search_page(["too-large", "boundary", "unknown"]),
            playlist_details({"too-large": 31, "boundary": 30}),
        ]

        results = await self.api.search_playlist(
            "album",
            limit=3,
            max_tracks=30,
        )

        self.assertEqual(
            [(playlist.id, playlist.track_count) for playlist in results],
            [("boundary", 30), ("unknown", None)],
        )
        details_request = self.http_client.get.await_args_list[1]
        self.assertEqual(
            details_request.kwargs["params"]["id"],
            "too-large,boundary,unknown",
        )

    async def test_filter_fills_from_next_page_and_deduplicates(self):
        self.http_client.get.side_effect = [
            search_page(["large-1", "valid-1", "large-2"], "page-2"),
            playlist_details({"large-1": 20, "valid-1": 2, "large-2": 30}),
            search_page(["valid-1", "valid-2", "valid-3"], "unused-page"),
            playlist_details({"valid-2": 5, "valid-3": 6}),
        ]

        results = await self.api.search_playlist(
            "album",
            limit=3,
            max_tracks=10,
        )

        self.assertEqual(
            [playlist.id for playlist in results],
            ["valid-1", "valid-2", "valid-3"],
        )
        self.assertEqual(self.http_client.get.await_count, 4)
        second_search = self.http_client.get.await_args_list[2]
        self.assertEqual(second_search.kwargs["params"]["pageToken"], "page-2")
        self.assertEqual(second_search.kwargs["params"]["maxResults"], 3)
        second_details = self.http_client.get.await_args_list[3]
        self.assertEqual(
            second_details.kwargs["params"]["id"],
            "valid-2,valid-3",
        )

    async def test_filter_stops_after_fifty_examined_candidates(self):
        responses = []
        expected_page_sizes = [7, 7, 7, 7, 7, 7, 7, 1]
        for page_number, page_size in enumerate(expected_page_sizes):
            ids = [
                f"page-{page_number}-playlist-{index}"
                for index in range(page_size)
            ]
            responses.extend(
                [
                    search_page(ids, f"page-{page_number + 1}"),
                    playlist_details({playlist_id: 99 for playlist_id in ids}),
                ]
            )
        self.http_client.get.side_effect = responses

        results = await self.api.search_playlist(
            "album",
            limit=7,
            max_tracks=10,
        )

        self.assertEqual(results, [])
        search_requests = [
            call
            for call in self.http_client.get.await_args_list
            if call.args[0].endswith("/search")
        ]
        self.assertEqual(len(search_requests), 8)
        self.assertEqual(
            [call.kwargs["params"]["maxResults"] for call in search_requests],
            expected_page_sizes,
        )

    async def test_additional_page_failure_is_propagated(self):
        failure = UpstreamServiceError(
            "YouTube",
            "searching playlists",
            "second page failed",
        )
        self.http_client.get.side_effect = [
            search_page(["large-1", "large-2"], "page-2"),
            playlist_details({"large-1": 20, "large-2": 30}),
            failure,
        ]

        with self.assertRaises(UpstreamServiceError) as raised:
            await self.api.search_playlist(
                "album",
                limit=2,
                max_tracks=10,
            )
        self.assertIs(raised.exception, failure)

    async def test_search_options_reject_invalid_direct_calls(self):
        invalid_options = [
            {"limit": 0},
            {"limit": 51},
            {"limit": 1.5},
            {"limit": True},
            {"max_tracks": 0},
            {"max_tracks": 1.5},
            {"max_tracks": True},
        ]
        for options in invalid_options:
            with self.subTest(options=options):
                with self.assertRaises(ValueError):
                    await self.api.search_playlist("album", **options)

        self.http_client.get.assert_not_awaited()

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
