from typing import Optional


class Track:
    def __init__(
        self,
        number: int,
        title: str,
        disc_number: int = 1,
        position: Optional[int] = None,
        global_position: Optional[int] = None,
        artist: Optional[str] = None,
        duration_seconds: Optional[float] = None,
    ):
        self.artist = artist
        self.duration_seconds = duration_seconds
        self.number = number
        self.title = title
        self.disc_number = disc_number
        self.position = position if position is not None else number
        self.global_position = (
            global_position if global_position is not None else number
        )

    def __repr__(self):
        return (
            f"<Track disc={self.disc_number} position={self.position} "
            f"global={self.global_position} - {self.title}>"
        )

    def to_dict(self):
        data = {
            "artist": self.artist,
            "number": self.number,
            "title": self.title,
            "disc_number": self.disc_number,
            "position": self.position,
            "global_position": self.global_position,
        }
        if self.duration_seconds is not None:
            data["duration_seconds"] = self.duration_seconds
        return data
