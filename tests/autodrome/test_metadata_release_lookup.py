import unittest
from unittest.mock import AsyncMock, call

from autodrome.metadata_service import MetadataService


class TestMetadataReleaseLookup(unittest.IsolatedAsyncioTestCase):
    async def test_get_release_fetches_and_parses_musicbrainz_metadata(self):
        http_client = AsyncMock()
        release_data = {
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
        http_client.get.side_effect = [
            release_data,
            {
                "images": [
                    {
                        "front": True,
                        "thumbnails": {"small": "https://archive.test/small.jpg"},
                    }
                ]
            },
        ]
        service = MetadataService(http_client=http_client)

        release = await service.get_release("release-1")

        http_client.get.assert_has_awaits(
            [
                call(
                    "https://musicbrainz.org/ws/2/release/release-1",
                    params={"inc": "recordings artist-credits", "fmt": "json"},
                    provider="MusicBrainz",
                    context="loading release release-1",
                ),
                call(
                    "https://coverartarchive.org/release/release-1",
                    provider="Cover Art Archive",
                    context="loading cover metadata for release release-1",
                ),
            ]
        )
        self.assertEqual(release.id, "release-1")
        self.assertEqual(release.title, "Album")
        self.assertEqual(release.date, "2020-01-01")
        self.assertEqual(release.artist, "Artist")
        self.assertEqual(release.cover_url, "https://archive.test/small.jpg")
        self.assertEqual(
            [track.to_dict() for track in release.tracks],
            [
                {
                    "number": 1,
                    "title": "First",
                    "disc_number": 1,
                    "position": 1,
                    "global_position": 1,
                    "artist": None,
                },
                {
                    "number": 2,
                    "title": "Second",
                    "disc_number": 1,
                    "position": 2,
                    "global_position": 2,
                    "artist": None,
                },
            ],
        )

    async def test_get_release_preserves_multidisc_order(self):
        http_client = AsyncMock()
        release_data = {
            "id": "release-1",
            "title": "Double Album",
            "artist-credit": [{"name": "Artist"}],
            "media": [
                {
                    "position": 2,
                    "tracks": [
                        {"number": "1", "position": 1, "title": "Disc 2 First"}
                    ],
                },
                {
                    "position": 1,
                    "tracks": [
                        {"number": "2", "position": 2, "title": "Disc 1 Second"},
                        {"number": "1", "position": 1, "title": "Disc 1 First"},
                    ],
                },
            ],
        }
        http_client.get.side_effect = [release_data, {"images": []}]
        service = MetadataService(http_client=http_client)

        release = await service.get_release("release-1")

        self.assertEqual(
            [track.title for track in release.tracks],
            ["Disc 1 First", "Disc 1 Second", "Disc 2 First"],
        )
        self.assertEqual(
            [track.disc_number for track in release.tracks], [1, 1, 2]
        )
        self.assertEqual([track.position for track in release.tracks], [1, 2, 1])
        self.assertEqual(
            [track.global_position for track in release.tracks], [1, 2, 3]
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

class TestArtistCredits(unittest.IsolatedAsyncioTestCase):
    async def test_collaboration_and_track_credits_survive_cache(self):
        from unittest.mock import MagicMock
        cache = MagicMock()
        cache.get_release.return_value = None
        client = AsyncMock()
        client.get.side_effect = [{
            "id": "release", "title": "Compilation", "date": "2026",
            "artist-credit": [{"name": "Alice", "joinphrase": " & "}, {"name": "Bob"}],
            "media": [{"tracks": [
                {"title": "One", "artist-credit": [{"name": "Credited Alice", "artist": {"name": "Canonical Alice"}}]},
                {"title": "Two", "artist-credit": [{"name": "Bob", "joinphrase": " feat. "}, {"name": "Carol"}]},
                {"title": "Three", "recording": {"artist-credit": [{"artist": {"name": "Dave"}}]}},
                {"title": "Four"},
            ]}],
        }, {"images": []}]
        service = MetadataService(client, cache)
        release = await service.get_release("release")
        self.assertEqual(release.artist, "Alice & Bob")
        self.assertEqual([t.artist for t in release.tracks], ["Credited Alice", "Bob feat. Carol", "Dave", None])
        cached = cache.set_release.call_args.args[1]
        cache.get_release.return_value = cached
        restored = await service.get_release("release")
        self.assertEqual([t.to_dict() for t in restored.tracks], [t.to_dict() for t in release.tracks])
        for track in cached["tracks"]:
            track.pop("artist")
        old = await service.get_release("release")
        self.assertTrue(all(t.artist is None for t in old.tracks))
