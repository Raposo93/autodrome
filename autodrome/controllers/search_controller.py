from autodrome.metadata_service import MetadataService
from autodrome.yt_api import YTApi
from autodrome.http_client import HTTP_client

class SearchController:
    def __init__(self, http_client=None):
        self.http_client = http_client or HTTP_client()
        self.metadata_service = MetadataService(http_client=self.http_client)
        self.yt_api = YTApi(http_client=self.http_client)

    def search(self, artist: str, album: str):
        query = f"{artist} {album}".strip()

        playlists = []
        if query:
            playlists_results = self.yt_api.search_playlist(query)
            playlists = [p.__dict__ for p in playlists_results]

        releases = []
        if artist or album:
            releases_results = self.metadata_service.search_releases(artist, album)
            releases = [
                {
                    "id": r.id,
                    "title": r.title,
                    "date": r.date,
                    "artist": r.artist,
                    "cover_url": r.cover_url,
                    "tracks": [t.to_dict() for t in r.tracks]
                }
                for r in releases_results
            ]

        return {
            "playlists": playlists,
            "releases": releases
        }
