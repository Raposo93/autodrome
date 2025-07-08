import shutil
import os
from mutagen.easyid3 import EasyID3
from mutagen.id3 import ID3, APIC, error
from mutagen.mp3 import MP3
from autodrome.logger import logger
from autodrome import config

conf = config.Config()

class Organizer:
    def tag_and_rename(self, folder_path, artist, album, tracks, cover_path=None):
        logger.debug(f"Tagging and renaming files in folder: {folder_path}")  
        files = sorted(
            f for f in os.listdir(folder_path) if f.lower().endswith(".mp3")
        )
                
        for file, track in zip(files, tracks):
            full_path = os.path.join(folder_path, file)
            new_name = f"{track.number:02d} - {track.title}.mp3"
            new_path = os.path.join(folder_path, new_name)

            # Renombrar archivo
            os.rename(full_path, new_path)

            # Etiquetar archivo
            audio = MP3(new_path, ID3=EasyID3)
            audio["artist"] = artist
            audio["album"] = album
            audio["title"] = track.title
            audio["tracknumber"] = str(track.number)
            audio.save()
            
            if cover_path and os.path.isfile(cover_path):
                self.embed_cover_art(new_path, cover_path)
            else:
                logger.debug(f"No valid cover art found to embed for '{new_name}'")
        logger.info("Tagging and renaming completed.")

            
    def embed_cover_art(self, mp3_file_path, cover_image_path):
        logger.debug(f"Embedding cover art from '{cover_image_path}' into '{mp3_file_path}'")
        audio = MP3(mp3_file_path, ID3=ID3)

        try:
            audio.add_tags()
        except error:
            pass

        with open(cover_image_path, 'rb') as img:
            audio.tags.add(
                APIC(
                    encoding=3,          
                    mime='image/jpeg',   # Cambia si usas PNG: image/png
                    type=3,              
                    desc='Cover',
                    data=img.read()
                )
            )
        audio.save()
        logger.debug(f"Cover art embedded successfully in '{mp3_file_path}'")


    def move_to_library(self, temp_folder, artist, album):
        """
        Mueve la carpeta temporal con la música a la carpeta de biblioteca,
        organizada por artista y álbum.
        """
        destination = conf.library_path
        artist_folder = os.path.join(destination, self._sanitize_filename(artist))
        album_folder = os.path.join(artist_folder, self._sanitize_filename(album))

        try:
            logger.debug(f"Moving album folder from '{temp_folder}' to '{album_folder}'")

            os.makedirs(album_folder, exist_ok=True)

            for item in os.listdir(temp_folder):
                src = os.path.join(temp_folder, item)
                dst = os.path.join(album_folder, item)
                logger.debug(f"Moving '{src}' to '{dst}'")
                shutil.move(src, dst)

            if not os.listdir(temp_folder):
                os.rmdir(temp_folder)
                logger.debug(f"Deleted empty temporary folder '{temp_folder}'")

            logger.info("Move to library completed successfully.")
        except Exception as e:
            logger.error(f"Error moving files to library: {e}")
            raise

    def _sanitize_filename(self, name):
        invalid_chars = '<>:"/\\|?¿*!¡'
        for ch in invalid_chars:
            name = name.replace(ch, '_')
        return name.strip()