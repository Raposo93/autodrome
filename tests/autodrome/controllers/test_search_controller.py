import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock

from autodrome.controllers.search_controller import SearchController
from autodrome.models.playlist import Playlist
from autodrome.models.release import Release
from autodrome.http_client_async import UpstreamServiceError


class TestSearchController(unittest.IsolatedAsyncioTestCase):
    async def test_provider_results_and_errors_are_independent(self):
        for youtube_fails, musicbrainz_fails in [(False, False), (True, False), (False, True), (True, True)]:
            with self.subTest(youtube=youtube_fails, musicbrainz=musicbrainz_fails):
                controller = SearchController(http_client=MagicMock())
                controller.yt_api.search_playlist = AsyncMock(
                    return_value=[Playlist("p", "Album", "Channel", "url", None, 2)],
                    side_effect=UpstreamServiceError("YouTube", "searching", "timeout") if youtube_fails else None,
                )
                controller.metadata_service.search_releases = AsyncMock(
                    return_value=[Release("r", "Album", "2020", "Artist", None, track_count=2)],
                    side_effect=UpstreamServiceError("MusicBrainz", "searching", "timeout") if musicbrainz_fails else None,
                )
                result = await controller.search("Artist", "Album")
                self.assertEqual([p["id"] for p in result["playlists"]], [] if youtube_fails else ["p"])
                self.assertEqual([r["id"] for r in result["releases"]], [] if musicbrainz_fails else ["r"])
                self.assertEqual("youtube" in result["errors"], youtube_fails)
                self.assertEqual("musicbrainz" in result["errors"], musicbrainz_fails)
                for error in result["errors"].values():
                    self.assertIn("timeout", error)

    async def test_provider_searches_overlap(self):
        controller = SearchController(http_client=MagicMock())
        youtube_started = asyncio.Event()
        musicbrainz_started = asyncio.Event()

        async def youtube(query, limit, max_tracks):
            self.assertEqual(limit, 10)
            self.assertIsNone(max_tracks)
            youtube_started.set()
            await musicbrainz_started.wait()
            return []

        async def musicbrainz(artist, album, limit, max_tracks):
            self.assertEqual(limit, 10)
            self.assertIsNone(max_tracks)
            musicbrainz_started.set()
            await youtube_started.wait()
            return []

        controller.yt_api.search_playlist = youtube
        controller.metadata_service.search_releases = musicbrainz
        result = await asyncio.wait_for(controller.search("Artist", "Album"), 1)
        self.assertEqual(result, {"playlists": [], "releases": [], "errors": {}})

    async def test_search_forwards_shared_options_to_both_providers(self):
        controller = SearchController(http_client=MagicMock())
        controller.yt_api.search_playlist = AsyncMock(return_value=[])
        controller.metadata_service.search_releases = AsyncMock(return_value=[])

        await controller.search(
            "Artist",
            "Album",
            result_limit=37,
            max_tracks=28,
        )

        controller.yt_api.search_playlist.assert_awaited_once_with(
            "Artist Album", limit=37, max_tracks=28
        )
        controller.metadata_service.search_releases.assert_awaited_once_with(
            "Artist", "Album", limit=37, max_tracks=28
        )

    async def test_unexpected_provider_failure_preserves_other_results(self):
        controller = SearchController(http_client=MagicMock())
        controller.yt_api.search_playlist = AsyncMock(side_effect=ValueError("private detail"))
        controller.metadata_service.search_releases = AsyncMock(return_value=[])
        result = await controller.search("Artist", "Album")
        self.assertEqual(result["errors"], {"youtube": "Unexpected youtube search failure"})

    async def test_search_returns_remote_thumbnail_without_downloading_cover(self):
        controller = SearchController(http_client=MagicMock())
        controller.yt_api.search_playlist = AsyncMock(return_value=[])
        release = Release(
            release_id="release-1",
            title="Album",
            date="2020",
            artist="Artist",
            cover_url="https://archive.test/small.jpg",
            tracks=[],
            track_count=11,
        )
        controller.metadata_service.search_releases = AsyncMock(
            return_value=[release]
        )
        controller.metadata_service.get_cover_art = AsyncMock()

        result = await controller.search("Artist", "Album")

        self.assertEqual(
            result["releases"][0]["cover_url"],
            "https://archive.test/small.jpg",
        )
        self.assertEqual(result["releases"][0]["track_count"], 11)
        self.assertNotIn("tracks", result["releases"][0])
        controller.metadata_service.get_cover_art.assert_not_awaited()

    async def test_search_sorts_playlists_and_releases_by_track_count(self):
        controller = SearchController(http_client=MagicMock())
        controller.yt_api.search_playlist = AsyncMock(
            return_value=[
                Playlist("playlist-1", "One", "Channel", "url-1", None, 5),
                Playlist("playlist-2", "Two", "Channel", "url-2", None, None),
                Playlist("playlist-3", "Three", "Channel", "url-3", None, 12),
                Playlist("playlist-4", "Four", "Channel", "url-4", None, 5),
            ]
        )
        controller.metadata_service.search_releases = AsyncMock(
            return_value=[
                Release("release-1", "One", "2020", "Artist", None, track_count=8),
                Release("release-2", "Two", "2020", "Artist", None, track_count=None),
                Release("release-3", "Three", "2020", "Artist", None, track_count=10),
                Release("release-4", "Four", "2020", "Artist", None, track_count=8),
            ]
        )

        result = await controller.search("Artist", "Album")

        self.assertEqual(
            [playlist["id"] for playlist in result["playlists"]],
            ["playlist-3", "playlist-1", "playlist-4", "playlist-2"],
        )
        self.assertEqual(
            [release["id"] for release in result["releases"]],
            ["release-3", "release-1", "release-4", "release-2"],
        )

    async def test_shared_limit_and_track_filter_apply_to_both_result_sets(self):
        controller = SearchController(http_client=MagicMock())
        controller.yt_api.search_playlist = AsyncMock(
            return_value=[
                Playlist("playlist-1", "One", "Channel", "url-1", None, 8),
                Playlist("playlist-2", "Two", "Channel", "url-2", None, 30),
                Playlist("playlist-3", "Three", "Channel", "url-3", None, None),
            ]
        )
        controller.metadata_service.search_releases = AsyncMock(
            return_value=[
                Release("release-1", "One", "2020", "Artist", None, track_count=7),
                Release("release-2", "Two", "2020", "Artist", None, track_count=34),
                Release("release-3", "Three", "2020", "Artist", None, track_count=None),
            ]
        )

        result = await controller.search(
            "Artist", "Album", result_limit=2, max_tracks=20
        )

        self.assertEqual(
            [playlist["id"] for playlist in result["playlists"]],
            ["playlist-1", "playlist-3"],
        )
        self.assertEqual(
            [release["id"] for release in result["releases"]],
            ["release-1", "release-3"],
        )

    async def test_selected_release_returns_full_details(self):
        metadata_service = MagicMock()
        metadata_service.get_release = AsyncMock(
            return_value=Release(
                release_id="release-1",
                title="Album",
                date="2020",
                artist="Artist",
                cover_url="https://archive.test/small.jpg",
                tracks=[],
            )
        )
        controller = SearchController(
            http_client=MagicMock(),
            metadata_service=metadata_service,
        )

        with self.assertLogs("autodrome", level="INFO") as logs:
            details = await controller.get_release_details("release-1")

        self.assertEqual(details["id"], "release-1")
        self.assertEqual(details["track_count"], 0)
        self.assertEqual(details["tracks"], [])
        metadata_service.get_release.assert_awaited_once_with("release-1")
        self.assertTrue(
            any("details fetched in" in entry for entry in logs.output)
        )


if __name__ == "__main__":
    unittest.main()
