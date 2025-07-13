from typing import List, Optional


class Release:
    def __init__(self, release_id: str, title: str, date: str, artist: str, tracks: Optional[List[dict]] = None):
        self.id = release_id
        self.title = title
        self.date = date
        self.artist = artist
        self.tracks = tracks or []

    def __repr__(self):
        return (f"<Release {self.title} ({self.date}) by {self.artist}, "
                f"id={self.id}, tracks_count={len(self.tracks)}>")
