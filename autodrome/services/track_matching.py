import re
import unicodedata
from difflib import SequenceMatcher
from typing import Any, Mapping, Sequence


CLOSE_MATCH_THRESHOLD = 0.82
DURATION_ABSOLUTE_TOLERANCE_SECONDS = 30
DURATION_RELATIVE_TOLERANCE = 0.35
ARTIST_PREFIX_SEPARATOR = re.compile(r"[-:|\u2013\u2014]")
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


def _without_artist_prefix(value: str, artist: str | None) -> tuple[str, bool]:
    if not artist:
        return value, False

    normalized_artist = normalize_track_title(artist)
    for separator in ARTIST_PREFIX_SEPARATOR.finditer(value):
        prefix = value[:separator.start()]
        suffix = value[separator.end():].strip()
        if suffix and normalize_track_title(prefix) == normalized_artist:
            return suffix, True
    return value, False


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


def _durations_are_incompatible(
    youtube_duration_seconds: float | None,
    release_duration_seconds: float | None,
) -> bool:
    if youtube_duration_seconds is None or release_duration_seconds is None:
        return False
    tolerance = max(
        DURATION_ABSOLUTE_TOLERANCE_SECONDS,
        release_duration_seconds * DURATION_RELATIVE_TOLERANCE,
    )
    return abs(youtube_duration_seconds - release_duration_seconds) > tolerance


def compare_track_titles(
    youtube_title: str,
    release_title: str,
    *,
    artist: str | None = None,
    youtube_duration_seconds: float | None = None,
    release_duration_seconds: float | None = None,
) -> dict[str, Any]:
    youtube_normalized = normalize_track_title(youtube_title)
    release_normalized = normalize_track_title(release_title)
    title_without_artist, artist_prefix_removed = _without_artist_prefix(
        youtube_title,
        artist,
    )
    youtube_comparison_normalized = normalize_track_title(title_without_artist)
    youtube_clean = clean_youtube_title(title_without_artist)
    score = SequenceMatcher(None, youtube_clean, release_normalized).ratio()
    youtube_markers = _version_markers(youtube_comparison_normalized)
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
        reasons = []
        if artist_prefix_removed:
            reasons.append("artist_prefix")
        if youtube_clean != youtube_comparison_normalized:
            reasons.append("youtube_decoration")
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

    if artist_prefix_removed and "artist_prefix" not in reasons:
        reasons.insert(0, "artist_prefix")

    if _durations_are_incompatible(
        youtube_duration_seconds,
        release_duration_seconds,
    ):
        status = "mismatch"
        reasons.append("duration_mismatch")

    return {
        "score": round(score, 3),
        "status": status,
        "reasons": reasons,
    }


def compare_tracklists(
    playlist_tracks: Sequence[Mapping[str, Any]],
    release_tracks: Sequence[Mapping[str, Any]],
    *,
    artist: str | None = None,
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
            artist=artist,
            youtube_duration_seconds=youtube_track.get("duration_seconds"),
            release_duration_seconds=release_track.get("duration_seconds"),
        )
        summary[comparison["status"]] += 1
        comparisons.append({
            "position": position,
            "youtube_title": youtube_track["title"],
            "release_title": release_track["title"],
            "youtube_duration_seconds": youtube_track.get("duration_seconds"),
            "release_duration_seconds": release_track.get("duration_seconds"),
            **comparison,
        })

    if summary["mismatch"]:
        verified = sum(
            summary[key]
            for key in ("exact", "clean", "close", "warning")
        )
        status = "review" if verified > summary["mismatch"] else "mismatch"
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
