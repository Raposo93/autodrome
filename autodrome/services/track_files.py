"""Match audio to explicit numeric track identities, never directory ordering."""
import re


def match_track_files(files, tracks, *, downloaded=False):
    multi_disc = len({t.disc_number for t in tracks}) > 1 or any(
        t.disc_number != 1 for t in tracks
    )
    expected = {}
    for track in tracks:
        key = ((track.global_position,) if downloaded else
               (track.disc_number, track.position) if multi_disc else (track.number,))
        if any(type(number) is not int or number < 1 for number in key) or key in expected:
            raise ValueError("Missing or duplicate track identity")
        expected[key] = track
    actual = {}
    for file in files:
        match = re.fullmatch(r"(\d+)(?:-(\d+))?(?: - .+)?\.mp3", file, re.IGNORECASE)
        if not match:
            raise ValueError(f"Missing audio track identity: {file}")
        key = tuple(int(value) for value in match.groups() if value is not None)
        if key in actual:
            raise ValueError(f"Duplicate audio track identity: {file}")
        actual[key] = file
    if actual.keys() != expected.keys():
        raise ValueError("Audio and metadata track identities do not match")
    return [(actual[key], track) for key, track in expected.items()]
