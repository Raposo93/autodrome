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
        logger.debug(f"Starting download_and_tag for release_id: {release_id}")

        release_data = await self._get_release_data(release_id)

        tracks: List[Track] = [Track(**t) for t in release_data.get("tracks", [])]
        date: Optional[str] = release_data.get("date")

        with self.downloader.create_temp_folder() as tmpdir:
            await self.downloader.download_playlist(playlist_url, tmpdir, total=track_count)
            cover_path: Optional[str] = await self.metadata_service.get_cover_art(release_id)

            self.organizer.tag_and_rename(tmpdir, artist, album, tracks, cover_path, date)
            self.organizer.move_to_library(tmpdir, artist, album)

        logger.info(f"Download and tagging completed for release_id: {release_id}")

    async def _get_release_data(self, release_id: str) -> Dict[str, Any]:
        try:
            cached_release = self.redis_cache.get_release(release_id)
        except Exception as e:
            logger.warning(f"Could not read release {release_id} from cache: {e}")
            cached_release = None

        if cached_release is not None:
            return cached_release

        logger.info(
            f"Release {release_id} was not available in cache; fetching MusicBrainz"
        )
        try:
            release = await self.metadata_service.get_release(release_id)
        except Exception as e:
            raise RuntimeError(
                f"Could not load release {release_id}: cache miss and "
                "MusicBrainz lookup failed"
            ) from e

        release_data = {
            "id": release.id,
            "title": release.title,
            "date": release.date,
            "artist": release.artist,
            "cover_url": release.cover_url,
            "tracks": [track.to_dict() for track in release.tracks],
        }

        try:
            self.redis_cache.set_release(release_id, release_data)
        except Exception as e:
            logger.warning(f"Could not cache release {release_id}: {e}")

        return release_data
