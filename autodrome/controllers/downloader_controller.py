from typing import Any, Dict, List, Optional
from autodrome.http_client_async import AsyncHttpClient, UpstreamServiceError
from autodrome.logger import logger
from autodrome.models.track import Track
from autodrome.services.organizer import Organizer
from autodrome.metadata_service import MetadataService
from autodrome.yt_downloader import YTDownloader

class DownloaderController:
    def __init__(
        self, 
        downloader: YTDownloader, 
        organizer: Organizer, 
        metadata_service: MetadataService,
        http_client: Optional[AsyncHttpClient] = None
    ) -> None:
        self.downloader = downloader
        self.organizer = organizer
        self.metadata_service = metadata_service
        self.http_client = http_client


    async def download_and_tag(
        self, 
        playlist_url: str, 
        artist: str, 
        album: str, 
        release_id: Optional[str],
        track_count: Optional[int] = None,
        metadata_mode: str = "musicbrainz",
        manual_confirmed: bool = False
    ) -> None:
        logger.debug(f"Starting download_and_tag for release_id: {release_id}")

        manifest = None
        if metadata_mode == "manual":
            if release_id is not None or not manual_confirmed:
                raise ValueError("Manual metadata requires explicit confirmation")
            manifest = await self.downloader.get_playlist_manifest(playlist_url, track_count)
            tracks = [Track(number=entry["position"], title=entry["title"])
                      for entry in manifest["tracks"]]
            date = None
        elif metadata_mode == "musicbrainz" and release_id:
            release_data = await self._get_release_data(release_id)
            artist = release_data.get("artist") or artist
            tracks = [Track(**t) for t in release_data.get("tracks", [])]
            date = release_data.get("date")
        else:
            raise ValueError("MusicBrainz mode requires a release")
        if track_count is not None and track_count != len(tracks):
            raise ValueError(
                f"Track count mismatch: playlist has {track_count} tracks, "
                f"but the selected release has {len(tracks)}. Choose a matching pair."
            )

        with self.organizer.create_staging_folder(artist, album) as tmpdir:
            await self.downloader.download_playlist(
                playlist_url, tmpdir, total=len(tracks),
                **({"manifest": manifest} if manifest is not None else {}),
            )
            cover_path = await self.metadata_service.get_cover_art(release_id) if release_id else None

            self.organizer.tag_and_rename(tmpdir, artist, album, tracks, cover_path, date)
            self.organizer.validate_album(tmpdir, artist, album, tracks)
            self.organizer.move_to_library(tmpdir, artist, album)

        logger.info(f"Download and tagging completed for release_id: {release_id}")

    async def _get_release_data(self, release_id: str) -> Dict[str, Any]:
        try:
            release = await self.metadata_service.get_release(release_id)
        except UpstreamServiceError:
            raise
        except Exception as e:
            raise RuntimeError(
                f"Could not load release {release_id} from MusicBrainz"
            ) from e

        return {
            "id": release.id,
            "title": release.title,
            "date": release.date,
            "artist": release.artist,
            "cover_url": release.cover_url,
            "tracks": [track.to_dict() for track in release.tracks],
        }
