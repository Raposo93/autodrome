class Playlist:
    def __init__(self, playlist_id, title, channel, url, thumbnail, track_count=None):
        self.id = playlist_id
        self.title = title
        self.channel = channel
        self.url = url
        self.thumbnail = thumbnail
        self.track_count = track_count

    def __repr__(self):
        return f"<Playlist '{self.title}' by {self.channel} ({self.track_count or '?' } tracks)>"
