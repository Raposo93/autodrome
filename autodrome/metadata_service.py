from typing import Any, Dict, List, Optional
from autodrome.http_client import HTTP_client
from autodrome.models.track import Track
from autodrome.models.release import Release
from autodrome.logger import logger
from autodrome.services.redis_cache import RedisCache
import os

class MetadataService:
    
    def __init__(self, http_client: HTTP_client):
        self.http_client = http_client
        self.redis_cache = RedisCache()
        self.base_dir = os.path.dirname(os.path.abspath(__file__))
        self.cover_dir = os.path.abspath(os.path.join(self.base_dir, '..', 'covers'))

    def search_releases(self, artist: Optional[str], album: Optional[str]) -> List[Release]:
        query = self._build_mb_query(artist, album)
        data = self._fetch_releases_data(query)
        releases = self._parse_releases(data, artist)

        for i, release in enumerate(releases):
            release_id = release.id
            cached = self.redis_cache.get_release(release_id)
            if cached:
                logger.debug(f"Cache hit for release {release_id}")
                releases[i].tracks = [Track(**track) for track in cached.get("tracks", [])]
            else:
                logger.debug(f"Cache miss for release {release_id}")
                tracks = self._get_tracks(release_id)
                releases[i].tracks = tracks
                cache_data = {
                    "id": release.id,
                    "title": release.title,
                    "date": release.date,
                    "artist": release.artist,
                    "cover_url": release.cover_url,
                    "tracks": [t.to_dict() for t in tracks]
                }
                self.redis_cache.set_release(release_id, cache_data)

        return releases

    def get_cover_art(self, release_id: str) -> Optional[str]:
        path = self.get_cover_path(release_id)
        if os.path.exists(path):
            return os.path.abspath(path)
        try:
            self._download_cover_art(release_id, path)
            return os.path.abspath(path) if os.path.exists(path) else None
        except Exception as e:
            logger.error(f"Failed to download cover art for {release_id}: {e}")
            return None

    def should_download_cover(self, release_id: str) -> bool:
        path = self.get_cover_path(release_id)
        return not os.path.exists(path)

    def get_cover_path(self, release_id: str) -> str:
        os.makedirs(self.cover_dir, exist_ok=True)
        return os.path.join(self.cover_dir, f"{release_id}.jpg")

    
    def _get_tracks(self, release_id: str) -> List[Track]:
        data = self._fetch_tracks_data(release_id)
        # logger.debug(f"_get_tracks data: {data}")
        tracks = self._parse_tracks(data)
        return tracks

    def _get_cover_url(self, release_id: str) -> Optional[str]:
        url = f"https://coverartarchive.org/release/{release_id}"
        try:
            data = self.http_client.get(url)
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
    
    def _fetch_releases_data(self, query) -> Dict[str, Any]:
        url = "https://musicbrainz.org/ws/2/release/"
        params = {
            "query": query,
            "fmt": "json",
            "limit": 5,
        }
        try:
            return self.http_client.get(url, params=params)
        except Exception as e:
            logger.error(f"MusicBrainz request failed: {e}")
            return {}

    def _parse_releases(self, data: Dict[str, Any], artist: Optional[str]) -> List[Release]:
        releases = []
        for r in data.get("releases", []):
            # logger.debug(f"response releaseRaw: {r}")
            release_id = r["id"]
            cover_url = self._get_cover_url(release_id)
            tracks = self._get_tracks(release_id)
            # logger.debug(f"response tracks: {tracks}")
            releases.append(
                Release(
                    release_id=release_id,
                    title=r.get("title", "Unknown"),
                    date=r.get("date", "Unknown"),
                    cover_url=cover_url,
                    artist=r.get("artist-credit", [{}])[0].get("name", artist),
                    tracks=[t.to_dict() for t in tracks]
                )
            )
        logger.debug(f"Parsed releases: {releases}")
        return releases

    def _fetch_tracks_data(self, release_id: str) -> Dict[str, Any]:
        url = f"https://musicbrainz.org/ws/2/release/{release_id}"
        params = {
            "inc": "recordings",
            "fmt": "json"
        }
        try:
            return self.http_client.get(url, params=params)
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
                try:
                    return int(number_main)
                except ValueError:
                    pass
            try:
                return int(position)
            except (ValueError, TypeError):
                return 0

        for medium in data.get("media", []):
            for t in medium.get("tracks", []):
                # logger.debug(f"response trackRaw: {t}")

                sort_key = get_track_sort_key(t)
                title = t.get("title", "Unknown")
                tracks.append(Track(sort_key, title))

        tracks.sort(key=lambda tr: tr.number)
        return tracks
    
    def _download_cover_art(self, release_id: str, path: str) -> bool:
        url = f"https://coverartarchive.org/release/{release_id}/front"
        try:
            response = self.http_client.get_binary(url)
            with open(path, "wb") as f:
                for chunk in response.iter_content(1024):
                    f.write(chunk)
            logger.info(f"Cover art saved to {path}")
            return True
        except Exception as e:
            logger.error(f"Error downloading cover art for {release_id}: {e}")
            return False
        