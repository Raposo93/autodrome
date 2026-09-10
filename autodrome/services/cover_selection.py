import os
import stat
import tempfile
from pathlib import Path
from typing import Optional
from uuid import UUID, uuid4

from autodrome import config
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

    def __init__(
        self,
        *,
        http_client,
        embedder: CoverEmbedder,
        storage_dir: Optional[str] = None,
        max_upload_bytes: Optional[int] = None,
    ) -> None:
        self.http_client = http_client
        self.embedder = embedder
        self.storage_dir = Path(
            storage_dir or Path(__file__).resolve().parents[2] / "covers" / "selected"
        ).resolve()
        self.max_upload_bytes = (
            conf.max_cover_upload_bytes
            if max_upload_bytes is None
            else max_upload_bytes
        )

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
