from typing import Any, Dict, List, Optional
from autodrome.logger import logger
from autodrome.models.track import Track
from autodrome.services.redis_cache import RedisCache

class DownloaderController:
    def __init__(self, downloader, organizer, metadata_service):
        self.downloader = downloader
        self.organizer = organizer
        self.metadata_service = metadata_service
        self.redis_cache = RedisCache()

    def download_and_tag(self, playlist_url: str, artist: str, album: str, release_id: str, track_count: Optional[int] = None) -> None:

        logger.debug(f"download_and_tag release_id: {release_id}")

        cached: Optional[Dict[str, Any]] = self.redis_cache.get_release(release_id)
        if not cached:
            raise ValueError(f"Release {release_id} not found in cache")

        tracks: List[Track] = [Track(**t) for t in cached.get("tracks", [])]
        logger.debug(f"Cached tracks: {tracks}")

        with self.downloader.create_temp_folder() as tmpdir:
            self.downloader.download_playlist(playlist_url, tmpdir, total=track_count)

            cover_path = self.metadata_service.get_cover_art(release_id)

            self.organizer.tag_and_rename(tmpdir, artist, album, tracks, cover_path)
            self.organizer.move_to_library(tmpdir, artist, album)
