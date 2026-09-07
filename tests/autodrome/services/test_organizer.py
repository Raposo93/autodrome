import os
import tempfile
from unittest import mock

import pytest

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

def test_tag_and_rename_rejects_missing_download_before_changes(monkeypatch):
    organizer = Organizer()

    with tempfile.TemporaryDirectory() as tmpdir:
        create_dummy_mp3(tmpdir, "track1.mp3")
        tracks = [Track(1, "Song A"), Track(2, "Song B")]

        monkeypatch.setattr(organizer.tagger, "tag_files", mock.MagicMock())
        monkeypatch.setattr(organizer.cover_embedder, "embed_cover", mock.MagicMock())

        with pytest.raises(
            ValueError,
            match="Downloaded track count mismatch: expected 2, got 1",
        ):
            organizer.tag_and_rename(tmpdir, "Artist", "Album", tracks)

        assert os.listdir(tmpdir) == ["track1.mp3"]
        organizer.tagger.tag_files.assert_not_called()
        organizer.cover_embedder.embed_cover.assert_not_called()

def test_tag_and_rename_rejects_extra_download_before_changes(monkeypatch):
    organizer = Organizer()

    with tempfile.TemporaryDirectory() as tmpdir:
        create_dummy_mp3(tmpdir, "track1.mp3")
        create_dummy_mp3(tmpdir, "track2.mp3")
        tracks = [Track(1, "Song A")]

        monkeypatch.setattr(organizer.tagger, "tag_files", mock.MagicMock())
        monkeypatch.setattr(organizer.cover_embedder, "embed_cover", mock.MagicMock())

        with pytest.raises(
            ValueError,
            match="Downloaded track count mismatch: expected 1, got 2",
        ):
            organizer.tag_and_rename(tmpdir, "Artist", "Album", tracks)

        assert sorted(os.listdir(tmpdir)) == ["track1.mp3", "track2.mp3"]
        organizer.tagger.tag_files.assert_not_called()
        organizer.cover_embedder.embed_cover.assert_not_called()

def test_move_to_library_basic(monkeypatch):
    organizer = Organizer()

    with tempfile.TemporaryDirectory() as root:
        libdir = os.path.join(root, "library")
        staging_dir = os.path.join(root, "staging")
        monkeypatch.setattr("autodrome.services.organizer.conf.library_path", libdir)
        monkeypatch.setattr("autodrome.services.organizer.conf.staging_path", staging_dir)
        monkeypatch.setattr(
            "autodrome.services.organizer.conf.minimum_staging_free_bytes", 0
        )

        with organizer.create_staging_folder("Artist", "Album") as tmpdir:
            create_dummy_mp3(tmpdir, "01 - Song A.mp3")
            create_dummy_mp3(tmpdir, "02 - Song B.mp3")

            organizer.move_to_library(tmpdir, "Artist", "Album")

        album_path = os.path.join(libdir, "Artist", "Album")
        assert os.path.isdir(album_path)
        assert sorted(os.listdir(album_path)) == ["01 - Song A.mp3", "02 - Song B.mp3"]
        assert not os.path.exists(tmpdir)

def test_create_staging_folder_rejects_existing_album(monkeypatch):
    organizer = Organizer()

    with tempfile.TemporaryDirectory() as root:
        libdir = os.path.join(root, "library")
        staging_dir = os.path.join(root, "staging")
        album_path = os.path.join(libdir, "Artist", "Album")
        os.makedirs(album_path)
        existing_file = create_dummy_mp3(album_path, "existing.mp3")

        monkeypatch.setattr("autodrome.services.organizer.conf.library_path", libdir)
        monkeypatch.setattr("autodrome.services.organizer.conf.staging_path", staging_dir)
        monkeypatch.setattr(
            "autodrome.services.organizer.conf.minimum_staging_free_bytes", 0
        )

        with pytest.raises(FileExistsError, match="Album already exists"):
            with organizer.create_staging_folder("Artist", "Album"):
                pass

        assert os.path.isfile(existing_file)

def test_create_staging_folder_rejects_insufficient_space(monkeypatch):
    organizer = Organizer()

    with tempfile.TemporaryDirectory() as root:
        libdir = os.path.join(root, "library")
        staging_dir = os.path.join(root, "staging")
        monkeypatch.setattr("autodrome.services.organizer.conf.library_path", libdir)
        monkeypatch.setattr("autodrome.services.organizer.conf.staging_path", staging_dir)
        monkeypatch.setattr(
            "autodrome.services.organizer.conf.minimum_staging_free_bytes", 1024
        )
        monkeypatch.setattr(
            "autodrome.services.organizer.shutil.disk_usage",
            mock.MagicMock(return_value=mock.MagicMock(free=512)),
        )

        with pytest.raises(
            OSError,
            match="required at least 1024 bytes, available 512 bytes",
        ):
            with organizer.create_staging_folder("Artist", "Album"):
                pass

def test_failed_staging_is_preserved_by_default(monkeypatch):
    organizer = Organizer()
    staging_folder = None

    with tempfile.TemporaryDirectory() as root:
        libdir = os.path.join(root, "library")
        staging_dir = os.path.join(root, "staging")
        monkeypatch.setattr("autodrome.services.organizer.conf.library_path", libdir)
        monkeypatch.setattr("autodrome.services.organizer.conf.staging_path", staging_dir)
        monkeypatch.setattr(
            "autodrome.services.organizer.conf.minimum_staging_free_bytes", 0
        )
        monkeypatch.setattr(
            "autodrome.services.organizer.conf.preserve_failed_staging", True
        )

        with pytest.raises(RuntimeError, match="tagging failed"):
            with organizer.create_staging_folder("Artist", "Album") as staging_folder:
                create_dummy_mp3(staging_folder, "downloaded.mp3")
                raise RuntimeError("tagging failed")

        assert os.path.isfile(os.path.join(staging_folder, "downloaded.mp3"))

def test_publication_failure_leaves_no_partial_album(monkeypatch):
    organizer = Organizer()
    staging_folder = None

    with tempfile.TemporaryDirectory() as root:
        libdir = os.path.join(root, "library")
        staging_dir = os.path.join(root, "staging")
        monkeypatch.setattr("autodrome.services.organizer.conf.library_path", libdir)
        monkeypatch.setattr("autodrome.services.organizer.conf.staging_path", staging_dir)
        monkeypatch.setattr(
            "autodrome.services.organizer.conf.minimum_staging_free_bytes", 0
        )
        monkeypatch.setattr(
            "autodrome.services.organizer.conf.preserve_failed_staging", True
        )

        with pytest.raises(OSError, match="rename failed"):
            with organizer.create_staging_folder("Artist", "Album") as staging_folder:
                create_dummy_mp3(staging_folder, "01 - Song A.mp3")
                monkeypatch.setattr(
                    "autodrome.services.organizer.os.rename",
                    mock.MagicMock(side_effect=OSError("rename failed")),
                )
                organizer.move_to_library(staging_folder, "Artist", "Album")

        assert not os.path.exists(os.path.join(libdir, "Artist", "Album"))
        assert os.path.isfile(os.path.join(staging_folder, "01 - Song A.mp3"))
