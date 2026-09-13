import re
import unicodedata
from difflib import SequenceMatcher
from typing import Any, Mapping, Sequence


CLOSE_MATCH_THRESHOLD = 0.82
YOUTUBE_NOISE_SUFFIXES = (
    "official audio",
    "official video",
    "official music video",
    "lyrics",
    "hq",
    "hd",
)
SENSITIVE_MARKERS = (
    "live",
    "demo",
    "remix",
    "acoustic",
    "radio edit",
    "extended",
    "instrumental",
    "remastered",
    "re recorded",
    "mono",
    "stereo",
)


def normalize_track_title(value: str) -> str:
    """Normalize superficial typography without removing musical meaning."""
    normalized = unicodedata.normalize("NFKC", value).casefold()
    characters = []
    for character in normalized:
        if character in {"'", "’", "ʼ"}:
            continue
        if unicodedata.category(character).startswith("P"):
            characters.append(" ")
        else:
            characters.append(character)
    return " ".join("".join(characters).split())


def clean_youtube_title(value: str) -> str:
    normalized = normalize_track_title(value)
    changed = True
    while changed and normalized:
        changed = False
        for suffix in YOUTUBE_NOISE_SUFFIXES:
            if normalized == suffix:
                continue
            if normalized.endswith(f" {suffix}"):
                normalized = normalized[: -(len(suffix) + 1)].strip()
                changed = True
                break
    return normalized


def _version_markers(normalized: str) -> set[str]:
    return {
        marker
        for marker in SENSITIVE_MARKERS
        if re.search(rf"\b{re.escape(marker)}\b", normalized)
    }


def _without_markers(normalized: str, markers: set[str]) -> str:
    for marker in sorted(markers, key=len, reverse=True):
        normalized = re.sub(rf"\b{re.escape(marker)}\b", " ", normalized)
    return " ".join(normalized.split())


def compare_track_titles(youtube_title: str, release_title: str) -> dict[str, Any]:
    youtube_normalized = normalize_track_title(youtube_title)
    release_normalized = normalize_track_title(release_title)
    youtube_clean = clean_youtube_title(youtube_title)
    score = SequenceMatcher(None, youtube_clean, release_normalized).ratio()
    youtube_markers = _version_markers(youtube_normalized)
    release_markers = _version_markers(release_normalized)
    marker_difference = youtube_markers ^ release_markers
    base_score = SequenceMatcher(
        None,
        _without_markers(youtube_clean, youtube_markers),
        _without_markers(release_normalized, release_markers),
    ).ratio()

    if youtube_normalized == release_normalized:
        status = "exact"
        reasons = []
    elif marker_difference and base_score >= CLOSE_MATCH_THRESHOLD:
        status = "warning"
        reasons = [
            f"version_marker:{marker}"
            for marker in sorted(marker_difference)
        ]
    elif youtube_clean == release_normalized:
        status = "clean"
        reasons = ["youtube_decoration"]
    elif score >= CLOSE_MATCH_THRESHOLD:
        status = "close"
        reasons = ["minor_title_difference"]
    else:
        status = "mismatch"
        reasons = ["low_similarity"]
        reasons.extend(
            f"version_marker:{marker}"
            for marker in sorted(marker_difference)
        )

    return {
        "score": round(score, 3),
        "status": status,
        "reasons": reasons,
    }


def compare_tracklists(
    playlist_tracks: Sequence[Mapping[str, Any]],
    release_tracks: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    playlist_count = len(playlist_tracks)
    release_count = len(release_tracks)
    summary = {
        "exact": 0,
        "clean": 0,
        "close": 0,
        "warning": 0,
        "mismatch": 0,
    }
    if playlist_count != release_count:
        return {
            "status": "mismatch",
            "reason": "track_count_mismatch",
            "playlist_count": playlist_count,
            "release_count": release_count,
            "summary": summary,
            "tracks": [],
        }

    playlist_by_position = {
        track["position"]: track
        for track in playlist_tracks
    }
    release_by_position = {
        track["global_position"]: track
        for track in release_tracks
    }
    comparisons = []
    for position in range(1, playlist_count + 1):
        youtube_track = playlist_by_position[position]
        release_track = release_by_position[position]
        comparison = compare_track_titles(
            youtube_track["title"],
            release_track["title"],
        )
        summary[comparison["status"]] += 1
        comparisons.append({
            "position": position,
            "youtube_title": youtube_track["title"],
            "release_title": release_track["title"],
            **comparison,
        })

    if summary["mismatch"]:
        status = "mismatch"
    elif summary["warning"]:
        status = "review"
    elif summary["close"]:
        status = "likely"
    else:
        status = "strong"
    return {
        "status": status,
        "reason": None,
        "playlist_count": playlist_count,
        "release_count": release_count,
        "summary": summary,
        "tracks": comparisons,
    }
