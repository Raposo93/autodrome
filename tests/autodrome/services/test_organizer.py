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

def test_tag_and_rename_rejects_sanitized_filename_collision(monkeypatch):
    organizer = Organizer()

    with tempfile.TemporaryDirectory() as tmpdir:
        create_dummy_mp3(tmpdir, "track1.mp3")
        create_dummy_mp3(tmpdir, "track2.mp3")
        tracks = [Track(1, "Song?"), Track(1, "Song*")]

        monkeypatch.setattr(organizer.tagger, "tag_files", mock.MagicMock())

        with pytest.raises(
            ValueError,
            match="Track filename collision after sanitization: 01 - Song_.mp3",
        ):
            organizer.tag_and_rename(tmpdir, "Artist", "Album", tracks)

        assert sorted(os.listdir(tmpdir)) == ["track1.mp3", "track2.mp3"]
        organizer.tagger.tag_files.assert_not_called()

def test_tag_and_rename_uses_unambiguous_multidisc_names(monkeypatch):
    organizer = Organizer()

    with tempfile.TemporaryDirectory() as tmpdir:
        create_dummy_mp3(tmpdir, "track1.mp3")
        create_dummy_mp3(tmpdir, "track2.mp3")
        tracks = [
            Track(1, "First", disc_number=1, position=1, global_position=1),
            Track(1, "First", disc_number=2, position=1, global_position=2),
        ]
        monkeypatch.setattr(organizer.tagger, "tag_files", mock.MagicMock())

        organizer.tag_and_rename(tmpdir, "Artist", "Album", tracks)

        assert sorted(os.listdir(tmpdir)) == [
            "01-01 - First.mp3",
            "02-01 - First.mp3",
        ]


def test_tag_and_rename_prepares_cover_once_before_modifying_tracks(monkeypatch):
    organizer = Organizer()

    with tempfile.TemporaryDirectory() as tmpdir:
        create_dummy_mp3(tmpdir, "track1.mp3")
        create_dummy_mp3(tmpdir, "track2.mp3")
        cover_path = os.path.join(tmpdir, "cover.png")
        with open(cover_path, "wb") as cover_file:
            cover_file.write(b"cover")
        tracks = [Track(1, "Song A"), Track(2, "Song B")]
        prepared_cover = object()

        monkeypatch.setattr(organizer.tagger, "tag_files", mock.MagicMock())
        monkeypatch.setattr(organizer.cover_embedder, "embed_cover", mock.MagicMock())

        def prepare_before_changes(path):
            assert path == cover_path
            assert sorted(os.listdir(tmpdir)) == [
                "cover.png",
                "track1.mp3",
                "track2.mp3",
            ]
            organizer.tagger.tag_files.assert_not_called()
            return prepared_cover

        monkeypatch.setattr(
            organizer.cover_embedder,
            "prepare_cover",
            mock.MagicMock(side_effect=prepare_before_changes),
        )

        organizer.tag_and_rename(
            tmpdir, "Artist", "Album", tracks, cover_path=cover_path
        )

        organizer.cover_embedder.prepare_cover.assert_called_once_with(cover_path)
        assert organizer.cover_embedder.embed_cover.call_args_list == [
            mock.call(os.path.join(tmpdir, "01 - Song A.mp3"), prepared_cover),
            mock.call(os.path.join(tmpdir, "02 - Song B.mp3"), prepared_cover),
        ]


def test_tag_and_rename_rejects_cover_before_modifying_tracks(monkeypatch):
    organizer = Organizer()

    with tempfile.TemporaryDirectory() as tmpdir:
        create_dummy_mp3(tmpdir, "track1.mp3")
        cover_path = os.path.join(tmpdir, "cover.jpg")
        with open(cover_path, "wb") as cover_file:
            cover_file.write(b"damaged")
        monkeypatch.setattr(organizer.tagger, "tag_files", mock.MagicMock())
        monkeypatch.setattr(
            organizer.cover_embedder,
            "prepare_cover",
            mock.MagicMock(side_effect=ValueError("invalid cover")),
        )
        monkeypatch.setattr(organizer.cover_embedder, "embed_cover", mock.MagicMock())

        with pytest.raises(ValueError, match="invalid cover"):
            organizer.tag_and_rename(
                tmpdir,
                "Artist",
                "Album",
                [Track(1, "Song A")],
                cover_path=cover_path,
            )

        assert sorted(os.listdir(tmpdir)) == ["cover.jpg", "track1.mp3"]
        organizer.tagger.tag_files.assert_not_called()
        organizer.cover_embedder.embed_cover.assert_not_called()


def test_validate_album_accepts_readable_tagged_mp3s(monkeypatch):
    organizer = Organizer()
    tracks = [Track(1, "Song A"), Track(2, "Song B")]

    with tempfile.TemporaryDirectory() as tmpdir:
        files = ["01 - Song A.mp3", "02 - Song B.mp3"]
        for file in files:
            create_dummy_mp3(tmpdir, file)

        audio_files = []
        for track in tracks:
            audio = mock.MagicMock()
            audio.info.length = 180
            audio.get.side_effect = {
                "artist": ["Artist"],
                "album": ["Album"],
                "title": [track.title],
                "tracknumber": [str(track.number)],
            }.get
            audio_files.append(audio)

        monkeypatch.setattr(
            "autodrome.services.organizer.MP3", mock.MagicMock(side_effect=audio_files)
        )
        id3 = mock.MagicMock()
        id3.getall.return_value = [mock.MagicMock(data=b"cover")]
        monkeypatch.setattr(
            "autodrome.services.organizer.ID3", mock.MagicMock(return_value=id3)
        )
        monkeypatch.setattr(
            "autodrome.services.organizer.conf.max_embedded_cover_bytes", 1024
        )

        organizer.validate_album(tmpdir, "Artist", "Album", tracks)

def test_validate_album_rejects_zero_duration(monkeypatch):
    organizer = Organizer()

    with tempfile.TemporaryDirectory() as tmpdir:
        create_dummy_mp3(tmpdir, "01 - Song A.mp3")
        audio = mock.MagicMock()
        audio.info.length = 0
        monkeypatch.setattr(
            "autodrome.services.organizer.MP3", mock.MagicMock(return_value=audio)
        )

        with pytest.raises(ValueError, match="has no positive duration"):
            organizer.validate_album(
                tmpdir, "Artist", "Album", [Track(1, "Song A")]
            )

def test_validate_album_rejects_oversized_embedded_cover(monkeypatch):
    organizer = Organizer()

    with tempfile.TemporaryDirectory() as tmpdir:
        create_dummy_mp3(tmpdir, "01 - Song A.mp3")
        audio = mock.MagicMock()
        audio.info.length = 180
        audio.get.side_effect = {
            "artist": ["Artist"],
            "album": ["Album"],
            "title": ["Song A"],
            "tracknumber": ["1"],
        }.get
        monkeypatch.setattr(
            "autodrome.services.organizer.MP3", mock.MagicMock(return_value=audio)
        )
        id3 = mock.MagicMock()
        id3.getall.return_value = [mock.MagicMock(data=b"oversized")]
        monkeypatch.setattr(
            "autodrome.services.organizer.ID3", mock.MagicMock(return_value=id3)
        )
        monkeypatch.setattr(
            "autodrome.services.organizer.conf.max_embedded_cover_bytes", 4
        )

        with pytest.raises(
            ValueError,
            match=r"size 9 bytes, limit 4 bytes",
        ):
            organizer.validate_album(
                tmpdir, "Artist", "Album", [Track(1, "Song A")]
            )

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
