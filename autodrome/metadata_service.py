import os
import tempfile
from typing import Any, Dict, List, Optional
from autodrome.logger import logger
from autodrome.services.redis_cache import NullCache, ReleaseCache
from autodrome.models.track import Track
from autodrome.models.release import Release
from autodrome.http_client_async import AsyncHttpClient, UpstreamServiceError


LUCENE_SPECIAL_CHARACTERS = frozenset('+-&|!(){}[]^"~*?:\\/')


def quote_musicbrainz_field_value(value: str) -> str:
    """Quote one raw field value so Lucene treats it as literal text."""
    escaped = "".join(
        f"\\{character}"
        if character in LUCENE_SPECIAL_CHARACTERS
        else character
        for character in value
    )
    return f'"{escaped}"'


class MetadataService:
    MAX_SEARCH_RESULTS = 50

    def __init__(
        self,
        http_client: AsyncHttpClient,
        redis_cache: Optional[ReleaseCache] = None,
    ):
        self.http_client = http_client
        self.redis_cache = redis_cache if redis_cache is not None else NullCache()
        self.base_dir = os.path.dirname(os.path.abspath(__file__))
        self.cover_dir = os.path.abspath(os.path.join(self.base_dir, '..', 'covers'))

    async def search_releases(
        self,
        artist: Optional[str],
        album: Optional[str],
        limit: int = 10,
        max_tracks: Optional[int] = None,
    ) -> List[Release]:
        self._validate_search_options(limit, max_tracks)
        query = self._build_mb_query(artist, album)
        if not query:
            return []
        candidate_limit = self.MAX_SEARCH_RESULTS if max_tracks is not None else limit
        data = await self._fetch_releases_data(query, candidate_limit)
        releases = self._parse_releases(data, artist)
        if max_tracks is not None:
            releases = [
                release
                for release in releases
                if not self._exceeds_track_limit(release.track_count, max_tracks)
            ]
        return releases[:limit]

    def _cache_release(self, release: Release) -> None:
        cache_data = {
            "id": release.id,
            "title": release.title,
            "date": release.date,
            "artist": release.artist,
            "cover_url": release.cover_url,
            "cover_url_kind": "thumbnail",
            "tracks": [track.to_dict() for track in release.tracks],
        }
        self.redis_cache.set_release(release.id, cache_data)

    async def get_release(self, release_id: str) -> Release:
        """Fetch the metadata required to download a release by its ID."""
        cached = self.redis_cache.get_release(release_id)
        release = self._release_from_cache(release_id, cached)
        if release is not None:
            logger.debug(f"Cache hit for release {release_id}")
            if cached.get("cover_url_kind") == "thumbnail":
                return release
            release.cover_url = await self._get_cover_url(release_id)
            self._cache_release(release)
            return release

        logger.debug(f"Cache miss for release {release_id}")
        url = f"https://musicbrainz.org/ws/2/release/{release_id}"
        params = {"inc": "recordings artist-credits", "fmt": "json"}

        try:
            data = await self.http_client.get(
                url,
                params=params,
                provider="MusicBrainz",
                context=f"loading release {release_id}",
            )
        except UpstreamServiceError:
            raise
        except Exception as e:
            raise RuntimeError(
                f"Could not retrieve release {release_id} from MusicBrainz"
            ) from e

        if (
            not isinstance(data, dict)
            or data.get("id") != release_id
            or not isinstance(data.get("media"), list)
        ):
            raise UpstreamServiceError(
                provider="MusicBrainz",
                context=f"loading release {release_id}",
                reason="invalid response",
            )

        artist_credit = data.get("artist-credit") or []
        if (
            not isinstance(artist_credit, list)
            or not artist_credit
            or not isinstance(artist_credit[0], dict)
        ):
            raise UpstreamServiceError(
                provider="MusicBrainz",
                context=f"loading release {release_id}",
                reason="invalid response",
            )
        tracks = self._parse_tracks(
            data,
            context=f"loading release {release_id}",
        )
        release = Release(
            release_id=release_id,
            title=data.get("title") or "Unknown",
            date=data.get("date") or "Unknown",
            artist=self._artist_credit(artist_credit) or "Unknown",
            cover_url=await self._get_cover_url(release_id),
            tracks=tracks,
        )
        self._cache_release(release)
        return release

    @staticmethod
    def _release_from_cache(
        release_id: str,
        cached: Optional[Dict[str, Any]],
    ) -> Optional[Release]:
        if not isinstance(cached, dict) or cached.get("id") != release_id:
            return None
        if not all(
            isinstance(cached.get(field), str)
            for field in ("title", "date", "artist")
        ) or not isinstance(cached.get("tracks"), list):
            return None
        cover_url = cached.get("cover_url")
        if cover_url is not None and not isinstance(cover_url, str):
            return None
        try:
            tracks = [Track(**track) for track in cached["tracks"]]
        except (TypeError, ValueError):
            return None
        return Release(
            release_id=release_id,
            title=cached["title"],
            date=cached["date"],
            artist=cached["artist"],
            cover_url=cover_url,
            tracks=tracks,
        )

    async def get_cover_art(self, release_id: str) -> Optional[str]:
        path = self.get_cover_path(release_id)
        if os.path.exists(path):
            return os.path.abspath(path)
        try:
            await self._download_cover_art(release_id, path)
        except UpstreamServiceError as e:
            if e.status == 404:
                logger.info(f"Cover Art Archive has no front cover for {release_id}")
                return None
            raise
        return os.path.abspath(path)

    def get_cover_path(self, release_id: str) -> str:
        os.makedirs(self.cover_dir, exist_ok=True)
        return os.path.join(self.cover_dir, f"{release_id}.jpg")

    async def _get_cover_url(self, release_id: str) -> Optional[str]:
        url = f"https://coverartarchive.org/release/{release_id}"
        try:
            data = await self.http_client.get(
                url,
                provider="Cover Art Archive",
                context=f"loading cover metadata for release {release_id}",
            )
        except UpstreamServiceError as e:
            if e.status == 404:
                return None
            raise

        if not isinstance(data, dict) or not isinstance(data.get("images"), list):
            raise UpstreamServiceError(
                provider="Cover Art Archive",
                context=f"loading cover metadata for release {release_id}",
                reason="invalid response",
            )
        for image in data["images"]:
            if not isinstance(image, dict):
                raise UpstreamServiceError(
                    provider="Cover Art Archive",
                    context=f"loading cover metadata for release {release_id}",
                    reason="invalid response",
                )
            if image.get("front", False):
                thumbnails = image.get("thumbnails") or {}
                if not isinstance(thumbnails, dict):
                    raise UpstreamServiceError(
                        provider="Cover Art Archive",
                        context=f"loading cover metadata for release {release_id}",
                        reason="invalid response",
                    )
                return (
                    thumbnails.get("small")
                    or thumbnails.get("250")
                    or thumbnails.get("500")
                )
        return None

    def _build_mb_query(self, artist: Optional[str], album: Optional[str]) -> str:
        terms = []
        album = album.strip() if album else ""
        artist = artist.strip() if artist else ""
        if album:
            terms.append(f"release:{quote_musicbrainz_field_value(album)}")
        if artist:
            terms.append(f"artist:{quote_musicbrainz_field_value(artist)}")
        return " AND ".join(terms)

    async def _fetch_releases_data(
        self, query: str, limit: int = 10
    ) -> Dict[str, Any]:
        url = "https://musicbrainz.org/ws/2/release/"
        params = {"query": query, "fmt": "json", "limit": limit}
        return await self.http_client.get(
            url,
            params=params,
            provider="MusicBrainz",
            context="searching releases",
        )

    def _validate_search_options(
        self,
        limit: int,
        max_tracks: Optional[int],
    ) -> None:
        if (
            not isinstance(limit, int)
            or isinstance(limit, bool)
            or not 1 <= limit <= self.MAX_SEARCH_RESULTS
        ):
            raise ValueError(
                "MusicBrainz result limit must be between 1 and "
                f"{self.MAX_SEARCH_RESULTS}"
            )
        if (
            max_tracks is not None
            and (
                not isinstance(max_tracks, int)
                or isinstance(max_tracks, bool)
                or max_tracks < 1
            )
        ):
            raise ValueError("MusicBrainz maximum tracks must be a positive integer")

    @staticmethod
    def _exceeds_track_limit(track_count, max_tracks: int) -> bool:
        return (
            isinstance(track_count, int)
            and not isinstance(track_count, bool)
            and track_count >= 0
            and track_count > max_tracks
        )

    async def _get_tracks(self, release_id: str) -> List[Track]:
        data = await self._fetch_tracks_data(release_id)
        if not isinstance(data, dict) or not isinstance(data.get("media"), list):
            raise UpstreamServiceError(
                provider="MusicBrainz",
                context=f"loading tracks for release {release_id}",
                reason="invalid response",
            )
        return self._parse_tracks(
            data,
            context=f"loading tracks for release {release_id}",
        )

    async def _fetch_tracks_data(self, release_id: str) -> Dict[str, Any]:
        url = f"https://musicbrainz.org/ws/2/release/{release_id}"
        params = {"inc": "recordings artist-credits", "fmt": "json"}
        return await self.http_client.get(
            url,
            params=params,
            provider="MusicBrainz",
            context=f"loading tracks for release {release_id}",
        )

    @staticmethod
    def _artist_credit(credits) -> Optional[str]:
        if not credits:
            return None
        parts = []
        for credit in credits:
            if isinstance(credit, str):
                parts.append(credit)
            elif isinstance(credit, dict):
                name = credit.get("name") or (credit.get("artist") or {}).get("name")
                if not isinstance(name, str) or not name:
                    raise ValueError("Invalid MusicBrainz artist credit")
                parts.append(name + (credit.get("joinphrase") or ""))
            else:
                raise ValueError("Invalid MusicBrainz artist credit")
        return "".join(parts) or None

    def _parse_tracks(
        self,
        data: Dict[str, Any],
        context: str = "loading tracks",
    ) -> List[Track]:
        tracks = []

        def positive_int(value, fallback):
            try:
                parsed = int(value)
            except (ValueError, TypeError):
                return fallback
            return parsed if parsed > 0 else fallback

        media = data.get("media", [])
        if any(
            not isinstance(medium, dict)
            or not isinstance(medium.get("tracks"), list)
            for medium in media
        ):
            raise UpstreamServiceError(
                provider="MusicBrainz",
                context=context,
                reason="invalid response",
            )

        indexed_media = list(enumerate(media, start=1))
        indexed_media.sort(
            key=lambda item: positive_int(item[1].get("position"), item[0])
        )

        global_position = 0
        for medium_index, medium in indexed_media:
            medium_tracks = medium["tracks"]
            if any(not isinstance(track, dict) for track in medium_tracks):
                raise UpstreamServiceError(
                    provider="MusicBrainz",
                    context=context,
                    reason="invalid response",
                )
            disc_number = positive_int(medium.get("position"), medium_index)
            indexed_tracks = list(enumerate(medium_tracks, start=1))
            indexed_tracks.sort(
                key=lambda item: positive_int(item[1].get("position"), item[0])
            )
            for track_index, track_data in indexed_tracks:
                position = positive_int(track_data.get("position"), track_index)
                number_value = str(track_data.get("number", "")).split(".")[0]
                number = positive_int(number_value, position)
                global_position += 1
                tracks.append(
                    Track(
                        artist=(self._artist_credit(track_data.get("artist-credit"))
                                or self._artist_credit((track_data.get("recording") or {}).get("artist-credit"))),
                        number=number,
                        title=track_data.get("title", "Unknown"),
                        disc_number=disc_number,
                        position=position,
                        global_position=global_position,
                    )
                )

        return tracks

    def _parse_releases(self, data: Dict[str, Any], artist: Optional[str]) -> List[Release]:
        
        if not isinstance(data, dict) or not isinstance(data.get("releases"), list):
            raise UpstreamServiceError(
                provider="MusicBrainz",
                context="searching releases",
                reason="invalid response",
            )
        
        releases = []
        for r in data.get("releases", []):
            if not isinstance(r, dict) or not isinstance(r.get("id"), str):
                raise UpstreamServiceError(
                    provider="MusicBrainz",
                    context="searching releases",
                    reason="invalid response",
                )
            release_id = r["id"]
            artist_credit = r.get("artist-credit") or []
            if (
                not isinstance(artist_credit, list)
                or not artist_credit
                or not isinstance(artist_credit[0], dict)
            ):
                raise UpstreamServiceError(
                    provider="MusicBrainz",
                    context="searching releases",
                    reason="invalid response",
                )
            cover_art = r.get("cover-art-archive")
            cover_url = None
            if isinstance(cover_art, dict) and cover_art.get("front") is True:
                cover_url = (
                    f"https://coverartarchive.org/release/{release_id}/front-250"
                )
            releases.append(
                Release(
                    release_id=release_id,
                    title=r.get("title") or "Unknown",
                    date=r.get("date") or "Unknown",
                    cover_url=cover_url,
                    artist=self._artist_credit(artist_credit) or artist or "Unknown",
                    tracks=[],
                    track_count=self._parse_search_track_count(
                        r.get("track-count")
                    ),
                )
            )
        return releases

    @staticmethod
    def _parse_search_track_count(value: Any) -> Optional[int]:
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            return None
        return value



    async def _download_cover_art(self, release_id: str, path: str) -> bool:
        url = f"https://coverartarchive.org/release/{release_id}/front"
        content = await self.http_client.get_binary(
            url,
            provider="Cover Art Archive",
            context=f"downloading front cover for release {release_id}",
        )
        directory = os.path.dirname(path)
        os.makedirs(directory, exist_ok=True)
        descriptor, temp_path = tempfile.mkstemp(
            prefix=".autodrome-cover-",
            suffix=".tmp",
            dir=directory,
        )
        try:
            with os.fdopen(descriptor, "wb") as cover_file:
                cover_file.write(content)
                cover_file.flush()
                os.fsync(cover_file.fileno())
            os.replace(temp_path, path)
        except Exception:
            if os.path.exists(temp_path):
                os.unlink(temp_path)
            raise
        logger.debug(f"Cover art saved to {path}")
        return True
