import os
import stat
import tempfile
import time
from itertools import islice
from pathlib import Path
from typing import Callable, Iterable, Optional
from uuid import UUID, uuid4

from autodrome import config
from autodrome.logger import logger
from autodrome.services.cover_embedder import (
    CoverEmbedder,
    CoverPreparationError,
    PreparedCover,
)
from autodrome.url_safety import validate_youtube_thumbnail_url


conf = config.Config()


class CoverSelectionError(ValueError):
    pass


class CoverSelectionService:
    ALLOWED_MIME_TYPES = {"image/jpeg", "image/png", "image/webp"}
    DEFAULT_ORPHAN_TTL_SECONDS = 24 * 60 * 60
    MAX_CLEANUP_ENTRIES = 256

    def __init__(
        self,
        *,
        http_client,
        embedder: CoverEmbedder,
        storage_dir: Optional[str] = None,
        max_upload_bytes: Optional[int] = None,
        orphan_ttl_seconds: int = DEFAULT_ORPHAN_TTL_SECONDS,
        clock: Callable[[], float] = time.time,
    ) -> None:
        if orphan_ttl_seconds < 0:
            raise ValueError("Selected cover orphan TTL cannot be negative")
        self.http_client = http_client
        self.embedder = embedder
        self.storage_dir = Path(
            storage_dir or conf.cover_storage_path
        ).resolve()
        self.max_upload_bytes = (
            conf.max_cover_upload_bytes
            if max_upload_bytes is None
            else max_upload_bytes
        )
        self.orphan_ttl_seconds = orphan_ttl_seconds
        self._clock = clock
        self._protected_cover_ids: Callable[[], set[str]] = set

    def set_protected_cover_ids_provider(
        self,
        provider: Callable[[], set[str]],
    ) -> None:
        self._protected_cover_ids = provider

    def cleanup_expired(
        self,
        protected_cover_ids: Optional[Iterable[str]] = None,
    ) -> int:
        protected = self._normalize_cover_ids(
            self._protected_cover_ids()
            if protected_cover_ids is None
            else protected_cover_ids
        )
        cutoff = self._clock() - self.orphan_ttl_seconds
        removed = 0
        try:
            entries = os.scandir(self.storage_dir)
        except FileNotFoundError:
            return 0
        except OSError as error:
            logger.warning(f"Could not scan prepared covers for cleanup: {error}")
            return 0

        with entries:
            for entry in islice(entries, self.MAX_CLEANUP_ENTRIES):
                cover_id = self._cover_id_from_filename(entry.name)
                if cover_id is None or cover_id in protected:
                    continue
                try:
                    file_stat = entry.stat(follow_symlinks=False)
                    if (
                        not stat.S_ISREG(file_stat.st_mode)
                        or file_stat.st_mtime > cutoff
                    ):
                        continue
                    os.unlink(entry.path)
                    removed += 1
                except OSError as error:
                    logger.warning(
                        f"Could not remove expired prepared cover {cover_id}: {error}"
                    )
        return removed

    def delete_unreferenced(
        self,
        cover_ids: Iterable[str],
        protected_cover_ids: Iterable[str],
    ) -> int:
        protected = self._normalize_cover_ids(protected_cover_ids)
        removed = 0
        for cover_id in self._normalize_cover_ids(cover_ids) - protected:
            path = self._cover_path(cover_id)
            try:
                file_stat = os.lstat(path)
                if not stat.S_ISREG(file_stat.st_mode):
                    continue
                os.unlink(path)
                removed += 1
            except FileNotFoundError:
                continue
            except OSError as error:
                logger.warning(
                    f"Could not remove unused prepared cover {cover_id}: {error}"
                )
        return removed

    def store_manual(self, content: bytes) -> dict:
        return self._store(content, square=False)

    async def store_youtube(self, thumbnail_url: str) -> dict:
        validate_youtube_thumbnail_url(thumbnail_url)
        content = await self.http_client.get_binary(
            thumbnail_url,
            timeout=10,
            provider="YouTube",
            context="downloading the selected playlist thumbnail",
            allow_redirects=False,
        )
        return self._store(content, square=True)

    def load_prepared(self, cover_id: str) -> PreparedCover:
        path = self._cover_path(cover_id)
        try:
            file_stat = os.lstat(path)
        except OSError as error:
            raise CoverSelectionError(
                "The selected cover is no longer available; choose it again."
            ) from error
        if not stat.S_ISREG(file_stat.st_mode):
            raise CoverSelectionError(
                "The selected cover is no longer available; choose it again."
            )
        try:
            return self.embedder.prepare_cover(
                str(path),
                allowed_mime_types=self.ALLOWED_MIME_TYPES,
            )
        except CoverPreparationError as error:
            raise CoverSelectionError(self._safe_preparation_error(error)) from error

    def _store(self, content: bytes, *, square: bool) -> dict:
        if not content:
            raise CoverSelectionError("Cover image is empty.")
        if len(content) > self.max_upload_bytes:
            raise CoverSelectionError(
                f"Cover image exceeds the upload limit of {self.max_upload_bytes} bytes."
            )

        self.cleanup_expired()
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        descriptor, temporary_path = tempfile.mkstemp(
            prefix=".autodrome-cover-",
            suffix=".upload",
            dir=self.storage_dir,
        )
        cover_id = str(uuid4())
        final_path = self._cover_path(cover_id)
        try:
            with os.fdopen(descriptor, "wb") as temporary_file:
                temporary_file.write(content)
                temporary_file.flush()
                os.fsync(temporary_file.fileno())
            try:
                if square:
                    prepared = self.embedder.prepare_square_cover(
                        temporary_path,
                        allowed_mime_types=self.ALLOWED_MIME_TYPES,
                    )
                else:
                    prepared = self.embedder.prepare_cover(
                        temporary_path,
                        allowed_mime_types=self.ALLOWED_MIME_TYPES,
                    )
            except CoverPreparationError as error:
                raise CoverSelectionError(
                    self._safe_preparation_error(error)
                ) from error

            with open(temporary_path, "wb") as temporary_file:
                temporary_file.write(prepared.data)
                temporary_file.flush()
                os.fsync(temporary_file.fileno())
            os.replace(temporary_path, final_path)
        except Exception:
            if os.path.exists(temporary_path):
                os.unlink(temporary_path)
            raise

        return {
            "cover_id": cover_id,
            "mime_type": prepared.mime_type,
            "size": prepared.final_size,
            "width": prepared.dimensions[0],
            "height": prepared.dimensions[1],
        }

    def _cover_path(self, cover_id: str) -> Path:
        try:
            normalized_id = str(UUID(str(cover_id)))
        except (TypeError, ValueError) as error:
            raise CoverSelectionError("Invalid selected cover identifier.") from error
        return self.storage_dir / f"{normalized_id}.cover"

    @staticmethod
    def _cover_id_from_filename(filename: str) -> Optional[str]:
        if not filename.endswith(".cover"):
            return None
        candidate = filename[:-len(".cover")]
        try:
            normalized = str(UUID(candidate))
        except ValueError:
            return None
        return normalized if candidate == normalized else None

    @staticmethod
    def _normalize_cover_ids(cover_ids: Iterable[str]) -> set[str]:
        normalized = set()
        for cover_id in cover_ids:
            try:
                normalized.add(str(UUID(str(cover_id))))
            except (TypeError, ValueError):
                continue
        return normalized

    @staticmethod
    def _safe_preparation_error(error: CoverPreparationError) -> str:
        message = str(error)
        if "safe decoding limit" in message:
            return "Cover image exceeds the safe pixel limit."
        if "unsupported format" in message:
            return "Cover image must be a valid JPEG, PNG, or WebP file."
        if "damaged or unsupported" in message:
            return "Cover image is damaged or unsupported."
        if "could not be optimized" in message or "requires optimization" in message:
            return "Cover image cannot meet the configured size and dimension limits."
        return "Cover image could not be prepared safely."
