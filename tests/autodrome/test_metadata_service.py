import os
import tempfile
import unittest
from unittest.mock import AsyncMock, MagicMock

from autodrome.http_client_async import UpstreamServiceError
from autodrome.metadata_service import MetadataService
from autodrome.models.release import Release


class TestMetadataService(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.http_client = MagicMock()
        self.http_client.get = AsyncMock()
        self.service = MetadataService(http_client=self.http_client)
        self.service.redis_cache = MagicMock()

    async def test_search_releases_returns_candidates_without_loading_tracks(self):
        self.http_client.get.return_value = {
            "releases": [
                {
                    "id": "release1",
                    "title": "Test Album",
                    "date": "2020-01-01",
                    "artist-credit": [{"name": "Test Artist"}],
                    "cover-art-archive": {"front": True},
                },
                {
                    "id": "release2",
                    "title": "Another Edition",
                    "date": "2021",
                    "artist-credit": [{"name": "Test Artist"}],
                },
            ]
        }
        self.service._get_tracks = AsyncMock(return_value=[])
        self.service._get_cover_url = AsyncMock(return_value=None)

        releases = await self.service.search_releases("Test Artist", "Test Album")

        self.assertEqual(len(releases), 2)
        release = releases[0]
        self.assertIsInstance(release, Release)
        self.assertEqual(release.id, "release1")
        self.assertEqual(release.title, "Test Album")
        self.assertEqual(release.date, "2020-01-01")
        self.assertEqual(release.artist, "Test Artist")
        self.assertEqual(release.tracks, [])
        self.assertEqual(
            release.cover_url,
            "https://coverartarchive.org/release/release1/front-250",
        )
        self.assertIsNone(releases[1].cover_url)
        self.service._get_tracks.assert_not_awaited()
        self.service._get_cover_url.assert_not_awaited()
        self.service.redis_cache.get_release.assert_not_called()
        self.service.redis_cache.set_release.assert_not_called()

    async def test_search_releases_handles_empty_response(self):
        self.http_client.get.return_value = {"releases": []}

        releases = await self.service.search_releases(None, None)

        self.assertEqual(releases, [])

    async def test_search_releases_rejects_invalid_response(self):
        self.http_client.get.return_value = {}

        with self.assertRaisesRegex(
            UpstreamServiceError,
            "MusicBrainz failed while searching releases: invalid response",
        ):
            await self.service.search_releases("Artist", "Album")

    async def test_cover_lookup_uses_thumbnail_url_only(self):
        self.http_client.get.return_value = {
            "images": [
                {
                    "front": True,
                    "image": "https://archive.test/original.jpg",
                    "thumbnails": {
                        "small": "https://archive.test/small.jpg",
                    },
                }
            ]
        }

        cover_url = await self.service._get_cover_url("release-1")

        self.assertEqual(cover_url, "https://archive.test/small.jpg")
        self.http_client.get.assert_awaited_once_with(
            "https://coverartarchive.org/release/release-1",
            provider="Cover Art Archive",
            context="loading cover metadata for release release-1",
        )

    async def test_cover_lookup_treats_empty_images_as_valid_absence(self):
        self.http_client.get.return_value = {"images": []}

        cover_url = await self.service._get_cover_url("release-1")

        self.assertIsNone(cover_url)

    async def test_legacy_cached_full_cover_url_is_replaced_with_thumbnail(self):
        self.service.redis_cache.get_release.return_value = {
            "id": "release1",
            "title": "Album",
            "date": "2020",
            "artist": "Artist",
            "tracks": [],
            "cover_url": "https://archive.test/original.jpg",
        }
        self.service._get_cover_url = AsyncMock(
            return_value="https://archive.test/small.jpg"
        )

        release = await self.service.get_release("release1")

        self.assertEqual(
            release.cover_url,
            "https://archive.test/small.jpg",
        )
        self.http_client.get.assert_not_awaited()
        cached_data = self.service.redis_cache.set_release.call_args.args[1]
        self.assertEqual(cached_data["cover_url_kind"], "thumbnail")

    async def test_complete_cached_details_avoid_upstream_requests(self):
        self.service.redis_cache.get_release.return_value = {
            "id": "release1",
            "title": "Album",
            "date": "2020",
            "artist": "Artist",
            "cover_url": "https://archive.test/small.jpg",
            "cover_url_kind": "thumbnail",
            "tracks": [{"number": 1, "title": "First"}],
        }
        self.service._get_cover_url = AsyncMock()

        release = await self.service.get_release("release1")

        self.assertEqual([track.title for track in release.tracks], ["First"])
        self.http_client.get.assert_not_awaited()
        self.service._get_cover_url.assert_not_awaited()
        self.service.redis_cache.set_release.assert_not_called()

    async def test_selected_release_downloads_full_cover_atomically(self):
        self.http_client.get_binary = AsyncMock(return_value=b"cover data")
        with tempfile.TemporaryDirectory() as cover_dir:
            self.service.cover_dir = cover_dir

            cover_path = await self.service.get_cover_art("release-1")

            self.assertEqual(
                cover_path,
                os.path.join(cover_dir, "release-1.jpg"),
            )
            with open(cover_path, "rb") as cover_file:
                self.assertEqual(cover_file.read(), b"cover data")
            self.http_client.get_binary.assert_awaited_once_with(
                "https://coverartarchive.org/release/release-1/front",
                provider="Cover Art Archive",
                context="downloading front cover for release release-1",
            )
            self.assertEqual(
                [name for name in os.listdir(cover_dir) if name.endswith(".tmp")],
                [],
            )

    async def test_missing_full_cover_is_a_valid_absence(self):
        self.http_client.get_binary = AsyncMock(
            side_effect=UpstreamServiceError(
                provider="Cover Art Archive",
                context="downloading front cover for release release-1",
                reason="HTTP 404",
                status=404,
            )
        )
        with tempfile.TemporaryDirectory() as cover_dir:
            self.service.cover_dir = cover_dir

            cover_path = await self.service.get_cover_art("release-1")

            self.assertIsNone(cover_path)
            self.assertEqual(os.listdir(cover_dir), [])


if __name__ == "__main__":
    unittest.main()
