from typing import Annotated, Optional
from urllib.parse import parse_qs, urlsplit
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator, model_validator

from autodrome.path_safety import validate_path_component


NonEmptyText = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=255),
]


class DownloadRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    playlist_url: str
    artist: NonEmptyText
    album: NonEmptyText
    release_id: UUID
    track_count: Optional[int] = Field(default=None, ge=0, le=10_000)

    @field_validator("artist", "album")
    @classmethod
    def validate_path_fields(cls, value: str) -> str:
        return validate_path_component(value)

    @field_validator("playlist_url")
    @classmethod
    def validate_playlist_url(cls, value: str) -> str:
        try:
            parsed = urlsplit(value)
            port = parsed.port
        except ValueError as e:
            raise ValueError("Invalid playlist URL") from e

        if parsed.scheme != "https":
            raise ValueError("Playlist URL must use HTTPS")
        if parsed.username or parsed.password:
            raise ValueError("Playlist URL cannot contain credentials")
        if parsed.hostname not in {
            "youtube.com",
            "www.youtube.com",
            "music.youtube.com",
        }:
            raise ValueError("Playlist URL must use an allowed YouTube host")
        if port not in {None, 443}:
            raise ValueError("Playlist URL cannot use a custom port")
        if parsed.path.rstrip("/") != "/playlist":
            raise ValueError("Playlist URL must point to the YouTube playlist path")

        playlist_ids = parse_qs(parsed.query).get("list", [])
        if len(playlist_ids) != 1:
            raise ValueError("Playlist URL must contain one playlist identifier")
        playlist_id = playlist_ids[0]
        if not 10 <= len(playlist_id) <= 128 or not all(
            character.isalnum() or character in {"-", "_"}
            for character in playlist_id
        ):
            raise ValueError("Playlist URL contains an invalid playlist identifier")

        return value


class SearchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artist: Optional[NonEmptyText] = None
    album: Optional[NonEmptyText] = None

    @model_validator(mode="after")
    def require_search_term(self) -> "SearchRequest":
        if self.artist is None and self.album is None:
            raise ValueError("At least one of artist or album is required")
        return self
