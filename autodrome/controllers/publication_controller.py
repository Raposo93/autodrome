"""Read publication provenance and rebuild a safe Review starting point."""

from __future__ import annotations

import asyncio
from typing import Any, Dict, Optional

from autodrome.services.publication_catalog import PublicationCatalog


class PublicationController:
    def __init__(self, catalog: PublicationCatalog, downloader, metadata_service) -> None:
        self.catalog = catalog
        self.downloader = downloader
        self.metadata_service = metadata_service

    def list_publications(
        self,
        limit: int = 100,
        *,
        destination: Optional[str] = None,
        release_id: Optional[str] = None,
    ) -> list[Dict[str, Any]]:
        return self.catalog.list_publications(
            limit,
            destination=destination,
            release_id=release_id,
        )

    def get_publication(self, publication_id: str) -> Dict[str, Any]:
        return self.catalog.get_publication(publication_id)

    async def recreate_review(self, publication_id: str) -> Dict[str, Any]:
        original = self.catalog.get_publication(publication_id)
        manifest_result, release_result = await asyncio.gather(
            self._refresh_manifest(original),
            self._refresh_release(original),
        )
        original_manifest = original["manifest"]
        original_release = original.get("release")

        return {
            "publication": original,
            "review": {
                "metadata_mode": original["metadata"]["mode"],
                "artist": original["metadata"]["artist"],
                "album": original["metadata"]["album"],
                "playlist": {
                    **original["playlist"],
                    "track_count": original["track_count"],
                    "tracks": original_manifest["tracks"],
                },
                "release": original_release,
                "cover": original["cover"],
                "accepted_overrides": original.get("accepted_overrides", []),
            },
            "drift": {
                "playlist": self._compare_manifest(
                    original_manifest,
                    manifest_result.get("value"),
                    manifest_result.get("error"),
                ),
                "release": self._compare_release(
                    original_release,
                    release_result.get("value"),
                    release_result.get("error"),
                ),
            },
            "enqueued": False,
        }

    async def _refresh_manifest(self, record: Dict[str, Any]) -> Dict[str, Any]:
        try:
            value = await self.downloader.get_playlist_manifest(
                record["playlist"]["url"],
                refresh=True,
                allow_unavailable=True,
            )
        except Exception:
            return {"error": "The current YouTube manifest could not be loaded."}
        return {"value": value}

    async def _refresh_release(self, record: Dict[str, Any]) -> Dict[str, Any]:
        release = record.get("release")
        if release is None:
            return {"value": None}
        try:
            current = await self.metadata_service.get_release(
                release["id"], refresh=True
            )
        except Exception:
            return {"error": "The current MusicBrainz release could not be loaded."}
        return {"value": self._release_dict(current)}

    @staticmethod
    def _release_dict(release) -> Dict[str, Any]:
        return {
            "id": release.id,
            "title": release.title,
            "date": release.date,
            "artist": release.artist,
            "cover_url": release.cover_url,
            "track_count": len(release.tracks),
            "country": release.country,
            "media_format": release.media_format,
            "medium_count": release.medium_count,
            "tracks": [track.to_dict() for track in release.tracks],
        }

    @classmethod
    def _compare_manifest(
        cls,
        original: Dict[str, Any],
        current: Optional[Dict[str, Any]],
        error: Optional[str],
    ) -> Dict[str, Any]:
        if error:
            return {
                "status": "unavailable",
                "changed": None,
                "error": error,
                "changes": [],
            }
        original_tracks = cls._tracks_by_position(original.get("tracks", []))
        current_tracks = cls._tracks_by_position((current or {}).get("tracks", []))
        changes = []
        for position in sorted(original_tracks.keys() | current_tracks.keys()):
            before = original_tracks.get(position)
            after = current_tracks.get(position)
            if before == after:
                continue
            status = "changed"
            if before is None:
                status = "added"
            elif after is None:
                status = "removed"
            changes.append(
                {
                    "position": position,
                    "status": status,
                    "original": before,
                    "current": after,
                }
            )
        return {
            "status": "changed" if changes else "unchanged",
            "changed": bool(changes),
            "error": None,
            "original_track_count": len(original_tracks),
            "current_track_count": len(current_tracks),
            "current_unavailable": int((current or {}).get("unavailable") or 0),
            "changes": changes,
        }

    @staticmethod
    def _tracks_by_position(tracks: list[Dict[str, Any]]) -> Dict[int, Dict[str, Any]]:
        return {
            int(track["position"]): {
                key: track.get(key) for key in ("position", "id", "url", "title")
            }
            for track in tracks
            if isinstance(track, dict) and isinstance(track.get("position"), int)
        }

    @classmethod
    def _compare_release(
        cls,
        original: Optional[Dict[str, Any]],
        current: Optional[Dict[str, Any]],
        error: Optional[str],
    ) -> Dict[str, Any]:
        if original is None:
            return {
                "status": "not_applicable",
                "changed": False,
                "error": None,
                "changes": [],
            }
        if error:
            return {
                "status": "unavailable",
                "changed": None,
                "error": error,
                "changes": [],
            }
        fields = (
            "title", "date", "artist", "cover_url", "track_count",
            "country", "media_format", "medium_count", "tracks",
        )
        changes = [
            {"field": field, "original": original.get(field), "current": (current or {}).get(field)}
            for field in fields
            if original.get(field) != (current or {}).get(field)
        ]
        return {
            "status": "changed" if changes else "unchanged",
            "changed": bool(changes),
            "error": None,
            "changes": changes,
        }
