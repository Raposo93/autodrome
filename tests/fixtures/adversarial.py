"""Load small shared fixtures and generate deterministic large edge cases."""

import copy
import json
from pathlib import Path
from typing import Any, Dict


FIXTURE_DIR = Path(__file__).parent


def _load_json(name: str) -> Dict[str, Any]:
    with (FIXTURE_DIR / name).open(encoding="utf-8") as fixture_file:
        return json.load(fixture_file)


def playlist_from_hell() -> Dict[str, Any]:
    """Return yt-dlp data with missing entries and hostile track titles."""
    return copy.deepcopy(_load_json("playlist_from_hell.json"))


def complex_release_fixture() -> Dict[str, Any]:
    """Return MusicBrainz input plus its normalized API representation."""
    return copy.deepcopy(_load_json("complex_release.json"))


def generated_playlist(track_count: int) -> Dict[str, Any]:
    """Build a stable yt-dlp playlist whose IDs encode original audio identity."""
    if track_count < 1:
        raise ValueError("track_count must be positive")
    return {
        "id": f"generated-{track_count}",
        "title": f"Generated {track_count}-track boundary playlist",
        "entries": [
            {
                "id": f"audio-{position:03d}",
                "webpage_url": (
                    "https://youtube.test/watch?v="
                    f"audio-{position:03d}"
                ),
                "title": f"Source audio {position:03d}",
            }
            for position in range(1, track_count + 1)
        ],
    }


def generated_musicbrainz_release(
    track_count: int,
    *,
    first_disc_tracks: int | None = None,
) -> Dict[str, Any]:
    """Build MusicBrainz data with stable per-track metadata identities.

    ``first_disc_tracks`` splits the release after that many global tracks. Each
    disc restarts its local track number, while every title and artist retains
    the global identity needed to detect audio/metadata swaps above track 99.
    """
    if track_count < 1:
        raise ValueError("track_count must be positive")
    if first_disc_tracks is not None and not 1 <= first_disc_tracks < track_count:
        raise ValueError("first_disc_tracks must split the release")

    disc_sizes = (
        [track_count]
        if first_disc_tracks is None
        else [first_disc_tracks, track_count - first_disc_tracks]
    )
    media = []
    global_position = 0
    for disc_number, disc_size in enumerate(disc_sizes, start=1):
        tracks = []
        for position in range(1, disc_size + 1):
            global_position += 1
            tracks.append(
                {
                    "number": str(position),
                    "position": position,
                    "title": f"Metadata {global_position:03d}",
                    "artist-credit": [
                        {"name": f"Performer {global_position:03d}"}
                    ],
                }
            )
        media.append({"position": disc_number, "tracks": tracks})

    return {
        "id": f"generated-release-{track_count}",
        "title": f"Generated {track_count}-track release",
        "date": "2026",
        "artist-credit": [{"name": "Boundary Album Artist"}],
        "media": media,
    }
