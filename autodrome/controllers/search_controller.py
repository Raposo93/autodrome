import time
from autodrome.logger import logger
from autodrome.metadata_service import MetadataService
from autodrome.yt_api import YTApi
from autodrome.http_client_async import AsyncHttpClient

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

        playlists = []
        if query:
            t1 = time.monotonic()
            playlists_results = await self.yt_api.search_playlist(query)
            playlists = [p.__dict__ for p in playlists_results]
            logger.debug(f"SearchController: playlists:{playlists} playlists")
            logger.debug(f"SearchController: playlists fetched in {time.monotonic() - t1:.2f}s")

        releases = []
        if artist or album:
            t2 = time.monotonic()
            releases_results = await self.metadata_service.search_releases(artist, album)
            logger.info(
                "SearchController: release candidates fetched in "
                f"{time.monotonic() - t2:.2f}s"
            )

            releases = [
                {
                    "id": r.id,
                    "title": r.title,
                    "date": r.date,
                    "artist": r.artist,
                    "cover_url": r.cover_url,
                }
                for r in releases_results
            ]
        elapsed = time.monotonic() - start
        logger.info(f"SearchController: completed search for '{query}' in {elapsed:.2f} seconds")
        return {
            "playlists": playlists,
            "releases": releases
        }

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
            "tracks": [track.to_dict() for track in release.tracks],
        }
        
