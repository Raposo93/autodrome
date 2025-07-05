from http_client import HTTP_client
from models import Track, Release
from logger import logger
import os

class MetadataService:
    
    def __init__(self):
        self.http_client = HTTP_client()
        
    def search_releases(self, artist, album):
        url = "https://musicbrainz.org/ws/2/release/"
        query = f'release:{album} AND artist:{artist}'
        params = {
            "query": query,
            "fmt": "json",
            "limit": 5,
        }
        try:
            data = self.http_client.get(url, params=params)
            # logger.debug(f"data musicbrainz: {data}")
        except Exception as e:
            logger.error(f"MusicBrainz request failed: {e}")
        
        releases = []
        for r in data.get("releases", []):
            releases.append(
                Release(
                    id=r["id"],
                    title=r.get("title", "Unknown"),
                    date=r.get("date", "Unknown"),
                    artist=r.get("artist-credit", [{}])[0].get("name", artist),
                )
            )            
        return releases


    def get_tracks(self, release_id):
        url = f"https://musicbrainz.org/ws/2/release/{release_id}"
        params = {
            "inc": "recordings",
            "fmt": "json"
        }

        try:
            data = self.http_client.get(url, params=params)
        except Exception as e:
            logger.error(f"Failed to get tracks for release {release_id}: {e}")
            return []

        tracks = []
        for medium in data.get("media", []):
            for t in medium.get("tracks", []):
                number = int(t.get("number", "0").split(".")[0])  # a veces es "1.1", "2.3", etc.
                title = t.get("title", "Unknown")
                tracks.append(Track(number, title))
        # logger.debug(f"tracks: {tracks}")
        return tracks

    
    def get_cover_art(self, release_id):
        url = f"https://coverartarchive.org/release/{release_id}/front"
        cover_dir = "covers"
        os.makedirs(cover_dir, exist_ok=True)
        path = os.path.join(cover_dir, f"{release_id}.jpg")

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