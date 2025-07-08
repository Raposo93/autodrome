from autodrome.http_client import HTTP_client
from autodrome.models.track import Track
from autodrome.models.release import Release
from autodrome.logger import logger
import os

class MetadataService:
    
    def __init__(self):
        self.http_client = HTTP_client() 
        self.base_dir = os.path.dirname(os.path.abspath(__file__))  # autodrome/
        self.cover_dir = os.path.abspath(os.path.join(self.base_dir, '..', 'covers'))  # covers/

        
    def search_releases(self, artist, album):
        url = "https://musicbrainz.org/ws/2/release/"
        terms = []
        if album:
            terms.append(f"release:{album}")
        if artist:
            terms.append(f"artist:{artist}")
        query = " AND ".join(terms)
        # query = f'release:{album} AND artist:{artist}'

        logger.debug(f"query musicbrainz: {query}")
        params = {
            "query": query,
            "fmt": "json",
            "limit": 5,
        }
        data = {}
        try:
            data = self.http_client.get(url, params=params)
        except Exception as e:
            logger.error(f"MusicBrainz request failed: {e}")
        
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


    def get_tracks(self, release_id):
        url = f"https://musicbrainz.org/ws/2/release/{release_id}"
        params = {
            "inc": "recordings",
            "fmt": "json"
        }
        logger.debug(f"response musicbrainz: {release_id}")

        try:
            data = self.http_client.get(url, params=params)
            # logger.debug(f"response musicbrainz: {data}")
        except Exception as e:
            logger.error(f"Failed to get tracks for release {release_id}: {e}")
            return []

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


    
    def get_cover_art(self, release_id):
        url = f"https://coverartarchive.org/release/{release_id}/front"
        os.makedirs(self.cover_dir, exist_ok=True)
        path = os.path.join(self.cover_dir, f"{release_id}.jpg")

        try:
            response = self.http_client.get_binary(url)
            with open(path, "wb") as f:
                for chunk in response.iter_content(1024):
                    f.write(chunk)
            logger.info(f"Cover art saved to {path}")
            return path
        except Exception as e:
            logger.warning(f"Cover art not available for release {release_id}: {e}")
            return None