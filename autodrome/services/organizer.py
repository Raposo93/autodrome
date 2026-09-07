import os
import shutil
import tempfile
import uuid
from contextlib import contextmanager
from typing import Iterator, List, Optional, Tuple

from mutagen.easyid3 import EasyID3
from mutagen.id3 import ID3
from mutagen.mp3 import MP3
from autodrome.models.track import Track
from autodrome.logger import logger
from autodrome import config
from autodrome.services.tagger import Tagger
from autodrome.services.cover_embedder import CoverEmbedder
from autodrome.path_safety import resolve_album_path, validate_path_component

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

        rename_plan = self._build_rename_plan(folder_path, files, tracks)
        prepared_cover = None
        if cover_path:
            if not os.path.isfile(cover_path):
                raise FileNotFoundError(f"Cover image not found: {cover_path}")
            prepared_cover = self.cover_embedder.prepare_cover(cover_path)

        staged_renames = []
        for original_path, new_path in rename_plan:
            intermediate_path = os.path.join(
                folder_path, f".autodrome-rename-{uuid.uuid4().hex}.mp3"
            )
            os.rename(original_path, intermediate_path)
            staged_renames.append((intermediate_path, new_path))

        for intermediate_path, new_path in staged_renames:
            os.rename(intermediate_path, new_path)

        self.tagger.tag_files(folder_path, artist, album, tracks, date)

        if prepared_cover:
            for file in sorted(f for f in os.listdir(folder_path) if f.lower().endswith(".mp3")):
                mp3_path = os.path.join(folder_path, file)
                self.cover_embedder.embed_cover(mp3_path, prepared_cover)
        else:
            logger.debug(f"No valid cover art found to embed (path: {cover_path})")

        logger.info("Tagging and renaming completed.")

    def validate_album(
        self,
        folder_path: str,
        artist: str,
        album: str,
        tracks: List[Track],
    ) -> None:
        files = sorted(f for f in os.listdir(folder_path) if f.lower().endswith(".mp3"))
        if len(files) != len(tracks):
            raise ValueError(
                "Staged album track count mismatch: "
                f"expected {len(tracks)}, got {len(files)}"
            )

        for index, file in enumerate(files):
            track = tracks[index]
            file_path = os.path.join(folder_path, file)
            try:
                audio = MP3(file_path, ID3=EasyID3)
            except Exception as e:
                raise ValueError(f"Staged MP3 is not readable: {file}") from e

            duration = getattr(audio.info, "length", 0)
            if duration <= 0:
                raise ValueError(f"Staged MP3 has no positive duration: {file}")

            expected_tags = {
                "artist": artist,
                "album": album,
                "title": track.title,
                "tracknumber": str(track.number),
            }
            if self._is_multi_disc(tracks):
                expected_tags["discnumber"] = str(track.disc_number)
            for tag_name, expected_value in expected_tags.items():
                if expected_value not in audio.get(tag_name, []):
                    raise ValueError(
                        f"Staged MP3 has invalid {tag_name} tag: {file}"
                    )

            try:
                covers = ID3(file_path).getall("APIC")
            except Exception as e:
                raise ValueError(f"Staged MP3 has unreadable ID3 tags: {file}") from e

            for cover in covers:
                cover_size = len(cover.data)
                if cover_size > conf.max_embedded_cover_bytes:
                    raise ValueError(
                        f"Embedded cover exceeds limit in {file}: "
                        f"size {cover_size} bytes, limit "
                        f"{conf.max_embedded_cover_bytes} bytes"
                    )

        logger.info(f"Validated {len(files)} staged MP3 files before publication")

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
        safe_artist = self._sanitize_filename(validate_path_component(artist))
        safe_album = self._sanitize_filename(validate_path_component(album))
        validate_path_component(safe_artist)
        validate_path_component(safe_album)
        return str(resolve_album_path(destination, safe_artist, safe_album))

    def _build_rename_plan(
        self,
        folder_path: str,
        files: List[str],
        tracks: List[Track],
    ) -> List[Tuple[str, str]]:
        rename_plan = []
        final_names = set()
        multi_disc = self._is_multi_disc(tracks)

        for index, file in enumerate(files):
            track = tracks[index]
            sanitized_title = self._sanitize_filename(track.title)
            if multi_disc:
                prefix = f"{track.disc_number:02d}-{track.position:02d}"
            else:
                prefix = f"{track.number:02d}"
            new_filename = f"{prefix} - {sanitized_title}.mp3"
            collision_key = new_filename.casefold()
            if collision_key in final_names:
                raise ValueError(
                    f"Track filename collision after sanitization: {new_filename}"
                )
            final_names.add(collision_key)
            rename_plan.append(
                (
                    os.path.join(folder_path, file),
                    os.path.join(folder_path, new_filename),
                )
            )

        return rename_plan

    @staticmethod
    def _is_multi_disc(tracks: List[Track]) -> bool:
        disc_numbers = {track.disc_number for track in tracks}
        return len(disc_numbers) > 1 or any(number != 1 for number in disc_numbers)

    def _sanitize_filename(self, name: str) -> str:
        invalid_chars = '<>:"/\\|?¿*!¡'
        for ch in invalid_chars:
            name = name.replace(ch, '_')
        return name.strip()
