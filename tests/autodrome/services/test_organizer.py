import os
import tempfile
from unittest import mock

import pytest

from autodrome.services.organizer import Organizer
from autodrome.metadata_service import MetadataService
from autodrome.models.track import Track
from tests.fixtures import (
    generated_musicbrainz_release,
    generated_playlist,
    playlist_from_hell,
)

def create_dummy_mp3(folder: str, filename: str):
    path = os.path.join(folder, filename)
    with open(path, "wb") as f:
        f.write(b"ID3")  # mínimo para que lo detecte mutagen
    return path

def test_tag_and_rename_basic(monkeypatch):
    organizer = Organizer()

    with tempfile.TemporaryDirectory() as tmpdir:
        create_dummy_mp3(tmpdir, "01 - Audio.mp3")
        create_dummy_mp3(tmpdir, "02 - Audio.mp3")

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
        create_dummy_mp3(tmpdir, "01 - Audio.mp3")
        tracks = [Track(1, "Song A"), Track(2, "Song B")]

        monkeypatch.setattr(organizer.tagger, "tag_files", mock.MagicMock())
        monkeypatch.setattr(organizer.cover_embedder, "embed_cover", mock.MagicMock())

        with pytest.raises(
            ValueError,
            match="Downloaded track count mismatch: expected 2, got 1",
        ):
            organizer.tag_and_rename(tmpdir, "Artist", "Album", tracks)

        assert os.listdir(tmpdir) == ["01 - Audio.mp3"]
        organizer.tagger.tag_files.assert_not_called()
        organizer.cover_embedder.embed_cover.assert_not_called()

def test_tag_and_rename_rejects_extra_download_before_changes(monkeypatch):
    organizer = Organizer()

    with tempfile.TemporaryDirectory() as tmpdir:
        create_dummy_mp3(tmpdir, "01 - Audio.mp3")
        create_dummy_mp3(tmpdir, "02 - Audio.mp3")
        tracks = [Track(1, "Song A")]

        monkeypatch.setattr(organizer.tagger, "tag_files", mock.MagicMock())
        monkeypatch.setattr(organizer.cover_embedder, "embed_cover", mock.MagicMock())

        with pytest.raises(
            ValueError,
            match="Downloaded track count mismatch: expected 1, got 2",
        ):
            organizer.tag_and_rename(tmpdir, "Artist", "Album", tracks)

        assert sorted(os.listdir(tmpdir)) == ["01 - Audio.mp3", "02 - Audio.mp3"]
        organizer.tagger.tag_files.assert_not_called()
        organizer.cover_embedder.embed_cover.assert_not_called()

def test_tag_and_rename_rejects_sanitized_filename_collision(monkeypatch):
    organizer = Organizer()

    with tempfile.TemporaryDirectory() as tmpdir:
        create_dummy_mp3(tmpdir, "01 - Audio.mp3")
        create_dummy_mp3(tmpdir, "02 - Audio.mp3")
        tracks = [Track(1, "Song?"), Track(1, "Song*")]

        monkeypatch.setattr(organizer.tagger, "tag_files", mock.MagicMock())

        with pytest.raises(
            ValueError,
            match="duplicate track identity",
        ):
            organizer.tag_and_rename(tmpdir, "Artist", "Album", tracks)

        assert sorted(os.listdir(tmpdir)) == ["01 - Audio.mp3", "02 - Audio.mp3"]
        organizer.tagger.tag_files.assert_not_called()

def test_tag_and_rename_uses_unambiguous_multidisc_names(monkeypatch):
    organizer = Organizer()

    with tempfile.TemporaryDirectory() as tmpdir:
        create_dummy_mp3(tmpdir, "01 - Audio.mp3")
        create_dummy_mp3(tmpdir, "02 - Audio.mp3")
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


