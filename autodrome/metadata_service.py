from typing import Any, Dict, List, Optional
from autodrome.http_client import HTTP_client
from autodrome.models.track import Track
from autodrome.models.release import Release
from autodrome.logger import logger
import os

class MetadataService:
    
    def __init__(self):
        self.http_client = HTTP_client() 
        self.base_dir = os.path.dirname(os.path.abspath(__file__))
        self.cover_dir = os.path.abspath(os.path.join(self.base_dir, '..', 'covers'))

        
    def search_releases(self, artist: Optional[str], album: Optional[str]):
        query = self._build_mb_query(artist, album)
        data = self._fetch_releases_data(query)
        releases = self._parse_releases(data, artist)     
        return releases

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
            release_id = r["id"]
            tracks = self.get_tracks(release_id)  # llama al método ya existente

            releases.append(
                Release(
                    id=release_id,
                    title=r.get("title", "Unknown"),
                    date=r.get("date", "Unknown"),
                    artist=r.get("artist-credit", [{}])[0].get("name", artist),
                    tracks=[t.to_dict() for t in tracks]
                )
            )
        return releases

    def get_tracks(self, release_id: str) -> List[Track]:
        data = self._fetch_tracks_data(release_id)
        tracks = self._parse_tracks(data)
        return tracks
    
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
            # Tomar parte antes del punto si existe (e.g. "1.1" -> "1")
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
                logger.debug(f"response trackRaw: {t}")

                sort_key = get_track_sort_key(t)
                title = t.get("title", "Unknown")
                tracks.append(Track(sort_key, title))

        tracks.sort(key=lambda tr: tr.number)
        return tracks

    def get_cover_art(self, release_id: str) -> Optional[str]:
        path = self._cover_art_path(release_id)
        if self._download_cover_art(release_id, path):
            return path
        return None
    
    def _cover_art_path(self, release_id: str) -> str:
        os.makedirs(self.cover_dir, exist_ok=True)
        return os.path.join(self.cover_dir, f"{release_id}.jpg")
    
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
            logger.warning(f"Cover art not available for release {release_id}: {e}")
            return False