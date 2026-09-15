import unittest
from unittest.mock import AsyncMock, MagicMock

from autodrome.controllers.publication_controller import PublicationController
from autodrome.models.release import Release
from autodrome.models.track import Track


ORIGINAL = {
    "record_version": 1,
    "publication_id": "publication-1",
    "job_id": "job-1",
    "published_at": "2026-09-15T12:00:00+00:00",
    "destination": {"relative_path": "Artist/Album", "artist": "Artist", "album": "Album"},
    "metadata": {"mode": "musicbrainz", "artist": "Artist", "album": "Album", "date": "2020", "tracks": []},
    "release": {
        "id": "release-1", "title": "Album", "artist": "Artist", "date": "2020",
        "cover_url": None, "track_count": 1, "country": "GB", "media_format": "CD",
        "medium_count": 1, "tracks": [Track(1, "First").to_dict()],
    },
    "playlist": {"id": "PL1234567890", "url": "https://www.youtube.com/playlist?list=PL1234567890", "title": "Playlist", "channel": "Channel", "thumbnail": None},
    "manifest": {"track_count": 1, "unavailable": 0, "tracks": [{"position": 1, "id": "video-1", "url": "one", "title": "First"}]},
    "mapping": [], "track_count": 1, "files": [],
    "cover": {"source": "none"}, "accepted_overrides": [],
    "autodrome": {"version": "test", "commit": None},
}


class TestPublicationController(unittest.IsolatedAsyncioTestCase):
    async def test_recreate_preserves_original_and_reports_provider_drift(self):
        catalog = MagicMock()
        catalog.get_publication.return_value = ORIGINAL
        downloader = MagicMock()
        downloader.get_playlist_manifest = AsyncMock(return_value={
            "unavailable": 0,
            "tracks": [{"position": 1, "id": "video-2", "url": "two", "title": "Changed"}],
        })
        metadata = MagicMock()
        metadata.get_release = AsyncMock(return_value=Release(
            "release-1", "Album remaster", "2021", "Artist", None,
            tracks=[Track(1, "First remaster")], track_count=1,
            country="US", media_format="Digital Media", medium_count=1,
        ))
        controller = PublicationController(catalog, downloader, metadata)

        result = await controller.recreate_review("publication-1")

        self.assertFalse(result["enqueued"])
        self.assertEqual(result["review"]["playlist"]["tracks"][0]["id"], "video-1")
        self.assertEqual(result["review"]["release"]["title"], "Album")
        self.assertEqual(result["drift"]["playlist"]["status"], "changed")
        self.assertEqual(result["drift"]["playlist"]["changes"][0]["current"]["id"], "video-2")
        self.assertEqual(result["drift"]["release"]["status"], "changed")
        downloader.get_playlist_manifest.assert_awaited_once_with(
            ORIGINAL["playlist"]["url"],
            refresh=True,
            allow_unavailable=True,
        )
        metadata.get_release.assert_awaited_once_with("release-1", refresh=True)

    async def test_recreate_keeps_history_when_providers_fail(self):
        catalog = MagicMock()
        catalog.get_publication.return_value = ORIGINAL
        downloader = MagicMock()
        downloader.get_playlist_manifest = AsyncMock(side_effect=RuntimeError("private"))
        metadata = MagicMock()
        metadata.get_release = AsyncMock(side_effect=RuntimeError("private"))

        result = await PublicationController(catalog, downloader, metadata).recreate_review(
            "publication-1"
        )

        self.assertEqual(result["drift"]["playlist"]["status"], "unavailable")
        self.assertEqual(result["drift"]["release"]["status"], "unavailable")
        self.assertNotIn("private", str(result))
