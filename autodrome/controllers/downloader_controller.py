from typing import Any, Dict, List, Optional
from autodrome.http_client_async import AsyncHttpClient, UpstreamServiceError
from autodrome.logger import logger
from autodrome.models.track import Track
from autodrome.models.progress import report_progress, ProgressCallback
from autodrome.services.organizer import Organizer
from autodrome.services.cover_selection import CoverSelectionService
from autodrome.services.cover_embedder import PreparedCover
from autodrome.services.publication_catalog import (
    PublicationCatalog,
    PublicationCatalogError,
)
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
        publication_catalog: Optional[PublicationCatalog] = None,
        application_version: Optional[str] = None,
        build_commit: Optional[str] = None,
    ) -> None:
        self.downloader = downloader
        self.organizer = organizer
        self.metadata_service = metadata_service
        self.http_client = http_client
        self.cover_selection = cover_selection
        self.publication_catalog = publication_catalog
        self.application_version = application_version
        self.build_commit = build_commit

    async def ensure_destination_available(self, artist: str, album: str) -> None:
        destination = self.organizer.inspect_album_destination(artist, album)
        if destination["state"] == "exists":
            raise FileExistsError("Album already exists in the library")
        if destination["state"] != "not_found":
            raise OSError("Album destination could not be checked")

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
        cover_square_mode: Optional[str] = None,
        progress: Optional[ProgressCallback] = None,
        job_id: Optional[str] = None,
        playlist_id: Optional[str] = None,
        playlist_title: Optional[str] = None,
        playlist_channel: Optional[str] = None,
        playlist_thumbnail: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        logger.debug(f"Starting download_and_tag for release_id: {release_id}")

        if self.publication_catalog is not None and not job_id:
            raise ValueError("A durable job ID is required for publication")

        await report_progress(progress, "metadata")
        manifest = None
        release_data = None
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
                cover_square_mode=cover_square_mode,
            )

        await report_progress(progress, "staging")
        with self.organizer.create_staging_folder(artist, album) as tmpdir:
            used_manifest = await self.downloader.download_playlist(
                playlist_url, tmpdir, total=len(tracks),
                **({"progress": progress} if progress is not None else {}),
                **({"manifest": manifest} if manifest is not None else {}),
            )
            manifest = used_manifest or manifest
            if resolved_cover_source == "cover_art_archive":
                await report_progress(progress, "cover")
                prepared_cover = await self._prepare_cover(
                    release_id=release_id,
                    cover_source=resolved_cover_source,
                    cover_id=cover_id,
                    cover_url=cover_url,
                    cover_square_mode=cover_square_mode,
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
            destination_path = self.organizer.move_to_library(tmpdir, artist, album)

            publication = None
            if self.publication_catalog is not None:
                try:
                    publication = self.publication_catalog.record_publication(
                        job_id=job_id,
                        destination_path=destination_path,
                        library_root=self.organizer.library_root,
                        artist=artist,
                        album=album,
                        metadata_mode=metadata_mode,
                        release=release_data,
                        playlist={
                            "id": playlist_id,
                            "url": playlist_url,
                            "title": playlist_title,
                            "channel": playlist_channel,
                            "thumbnail": playlist_thumbnail,
                        },
                        manifest=manifest,
                        tracks=tracks,
                        cover=self._publication_cover(
                            requested_source=resolved_cover_source,
                            prepared_cover=prepared_cover,
                            cover_url=cover_url,
                            square_mode=cover_square_mode,
                        ),
                        accepted_overrides=(
                            ["manual_metadata_without_musicbrainz"]
                            if manual_confirmed else []
                        ),
                        application_version=self.application_version,
                        build_commit=self.build_commit,
                    )
                except Exception as error:
                    relative_path = self.organizer.inspect_album_destination(
                        artist, album
                    ).get("relative_path", f"{artist}/{album}")
                    raise PublicationCatalogError(
                        "Album was published at "
                        f"{relative_path}, but its provenance record could not be "
                        "saved. Inspect the library and catalog before retrying; "
                        "Autodrome will not overwrite the published album."
                    ) from error

        logger.debug("download_workflow_completed release_id=%s", release_id)
        return publication

    @staticmethod
    def _publication_cover(
        *,
        requested_source: str,
        prepared_cover: Optional[PreparedCover],
        cover_url: Optional[str],
        square_mode: Optional[str],
    ) -> Dict[str, Any]:
        embedded = prepared_cover is not None
        source = requested_source if embedded else "none"
        dimensions = getattr(prepared_cover, "dimensions", None)
        return {
            "source": source,
            "requested_source": requested_source,
            "embedded": embedded,
            "square_strategy": (
                square_mode
                if requested_source in {"youtube_thumbnail", "manual_upload"}
                else None
            ),
            "source_url": cover_url if requested_source == "youtube_thumbnail" else None,
            "mime_type": getattr(prepared_cover, "mime_type", None),
            "width": dimensions[0] if dimensions else None,
            "height": dimensions[1] if dimensions else None,
        }

    async def _prepare_cover(
        self,
        *,
        release_id: Optional[str],
        cover_source: Optional[str],
        cover_id: Optional[str],
        cover_url: Optional[str],
        cover_square_mode: Optional[str],
    ) -> Optional[PreparedCover]:
        source = cover_source or ("cover_art_archive" if release_id else "none")
        if source == "none":
            if (
                cover_id is not None
                or cover_url is not None
                or cover_square_mode is not None
            ):
                raise ValueError("No-cover selection cannot include an image")
            return None
        if source == "cover_art_archive":
            if not release_id:
                raise ValueError("Cover Art Archive selection requires a release")
            if (
                cover_id is not None
                or cover_url is not None
                or cover_square_mode is not None
            ):
                raise ValueError("Cover Art Archive selection cannot include an alternative cover")
            cover_path = await self.metadata_service.get_cover_art(release_id)
            if cover_path is None:
                return None
            return self.organizer.cover_embedder.prepare_cover(cover_path)
        if source in {"youtube_thumbnail", "manual_upload"}:
            if not cover_id or self.cover_selection is None:
                raise ValueError("The selected alternative cover is unavailable")
            if cover_square_mode not in {None, "fit", "crop"}:
                raise ValueError("Alternative cover selection has an unsupported square mode")
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
            "track_count": len(release.tracks),
            "country": release.country,
            "media_format": release.media_format,
            "medium_count": release.medium_count,
            "tracks": [track.to_dict() for track in release.tracks],
        }
