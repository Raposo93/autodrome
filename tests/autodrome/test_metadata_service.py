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

    async def test_search_releases_returns_correct_releases(self):
        self.http_client.get.return_value = {
            "releases": [
                {
                    "id": "release1",
                    "title": "Test Album",
                    "date": "2020-01-01",
                    "artist-credit": [{"name": "Test Artist"}],
                }
            ]
        }
        self.service.redis_cache.get_release.return_value = None
        self.service._get_tracks = AsyncMock(return_value=[])
        self.service._get_cover_url = AsyncMock(return_value=None)

        releases = await self.service.search_releases("Test Artist", "Test Album")

        self.assertEqual(len(releases), 1)
        release = releases[0]
        self.assertIsInstance(release, Release)
        self.assertEqual(release.id, "release1")
        self.assertEqual(release.title, "Test Album")
        self.assertEqual(release.date, "2020-01-01")
        self.assertEqual(release.artist, "Test Artist")
        self.assertEqual(release.tracks, [])
        self.service._get_tracks.assert_awaited_once_with("release1")
        self.service.redis_cache.set_release.assert_called_once()

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
        self.http_client.get.return_value = {
            "releases": [
                {
                    "id": "release1",
                    "title": "Album",
                    "artist-credit": [{"name": "Artist"}],
                }
            ]
        }
        self.service.redis_cache.get_release.return_value = {
            "tracks": [],
            "cover_url": "https://archive.test/original.jpg",
        }
        self.service._get_tracks = AsyncMock()
        self.service._get_cover_url = AsyncMock(
            return_value="https://archive.test/small.jpg"
        )

        releases = await self.service.search_releases("Artist", "Album")

        self.assertEqual(
            releases[0].cover_url,
            "https://archive.test/small.jpg",
        )
        self.service._get_tracks.assert_not_awaited()
        cached_data = self.service.redis_cache.set_release.call_args.args[1]
        self.assertEqual(cached_data["cover_url_kind"], "thumbnail")

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
