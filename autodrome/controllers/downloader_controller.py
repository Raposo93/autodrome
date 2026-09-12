from typing import Any, Dict, List, Optional
from autodrome.http_client_async import AsyncHttpClient, UpstreamServiceError
from autodrome.logger import logger
from autodrome.models.track import Track
from autodrome.models.progress import report_progress, ProgressCallback
from autodrome.services.organizer import Organizer
from autodrome.services.cover_selection import CoverSelectionService
from autodrome.services.cover_embedder import PreparedCover
from autodrome.url_safety import validate_youtube_thumbnail_url
from autodrome.metadata_service import MetadataService
from autodrome.yt_downloader import YTDownloader

class DownloaderController:
    def __init__(
        self, 
        downloader: YTDownloader, 
        organizer: Organizer, 
        metadata_service: MetadataService,
        http_client: Optional[AsyncHttpClient] = None,
        cover_selection: Optional[CoverSelectionService] = None,
    ) -> None:
        self.downloader = downloader
        self.organizer = organizer
        self.metadata_service = metadata_service
        self.http_client = http_client
        self.cover_selection = cover_selection


    async def download_and_tag(
        self, 
        playlist_url: str, 
        artist: str, 
        album: str, 
        release_id: Optional[str],
        track_count: Optional[int] = None,
        metadata_mode: str = "musicbrainz",
        manual_confirmed: bool = False,
        cover_source: Optional[str] = None,
        cover_id: Optional[str] = None,
        cover_url: Optional[str] = None,
        progress: Optional[ProgressCallback] = None
    ) -> None:
        logger.debug(f"Starting download_and_tag for release_id: {release_id}")

        await report_progress(progress, "metadata")
        manifest = None
        if metadata_mode == "manual":
            if release_id is not None or not manual_confirmed:
                raise ValueError("Manual metadata requires explicit confirmation")
            await report_progress(progress, "manifest")
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

        resolved_cover_source = cover_source or (
            "cover_art_archive" if release_id else "none"
        )
        prepared_cover = None
        if resolved_cover_source != "cover_art_archive":
            await report_progress(progress, "cover")
            prepared_cover = await self._prepare_cover(
                release_id=release_id,
                cover_source=resolved_cover_source,
                cover_id=cover_id,
                cover_url=cover_url,
            )

        await report_progress(progress, "staging")
        with self.organizer.create_staging_folder(artist, album) as tmpdir:
            await self.downloader.download_playlist(
                playlist_url, tmpdir, total=len(tracks),
                **({"progress": progress} if progress is not None else {}),
                **({"manifest": manifest} if manifest is not None else {}),
            )
            if resolved_cover_source == "cover_art_archive":
                await report_progress(progress, "cover")
                prepared_cover = await self._prepare_cover(
                    release_id=release_id,
                    cover_source=resolved_cover_source,
                    cover_id=cover_id,
                    cover_url=cover_url,
                )
            await report_progress(progress, "tagging")
            self.organizer.tag_and_rename(
                tmpdir,
                artist,
                album,
                tracks,
                None,
                date,
                prepared_cover=prepared_cover,
            )
            await report_progress(progress, "validating")
            self.organizer.validate_album(tmpdir, artist, album, tracks)
            await report_progress(progress, "publishing")
            self.organizer.move_to_library(tmpdir, artist, album)

        logger.debug("download_workflow_completed release_id=%s", release_id)

    async def _prepare_cover(
        self,
        *,
        release_id: Optional[str],
        cover_source: Optional[str],
        cover_id: Optional[str],
        cover_url: Optional[str],
    ) -> Optional[PreparedCover]:
        source = cover_source or ("cover_art_archive" if release_id else "none")
        if source == "none":
            if cover_id is not None or cover_url is not None:
                raise ValueError("No-cover selection cannot include an image")
            return None
        if source == "cover_art_archive":
            if not release_id:
                raise ValueError("Cover Art Archive selection requires a release")
            if cover_id is not None or cover_url is not None:
                raise ValueError("Cover Art Archive selection cannot include an alternative cover")
            cover_path = await self.metadata_service.get_cover_art(release_id)
            if cover_path is None:
                return None
            return self.organizer.cover_embedder.prepare_cover(cover_path)
        if source in {"youtube_thumbnail", "manual_upload"}:
            if not cover_id or self.cover_selection is None:
                raise ValueError("The selected alternative cover is unavailable")
            if source == "youtube_thumbnail":
                if cover_url is None:
                    raise ValueError("YouTube cover selection requires its URL")
                validate_youtube_thumbnail_url(cover_url)
            elif cover_url is not None:
                raise ValueError("Manual cover selection cannot include a URL")
            return self.cover_selection.load_prepared(cover_id)
        raise ValueError(f"Unsupported cover source: {source}")

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
