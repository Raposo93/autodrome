from typing import Any, Dict, List, Optional
from autodrome.http_client_async import AsyncHttpClient
from autodrome.logger import logger
from autodrome.models.track import Track
from autodrome.services.redis_cache import RedisCache
from autodrome.services.organizer import Organizer
from autodrome.metadata_service import MetadataService
from autodrome.yt_downloader import YTDownloader

class DownloaderController:
    def __init__(
        self, 
        downloader: YTDownloader, 
        organizer: Organizer, 
        metadata_service: MetadataService,
        redis_cache: Optional[RedisCache] = None,
        http_client: Optional[AsyncHttpClient] = None
    ) -> None:
        self.downloader = downloader
        self.organizer = organizer
        self.metadata_service = metadata_service
        self.redis_cache = redis_cache or RedisCache()
        self.http_client = http_client


    async def download_and_tag(
        self, 
        playlist_url: str, 
        artist: str, 
        album: str, 
        release_id: str, 
        track_count: Optional[int] = None
    ) -> None:
        logger.debug(f"Starting download and tagging for release_id: {release_id}")

        cached_release: Optional[Dict[str, Any]] = self.redis_cache.get_release(release_id)
        if cached_release is None:
            raise ValueError(f"Release {release_id} not found in cache")

        tracks: List[Track] = [Track(**t) for t in cached_release.get("tracks", [])]
        date: Optional[str] = cached_release.get("date")

        with self.downloader.create_temp_folder() as tmpdir:
            self.downloader.download_playlist(playlist_url, tmpdir, total=track_count)

            cover_path: Optional[str] = await self.metadata_service.get_cover_art(release_id)


            self.organizer.tag_and_rename(tmpdir, artist, album, tracks, cover_path, date)
            self.organizer.move_to_library(tmpdir, artist, album)

        logger.info(f"Download and tagging completed for release_id: {release_id}")
