import hashlib
import json
import sqlite3
from pathlib import Path

import pytest

from autodrome.models.track import Track
from autodrome.services.publication_catalog import (
    PublicationCatalog,
    PublicationCatalogError,
)


def build_record(catalog, library, *, job_id="job-1", album="Album"):
    destination = library / "Artist" / album
    destination.mkdir(parents=True)
    first = destination / "01 - First.mp3"
    second = destination / "02 - Second.mp3"
    first.write_bytes(b"published-first")
    second.write_bytes(b"published-second")
    tracks = [Track(1, "First"), Track(2, "Second")]
    manifest = {
        "unavailable": 0,
        "tracks": [
            {"position": 1, "id": "video-1", "url": "https://youtube.test/1", "title": "First upload"},
            {"position": 2, "id": "video-2", "url": "https://youtube.test/2", "title": "Second upload"},
        ],
    }
    record = catalog.record_publication(
        job_id=job_id,
        destination_path=str(destination),
        library_root=str(library),
        artist="Artist",
        album=album,
        metadata_mode="musicbrainz",
        release={
            "id": "release-1", "title": album, "artist": "Artist",
            "date": "2020", "cover_url": None, "track_count": 2,
            "country": "GB", "media_format": "CD", "medium_count": 1,
            "tracks": [track.to_dict() for track in tracks],
        },
        playlist={
            "url": "https://www.youtube.com/playlist?list=PL1234567890",
            "title": "Album playlist", "channel": "Uploader",
            "bearer_token": "must-never-be-persisted",
        },
        manifest=manifest,
        tracks=tracks,
        cover={"source": "none", "embedded": False, "square_strategy": None},
        accepted_overrides=[],
        application_version="autodrome/0.2.0.dev0",
        build_commit="abcdef1",
    )
    return record, destination


def test_publication_is_durable_versioned_and_hashes_final_files(tmp_path):
    library = tmp_path / "library"
    library.mkdir()
    path = tmp_path / "catalog.sqlite3"
    catalog = PublicationCatalog(str(path))

    record, destination = build_record(catalog, library)

    assert record["record_version"] == 1
    assert record["destination"]["relative_path"] == "Artist/Album"
    assert record["manifest"]["tracks"][0]["id"] == "video-1"
    assert record["mapping"][1]["published_file"] == "02 - Second.mp3"
    assert "must-never-be-persisted" not in json.dumps(record)
    assert record["files"][0]["sha256"] == hashlib.sha256(
        (destination / "01 - First.mp3").read_bytes()
    ).hexdigest()
    assert len(record["files"][0]["sha256"]) == 64
    assert PublicationCatalog(str(path)).get_publication(
        record["publication_id"]
    ) == record
    assert catalog.list_publications(destination="Artist/Album")[0][
        "publication_id"
    ] == record["publication_id"]
    assert catalog.list_publications(release_id="release-1")[0][
        "publication_id"
    ] == record["publication_id"]
    assert catalog.list_publications(release_id="other") == []
    with sqlite3.connect(path) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 1


def test_job_recording_is_idempotent_and_destination_is_unique(tmp_path):
    library = tmp_path / "library"
    library.mkdir()
    catalog = PublicationCatalog(str(tmp_path / "catalog.sqlite3"))
    first, destination = build_record(catalog, library)

    duplicate = catalog.record_publication(
        job_id="job-1",
        destination_path=str(destination),
        library_root=str(library),
        artist="Artist",
        album="Album",
        metadata_mode="manual",
        release=None,
        playlist={"url": "https://www.youtube.com/playlist?list=PL1234567890"},
        manifest={"tracks": [
            {"position": 1, "url": "one", "title": "One"},
            {"position": 2, "url": "two", "title": "Two"},
        ]},
        tracks=[Track(1, "First"), Track(2, "Second")],
        cover={"source": "none"},
        accepted_overrides=[],
        application_version=None,
        build_commit=None,
    )
    assert duplicate == first
    assert len(catalog.list_publications()) == 1

    with pytest.raises(PublicationCatalogError, match="different publication"):
        catalog.record_publication(
            job_id="job-2",
            destination_path=str(destination),
            library_root=str(library),
            artist="Artist", album="Album", metadata_mode="manual", release=None,
            playlist={"url": "https://www.youtube.com/playlist?list=PL1234567890"},
            manifest={"tracks": [
                {"position": 1, "url": "one", "title": "One"},
                {"position": 2, "url": "two", "title": "Two"},
            ]},
            tracks=[Track(1, "First"), Track(2, "Second")],
            cover={"source": "none"}, accepted_overrides=[],
            application_version=None, build_commit=None,
        )


def test_catalog_rejects_unknown_future_schema(tmp_path):
    path = tmp_path / "catalog.sqlite3"
    with sqlite3.connect(path) as connection:
        connection.execute("PRAGMA user_version = 99")
    with pytest.raises(PublicationCatalogError, match="Unsupported"):
        PublicationCatalog(str(path))
