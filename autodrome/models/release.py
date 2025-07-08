class Release:
    def __init__(self, id, title, date, artist, tracks=None):
        self.id = id
        self.title = title
        self.date = date
        self.artist = artist
        self.tracks = tracks or []

    def __repr__(self):
        return f"<Release {self.title} ({self.date}) by {self.artist}>"