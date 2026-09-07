import unittest
from unittest.mock import AsyncMock, MagicMock

from autodrome.controllers.downloader_controller import DownloaderController
from autodrome.models.release import Release
from autodrome.models.track import Track
from autodrome.services.redis_cache import RedisCache


class TestDownloaderController(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.downloader = MagicMock()
        self.downloader.download_playlist = AsyncMock()

        self.organizer = MagicMock()
        self.organizer.create_staging_folder.return_value.__enter__.return_value = (
            "/tmp/autodrome-download"
        )
        self.metadata_service = MagicMock()
        self.metadata_service.get_release = AsyncMock()
        self.metadata_service.get_cover_art = AsyncMock(return_value=None)
        self.redis_cache = MagicMock()

        self.controller = DownloaderController(
            downloader=self.downloader,
            organizer=self.organizer,
            metadata_service=self.metadata_service,
            redis_cache=self.redis_cache,
        )

    async def test_download_uses_cached_release(self):
        self.redis_cache.get_release.return_value = {
            "date": "2020-01-01",
            "tracks": [{"number": 1, "title": "First"}],
        }

        await self.controller.download_and_tag(
            "https://example.test/playlist",
            "Artist",
            "Album",
            "release-1",
            track_count=1,
        )

        self.metadata_service.get_release.assert_not_awaited()
        self.downloader.download_playlist.assert_awaited_once_with(
            "https://example.test/playlist", "/tmp/autodrome-download", total=1
        )
        self.organizer.tag_and_rename.assert_called_once()
        self.organizer.validate_album.assert_called_once()
        self.organizer.move_to_library.assert_called_once()

    async def test_cache_miss_fetches_release_from_musicbrainz(self):
        self.redis_cache.get_release.return_value = None
        self.metadata_service.get_release.return_value = Release(
            release_id="release-1",
            title="Album",
            date="2020-01-01",
            artist="Artist",
            cover_url=None,
            tracks=[Track(1, "First")],
        )

        await self.controller.download_and_tag(
            "https://example.test/playlist",
            "Artist",
            "Album",
            "release-1",
        )

        self.metadata_service.get_release.assert_awaited_once_with("release-1")
        self.redis_cache.set_release.assert_called_once_with(
            "release-1",
            {
                "id": "release-1",
                "title": "Album",
                "date": "2020-01-01",
                "artist": "Artist",
                "cover_url": None,
                "tracks": [
                    {
                        "number": 1,
                        "title": "First",
                        "disc_number": 1,
                        "position": 1,
                        "global_position": 1,
                    }
                ],
            },
        )
        self.downloader.download_playlist.assert_awaited_once()

    async def test_redis_failure_does_not_block_download(self):
        redis_client = MagicMock()
        redis_client.get.side_effect = ConnectionError("Redis is down")
        redis_client.set.side_effect = ConnectionError("Redis is down")
        self.controller.redis_cache = RedisCache(client=redis_client)
        self.metadata_service.get_release.return_value = Release(
            release_id="release-1",
            title="Album",
            date="2020-01-01",
            artist="Artist",
            cover_url=None,
            tracks=[Track(1, "First")],
        )

        await self.controller.download_and_tag(
            "https://example.test/playlist",
            "Artist",
            "Album",
            "release-1",
        )

        self.metadata_service.get_release.assert_awaited_once_with("release-1")
        self.downloader.download_playlist.assert_awaited_once()
        self.organizer.move_to_library.assert_called_once()

    async def test_musicbrainz_failure_stops_job_with_useful_error(self):
        self.redis_cache.get_release.return_value = None
        self.metadata_service.get_release.side_effect = ConnectionError(
            "MusicBrainz is down"
        )

        with self.assertRaisesRegex(
            RuntimeError,
            "Could not load release release-1: cache miss and MusicBrainz lookup failed",
        ):
            await self.controller.download_and_tag(
                "https://example.test/playlist",
                "Artist",
                "Album",
                "release-1",
            )

        self.downloader.download_playlist.assert_not_awaited()
        self.organizer.tag_and_rename.assert_not_called()

    async def test_validation_failure_prevents_publication(self):
        self.redis_cache.get_release.return_value = {
            "date": "2020-01-01",
            "tracks": [{"number": 1, "title": "First"}],
        }
        self.organizer.validate_album.side_effect = ValueError("invalid MP3")

        with self.assertRaisesRegex(ValueError, "invalid MP3"):
            await self.controller.download_and_tag(
                "https://example.test/playlist",
                "Artist",
                "Album",
                "release-1",
            )

        self.organizer.tag_and_rename.assert_called_once()
        self.organizer.validate_album.assert_called_once()
        self.organizer.move_to_library.assert_not_called()


if __name__ == "__main__":
    unittest.main()
