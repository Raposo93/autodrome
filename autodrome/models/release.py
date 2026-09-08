from typing import List, Optional


class Release:
    def __init__(
        self,
        release_id: str,
        title: str,
        date: str,
        artist: str,
        cover_url: Optional[str],
        tracks: Optional[List[dict]] = None,
        track_count: Optional[int] = None,
    ):
        self.id = release_id
        self.title = title
        self.date = date
        self.cover_url = cover_url
        self.artist = artist
        self.tracks = tracks or []
        self.track_count = track_count

    def __repr__(self):
        track_count = (
            self.track_count
            if self.track_count is not None
            else len(self.tracks)
        )
        return (f"<Release {self.title} ({self.date}) by {self.artist}, "
                f"id={self.id}, tracks_count={track_count}>")
