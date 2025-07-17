from typing import List, Optional
from autodrome import config
from autodrome.http_client import HttpClient
from autodrome.models.playlist import Playlist
from autodrome.logger import logger


class YTApi:
    BASE_URL = "https://www.googleapis.com/youtube/v3"

    def __init__(self, http_client: HttpClient):
        self.http_client = http_client
        self.api_key = config.Config().google_api_key

    def search_playlist(self, query: str) -> List[Playlist]:
        logger.debug(f"Searching playlists for query: {query}")
        data = self._fetch_search_results(query)
        return self._parse_playlists(data)

    def _fetch_search_results(self, query: str) -> dict:
        url = f"{self.BASE_URL}/search"
        params = {
            "part": "snippet",
            "q": query,
            "type": "playlist",
            "maxResults": 10,
            "key": self.api_key,
        }
        try:
            return self.http_client.get(url, params)
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
                track_count=self._get_track_count(playlist_id)
            )
            results.append(playlist)
        logger.info(f"Parsed {len(results)} playlists")
        return results

    def _extract_playlist_id(self, item: dict) -> Optional[str]:
        try:
            return item["id"]["playlistId"]
        except KeyError as e:
            logger.warning(f"Malformed item (missing playlistId): {e} - {item}")
            return None

    def _get_track_count(self, playlist_id: str) -> Optional[int]:
        url = f"{self.BASE_URL}/playlists"
        params = {
            "part": "contentDetails",
            "id": playlist_id,
            "key": self.api_key,
        }
        try:
            data = self.http_client.get(url, params)
            item = data.get("items", [{}])[0]
            return item.get("contentDetails", {}).get("itemCount")
        except Exception as e:
            logger.warning(f"Could not fetch track count for playlist {playlist_id}: {e}")
            return None
