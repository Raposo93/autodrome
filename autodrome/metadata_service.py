import asyncio
import os
from typing import Any, Dict, List, Optional
from autodrome.logger import logger
from autodrome.services.redis_cache import RedisCache
from autodrome.models.track import Track
from autodrome.models.release import Release
from autodrome.http_client_async import AsyncHttpClient

class MetadataService:
    def __init__(self, http_client: AsyncHttpClient):
        self.http_client = http_client
        self.redis_cache = RedisCache()
        self.base_dir = os.path.dirname(os.path.abspath(__file__))
        self.cover_dir = os.path.abspath(os.path.join(self.base_dir, '..', 'covers'))

    async def search_releases(self, artist: Optional[str], album: Optional[str]) -> List[Release]:
        logger.debug(f"MetadataService: start release search for artist='{artist}' album='{album}'")
        query = self._build_mb_query(artist, album)
        data = await self._fetch_releases_data(query)
        releases = self._parse_releases(data, artist)

        tasks_tracks = []
        tasks_cover_urls = []
        releases_to_update = []

        for release in releases:
            release_id = release.id
            cached = self.redis_cache.get_release(release_id)
            if cached:
                logger.debug(f"Cache hit for release {release_id}")
                release.cover_url = cached.get("cover_url")
                release.tracks = [Track(**track) for track in cached.get("tracks", [])]
            else:
                logger.debug(f"Cache miss for release {release_id}")
                releases_to_update.append(release)
                tasks_tracks.append(self._get_tracks(release_id))
                tasks_cover_urls.append(self._get_cover_url(release_id))
                    
        if tasks_tracks or tasks_cover_urls:
            tracks_results = await asyncio.gather(*tasks_tracks)
            cover_urls_results = await asyncio.gather(*tasks_cover_urls)       
            
            for release, tracks, cover_url in zip(releases_to_update, tracks_results, cover_urls_results):
                release.tracks = tracks
                release.cover_url = cover_url    
                cache_data = {
                    "id": release.id,
                    "title": release.title,
                    "date": release.date,
                    "artist": release.artist,
                    "cover_url": release.cover_url,
                    "tracks": [t.to_dict() for t in release.tracks]
                }
                self.redis_cache.set_release(release.id, cache_data)

        return releases

    async def get_cover_art(self, release_id: str) -> Optional[str]:
        path = self.get_cover_path(release_id)
        if os.path.exists(path):
            return os.path.abspath(path)
        try:
            success = await self._download_cover_art(release_id, path)
            return os.path.abspath(path) if success else None
        except Exception as e:
            logger.error(f"Failed to download cover art for {release_id}: {e}")
            return None

    def should_download_cover(self, release_id: str) -> bool:
        return not os.path.exists(self.get_cover_path(release_id))

    def get_cover_path(self, release_id: str) -> str:
        os.makedirs(self.cover_dir, exist_ok=True)
        return os.path.join(self.cover_dir, f"{release_id}.jpg")

    async def _get_cover_url(self, release_id: str) -> Optional[str]:
        url = f"https://coverartarchive.org/release/{release_id}"
        try:
            data = await self.http_client.get(url)
            for image in data.get("images", []):
                if image.get("front", False):
                    return image.get("image")
        except Exception as e:
            logger.warning(f"Could not fetch cover URL for {release_id}: {e}")
        return None

    def _build_mb_query(self, artist: Optional[str], album: Optional[str]) -> str:
        terms = []
        if album:
            terms.append(f"release:{album}")
        if artist:
            terms.append(f"artist:{artist}")
        return " AND ".join(terms)

    async def _fetch_releases_data(self, query:str) -> Dict[str, Any]:
        url = "https://musicbrainz.org/ws/2/release/"
        params = {"query": query, "fmt": "json", "limit": 10}
        try:
            return await self.http_client.get(url, params=params)

        except Exception as e:
            logger.error(f"MusicBrainz request failed: {e}")
            return {}

    async def _get_tracks(self, release_id: str) -> List[Track]:
        data = await self._fetch_tracks_data(release_id)
        return self._parse_tracks(data)

    async def _fetch_tracks_data(self, release_id: str) -> Dict[str, Any]:
        url = f"https://musicbrainz.org/ws/2/release/{release_id}"
        params = {"inc": "recordings", "fmt": "json"}
        try:
            return await self.http_client.get(url, params=params)
        except Exception as e:
            logger.error(f"Failed to get tracks for release {release_id}: {e}")
            return {}

    def _parse_tracks(self, data: Dict[str, Any]) -> List[Track]:
        tracks = []

        def get_track_sort_key(t):
            number_str = t.get("number", "")
            number_main = number_str.split(".")[0] if number_str else ""
            position = t.get("position", 0)

            if number_main.isdigit():
                return int(number_main)
            try:
                return int(position)
            except (ValueError, TypeError):
                return 0

        for medium in data.get("media", []):
            for t in medium.get("tracks", []):
                sort_key = get_track_sort_key(t)
                title = t.get("title", "Unknown")
                tracks.append(Track(sort_key, title))

        tracks.sort(key=lambda tr: tr.number)
        return tracks

    def _parse_releases(self, data: Dict[str, Any], artist: Optional[str]) -> List[Release]:
        logger.debug("MetadataService: parsing releases and downloading metadata")
        
        if not isinstance(data, dict) or "releases" not in data:
            # logger.warning(f"MetadataService: unexpected data format received: {data}")
            return []
        
        releases = []
        for r in data.get("releases", []):
            release_id = r["id"]
            releases.append(
                Release(
                    release_id=release_id,
                    title=r.get("title", "Unknown"),
                    date=r.get("date", "Unknown"),
                    cover_url=None,
                    artist=r.get("artist-credit", [{}])[0].get("name", artist),
                    tracks=[]
                )
            )
        # logger.debug(f"Parsed releases: {releases}")
        return releases



    async def _download_cover_art(self, release_id: str, path: str) -> bool:
        url = f"https://coverartarchive.org/release/{release_id}/front"
        try:
            content = await self.http_client.get_binary(url)
            with open(path, "wb") as f:
                f.write(content)
            logger.info(f"Cover art saved to {path}")
            return True
        except Exception as e:
            logger.error(f"Error downloading cover art for {release_id}: {e}")
            return False