def test_adversarial_titles_remain_distinct_after_sanitization(tmp_path, monkeypatch):
    fixture = playlist_from_hell()
    entries_by_id = {
        entry.get("id"): entry for entry in fixture["playlist"]["entries"]
    }
    tracks = []
    valid_positions = [
        position
        for position in range(1, len(fixture["playlist"]["entries"]) + 1)
        if position not in fixture["expected"]["unavailable_positions"]
    ]
    for position, track_id in zip(
        valid_positions, fixture["expected"]["extractable_ids"], strict=True
    ):
        entry = entries_by_id[track_id]
        tracks.append(Track(position, entry["title"]))
        (tmp_path / f"{position:02d} - Source.mp3").write_text(
            track_id, encoding="utf-8"
        )

    organizer = Organizer()
    monkeypatch.setattr(organizer.tagger, "tag_files", mock.MagicMock())
    organizer.tag_and_rename(str(tmp_path), "Artist", "Album", tracks)

    files = sorted(tmp_path.iterdir())
    assert len(files) == len(tracks)
    assert {path.read_text(encoding="utf-8") for path in files} == set(
        fixture["expected"]["extractable_ids"]
    )
    assert any("Beyoncé 🚗" in path.name for path in files)
    assert sum(path.name.endswith("Same title.mp3") for path in files) == 2
    assert sum("Sanitized _ collision.mp3" in path.name for path in files) == 2
    assert any("deliberately long title" in path.name for path in files)


def test_tag_and_rename_prepares_cover_once_before_modifying_tracks(monkeypatch):
    organizer = Organizer()

    with tempfile.TemporaryDirectory() as tmpdir:
        create_dummy_mp3(tmpdir, "01 - Audio.mp3")
        create_dummy_mp3(tmpdir, "02 - Audio.mp3")
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
                "01 - Audio.mp3",
                "02 - Audio.mp3",
                "cover.png",
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
        create_dummy_mp3(tmpdir, "01 - Audio.mp3")
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

        assert sorted(os.listdir(tmpdir)) == ["01 - Audio.mp3", "cover.jpg"]
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
                "albumartist": ["Artist"],
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
                "albumartist": ["Artist"],
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


def test_destination_preflight_reports_missing_and_normalized_names(tmp_path, monkeypatch):
    monkeypatch.setattr("autodrome.services.organizer.conf.library_path", str(tmp_path))
    before = list(tmp_path.iterdir())

    result = Organizer().inspect_album_destination("AC/DC", "Live: 1992")

    assert result == {
        "state": "not_found",
        "exists": False,
        "artist": "AC_DC",
        "album": "Live_ 1992",
        "relative_path": "AC_DC/Live_ 1992",
        "mp3_count": 0,
        "file_count": 0,
    }
    assert list(tmp_path.iterdir()) == before


def test_destination_preflight_counts_existing_regular_files(tmp_path, monkeypatch):
    monkeypatch.setattr("autodrome.services.organizer.conf.library_path", str(tmp_path))
    album = tmp_path / "Artist" / "Album"
    album.mkdir(parents=True)
    (album / "01.mp3").write_bytes(b"audio")
    (album / "02.MP3").write_bytes(b"audio")
    (album / "cover.jpg").write_bytes(b"image")
    (album / "nested").mkdir()
    (album / "linked.mp3").symlink_to(album / "01.mp3")

    result = Organizer().inspect_album_destination("Artist", "Album")

    assert result["state"] == "exists"
    assert result["exists"] is True
    assert result["mp3_count"] == 2
    assert result["file_count"] == 3


def test_destination_preflight_never_turns_filesystem_errors_into_missing(
    tmp_path, monkeypatch
):
    monkeypatch.setattr("autodrome.services.organizer.conf.library_path", str(tmp_path))
    monkeypatch.setattr(
        "autodrome.services.organizer.os.lstat",
        mock.MagicMock(side_effect=PermissionError("denied")),
    )

    result = Organizer().inspect_album_destination("Artist", "Album")

    assert result["state"] == "unknown"
    assert result["exists"] is None
    assert result["mp3_count"] is None


def test_destination_preflight_does_not_follow_library_symlinks(tmp_path, monkeypatch):
    library = tmp_path / "library"
    outside = tmp_path / "outside"
    library.mkdir()
    outside.mkdir()
    (outside / "Album").mkdir()
    (outside / "Album" / "private.mp3").write_bytes(b"private")
    (library / "Artist").symlink_to(outside, target_is_directory=True)
    monkeypatch.setattr("autodrome.services.organizer.conf.library_path", str(library))

    result = Organizer().inspect_album_destination("Artist", "Album")

    assert result["state"] == "unknown"
    assert result["exists"] is None
    assert result["mp3_count"] is None


