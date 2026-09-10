import unittest

from pydantic import ValidationError

from autodrome.models.requests import (
    AlbumDestinationRequest,
    DownloadRequest,
    SearchRequest,
)


VALID_DOWNLOAD = {
    "playlist_url": "https://www.youtube.com/playlist?list=PL1234567890",
    "artist": "Artist",
    "album": "Album",
    "release_id": "12345678-1234-1234-1234-123456789abc",
    "track_count": 10,
}


class TestRequestModels(unittest.TestCase):
    def test_valid_download_is_normalized(self):
        request = DownloadRequest(**{**VALID_DOWNLOAD, "artist": "  Artist  "})

        self.assertEqual(request.artist, "Artist")
        self.assertEqual(request.model_dump(mode="json")["release_id"], VALID_DOWNLOAD["release_id"])

    def test_download_preserves_known_zero_and_unknown_counts(self):
        for count in (0, None):
            self.assertEqual(
                DownloadRequest(**{**VALID_DOWNLOAD, "track_count": count}).track_count,
                count,
            )
        with self.assertRaises(ValidationError):
            DownloadRequest(**{**VALID_DOWNLOAD, "track_count": -1})

    def test_download_rejects_non_youtube_and_local_urls(self):
        for url in (
            "https://example.com/playlist?list=PL1234567890",
            "http://www.youtube.com/playlist?list=PL1234567890",
            "https://127.0.0.1/playlist?list=PL1234567890",
            "https://user:pass@www.youtube.com/playlist?list=PL1234567890",
        ):
            with self.subTest(url=url), self.assertRaises(ValidationError):
                DownloadRequest(**{**VALID_DOWNLOAD, "playlist_url": url})

    def test_download_rejects_missing_or_invalid_playlist_id(self):
        for url in (
            "https://www.youtube.com/playlist",
            "https://www.youtube.com/playlist?list=short",
            "https://www.youtube.com/watch?v=abcdefghijk",
        ):
            with self.subTest(url=url), self.assertRaises(ValidationError):
                DownloadRequest(**{**VALID_DOWNLOAD, "playlist_url": url})

    def test_download_rejects_unsafe_path_components(self):
        for component in (".", "..", "/tmp/album", "C:\\Music\\Album"):
            with self.subTest(component=component), self.assertRaises(ValidationError):
                DownloadRequest(**{**VALID_DOWNLOAD, "artist": component})

    def test_search_requires_at_least_one_nonempty_term(self):
        with self.assertRaises(ValidationError):
            SearchRequest()
        with self.assertRaises(ValidationError):
            SearchRequest(artist="   ")

    def test_album_destination_requires_safe_final_metadata(self):
        request = AlbumDestinationRequest(artist="  Artist  ", album="Album")
        self.assertEqual(request.artist, "Artist")
        for change in (
            {"artist": ".."},
            {"album": "/tmp/album"},
            {"extra": True},
        ):
            with self.subTest(change=change), self.assertRaises(ValidationError):
                AlbumDestinationRequest(
                    **{"artist": "Artist", "album": "Album", **change}
                )

    def test_cover_choice_is_explicit_and_validated(self):
        request = DownloadRequest(**VALID_DOWNLOAD)
        self.assertEqual(request.cover_source, "cover_art_archive")

        cover_id = "12345678-1234-1234-1234-123456789abc"
        youtube = DownloadRequest(
            **VALID_DOWNLOAD,
            cover_source="youtube_thumbnail",
            cover_id=cover_id,
            cover_url="https://i.ytimg.com/vi/video/mqdefault.jpg",
        )
        self.assertEqual(youtube.cover_source, "youtube_thumbnail")
        self.assertEqual(
            DownloadRequest(
                **VALID_DOWNLOAD,
                cover_source="manual_upload",
                cover_id=cover_id,
            ).cover_source,
            "manual_upload",
        )
        self.assertEqual(
            DownloadRequest(**VALID_DOWNLOAD, cover_source="none").cover_source,
            "none",
        )

        invalid = (
            {"cover_source": "youtube_thumbnail", "cover_id": cover_id},
            {
                "cover_source": "youtube_thumbnail",
                "cover_id": cover_id,
                "cover_url": "http://127.0.0.1/private",
            },
            {"cover_source": "manual_upload"},
            {"cover_source": "none", "cover_id": cover_id},
            {"cover_source": "cover_art_archive", "cover_id": cover_id},
        )
        for values in invalid:
            with self.subTest(values=values), self.assertRaises(ValidationError):
                DownloadRequest(**VALID_DOWNLOAD, **values)


if __name__ == "__main__":
    unittest.main()

class TestManualRequest(unittest.TestCase):
    def test_manual_mode_requires_confirmation_and_safe_explicit_metadata(self):
        manual = {**VALID_DOWNLOAD, "release_id": None, "metadata_mode": "manual", "manual_confirmed": True}
        self.assertEqual(DownloadRequest(**manual).artist, "Artist")
        for change in ({"manual_confirmed": False}, {"metadata_mode": "musicbrainz"},
                       {"artist": " "}, {"album": ".."}, {"release_id": VALID_DOWNLOAD["release_id"]}):
            with self.subTest(change=change), self.assertRaises(ValidationError):
                DownloadRequest(**{**manual, **change})
        with self.assertRaises(ValidationError):
            DownloadRequest(**{key: value for key, value in VALID_DOWNLOAD.items() if key != "release_id"})
