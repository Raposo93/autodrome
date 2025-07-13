class Track:
    def __init__(self, number: int, title: str):
        self.number = number
        self.title = title

    def __repr__(self):
        return f"<Track {self.number:02d} - {self.title}>"
    
    def to_dict(self):
        return {
            "number": self.number,
            "title": self.title
    }