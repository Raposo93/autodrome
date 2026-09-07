import unittest
from unittest.mock import AsyncMock

from autodrome.metadata_service import MetadataService


class TestMetadataReleaseLookup(unittest.IsolatedAsyncioTestCase):
    async def test_get_release_fetches_and_parses_musicbrainz_metadata(self):
        http_client = AsyncMock()
        http_client.get.return_value = {
            "id": "release-1",
            "title": "Album",
            "date": "2020-01-01",
            "artist-credit": [{"name": "Artist"}],
            "media": [
                {
                    "tracks": [
                        {"number": "1", "position": 1, "title": "First"},
                        {"number": "2", "position": 2, "title": "Second"},
                    ]
                }
            ],
        }
        service = MetadataService(http_client=http_client)

        release = await service.get_release("release-1")

        http_client.get.assert_awaited_once_with(
            "https://musicbrainz.org/ws/2/release/release-1",
            params={"inc": "recordings artist-credits", "fmt": "json"},
        )
        self.assertEqual(release.id, "release-1")
        self.assertEqual(release.title, "Album")
        self.assertEqual(release.date, "2020-01-01")
        self.assertEqual(release.artist, "Artist")
        self.assertEqual(
            [track.to_dict() for track in release.tracks],
            [
                {"number": 1, "title": "First"},
                {"number": 2, "title": "Second"},
            ],
        )

    async def test_get_release_propagates_musicbrainz_failure_with_context(self):
        http_client = AsyncMock()
        http_client.get.side_effect = ConnectionError("service unavailable")
        service = MetadataService(http_client=http_client)

        with self.assertRaisesRegex(
            RuntimeError,
            "Could not retrieve release release-1 from MusicBrainz",
        ):
            await service.get_release("release-1")


if __name__ == "__main__":
    unittest.main()
