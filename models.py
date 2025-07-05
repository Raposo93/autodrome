class Release:
    def __init__(self, id, title, date, artist):
        self.id = id
        self.title = title
        self.date = date
        self.artist = artist

    def __repr__(self):
        return f"<Release {self.title} ({self.date}) by {self.artist}>"

class Track:
    def __init__(self, number, title):
        self.number = number
        self.title = title

    def __repr__(self):
        return f"<Track {self.number:02d} - {self.title}>"

class Playlist:
    def __init__(self, playlist_id, title, channel, url, track_count=None):
        self.id = playlist_id
        self.title = title
        self.channel = channel
        self.url = url
        self.track_count = track_count

    def __repr__(self):
        return f"<Playlist '{self.title}' by {self.channel} ({self.track_count or '?' } tracks)>"
