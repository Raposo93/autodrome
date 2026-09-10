"""Reusable adversarial fixtures for backend and frontend tests."""

from .adversarial import (
    complex_release_fixture,
    generated_musicbrainz_release,
    generated_playlist,
    playlist_from_hell,
)

__all__ = [
    "complex_release_fixture",
    "generated_musicbrainz_release",
    "generated_playlist",
    "playlist_from_hell",
]
