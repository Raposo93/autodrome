from typing import Annotated, List, Optional, Literal
from urllib.parse import parse_qs, urlencode, urlsplit, urlunsplit
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator, model_validator

from autodrome.path_safety import validate_path_component
from autodrome.url_safety import validate_youtube_thumbnail_url


NonEmptyText = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=255),
]
TrackTitle = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=1000),
]
CoverSource = Literal[
    "cover_art_archive",
    "youtube_thumbnail",
    "manual_upload",
    "none",
]
CoverSquareMode = Literal["fit", "crop"]


class DownloadRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    playlist_url: str
    playlist_id: Optional[NonEmptyText] = None
    playlist_title: Optional[TrackTitle] = None
    playlist_channel: Optional[NonEmptyText] = None
    playlist_thumbnail: Optional[str] = None
    artist: NonEmptyText
    album: NonEmptyText
    release_id: Optional[UUID] = None
    metadata_mode: Literal["musicbrainz", "manual"] = "musicbrainz"
    manual_confirmed: bool = False
    track_count: Optional[int] = Field(default=None, ge=0, le=10_000)
    cover_source: Optional[CoverSource] = None
    cover_id: Optional[UUID] = None
    cover_url: Optional[str] = None
    cover_square_mode: Optional[CoverSquareMode] = None

    @model_validator(mode="after")
    def validate_metadata_mode(self):
        playlist_ids = parse_qs(urlsplit(self.playlist_url).query).get("list", [])
        if len(playlist_ids) == 1:
            if self.playlist_id is not None and self.playlist_id != playlist_ids[0]:
                raise ValueError("Playlist identifier does not match its URL")
            self.playlist_id = playlist_ids[0]
        if self.metadata_mode == "manual":
            if self.release_id is not None or not self.manual_confirmed:
                raise ValueError("Manual metadata requires confirmation and no MusicBrainz release")
            if self.cover_source not in {None, "none"}:
                raise ValueError("Manual metadata currently requires no cover")
            self.cover_source = "none"
        elif self.release_id is None or self.manual_confirmed:
            raise ValueError("MusicBrainz mode requires a release")

        if self.cover_source is None:
            self.cover_source = "cover_art_archive"
        if self.cover_source == "cover_art_archive":
            if (
                self.cover_id is not None
                or self.cover_url is not None
                or self.cover_square_mode is not None
            ):
                raise ValueError("Cover Art Archive selection cannot include an alternative cover")
        elif self.cover_source == "youtube_thumbnail":
            if self.cover_id is None or self.cover_url is None:
                raise ValueError("YouTube cover selection requires its prepared image and URL")
            validate_youtube_thumbnail_url(self.cover_url)
            self.cover_square_mode = self.cover_square_mode or "fit"
        elif self.cover_source == "manual_upload":
            if self.cover_id is None or self.cover_url is not None:
                raise ValueError("Manual cover selection requires its prepared image only")
            self.cover_square_mode = self.cover_square_mode or "fit"
        elif (
            self.cover_id is not None
            or self.cover_url is not None
            or self.cover_square_mode is not None
        ):
            raise ValueError("No-cover selection cannot include an image")
        return self

    @field_validator("playlist_thumbnail")
    @classmethod
    def validate_playlist_thumbnail(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        return validate_youtube_thumbnail_url(value)

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

        return urlunsplit(
            (
                "https",
                "www.youtube.com",
                "/playlist",
                urlencode({"list": playlist_id}),
                "",
            )
        )


class PlaylistPreflightRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    playlist_url: str
    track_count: Optional[int] = Field(default=None, ge=0, le=10_000)

    validate_playlist_url = field_validator("playlist_url")(DownloadRequest.validate_playlist_url.__func__)


class AlbumDestinationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artist: NonEmptyText
    album: NonEmptyText

    validate_path_fields = field_validator("artist", "album")(
        DownloadRequest.validate_path_fields.__func__
    )


class YoutubeCoverRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    thumbnail_url: str
    square_mode: CoverSquareMode = "fit"

    @field_validator("thumbnail_url")
    @classmethod
    def validate_thumbnail_url(cls, value: str) -> str:
        return validate_youtube_thumbnail_url(value)


class PlaylistMatchTrack(BaseModel):
    model_config = ConfigDict(extra="forbid")

    position: int = Field(ge=1, le=10_000)
    title: TrackTitle
    duration_seconds: Optional[float] = Field(default=None, gt=0, le=86_400)


class ReleaseMatchTrack(BaseModel):
    model_config = ConfigDict(extra="forbid")

    global_position: int = Field(ge=1, le=10_000)
    title: TrackTitle
    duration_seconds: Optional[float] = Field(default=None, gt=0, le=86_400)


class TrackCompatibilityRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    playlist_tracks: List[PlaylistMatchTrack] = Field(
        min_length=1,
        max_length=1000,
    )
    release_tracks: List[ReleaseMatchTrack] = Field(
        min_length=1,
        max_length=1000,
    )
    artist: Optional[NonEmptyText] = None

    @model_validator(mode="after")
    def require_contiguous_positions(self) -> "TrackCompatibilityRequest":
        playlist_positions = {track.position for track in self.playlist_tracks}
        release_positions = {
            track.global_position for track in self.release_tracks
        }
        if playlist_positions != set(range(1, len(self.playlist_tracks) + 1)):
            raise ValueError("Playlist positions must be unique and contiguous")
        if release_positions != set(range(1, len(self.release_tracks) + 1)):
            raise ValueError("Release positions must be unique and contiguous")
        return self


class SearchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artist: Optional[NonEmptyText] = None
    album: Optional[NonEmptyText] = None
    result_limit: Optional[int] = Field(default=None, ge=1, le=50)
    max_tracks: Optional[int] = Field(default=None, ge=1)
    youtube_limit: Optional[int] = Field(default=None, ge=1, le=50)
    youtube_max_tracks: Optional[int] = Field(default=None, ge=1)

    @model_validator(mode="after")
    def require_search_term(self) -> "SearchRequest":
        if self.artist is None and self.album is None:
            raise ValueError("At least one of artist or album is required")
        if self.youtube_limit is not None:
            if (
                self.result_limit is not None
                and self.result_limit != self.youtube_limit
            ):
                raise ValueError("Conflicting result limits")
            self.result_limit = self.youtube_limit
        elif self.result_limit is None:
            self.result_limit = 10
        if self.youtube_max_tracks is not None:
            if (
                self.max_tracks is not None
                and self.max_tracks != self.youtube_max_tracks
            ):
                raise ValueError("Conflicting maximum-track filters")
            self.max_tracks = self.youtube_max_tracks
        return self
