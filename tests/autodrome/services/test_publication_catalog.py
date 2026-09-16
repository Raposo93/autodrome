import asyncio
import hashlib
import json
import sqlite3
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

from autodrome.controllers.downloader_controller import DownloaderController
from autodrome.services.organizer import Organizer
from autodrome.services.download_queue import DownloadQueueManager

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
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 2


def test_job_recording_is_idempotent(tmp_path):
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



def test_catalog_rejects_unknown_future_schema(tmp_path):
    path = tmp_path / "catalog.sqlite3"
    with sqlite3.connect(path) as connection:
        connection.execute("PRAGMA user_version = 99")
    with pytest.raises(PublicationCatalogError, match="Unsupported"):
        PublicationCatalog(str(path))


def legacy_catalog(path, record):
    with sqlite3.connect(path) as connection:
        connection.executescript("""
            CREATE TABLE publications (
                publication_id TEXT PRIMARY KEY, job_id TEXT NOT NULL UNIQUE,
                published_at TEXT NOT NULL, destination TEXT NOT NULL UNIQUE,
                artist TEXT NOT NULL, album TEXT NOT NULL, metadata_mode TEXT NOT NULL,
                release_id TEXT, record_json TEXT NOT NULL
            );
            CREATE INDEX publications_release_id ON publications(release_id);
            CREATE INDEX publications_published_at ON publications(published_at DESC);
            PRAGMA user_version = 1;
        """)
        connection.execute(
            "INSERT INTO publications VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (record["publication_id"], record["job_id"], record["published_at"],
             record["destination"]["relative_path"], "Artist", "Album", "musicbrainz",
             "release-1", json.dumps(record)),
        )


def test_migrate_history_and_republish_through_queue(tmp_path, monkeypatch):
    library = tmp_path / "library"
    library.mkdir()
    initial = PublicationCatalog(str(tmp_path / "initial.sqlite3"))
    original, destination = build_record(initial, library)
    path = tmp_path / "legacy.sqlite3"
    legacy_catalog(path, original)
    catalog = PublicationCatalog(str(path))
    assert catalog.get_publication(original["publication_id"]) == original
    destination.rename(tmp_path / "archived-album")
    monkeypatch.setattr("autodrome.services.organizer.conf.library_path", str(library))
    monkeypatch.setattr("autodrome.services.organizer.conf.staging_path", str(tmp_path / "staging"))
    monkeypatch.setattr("autodrome.services.organizer.conf.minimum_staging_free_bytes", 0)
    organizer = Organizer()
    # Audio encoding/tag validation are covered separately; keep real publication IO.
    organizer.tagger.tag_files = MagicMock()
    organizer.validate_album = MagicMock()
    downloader = MagicMock()
    manifest = {"unavailable": 0, "tracks": [
        {"position": 1, "id": "new-video", "url": "video", "title": "New track"},
    ]}
    downloader.get_playlist_manifest = AsyncMock(return_value=manifest)

    async def download(url, folder, **kwargs):
        (Path(folder) / "01 - Source.mp3").write_bytes(b"new audio")
        return manifest

    downloader.download_playlist = AsyncMock(side_effect=download)
    controller = DownloaderController(
        downloader, organizer, MagicMock(), publication_catalog=catalog,
    )

    async def run():
        queue = DownloadQueueManager(controller, AsyncMock(), str(tmp_path / "queue.json"))
        payload = dict(playlist_url="playlist", artist="Artist", album="Album",
                       release_id=None, metadata_mode="manual", manual_confirmed=True,
                       track_count=1, cover_source="none")
        job_id = await queue.enqueue(payload)
        queue.start()
        try:
            await asyncio.wait_for(queue.queue.join(), timeout=5)
            assert queue._jobs[job_id].status == "succeeded"
            with pytest.raises(FileExistsError):
                await queue.enqueue(payload)
        finally:
            await queue.stop()
        return job_id

    job_id = asyncio.run(run())
    reopened = PublicationCatalog(str(path))
    records = reopened.list_publications(destination="Artist/Album")
    assert len(records) == 2
    new = reopened.get_publication(next(r["publication_id"] for r in records if r["job_id"] == job_id))
    assert new["metadata"]["mode"] == "manual"
    assert new["files"][0]["sha256"] == hashlib.sha256(b"new audio").hexdigest()
    assert new["files"] != original["files"]
    assert reopened.get_publication(original["publication_id"]) == original
    assert (destination / "01 - New track.mp3").read_bytes() == b"new audio"


def test_failed_migration_rolls_back_history_and_schema(tmp_path, monkeypatch):
    library = tmp_path / "library"
    library.mkdir()
    original, _ = build_record(PublicationCatalog(str(tmp_path / "initial.sqlite3")), library)
    path = tmp_path / "legacy.sqlite3"
    legacy_catalog(path, original)
    connect = PublicationCatalog._connect

    def fail_drop(self):
        connection = connect(self)
        connection.set_authorizer(lambda action, *args: (
            sqlite3.SQLITE_DENY if action == sqlite3.SQLITE_DROP_TABLE else sqlite3.SQLITE_OK
        ))
        return connection

    with monkeypatch.context() as context:
        context.setattr(PublicationCatalog, "_connect", fail_drop)
        with pytest.raises(PublicationCatalogError, match="initialize"):
            PublicationCatalog(str(path))
    with sqlite3.connect(path) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 1
        assert json.loads(connection.execute("SELECT record_json FROM publications").fetchone()[0]) == original
        assert connection.execute("SELECT name FROM sqlite_master WHERE name='publications_v2'").fetchone() is None
    assert PublicationCatalog(str(path)).get_publication(original["publication_id"]) == original
