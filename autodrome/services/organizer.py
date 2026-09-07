import os
import shutil
import tempfile
from contextlib import contextmanager
from typing import Iterator, List, Optional
from autodrome.models.track import Track
from autodrome.logger import logger
from autodrome import config
from autodrome.services.tagger import Tagger
from autodrome.services.cover_embedder import CoverEmbedder

conf = config.Config()

class Organizer:
    def __init__(self) -> None:
        self.tagger = Tagger()
        self.cover_embedder = CoverEmbedder()

    @contextmanager
    def create_staging_folder(self, artist: str, album: str) -> Iterator[str]:
        library_root = os.path.abspath(conf.library_path)
        staging_root = os.path.abspath(conf.staging_path)

        os.makedirs(library_root, exist_ok=True)
        os.makedirs(staging_root, exist_ok=True)

        if os.stat(library_root).st_dev != os.stat(staging_root).st_dev:
            raise OSError(
                "Staging and library directories must be on the same filesystem"
            )

        album_folder = self._get_album_folder(artist, album)
        if os.path.lexists(album_folder):
            raise FileExistsError(f"Album already exists: {album_folder}")

        free_bytes = shutil.disk_usage(staging_root).free
        required_bytes = conf.minimum_staging_free_bytes
        if free_bytes < required_bytes:
            raise OSError(
                "Insufficient staging space: "
                f"required at least {required_bytes} bytes, available {free_bytes} bytes"
            )

        staging_folder = tempfile.mkdtemp(prefix="album-", dir=staging_root)
        try:
            yield staging_folder
        except Exception:
            if conf.preserve_failed_staging:
                logger.error(
                    f"Album processing failed; preserving staging files in {staging_folder}"
                )
            else:
                shutil.rmtree(staging_folder, ignore_errors=True)
                logger.info(f"Removed failed staging folder {staging_folder}")
            raise
        else:
            if os.path.exists(staging_folder):
                shutil.rmtree(staging_folder)

    def tag_and_rename(
        self,
        folder_path: str,
        artist: str,
        album: str,
        tracks: List[Track],
        cover_path: Optional[str] = None,
        date: Optional[str] = None
    ) -> None:

        files = sorted(f for f in os.listdir(folder_path) if f.lower().endswith(".mp3"))
        expected_count = len(tracks)
        downloaded_count = len(files)
        if downloaded_count != expected_count:
            raise ValueError(
                "Downloaded track count mismatch: "
                f"expected {expected_count}, got {downloaded_count}"
            )

        for index, file in enumerate(files):
            track = tracks[index]
            original_path = os.path.join(folder_path, file)
            sanitized_title = self._sanitize_filename(track.title)
            new_filename = f"{track.number:02d} - {sanitized_title}.mp3"
            new_path = os.path.join(folder_path, new_filename)
            os.rename(original_path, new_path)

        self.tagger.tag_files(folder_path, artist, album, tracks, date)

        if cover_path and os.path.isfile(cover_path):
            for file in sorted(f for f in os.listdir(folder_path) if f.lower().endswith(".mp3")):
                mp3_path = os.path.join(folder_path, file)
                self.cover_embedder.embed_cover(mp3_path, cover_path)
        else:
            logger.debug(f"No valid cover art found to embed (path: {cover_path})")

        logger.info("Tagging and renaming completed.")

    def move_to_library(
        self,
        temp_folder: str,
        artist: str,
        album: str
    ) -> None:
        artist_folder = os.path.dirname(self._get_album_folder(artist, album))
        album_folder = self._get_album_folder(artist, album)

        if os.path.lexists(album_folder):
            raise FileExistsError(f"Album already exists: {album_folder}")

        artist_folder_created = not os.path.exists(artist_folder)
        os.makedirs(artist_folder, exist_ok=True)

        if os.stat(temp_folder).st_dev != os.stat(artist_folder).st_dev:
            if artist_folder_created and not os.listdir(artist_folder):
                os.rmdir(artist_folder)
            raise OSError(
                "Cannot publish album atomically across different filesystems"
            )

        try:
            os.rename(temp_folder, album_folder)
        except Exception:
            if artist_folder_created and not os.listdir(artist_folder):
                os.rmdir(artist_folder)
            raise

        logger.info(f"Published album atomically to: {album_folder}")

    def _get_album_folder(self, artist: str, album: str) -> str:
        destination = os.path.abspath(conf.library_path)
        artist_folder = os.path.join(destination, self._sanitize_filename(artist))
        return os.path.join(artist_folder, self._sanitize_filename(album))

    def _sanitize_filename(self, name: str) -> str:
        invalid_chars = '<>:"/\\|?¿*!¡'
        for ch in invalid_chars:
            name = name.replace(ch, '_')
        return name.strip()
