import unittest
from unittest.mock import patch, MagicMock, mock_open
from autodrome.services.cover_embedder import CoverEmbedder
from mutagen.id3 import error

class TestCoverEmbedder(unittest.TestCase):
    def setUp(self):
        self.embedder = CoverEmbedder()
        self.mp3_path = "/fake/song.mp3"
        self.img_path = "/fake/cover.jpg"
        self.fake_image_data = b"JPEGDATA"

    @patch("builtins.open", new_callable=mock_open, read_data=b"JPEGDATA")
    @patch("autodrome.services.cover_embedder.MP3")
    def test_embed_cover_success(self, mock_mp3, mock_file):
        mock_audio = MagicMock()
        mock_audio.tags = MagicMock()
        mock_mp3.return_value = mock_audio

        self.embedder.embed_cover(self.mp3_path, self.img_path)

        mock_file.assert_called_once_with(self.img_path, 'rb')
        mock_audio.tags.add.assert_called_once()
        mock_audio.save.assert_called_once()

    @patch("builtins.open", new_callable=mock_open, read_data=b"JPEGDATA")
    @patch("autodrome.services.cover_embedder.MP3")
    def test_embed_cover_add_tags_raises(self, mock_mp3, mock_file):
        mock_audio = MagicMock()
        mock_audio.tags = MagicMock()
        mock_audio.add_tags.side_effect = error("Already exists")
        mock_mp3.return_value = mock_audio

        self.embedder.embed_cover(self.mp3_path, self.img_path)

        mock_audio.tags.add.assert_called_once()
        mock_audio.save.assert_called_once()
