from dataclasses import dataclass
from io import BytesIO
import os
from typing import AbstractSet, Optional, Tuple

from PIL import Image, ImageOps
from mutagen.id3 import APIC, ID3, error
from mutagen.mp3 import MP3

from autodrome import config
from autodrome.logger import logger


conf = config.Config()


class CoverPreparationError(ValueError):
    pass


@dataclass(frozen=True)
class PreparedCover:
    data: bytes
    mime_type: str
    original_size: int
    dimensions: Tuple[int, int]
    optimized: bool

    @property
    def final_size(self) -> int:
        return len(self.data)


class CoverEmbedder:
    def __init__(
        self,
        max_bytes: Optional[int] = None,
        auto_optimize: Optional[bool] = None,
        max_width: Optional[int] = None,
        max_height: Optional[int] = None,
        max_source_pixels: Optional[int] = None,
    ) -> None:
        self.max_bytes = (
            conf.max_embedded_cover_bytes if max_bytes is None else max_bytes
        )
        self.auto_optimize = (
            conf.optimize_oversized_covers
            if auto_optimize is None
            else auto_optimize
        )
        self.max_width = (
            conf.max_embedded_cover_width if max_width is None else max_width
        )
        self.max_height = (
            conf.max_embedded_cover_height if max_height is None else max_height
        )
        self.max_source_pixels = (
            conf.max_cover_source_pixels
            if max_source_pixels is None
            else max_source_pixels
        )

    def prepare_cover(
        self,
        cover_image_path: str,
        *,
        allowed_mime_types: Optional[AbstractSet[str]] = None,
    ) -> PreparedCover:
        mime_type, width, height = self._inspect_cover(
            cover_image_path,
            allowed_mime_types=allowed_mime_types,
        )
        try:
            with open(cover_image_path, "rb") as image_file:
                original_data = image_file.read()
        except OSError as e:
            raise CoverPreparationError(
                f"Could not read cover image: {cover_image_path}"
            ) from e

        original_size = len(original_data)
        requires_optimization = (
            original_size > self.max_bytes
            or width > self.max_width
            or height > self.max_height
        )
        if not requires_optimization:
            prepared = PreparedCover(
                data=original_data,
                mime_type=mime_type,
                original_size=original_size,
                dimensions=(width, height),
                optimized=False,
            )
            self._log_prepared(prepared)
            return prepared

        if not self.auto_optimize:
            raise CoverPreparationError(
                "Cover image requires optimization but automatic optimization is "
                f"disabled: size {original_size} bytes, dimensions {width}x{height}, "
                f"limit {self.max_bytes} bytes and "
                f"{self.max_width}x{self.max_height}; replace the cover manually "
                "before retrying"
            )

        prepared = self._optimize_cover(cover_image_path, original_size)
        self._log_prepared(prepared)
        return prepared

    def prepare_square_cover(
        self,
        cover_image_path: str,
        *,
        allowed_mime_types: Optional[AbstractSet[str]] = None,
    ) -> PreparedCover:
        """Center an image on deterministic square padding without cropping it."""
        self._inspect_cover(
            cover_image_path,
            allowed_mime_types=allowed_mime_types,
        )
        try:
            original_size = os.path.getsize(cover_image_path)
            with Image.open(cover_image_path) as source:
                oriented = ImageOps.exif_transpose(source)
                oriented.load()
                image = self._to_rgb(oriented)
        except OSError as e:
            raise CoverPreparationError(
                f"Could not read cover image: {cover_image_path}"
            ) from e
        except Exception as e:
            raise CoverPreparationError(
                f"Cover image is damaged or unsupported: {cover_image_path}"
            ) from e

        side = min(max(image.size), self.max_width, self.max_height)
        image.thumbnail((side, side), Image.Resampling.LANCZOS)
        square = Image.new("RGB", (side, side), (27, 39, 43))
        offset = ((side - image.width) // 2, (side - image.height) // 2)
        square.paste(image, offset)
        prepared = self._encode_to_limits(square, original_size)
        self._log_prepared(prepared)
        return prepared

    def embed_cover(self, mp3_file_path: str, cover: PreparedCover) -> None:
        if cover.final_size > self.max_bytes:
            raise CoverPreparationError(
                "Prepared cover exceeds the embedding limit: "
                f"size {cover.final_size} bytes, limit {self.max_bytes} bytes"
            )

        audio = MP3(mp3_file_path, ID3=ID3)

        try:
            audio.add_tags()
        except error:
            pass

        audio.tags.add(
            APIC(
                encoding=3,
                mime=cover.mime_type,
                type=3,
                desc="Cover",
                data=cover.data,
            )
        )
        audio.save()

    def _optimize_cover(
        self, cover_image_path: str, original_size: int
    ) -> PreparedCover:
        try:
            with Image.open(cover_image_path) as source:
                icc_profile = source.info.get("icc_profile")
                if icc_profile and len(icc_profile) > 256 * 1024:
                    icc_profile = None
                oriented = ImageOps.exif_transpose(source)
                oriented.load()
                image = self._to_rgb(oriented)
        except Exception as e:
            raise CoverPreparationError(
                f"Could not optimize cover image: {cover_image_path}"
            ) from e

        return self._encode_to_limits(image, original_size, icc_profile)

    def _encode_to_limits(
        self,
        image: Image.Image,
        original_size: int,
        icc_profile: Optional[bytes] = None,
    ) -> PreparedCover:
        image.thumbnail((self.max_width, self.max_height), Image.Resampling.LANCZOS)
        while True:
            for quality in (88, 82, 76, 70, 64, 58):
                output = BytesIO()
                save_options = {
                    "format": "JPEG",
                    "quality": quality,
                    "optimize": True,
                    "progressive": True,
                }
                if icc_profile:
                    save_options["icc_profile"] = icc_profile
                image.save(output, **save_options)
                data = output.getvalue()
                if len(data) <= self.max_bytes:
                    return PreparedCover(
                        data=data,
                        mime_type="image/jpeg",
                        original_size=original_size,
                        dimensions=image.size,
                        optimized=True,
                    )

            width, height = image.size
            if max(width, height) <= 256:
                break
            next_size = (
                max(1, int(width * 0.8)),
                max(1, int(height * 0.8)),
            )
            image = image.resize(next_size, Image.Resampling.LANCZOS)

        raise CoverPreparationError(
            "Cover image could not be optimized below the embedding limit: "
            f"original size {original_size} bytes, limit {self.max_bytes} bytes; "
            "replace the cover manually before retrying"
        )

    def _inspect_cover(
        self,
        cover_image_path: str,
        *,
        allowed_mime_types: Optional[AbstractSet[str]] = None,
    ) -> Tuple[str, int, int]:
        try:
            with Image.open(cover_image_path) as image:
                image_format = image.format
                mime_type = Image.MIME.get(image_format or "")
                width, height = image.size
                source_pixels = width * height
                if (
                    width <= 0
                    or height <= 0
                    or not mime_type
                    or not mime_type.startswith("image/")
                    or (
                        allowed_mime_types is not None
                        and mime_type not in allowed_mime_types
                    )
                ):
                    raise CoverPreparationError(
                        f"Cover image has an unsupported format: {cover_image_path}"
                    )
                if source_pixels > self.max_source_pixels:
                    raise CoverPreparationError(
                        "Cover image exceeds the safe decoding limit: "
                        f"{width}x{height} ({source_pixels} pixels), limit "
                        f"{self.max_source_pixels} pixels"
                    )
                image.verify()
        except CoverPreparationError:
            raise
        except Exception as e:
            raise CoverPreparationError(
                f"Cover image is damaged or unsupported: {cover_image_path}"
            ) from e
        return mime_type, width, height

    @staticmethod
    def _to_rgb(image: Image.Image) -> Image.Image:
        if image.mode in {"RGBA", "LA"} or "transparency" in image.info:
            rgba = image.convert("RGBA")
            background = Image.new("RGB", rgba.size, "white")
            background.paste(rgba, mask=rgba.getchannel("A"))
            return background
        return image.convert("RGB")

    def _log_prepared(self, cover: PreparedCover) -> None:
        log = logger.info if cover.optimized else logger.debug
        log(
            "cover_%s original_bytes=%s final_bytes=%s limit_bytes=%s "
            "mime=%s dimensions=%sx%s",
            "optimized" if cover.optimized else "prepared",
            cover.original_size,
            cover.final_size,
            self.max_bytes,
            cover.mime_type,
            cover.dimensions[0],
            cover.dimensions[1],
        )