def test_album_created_after_preflight_is_not_overwritten(tmp_path, monkeypatch):
    library = tmp_path / "library"
    staging = tmp_path / "staging"
    monkeypatch.setattr("autodrome.services.organizer.conf.library_path", str(library))
    monkeypatch.setattr("autodrome.services.organizer.conf.staging_path", str(staging))
    monkeypatch.setattr(
        "autodrome.services.organizer.conf.minimum_staging_free_bytes", 0
    )
    organizer = Organizer()

    assert organizer.inspect_album_destination("Artist", "Album")["state"] == "not_found"
    with pytest.raises(FileExistsError, match="Album already exists"):
        with organizer.create_staging_folder("Artist", "Album") as staging_folder:
            create_dummy_mp3(staging_folder, "01 - Song.mp3")
            destination = library / "Artist" / "Album"
            destination.mkdir(parents=True)
            existing = destination / "existing.mp3"
            existing.write_bytes(b"existing")
            organizer.move_to_library(staging_folder, "Artist", "Album")

    assert existing.read_bytes() == b"existing"

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

@pytest.mark.parametrize("count,multidisc", [(99, False), (100, False), (101, False), (101, True)])
def test_audio_identity_survives_rename_tag_and_validation(tmp_path, monkeypatch, count, multidisc):
    raw_release = generated_musicbrainz_release(
        count,
        first_disc_tracks=60 if multidisc else None,
    )
    tracks = MetadataService(mock.AsyncMock())._parse_tracks(raw_release)
    playlist = generated_playlist(count)
    for index, entry in enumerate(playlist["entries"], start=1):
        (tmp_path / f"{index:02d} - Source.mp3").write_text(
            entry["id"], encoding="utf-8"
        )
    tagged = {}

    class Audio(dict):
        info = mock.Mock(length=180)

        def save(self):
            pass

    def load_audio(path, **kwargs):
        with open(path, encoding="utf-8") as audio_file:
            identity = audio_file.read()
        return tagged.setdefault(identity, Audio())

    monkeypatch.setattr("autodrome.services.tagger.MP3", load_audio)
    monkeypatch.setattr("autodrome.services.organizer.MP3", load_audio)
    monkeypatch.setattr("autodrome.services.organizer.ID3", lambda path: mock.Mock(getall=lambda name: []))
    organizer = Organizer()
    organizer.tag_and_rename(
        str(tmp_path), "Boundary Album Artist", "Boundary Album", tracks
    )
    for track in tracks:
        identity = f"audio-{track.global_position:03d}"
        audio = tagged[identity]
        assert audio["title"] == track.title
        assert audio["artist"] == track.artist
        assert audio["albumartist"] == "Boundary Album Artist"
        assert audio["tracknumber"] == str(track.number)
        if multidisc:
            assert audio["discnumber"] == str(track.disc_number)
        prefix = f"{track.disc_number:02d}-{track.position:02d}" if multidisc else f"{track.number:02d}"
        assert (tmp_path / f"{prefix} - {track.title}.mp3").read_text(
            encoding="utf-8"
        ) == identity
        for key, value in list(audio.items()):
            audio[key] = [value]  # EasyID3 reads return lists.
    organizer.validate_album(
        str(tmp_path), "Boundary Album Artist", "Boundary Album", tracks
    )


@pytest.mark.parametrize("files", [
    ["Audio.mp3", "02 - Audio.mp3"],
    ["01 - A.mp3", "1 - B.mp3"],
    ["01 - A.mp3", "03 - B.mp3"],
])
def test_unreliable_identity_rejected_before_any_rename(tmp_path, monkeypatch, files):
    for name in files:
        (tmp_path / name).write_bytes(b"audio")
    organizer = Organizer()
    tag = mock.Mock()
    monkeypatch.setattr(organizer.tagger, "tag_files", tag)
    with pytest.raises(ValueError, match="identity|identities"):
        organizer.tag_and_rename(str(tmp_path), "Artist", "Album", [Track(1, "A"), Track(2, "B")])
    assert sorted(p.name for p in tmp_path.iterdir()) == sorted(files)
    tag.assert_not_called()
