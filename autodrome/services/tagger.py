import os
from typing import List, Optional
from mutagen.easyid3 import EasyID3
from mutagen.mp3 import MP3
from autodrome.models.track import Track
from autodrome.logger import logger

class Tagger:
    def tag_files(
        self,
        folder_path: str,
        artist: str,
        album: str,
        tracks: List[Track],
        date: Optional[str] = None
    ) -> None:
        files = sorted(f for f in os.listdir(folder_path) if f.lower().endswith(".mp3"))
        expected_count = len(tracks)
        downloaded_count = len(files)
        if downloaded_count != expected_count:
            raise ValueError(
                "Downloaded track count mismatch before tagging: "
                f"expected {expected_count}, got {downloaded_count}"
            )

        disc_numbers = {track.disc_number for track in tracks}
        multi_disc = len(disc_numbers) > 1 or any(
            number != 1 for number in disc_numbers
        )

        for index, file in enumerate(files):
            track = tracks[index]
            file_path = os.path.join(folder_path, file)
            audio = MP3(file_path, ID3=EasyID3)
            audio["artist"] = artist
            audio["album"] = album
            audio["title"] = track.title
            audio["tracknumber"] = str(track.number)
            if multi_disc:
                audio["discnumber"] = str(track.disc_number)
            if date:
                audio["date"] = date
            audio.save()
