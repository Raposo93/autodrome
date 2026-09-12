import asyncio
import time
from typing import Optional

from autodrome.logger import logger
from autodrome.metadata_service import MetadataService
from autodrome.yt_api import YTApi
from autodrome.http_client_async import AsyncHttpClient, UpstreamServiceError

class SearchController:
    def __init__(self, http_client=None, metadata_service=None):
        self.http_client = http_client or AsyncHttpClient()
        self.metadata_service = (
            metadata_service
            if metadata_service is not None
            else MetadataService(http_client=self.http_client)
        )
        self.yt_api = YTApi(http_client=self.http_client)


    async def search(
        self,
        artist: str,
        album: str,
        result_limit: int = 10,
        max_tracks: Optional[int] = None,
    ):
        start = time.monotonic()
        query = f"{artist} {album}".strip()

        errors = {}
        playlists_results, releases_results = [], []
        if query:
            playlists_results, releases_results = await asyncio.gather(
                self._search_provider(
                    "youtube",
                    self.yt_api.search_playlist(
                        query,
                        limit=result_limit,
                        max_tracks=max_tracks,
                    ),
                    errors,
                ),
                self._search_provider(
                    "musicbrainz",
                    self.metadata_service.search_releases(
                        artist,
                        album,
                        limit=result_limit,
                        max_tracks=max_tracks,
                    ),
                    errors,
                ),
            )

        playlists = self._filter_sort_and_limit(
            [p.__dict__ for p in playlists_results],
            result_limit,
            max_tracks,
        )
        releases = self._filter_sort_and_limit(
            [
                {
                    "id": r.id,
                    "title": r.title,
                    "date": r.date,
                    "artist": r.artist,
                    "cover_url": r.cover_url,
                    "track_count": r.track_count,
                }
                for r in releases_results
            ],
            result_limit,
            max_tracks,
        )
        elapsed = time.monotonic() - start
        logger.info(
            "search_completed youtube=%s musicbrainz=%s errors=%s elapsed_ms=%s",
            len(playlists),
            len(releases),
            len(errors),
            round(elapsed * 1000),
        )
        return {
            "playlists": playlists,
            "releases": releases,
            "errors": errors,
        }

    @staticmethod
    async def _search_provider(provider, search, errors):
        try:
            return await search
        except UpstreamServiceError as error:
            logger.warning("search_provider_failed provider=%s", provider)
            errors[provider] = str(error)
        except Exception:
            logger.exception(f"Unexpected {provider} search failure")
            errors[provider] = f"Unexpected {provider} search failure"
        return []

    @staticmethod
    def _sort_by_track_count(items):
        def sort_key(item):
            count = item.get("track_count")
            if (
                isinstance(count, int)
                and not isinstance(count, bool)
                and count >= 0
            ):
                return (0, -count)
            return (1, 0)

        return sorted(items, key=sort_key)

    @classmethod
    def _filter_sort_and_limit(cls, items, limit, max_tracks):
        if max_tracks is not None:
            items = [
                item
                for item in items
                if not cls._exceeds_track_limit(item.get("track_count"), max_tracks)
            ]
        return cls._sort_by_track_count(items)[:limit]

    @staticmethod
    def _exceeds_track_limit(track_count, max_tracks):
        return (
            isinstance(track_count, int)
            and not isinstance(track_count, bool)
            and track_count >= 0
            and track_count > max_tracks
        )

    async def get_release_details(self, release_id: str):
        start = time.monotonic()
        try:
            release = await self.metadata_service.get_release(release_id)
        except Exception:
            logger.debug(
                "release_details_failed release_id=%s elapsed_ms=%s",
                release_id,
                round((time.monotonic() - start) * 1000),
            )
            raise
        logger.debug(
            "release_details_completed release_id=%s elapsed_ms=%s",
            release_id,
            round((time.monotonic() - start) * 1000),
        )
        return {
            "id": release.id,
            "title": release.title,
            "date": release.date,
            "artist": release.artist,
            "cover_url": release.cover_url,
            "track_count": len(release.tracks),
            "tracks": [track.to_dict() for track in release.tracks],
        }
        
