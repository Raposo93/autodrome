import unittest

from pydantic import ValidationError

from autodrome.models.requests import DownloadRequest, SearchRequest


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


if __name__ == "__main__":
    unittest.main()
