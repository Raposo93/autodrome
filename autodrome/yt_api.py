from autodrome import config
from autodrome.http_client import HTTP_client
from autodrome.models.playlist import Playlist
from autodrome.logger import logger

conf = config.Config()

class YTApi:
    def __init__(self):
        self.google_api_key = conf.google_api_key
        self.base_url = "https://www.googleapis.com/youtube/v3"
        self.http_client = HTTP_client()

    
    def search_playlist(self, query):
        url = f"{self.base_url}/search"
        params = {
            "part": "snippet",
            "q": query,
            "type": "playlist",
            "maxResults": 10,
            "key": self.google_api_key
        }
        logger.debug(f"Searching playlists for query: {query}")
        try:
            logger.debug(f"Request sent to YouTube API with query: {query}")
            data = self.http_client.get(url, params)
            logger.info(f"Received {len(data.get('items', []))} playlists")
        except Exception as e:
            logger.error(f"Error searching playlists: {e}")
            return []
        
        results = []
        for item in data.get("items", []):
            try:
                playlist_id = item["id"]["playlistId"]
            except KeyError as e:
                logger.warning(f"Malformed item (missing key): {e} - {item}")
                continue
            title = item["snippet"]["title"]
            channel = item["snippet"]["channelTitle"]
            thumbnail = item["snippet"]["thumbnails"].get("medium", {}).get("url")
            track_count = self.get_track_count(playlist_id)
            results.append(
                Playlist(
                    playlist_id=playlist_id,
                    title=title,
                    channel=channel,
                    url=f"https://www.youtube.com/playlist?list={playlist_id}",
                    thumbnail=thumbnail,
                    track_count=track_count
                )
            )
        return results

    def get_track_count(self, playlist_id):
        """Fetch the number of videos in a YouTube playlist using its ID."""
        count_url = f"{self.base_url}/playlists"
        count_params = {
            "part": "contentDetails",
            "id": playlist_id,
            "key": self.google_api_key
        }

        try:
            count_data = self.http_client.get(count_url, count_params)
            items = count_data.get("items")
            
            if items and isinstance(items, list) and "contentDetails" in items[0]:
                return items[0]["contentDetails"].get("itemCount")
            else:
                logger.warning(f"Missing or unexpected contentDetails for playlist {playlist_id}")
                return None

        except Exception as e:
            logger.warning(f"Could not fetch track count for playlist {playlist_id}: {e}")
            return None