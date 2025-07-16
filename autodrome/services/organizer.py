import os
import shutil
from typing import List, Optional
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

    def tag_and_rename(
        self,
        folder_path: str,
        artist: str,
        album: str,
        tracks: List[Track],
        cover_path: Optional[str] = None,
        date: Optional[str] = None
    ) -> None:
        logger.debug(f"Tagging and renaming in folder: {folder_path}")

        files = sorted(f for f in os.listdir(folder_path) if f.lower().endswith(".mp3"))

        for file, track in zip(files, tracks):
            original_path = os.path.join(folder_path, file)
            new_filename = f"{track.number:02d} - {track.title}.mp3"
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
        destination = conf.library_path
        artist_folder = os.path.join(destination, self._sanitize_filename(artist))
        album_folder = os.path.join(artist_folder, self._sanitize_filename(album))

        try:
            os.makedirs(album_folder, exist_ok=True)

            for item in os.listdir(temp_folder):
                src = os.path.join(temp_folder, item)
                dst = os.path.join(album_folder, item)
                shutil.move(src, dst)

            if not os.listdir(temp_folder):
                os.rmdir(temp_folder)
                logger.debug(f"Deleted empty temporary folder '{temp_folder}'")

            logger.info("Moved album to library successfully.")
        except Exception as e:
            logger.error(f"Error moving files to library: {e}")
            raise

    def _sanitize_filename(self, name: str) -> str:
        invalid_chars = '<>:"/\\|?¿*!¡'
        for ch in invalid_chars:
            name = name.replace(ch, '_')
        return name.strip()
