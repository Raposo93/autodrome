import html
import re
from functools import cached_property
from typing import List, Optional
from autodrome import config
from autodrome.http_client_async import AsyncHttpClient, UpstreamServiceError
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
        
        counts = await self._get_track_counts([p.id for p in playlists])
        for playlist in playlists:
            playlist.track_count = counts.get(playlist.id)
        
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
        data = await self.http_client.get(
            url,
            params=params,
            provider="YouTube",
            context="searching playlists",
        )
        if not isinstance(data, dict) or not isinstance(data.get("items", []), list):
            raise UpstreamServiceError(
                provider="YouTube",
                context="searching playlists",
                reason="invalid response",
            )
        return data

    def _parse_playlists(self, data: dict) -> List[Playlist]:
        results = []
        for item in data.get("items", []):
            playlist_id = self._extract_playlist_id(item)
            if not playlist_id:
                continue

            snippet = item.get("snippet", {})
            playlist = Playlist(
                playlist_id=playlist_id,
                title=self._normalize_text(snippet.get("title", "Untitled")),
                channel=self._normalize_text(snippet.get("channelTitle", "Unknown")),
                url=f"https://www.youtube.com/playlist?list={playlist_id}",
                thumbnail=snippet.get("thumbnails", {}).get("medium", {}).get("url"),
                track_count=None
            )
            results.append(playlist)
        logger.info(f"Parsed {len(results)} playlists")
        return results

    @staticmethod
    def _normalize_text(value: str) -> str:
        # Decode once, at the provider boundary. Require a semicolon so plain
        # text such as "&notebook" is not interpreted as a partial HTML entity.
        return re.sub(
            r"&(?:#[0-9]+|#[xX][0-9a-fA-F]+|[a-zA-Z][a-zA-Z0-9]*);",
            lambda match: (
                html.unescape(match.group())
                if match.group().startswith("&#") or match.group()[1:] in html.entities.html5
                else match.group()
            ),
            value,
        )

    def _extract_playlist_id(self, item: dict) -> Optional[str]:
        if item.get("id", {}).get("kind") != "youtube#playlist":
            logger.debug(f"Skipping non-playlist item: {item.get('id', {}).get('kind')}")
            return None
        return item["id"].get("playlistId")
    
    async def _get_track_counts(self, playlist_ids: List[str]) -> dict:
        if not playlist_ids:
            return {}
        url = f"{self.BASE_URL}/playlists"
        params = {
            "part": "contentDetails",
            "id": ",".join(playlist_ids),
            "maxResults": 50,
            "key": self.api_key,
        }
        data = await self.http_client.get(
            url,
            params=params,
            provider="YouTube",
            context="loading playlist details",
        )
        if not isinstance(data, dict) or not isinstance(data.get("items", []), list):
            raise UpstreamServiceError(
                provider="YouTube",
                context="loading playlist details",
                reason="invalid response",
            )
        return {
            item["id"]: item.get("contentDetails", {}).get("itemCount")
            for item in data.get("items", [])
            if item.get("id") in playlist_ids
        }
