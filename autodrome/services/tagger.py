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
        
        for file, track in zip(files, tracks):
            file_path = os.path.join(folder_path, file)
            audio = MP3(file_path, ID3=EasyID3)
            audio["artist"] = artist
            audio["album"] = album
            audio["title"] = track.title
            audio["tracknumber"] = str(track.number)
            if date:
                audio["date"] = date
            audio.save()
