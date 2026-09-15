"""Durable, versioned provenance records for published albums."""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, Optional
from urllib.parse import parse_qs, urlsplit
from uuid import NAMESPACE_URL, uuid5

from autodrome.models.track import Track
from autodrome.services.track_files import match_track_files


SCHEMA_VERSION = 1
RECORD_VERSION = 1
SENSITIVE_KEY_PARTS = ("password", "secret", "token", "credential", "ticket")


class PublicationCatalogError(RuntimeError):
    """Raised when publication provenance cannot be stored or read safely."""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class PublicationCatalog:
    def __init__(self, path: str) -> None:
        self.path = Path(path).absolute()
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA synchronous = FULL")
        return connection

    @contextmanager
    def _connection(self):
        connection = self._connect()
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def _initialize(self) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self._connection() as connection:
                version = connection.execute("PRAGMA user_version").fetchone()[0]
                if version > SCHEMA_VERSION:
                    raise PublicationCatalogError(
                        f"Unsupported publication catalog version: {version}"
                    )
                if version == 0:
                    connection.executescript(
                        """
                        CREATE TABLE publications (
                            publication_id TEXT PRIMARY KEY,
                            job_id TEXT NOT NULL UNIQUE,
                            published_at TEXT NOT NULL,
                            destination TEXT NOT NULL UNIQUE,
                            artist TEXT NOT NULL,
                            album TEXT NOT NULL,
                            metadata_mode TEXT NOT NULL,
                            release_id TEXT,
                            record_json TEXT NOT NULL
                        );
                        CREATE INDEX publications_release_id
                            ON publications(release_id);
                        CREATE INDEX publications_published_at
                            ON publications(published_at DESC);
                        PRAGMA user_version = 1;
                        """
                    )
            self._fsync_directory(self.path.parent)
        except PublicationCatalogError:
            raise
        except Exception as error:
            raise PublicationCatalogError(
                "Could not initialize durable publication catalog"
            ) from error

    def record_publication(
        self,
        *,
        job_id: str,
        destination_path: str,
        library_root: str,
        artist: str,
        album: str,
        metadata_mode: str,
        release: Optional[Dict[str, Any]],
        playlist: Dict[str, Any],
        manifest: Dict[str, Any],
        tracks: Iterable[Track],
        cover: Dict[str, Any],
        accepted_overrides: Iterable[str],
        application_version: Optional[str],
        build_commit: Optional[str],
    ) -> Dict[str, Any]:
        """Hash the final files and atomically record one successful publication."""
        existing_record = self._get_by_job_id(job_id)
        if existing_record is not None:
            return existing_record
        track_list = list(tracks)
        destination = Path(destination_path).resolve(strict=True)
        library = Path(library_root).resolve(strict=True)
        try:
            relative_destination = destination.relative_to(library)
        except ValueError as error:
            raise PublicationCatalogError(
                "Published album is outside the configured library"
            ) from error
        if destination == library or not destination.is_dir():
            raise PublicationCatalogError("Published album destination is invalid")

        files = self._snapshot_files(destination)
        mp3_names = [entry["name"] for entry in files if entry["name"].lower().endswith(".mp3")]
        if len(mp3_names) != len(track_list):
            raise PublicationCatalogError(
                "Published files no longer match the validated track count"
            )
        file_by_track = {
            id(track): filename
            for filename, track in match_track_files(mp3_names, track_list)
        }

        manifest_tracks = self._normalized_manifest_tracks(manifest)
        if len(manifest_tracks) != len(track_list):
            raise PublicationCatalogError(
                "Validated manifest no longer matches final metadata"
            )

        publication_id = str(
            uuid5(NAMESPACE_URL, f"autodrome:publication:{job_id}")
        )
        published_at = utc_now()
        mapping = []
        for manifest_entry, track in zip(manifest_tracks, track_list, strict=True):
            mapping.append(
                {
                    "playlist_position": manifest_entry["position"],
                    "video_id": manifest_entry.get("id"),
                    "metadata_position": track.global_position,
                    "disc_number": track.disc_number,
                    "track_position": track.position,
                    "title": track.title,
                    "published_file": file_by_track[id(track)],
                }
            )

        normalized_playlist = {
            "id": playlist.get("id") or self._playlist_id(playlist.get("url")),
            "url": playlist.get("url"),
            "title": playlist.get("title"),
            "channel": playlist.get("channel"),
            "thumbnail": playlist.get("thumbnail"),
        }
        record = {
            "record_version": RECORD_VERSION,
            "publication_id": publication_id,
            "job_id": job_id,
            "published_at": published_at,
            "destination": {
                "relative_path": relative_destination.as_posix(),
                "artist": relative_destination.parts[0],
                "album": relative_destination.parts[-1],
            },
            "metadata": {
                "mode": metadata_mode,
                "artist": artist,
                "album": album,
                "date": release.get("date") if release else None,
                "tracks": [track.to_dict() for track in track_list],
            },
            "release": release,
            "playlist": normalized_playlist,
            "manifest": {
                "track_count": len(manifest_tracks),
                "unavailable": int(manifest.get("unavailable") or 0),
                "tracks": manifest_tracks,
            },
            "mapping": mapping,
            "track_count": len(track_list),
            "files": files,
            "cover": cover,
            "accepted_overrides": sorted(set(accepted_overrides)),
            "autodrome": {
                "version": application_version or "unknown",
                "commit": build_commit,
            },
        }
        self._reject_sensitive_keys(record)
        serialized = json.dumps(
            record, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )

        try:
            with self._connection() as connection:
                existing = connection.execute(
                    "SELECT record_json FROM publications WHERE job_id = ?",
                    (job_id,),
                ).fetchone()
                if existing is not None:
                    return json.loads(existing["record_json"])
                connection.execute(
                    """
                    INSERT INTO publications (
                        publication_id, job_id, published_at, destination,
                        artist, album, metadata_mode, release_id, record_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        publication_id,
                        job_id,
                        published_at,
                        relative_destination.as_posix(),
                        artist,
                        album,
                        metadata_mode,
                        release.get("id") if release else None,
                        serialized,
                    ),
                )
        except sqlite3.IntegrityError as error:
            existing_record = self._get_by_job_id(job_id)
            if existing_record is not None:
                return existing_record
            raise PublicationCatalogError(
                "A different publication already owns this library destination"
            ) from error
        except Exception as error:
            raise PublicationCatalogError(
                "Could not persist publication provenance"
            ) from error
        return record

    def list_publications(
        self,
        limit: int = 100,
        *,
        destination: Optional[str] = None,
        release_id: Optional[str] = None,
    ) -> list[Dict[str, Any]]:
        if not 1 <= limit <= 1000:
            raise ValueError("Publication list limit must be between 1 and 1000")
        try:
            with self._connection() as connection:
                filters = []
                parameters: list[Any] = []
                if destination is not None:
                    filters.append("destination = ?")
                    parameters.append(destination)
                if release_id is not None:
                    filters.append("release_id = ?")
                    parameters.append(release_id)
                where = f"WHERE {' AND '.join(filters)}" if filters else ""
                rows = connection.execute(
                    f"""
                    SELECT record_json FROM publications
                    {where}
                    ORDER BY published_at DESC, publication_id DESC LIMIT ?
                    """,
                    (*parameters, limit),
                ).fetchall()
            return [
                self._summary(json.loads(row["record_json"])) for row in rows
            ]
        except Exception as error:
            raise PublicationCatalogError(
                "Could not read publication history"
            ) from error

    def get_publication(self, publication_id: str) -> Dict[str, Any]:
        try:
            with self._connection() as connection:
                row = connection.execute(
                    "SELECT record_json FROM publications WHERE publication_id = ?",
                    (publication_id,),
                ).fetchone()
            if row is None:
                raise KeyError("Publication not found")
            return json.loads(row["record_json"])
        except KeyError:
            raise
        except Exception as error:
            raise PublicationCatalogError("Could not read publication") from error

    def _get_by_job_id(self, job_id: str) -> Optional[Dict[str, Any]]:
        try:
            with self._connection() as connection:
                row = connection.execute(
                    "SELECT record_json FROM publications WHERE job_id = ?",
                    (job_id,),
                ).fetchone()
            return json.loads(row["record_json"]) if row is not None else None
        except Exception as error:
            raise PublicationCatalogError("Could not read publication") from error

    @staticmethod
    def _summary(record: Dict[str, Any]) -> Dict[str, Any]:
        return {
            key: record[key]
            for key in ("publication_id", "job_id", "published_at", "track_count")
        } | {
            "destination": record["destination"],
            "metadata": {
                key: record["metadata"].get(key)
                for key in ("mode", "artist", "album")
            },
            "release": (
                {
                    key: record["release"].get(key)
                    for key in (
                        "id", "title", "date", "artist", "country",
                        "media_format", "medium_count", "track_count",
                    )
                }
                if record.get("release") else None
            ),
            "playlist": record["playlist"],
            "cover": record["cover"],
            "autodrome": record["autodrome"],
        }

    @staticmethod
    def _snapshot_files(destination: Path) -> list[Dict[str, Any]]:
        files = []
        for path in sorted(destination.iterdir(), key=lambda item: item.name.casefold()):
            if path.is_symlink() or not path.is_file():
                raise PublicationCatalogError(
                    f"Published album contains unsupported entry: {path.name}"
                )
            digest = hashlib.sha256()
            try:
                with path.open("rb") as published_file:
                    for chunk in iter(lambda: published_file.read(1024 * 1024), b""):
                        digest.update(chunk)
                size = path.stat().st_size
            except OSError as error:
                raise PublicationCatalogError(
                    f"Could not checksum published file: {path.name}"
                ) from error
            files.append({"name": path.name, "size": size, "sha256": digest.hexdigest()})
        return files

    @staticmethod
    def _normalized_manifest_tracks(manifest: Dict[str, Any]) -> list[Dict[str, Any]]:
        tracks = manifest.get("tracks")
        if not isinstance(tracks, list):
            raise PublicationCatalogError("Validated manifest is unavailable")
        normalized = []
        for entry in tracks:
            if not isinstance(entry, dict):
                raise PublicationCatalogError("Validated manifest is invalid")
            normalized.append(
                {
                    "position": entry.get("position"),
                    "id": entry.get("id"),
                    "url": entry.get("url"),
                    "title": entry.get("title"),
                }
            )
        return normalized

    @staticmethod
    def _playlist_id(url: Any) -> Optional[str]:
        if not isinstance(url, str):
            return None
        identifiers = parse_qs(urlsplit(url).query).get("list", [])
        return identifiers[0] if len(identifiers) == 1 else None

    @classmethod
    def _reject_sensitive_keys(cls, value: Any) -> None:
        if isinstance(value, dict):
            for key, nested in value.items():
                if any(part in str(key).lower() for part in SENSITIVE_KEY_PARTS):
                    raise PublicationCatalogError(
                        "Publication record contains a sensitive field"
                    )
                cls._reject_sensitive_keys(nested)
        elif isinstance(value, list):
            for nested in value:
                cls._reject_sensitive_keys(nested)

    @staticmethod
    def _fsync_directory(directory: Path) -> None:
        descriptor = os.open(directory, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
