import asyncio
import time
from autodrome.logger import logger
from autodrome.metadata_service import MetadataService
from autodrome.yt_api import YTApi
from autodrome.http_client_async import AsyncHttpClient

class SearchController:
    def __init__(self, http_client=None):
        self.http_client = http_client or AsyncHttpClient()
        self.metadata_service = MetadataService(http_client=self.http_client)
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
            logger.debug(f"SearchController: releases fetched in {time.monotonic() - t2:.2f}s")

            to_download = [r.id for r in releases_results if self.metadata_service.should_download_cover(r.id)]
            
            if to_download:
                await asyncio.gather(*(self.metadata_service.get_cover_art(rid) for rid in to_download))
            releases = [
                {
                    "id": r.id,
                    "title": r.title,
                    "date": r.date,
                    "artist": r.artist,
                    "cover_url": r.cover_url,
                    "tracks": [t.to_dict() for t in r.tracks]
                }
                for r in releases_results
            ]
        elapsed = time.monotonic() - start
        logger.info(f"SearchController: completed search for '{query}' in {elapsed:.2f} seconds")
        return {
            "playlists": playlists,
            "releases": releases
        }
        
