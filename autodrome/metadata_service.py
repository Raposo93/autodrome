import asyncio
import os
import tempfile
from typing import Any, Dict, List, Optional
from autodrome.logger import logger
from autodrome.services.redis_cache import RedisCache
from autodrome.models.track import Track
from autodrome.models.release import Release
from autodrome.http_client_async import AsyncHttpClient, UpstreamServiceError

class MetadataService:
    def __init__(self, http_client: AsyncHttpClient):
        self.http_client = http_client
        self.redis_cache = RedisCache()
        self.base_dir = os.path.dirname(os.path.abspath(__file__))
        self.cover_dir = os.path.abspath(os.path.join(self.base_dir, '..', 'covers'))

    async def search_releases(self, artist: Optional[str], album: Optional[str]) -> List[Release]:
        query = self._build_mb_query(artist, album)
        data = await self._fetch_releases_data(query)
        releases = self._parse_releases(data, artist)

        await asyncio.gather(*(self._enrich_release(release) for release in releases))

        return releases

    async def _enrich_release(self, release: Release) -> None:
        try:
            cached = self.redis_cache.get_release(release.id)
        except Exception as e:
            logger.warning(f"Could not read release {release.id} from cache: {e}")
            cached = None

        if cached:
            logger.debug(f"Cache hit for release {release.id}")
            release.tracks = [Track(**track) for track in cached.get("tracks", [])]
            if cached.get("cover_url_kind") == "thumbnail":
                release.cover_url = cached.get("cover_url")
                return
            release.cover_url = await self._get_cover_url(release.id)
            self._cache_release(release)
            return

        logger.debug(f"Cache miss for release {release.id}")
        release.tracks, release.cover_url = await asyncio.gather(
            self._get_tracks(release.id),
            self._get_cover_url(release.id),
        )
        self._cache_release(release)

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
        try:
            self.redis_cache.set_release(release.id, cache_data)
        except Exception as e:
            logger.warning(f"Could not cache release {release.id}: {e}")

    async def get_release(self, release_id: str) -> Release:
        """Fetch the metadata required to download a release by its ID."""
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

        artist_credit = data.get("artist-credit") or [{}]
        return Release(
            release_id=release_id,
            title=data.get("title", "Unknown"),
            date=data.get("date", "Unknown"),
            artist=artist_credit[0].get("name", "Unknown"),
            cover_url=None,
            tracks=self._parse_tracks(
                data,
                context=f"loading release {release_id}",
            ),
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
        if album:
            terms.append(f"release:{album}")
        if artist:
            terms.append(f"artist:{artist}")
        return " AND ".join(terms)

    async def _fetch_releases_data(self, query:str) -> Dict[str, Any]:
        url = "https://musicbrainz.org/ws/2/release/"
        params = {"query": query, "fmt": "json", "limit": 10}
        return await self.http_client.get(
            url,
            params=params,
            provider="MusicBrainz",
            context="searching releases",
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
        params = {"inc": "recordings", "fmt": "json"}
        return await self.http_client.get(
            url,
            params=params,
            provider="MusicBrainz",
            context=f"loading tracks for release {release_id}",
        )

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
            releases.append(
                Release(
                    release_id=release_id,
                    title=r.get("title", "Unknown"),
                    date=r.get("date", "Unknown"),
                    cover_url=None,
                    artist=r.get("artist-credit", [{}])[0].get("name", artist),
                    tracks=[]
                )
            )
        return releases



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
