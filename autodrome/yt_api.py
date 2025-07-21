import asyncio
from functools import cached_property
from typing import List, Optional
from autodrome import config
from autodrome.http_client_async import AsyncHttpClient
from autodrome.models.playlist import Playlist
from autodrome.logger import logger


class YTApi:
    BASE_URL = "https://www.googleapis.com/youtube/v3"

    @cached_property
    def api_key(self) -> str:
        return config.Config().google_api_key
    
    def __init__(self, http_client: AsyncHttpClient):
        self.http_client = http_client
        self.api_key = config.Config().google_api_key


    async def search_playlist(self, query: str) -> List[Playlist]:
        logger.debug(f"Searching playlists for query: {query}")
        data = await self._fetch_search_results(query)
        playlists = self._parse_playlists(data)
        
        tasks = [self._get_track_count(p.id) for p in playlists]
        counts = await asyncio.gather(*tasks)
        for playlist, count in zip(playlists, counts):
            playlist.track_count = count
        
        return playlists
    
    async def _fetch_search_results(self, query: str) -> dict:
        url = f"{self.BASE_URL}/search"
        params = {
            "part": "snippet",
            "q": query,
            "type": "playlist",
            "maxResults": 10,
            "key": self.api_key,
        }
        try:
            data = await self.http_client.get(url, params=params)
            return data
        except Exception as e:
            logger.error(f"Error searching playlists: {e}")
            return {}

    def _parse_playlists(self, data: dict) -> List[Playlist]:
        results = []
        for item in data.get("items", []):
            playlist_id = self._extract_playlist_id(item)
            if not playlist_id:
                continue

            snippet = item.get("snippet", {})
            playlist = Playlist(
                playlist_id=playlist_id,
                title=snippet.get("title", "Untitled"),
                channel=snippet.get("channelTitle", "Unknown"),
                url=f"https://www.youtube.com/playlist?list={playlist_id}",
                thumbnail=snippet.get("thumbnails", {}).get("medium", {}).get("url"),
                track_count=None
            )
            results.append(playlist)
        logger.info(f"Parsed {len(results)} playlists")
        return results

    def _extract_playlist_id(self, item: dict) -> Optional[str]:
        if item.get("id", {}).get("kind") != "youtube#playlist":
            logger.debug(f"Skipping non-playlist item: {item.get('id', {}).get('kind')}")
            return None
        return item["id"].get("playlistId")
    
    async def _get_track_count(self, playlist_id: str) -> Optional[int]:
        url = f"{self.BASE_URL}/playlists"
        params = {
            "part": "contentDetails",
            "id": playlist_id,
            "key": self.api_key,
        }
        try:
            data = await self.http_client.get(url, params=params)
            items = data.get("items", [])
            if not items:
                logger.error(f"No items found in response for playlist {playlist_id}")
                return None
            item = items[0]
            count = item.get("contentDetails", {}).get("itemCount")
            return count
        except Exception as e:
            logger.warning(f"Could not fetch track count for playlist {playlist_id}: {e}")
            return None
