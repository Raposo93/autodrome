import os
import tempfile
from unittest import mock
from autodrome.services.organizer import Organizer
from autodrome.models.track import Track

def create_dummy_mp3(folder: str, filename: str):
    path = os.path.join(folder, filename)
    with open(path, "wb") as f:
        f.write(b"ID3")  # mínimo para que lo detecte mutagen
    return path

def test_tag_and_rename_basic(monkeypatch):
    organizer = Organizer()

    with tempfile.TemporaryDirectory() as tmpdir:
        create_dummy_mp3(tmpdir, "track1.mp3")
        create_dummy_mp3(tmpdir, "track2.mp3")

        tracks = [Track(1, "Song A"), Track(2, "Song B")]

        monkeypatch.setattr(organizer.tagger, "tag_files", mock.MagicMock())
        monkeypatch.setattr(organizer.cover_embedder, "embed_cover", mock.MagicMock())

        organizer.tag_and_rename(tmpdir, "Artist", "Album", tracks, cover_path=None)

        assert sorted(os.listdir(tmpdir)) == ["01 - Song A.mp3", "02 - Song B.mp3"]
        organizer.tagger.tag_files.assert_called_once()
        organizer.cover_embedder.embed_cover.assert_not_called()

def test_move_to_library_basic(monkeypatch):
    organizer = Organizer()

    with tempfile.TemporaryDirectory() as tmpdir, tempfile.TemporaryDirectory() as libdir:
        monkeypatch.setattr("autodrome.services.organizer.conf.library_path", libdir)

        create_dummy_mp3(tmpdir, "01 - Song A.mp3")
        create_dummy_mp3(tmpdir, "02 - Song B.mp3")

        organizer.move_to_library(tmpdir, "Artist", "Album")

        album_path = os.path.join(libdir, "Artist", "Album")
        assert os.path.isdir(album_path)
        assert sorted(os.listdir(album_path)) == ["01 - Song A.mp3", "02 - Song B.mp3"]
        assert not os.path.exists(tmpdir)
