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
            call("albumartist", "Test Artist"),
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

    @patch("os.listdir", return_value=["01.mp3"])
    @patch("autodrome.services.tagger.MP3")
    def test_tag_files_rejects_count_mismatch_before_loading_audio(
        self, mock_mp3, mock_listdir
    ):
        with self.assertRaisesRegex(
            ValueError,
            "Downloaded track count mismatch before tagging: expected 2, got 1",
        ):
            self.tagger.tag_files(
                folder_path=self.folder,
                artist="X",
                album="Y",
                tracks=self.tracks,
            )

        mock_mp3.assert_not_called()

    @patch("os.listdir", return_value=["01-01.mp3", "02-01.mp3"])
    @patch("autodrome.services.tagger.MP3")
    def test_tag_files_sets_discnumber_for_multidisc_release(
        self, mock_mp3, mock_listdir
    ):
        first_audio = MagicMock()
        second_audio = MagicMock()
        mock_mp3.side_effect = [first_audio, second_audio]
        tracks = [
            Track(1, "First", disc_number=1, position=1, global_position=1),
            Track(1, "Second", disc_number=2, position=1, global_position=2),
        ]

        self.tagger.tag_files(self.folder, "Artist", "Album", tracks)

        self.assertIn(call("discnumber", "1"), first_audio.__setitem__.call_args_list)
        self.assertIn(call("discnumber", "2"), second_audio.__setitem__.call_args_list)

    @patch("os.listdir", return_value=["01.mp3", "02.mp3"])
    @patch("autodrome.services.tagger.MP3")
    def test_compilation_uses_track_artist_and_album_fallback(self, mp3, listdir):
        first, second = MagicMock(), MagicMock()
        mp3.side_effect = [first, second]
        self.tagger.tag_files(self.folder, "Various Artists", "Compilation", [
            Track(1, "One", artist="Alice feat. Bob"), Track(2, "Two")
        ])
        self.assertIn(call("artist", "Alice feat. Bob"), first.__setitem__.call_args_list)
        self.assertIn(call("artist", "Various Artists"), second.__setitem__.call_args_list)
        for audio in (first, second):
            self.assertIn(call("albumartist", "Various Artists"), audio.__setitem__.call_args_list)
