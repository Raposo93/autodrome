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
    MAX_SEARCH_RESULTS = 50
    MAX_FILTER_CANDIDATES = 50

    @cached_property
    def api_key(self) -> str:
        return config.Config().google_api_key
    
    def __init__(self, http_client: AsyncHttpClient):
        self.http_client = http_client
        self.api_key = config.Config().google_api_key


    async def search_playlist(
        self,
        query: str,
        limit: int = 10,
        max_tracks: Optional[int] = None,
    ) -> List[Playlist]:
        self._validate_search_options(limit, max_tracks)
        logger.debug(f"Searching playlists for query: {query}")

        if max_tracks is None:
            data = await self._fetch_search_results(query, limit)
            playlists = self._parse_playlists(data)
            await self._populate_track_counts(playlists)
            return playlists

        return await self._search_filtered_playlists(query, limit, max_tracks)

    async def _search_filtered_playlists(
        self,
        query: str,
        limit: int,
        max_tracks: int,
    ) -> List[Playlist]:
        results = []
        seen_ids = set()
        page_token = None
        examined = 0

        while len(results) < limit and examined < self.MAX_FILTER_CANDIDATES:
            remaining_candidates = self.MAX_FILTER_CANDIDATES - examined
            page_limit = min(limit, remaining_candidates)
            data = await self._fetch_search_results(
                query,
                page_limit,
                page_token=page_token,
            )
            page_items = data.get("items", [])[:remaining_candidates]
            examined += len(page_items)
            if not page_items:
                break

            page_playlists = self._parse_playlists({"items": page_items})
            unique_playlists = []
            for playlist in page_playlists:
                if playlist.id in seen_ids:
                    continue
                seen_ids.add(playlist.id)
                unique_playlists.append(playlist)

            await self._populate_track_counts(unique_playlists)
            results.extend(
                playlist
                for playlist in unique_playlists
                if not self._exceeds_track_limit(playlist.track_count, max_tracks)
            )

            page_token = data.get("nextPageToken")
            if not page_token:
                break

        return results[:limit]

    async def _populate_track_counts(self, playlists: List[Playlist]) -> None:
        counts = await self._get_track_counts([playlist.id for playlist in playlists])
        for playlist in playlists:
            playlist.track_count = counts.get(playlist.id)

    @staticmethod
    def _exceeds_track_limit(track_count, max_tracks: int) -> bool:
        return (
            isinstance(track_count, int)
            and not isinstance(track_count, bool)
            and track_count >= 0
            and track_count > max_tracks
        )

    def _validate_search_options(
        self,
        limit: int,
        max_tracks: Optional[int],
    ) -> None:
        if (
            not isinstance(limit, int)
            or isinstance(limit, bool)
            or not 1 <= limit <= self.MAX_SEARCH_RESULTS
        ):
            raise ValueError(
                f"YouTube result limit must be between 1 and {self.MAX_SEARCH_RESULTS}"
            )
        if (
            max_tracks is not None
            and (
                not isinstance(max_tracks, int)
                or isinstance(max_tracks, bool)
                or max_tracks < 1
            )
        ):
            raise ValueError("YouTube maximum tracks must be a positive integer")
    
    async def _fetch_search_results(
        self,
        query: str,
        limit: int,
        page_token: Optional[str] = None,
    ) -> dict:
        url = f"{self.BASE_URL}/search"
        params = {
            "part": "snippet",
            "q": query,
            "type": "playlist",
            "maxResults": limit,
            "key": self.api_key,
        }
        if page_token:
            params["pageToken"] = page_token
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
