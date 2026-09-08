import asyncio
import time
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


    async def search(self, artist: str, album: str):
        start = time.monotonic()
        query = f"{artist} {album}".strip()

        errors = {}
        playlists_results, releases_results = [], []
        if query:
            playlists_results, releases_results = await asyncio.gather(
                self._search_provider(
                    "youtube", self.yt_api.search_playlist(query), errors
                ),
                self._search_provider(
                    "musicbrainz",
                    self.metadata_service.search_releases(artist, album),
                    errors,
                ),
            )

        playlists = self._sort_by_track_count(
            [p.__dict__ for p in playlists_results]
        )
        releases = self._sort_by_track_count([
            {
                "id": r.id,
                "title": r.title,
                "date": r.date,
                "artist": r.artist,
                "cover_url": r.cover_url,
                "track_count": r.track_count,
            }
            for r in releases_results
        ])
        elapsed = time.monotonic() - start
        logger.info(f"SearchController: completed search for '{query}' in {elapsed:.2f} seconds")
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
            logger.warning(f"Search provider failure: {error}")
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

    async def get_release_details(self, release_id: str):
        start = time.monotonic()
        try:
            release = await self.metadata_service.get_release(release_id)
        except Exception:
            logger.info(
                f"SearchController: release {release_id} details failed after "
                f"{time.monotonic() - start:.2f}s"
            )
            raise
        logger.info(
            f"SearchController: release {release_id} details fetched in "
            f"{time.monotonic() - start:.2f}s"
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
        
