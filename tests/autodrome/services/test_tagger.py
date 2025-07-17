import unittest
from unittest.mock import patch, MagicMock, call
import os
from autodrome.services.tagger import Tagger
from autodrome.models.track import Track

class TestTagger(unittest.TestCase):
    def setUp(self):
        self.tagger = Tagger()
        self.folder = "/fake/folder"
        self.tracks = [Track(number=1, title="First"), Track(number=2, title="Second")]

    @patch("os.listdir")
    @patch("autodrome.services.tagger.MP3")
    def test_tag_files_success(self, mock_mp3, mock_listdir):
        mock_listdir.return_value = ["01.mp3", "02.mp3"]

        mock_audio_1 = MagicMock()
        mock_audio_2 = MagicMock()
        mock_mp3.side_effect = [mock_audio_1, mock_audio_2]

        self.tagger.tag_files(
            folder_path=self.folder,
            artist="Test Artist",
            album="Test Album",
            tracks=self.tracks,
            date="2025"
        )

        mock_mp3.assert_has_calls([
            call(os.path.join(self.folder, "01.mp3"), ID3=unittest.mock.ANY),
            call(os.path.join(self.folder, "02.mp3"), ID3=unittest.mock.ANY)
        ])

        self.assertEqual(mock_audio_1.__setitem__.call_args_list, [
            call("artist", "Test Artist"),
            call("album", "Test Album"),
            call("title", "First"),
            call("tracknumber", "1"),
            call("date", "2025")
        ])
        self.assertEqual(mock_audio_1.save.call_count, 1)
        self.assertEqual(mock_audio_2.save.call_count, 1)

    @patch("os.listdir")
    @patch("autodrome.services.tagger.MP3")
    def test_tag_files_skips_non_mp3(self, mock_mp3, mock_listdir):
        mock_listdir.return_value = ["01.mp3", "cover.jpg"]
        mock_mp3.return_value = MagicMock()

        self.tagger.tag_files(
            folder_path=self.folder,
            artist="Artist",
            album="Album",
            tracks=[Track(number=1, title="Only")],
        )

        mock_mp3.assert_called_once_with(os.path.join(self.folder, "01.mp3"), ID3=unittest.mock.ANY)

    @patch("os.listdir", return_value=["01.mp3"])
    @patch("autodrome.services.tagger.MP3", side_effect=Exception("broken file"))
    def test_tag_files_raises_on_failure(self, mock_mp3, mock_listdir):
        with self.assertRaises(Exception):
            self.tagger.tag_files(
                folder_path=self.folder,
                artist="X",
                album="Y",
                tracks=[Track(number=1, title="T")],
            )

