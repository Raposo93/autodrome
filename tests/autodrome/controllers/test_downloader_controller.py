import unittest
from unittest.mock import AsyncMock, MagicMock

from autodrome.controllers.downloader_controller import DownloaderController
from autodrome.metadata_service import MetadataService
from autodrome.models.release import Release
from autodrome.models.track import Track
from autodrome.services.redis_cache import RedisCache
from autodrome.yt_downloader import PlaylistDownloadError


class TestDownloaderController(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.downloader = MagicMock()
        self.downloader.download_playlist = AsyncMock()

        self.organizer = MagicMock()
        self.organizer.cover_embedder.prepare_cover.return_value = "prepared-caa"
        self.organizer.create_staging_folder.return_value.__enter__.return_value = (
            "/tmp/autodrome-download"
        )
        self.metadata_service = MagicMock()
        self.metadata_service.get_release = AsyncMock(
            return_value=Release(
                release_id="release-1",
                title="Album",
                date="2020-01-01",
                artist="Artist",
                cover_url=None,
                tracks=[Track(1, "First")],
            )
        )
        self.metadata_service.get_cover_art = AsyncMock(return_value=None)

        self.controller = DownloaderController(
            downloader=self.downloader,
            organizer=self.organizer,
            metadata_service=self.metadata_service,
        )

    async def test_download_passes_playlist_count_to_downloader(self):
        await self.controller.download_and_tag(
            "https://example.test/playlist",
            "Artist",
            "Album",
            "release-1",
            track_count=1,
        )

        self.metadata_service.get_release.assert_awaited_once_with("release-1")
        self.downloader.download_playlist.assert_awaited_once_with(
            "https://example.test/playlist", "/tmp/autodrome-download", total=1
        )
        self.organizer.tag_and_rename.assert_called_once()
        self.organizer.validate_album.assert_called_once()
        self.organizer.move_to_library.assert_called_once()

    async def test_download_fetches_release_details_before_downloading(self):
        await self.controller.download_and_tag(
            "https://example.test/playlist",
            "Artist",
            "Album",
            "release-1",
        )

        self.metadata_service.get_release.assert_awaited_once_with("release-1")
        self.downloader.download_playlist.assert_awaited_once()

    async def test_count_mismatch_stops_before_audio_or_staging(self):
        for count in (0, 2):
            with self.subTest(count=count):
                with self.assertRaisesRegex(ValueError, f"playlist has {count} tracks.*release has 1"):
                    await self.controller.download_and_tag(
                        "https://example.test/playlist", "Artist", "Album",
                        "release-1", track_count=count,
                    )
        self.organizer.create_staging_folder.assert_not_called()
        self.downloader.download_playlist.assert_not_awaited()
        self.metadata_service.get_cover_art.assert_not_awaited()
        self.organizer.move_to_library.assert_not_called()

    async def test_unknown_count_keeps_final_validation(self):
        await self.controller.download_and_tag(
            "https://example.test/playlist", "Artist", "Album", "release-1",
            track_count=None,
        )
        self.downloader.download_playlist.assert_awaited_once()
        self.organizer.validate_album.assert_called_once()

    async def test_redis_failure_does_not_block_download(self):
        redis_client = MagicMock()
        redis_client.get.side_effect = ConnectionError("Redis is down")
        redis_client.set.side_effect = ConnectionError("Redis is down")
        http_client = MagicMock()
        http_client.get = AsyncMock(
            return_value={
                "id": "release-1",
                "title": "Album",
                "date": "2020-01-01",
                "artist-credit": [{"name": "Artist"}],
                "media": [
                    {
                        "tracks": [
                            {"number": "1", "position": 1, "title": "First"}
                        ]
                    }
                ],
            }
        )
        metadata_service = MetadataService(
            http_client=http_client,
            redis_cache=RedisCache(client=redis_client),
        )
        metadata_service._get_cover_url = AsyncMock(return_value=None)
        metadata_service.get_cover_art = AsyncMock(return_value=None)
        self.controller.metadata_service = metadata_service

        await self.controller.download_and_tag(
            "https://example.test/playlist",
            "Artist",
            "Album",
            "release-1",
        )

        http_client.get.assert_awaited_once()
        self.downloader.download_playlist.assert_awaited_once()
        self.organizer.move_to_library.assert_called_once()

    async def test_musicbrainz_failure_stops_job_with_useful_error(self):
        self.metadata_service.get_release.side_effect = ConnectionError(
            "MusicBrainz is down"
        )

        with self.assertRaisesRegex(
            RuntimeError,
            "Could not load release release-1 from MusicBrainz",
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

    async def test_partial_track_failure_prevents_tagging_and_publication(self):
        self.downloader.download_playlist.side_effect = PlaylistDownloadError(
            [(2, "https://youtube.test/second", "provider rejected track")]
        )

        with self.assertRaises(PlaylistDownloadError):
            await self.controller.download_and_tag(
                "https://example.test/playlist",
                "Artist",
                "Album",
                "release-1",
            )

        self.organizer.tag_and_rename.assert_not_called()
        self.organizer.validate_album.assert_not_called()
        self.organizer.move_to_library.assert_not_called()

    async def test_cover_art_archive_keeps_existing_post_download_flow(self):
        self.metadata_service.get_cover_art.return_value = "/tmp/caa.jpg"

        async def download(*args, **kwargs):
            self.metadata_service.get_cover_art.assert_not_awaited()
            self.organizer.cover_embedder.prepare_cover.assert_not_called()

        self.downloader.download_playlist.side_effect = download

        await self.controller.download_and_tag(
            "https://example.test/playlist",
            "Artist",
            "Album",
            "release-1",
            cover_source="cover_art_archive",
        )

        self.metadata_service.get_cover_art.assert_awaited_once_with("release-1")
        self.organizer.cover_embedder.prepare_cover.assert_called_once_with(
            "/tmp/caa.jpg"
        )
        self.assertEqual(
            self.organizer.tag_and_rename.call_args.kwargs["prepared_cover"],
            "prepared-caa",
        )

    async def test_alternative_cover_is_loaded_before_audio_and_reused(self):
        cover_selection = MagicMock()
        cover_selection.load_prepared.return_value = "prepared-alternative"
        self.controller.cover_selection = cover_selection

        async def download(*args, **kwargs):
            cover_selection.load_prepared.assert_called_once_with("cover-id")

        self.downloader.download_playlist.side_effect = download

        await self.controller.download_and_tag(
            "https://example.test/playlist",
            "Artist",
            "Album",
            "release-1",
            cover_source="youtube_thumbnail",
            cover_id="cover-id",
            cover_url="https://i.ytimg.com/vi/video/mqdefault.jpg",
        )

        self.metadata_service.get_cover_art.assert_not_awaited()
        self.assertEqual(
            self.organizer.tag_and_rename.call_args.kwargs["prepared_cover"],
            "prepared-alternative",
        )

    async def test_invalid_alternative_cover_stops_before_staging_or_audio(self):
        cover_selection = MagicMock()
        cover_selection.load_prepared.side_effect = ValueError("cover unavailable")
        self.controller.cover_selection = cover_selection

        with self.assertRaisesRegex(ValueError, "cover unavailable"):
            await self.controller.download_and_tag(
                "https://example.test/playlist",
                "Artist",
                "Album",
                "release-1",
                cover_source="manual_upload",
                cover_id="cover-id",
            )

        self.organizer.create_staging_folder.assert_not_called()
        self.downloader.download_playlist.assert_not_awaited()

    async def test_explicit_no_cover_does_not_query_cover_providers(self):
        await self.controller.download_and_tag(
            "https://example.test/playlist",
            "Artist",
            "Album",
            "release-1",
            cover_source="none",
        )

        self.metadata_service.get_cover_art.assert_not_awaited()
        self.assertIsNone(
            self.organizer.tag_and_rename.call_args.kwargs["prepared_cover"]
        )


if __name__ == "__main__":
    unittest.main()

class TestManualDownload(unittest.IsolatedAsyncioTestCase):
    setUp = TestDownloaderController.setUp

    async def test_manual_tracks_use_manifest_and_confirmed_metadata(self):
        manifest = {"tracks": [{"position": 1, "title": "Live track", "url": "video"}], "unavailable": 0}
        self.downloader.get_playlist_manifest = AsyncMock(return_value=manifest)
        await self.controller.download_and_tag("playlist", "Manual Artist", "Manual Album", None,
                                               1, metadata_mode="manual", manual_confirmed=True)
        self.metadata_service.get_release.assert_not_awaited()
        self.metadata_service.get_cover_art.assert_not_awaited()
        args = self.organizer.tag_and_rename.call_args.args
        self.assertEqual(args[1:3], ("Manual Artist", "Manual Album"))
        self.assertEqual(args[3][0].title, "Live track")
        self.assertEqual(args[3][0].number, 1)
        self.assertEqual(args[4:], (None, None))
        self.assertIs(self.downloader.download_playlist.call_args.kwargs["manifest"], manifest)
        self.organizer.validate_album.assert_called_once()
        self.organizer.move_to_library.assert_called_once_with("/tmp/autodrome-download", "Manual Artist", "Manual Album")

    async def test_invalid_manual_manifest_prevents_staging(self):
        self.downloader.get_playlist_manifest = AsyncMock(side_effect=RuntimeError("unavailable"))
        with self.assertRaisesRegex(RuntimeError, "unavailable"):
            await self.controller.download_and_tag("playlist", "Artist", "Album", None,
                                                   metadata_mode="manual", manual_confirmed=True)
        self.organizer.create_staging_folder.assert_not_called()
        self.downloader.download_playlist.assert_not_awaited()
