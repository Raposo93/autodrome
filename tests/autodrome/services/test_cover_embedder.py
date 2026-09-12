from io import BytesIO
from unittest import mock

import pytest
from PIL import Image
from mutagen.id3 import error

from autodrome.services.cover_embedder import (
    CoverEmbedder,
    CoverPreparationError,
    PreparedCover,
)


def save_image(path, image_format, size=(64, 64), color="navy"):
    Image.new("RGB", size, color).save(path, format=image_format)


@mock.patch("autodrome.services.cover_embedder.logger.debug")
def test_prepare_cover_preserves_valid_image_and_detects_real_mime(
    log_info, tmp_path
):
    cover_path = tmp_path / "cover.data"
    save_image(cover_path, "PNG")
    original = cover_path.read_bytes()
    embedder = CoverEmbedder(max_bytes=10_000)

    prepared = embedder.prepare_cover(str(cover_path))

    assert prepared.data == original
    assert prepared.mime_type == "image/png"
    assert prepared.dimensions == (64, 64)
    assert prepared.original_size == len(original)
    assert prepared.optimized is False
    assert log_info.call_args.args == (
        "cover_%s original_bytes=%s final_bytes=%s limit_bytes=%s "
        "mime=%s dimensions=%sx%s",
        "prepared",
        len(original),
        len(original),
        10_000,
        "image/png",
        64,
        64,
    )


def test_prepare_cover_optimizes_once_without_changing_original(tmp_path):
    cover_path = tmp_path / "cover.bmp"
    save_image(cover_path, "BMP", size=(800, 600))
    original = cover_path.read_bytes()
    embedder = CoverEmbedder(
        max_bytes=20_000,
        max_width=400,
        max_height=400,
        max_source_pixels=1_000_000,
    )

    prepared = embedder.prepare_cover(str(cover_path))

    assert prepared.optimized is True
    assert prepared.mime_type == "image/jpeg"
    assert prepared.final_size <= 20_000
    assert prepared.dimensions == (400, 300)
    assert cover_path.read_bytes() == original
    with Image.open(cover_path) as original_image:
        assert original_image.format == "BMP"
    with Image.open(BytesIO(prepared.data)) as optimized_image:
        assert optimized_image.size == (400, 300)


def test_prepare_cover_applies_orientation_before_resizing(tmp_path):
    cover_path = tmp_path / "rotated.jpg"
    image = Image.new("RGB", (80, 40), "navy")
    exif = Image.Exif()
    exif[274] = 6
    image.save(cover_path, format="JPEG", exif=exif)
    embedder = CoverEmbedder(max_bytes=10_000, max_width=50, max_height=50)

    prepared = embedder.prepare_cover(str(cover_path))

    assert prepared.optimized is True
    assert prepared.dimensions == (25, 50)


def test_prepare_cover_rejects_when_image_cannot_meet_byte_limit(tmp_path):
    cover_path = tmp_path / "cover.png"
    save_image(cover_path, "PNG")
    embedder = CoverEmbedder(max_bytes=50)

    with pytest.raises(CoverPreparationError, match="could not be optimized"):
        embedder.prepare_cover(str(cover_path))


def test_prepare_cover_can_disable_automatic_optimization(tmp_path):
    cover_path = tmp_path / "cover.bmp"
    save_image(cover_path, "BMP", size=(200, 200))
    embedder = CoverEmbedder(max_bytes=1_000, auto_optimize=False)

    with pytest.raises(
        CoverPreparationError,
        match="automatic optimization is disabled",
    ):
        embedder.prepare_cover(str(cover_path))


def test_prepare_cover_rejects_high_pixel_count_before_decoding(tmp_path):
    cover_path = tmp_path / "compressed.png"
    save_image(cover_path, "PNG", size=(1_000, 1_000), color="white")
    assert cover_path.stat().st_size < 1_000_000
    embedder = CoverEmbedder(
        max_bytes=1_000_000,
        max_source_pixels=500_000,
    )

    with pytest.raises(CoverPreparationError, match="safe decoding limit"):
        embedder.prepare_cover(str(cover_path))


def test_prepare_cover_rejects_damaged_image(tmp_path):
    cover_path = tmp_path / "damaged.jpg"
    cover_path.write_bytes(b"not an image")
    embedder = CoverEmbedder()

    with pytest.raises(CoverPreparationError, match="damaged or unsupported"):
        embedder.prepare_cover(str(cover_path))


def test_manual_cover_can_restrict_real_mime_independent_of_extension(tmp_path):
    supported = tmp_path / "cover.bin"
    unsupported = tmp_path / "cover.jpg"
    save_image(supported, "WEBP")
    save_image(unsupported, "BMP")
    allowed = {"image/jpeg", "image/png", "image/webp"}
    embedder = CoverEmbedder(max_bytes=100_000)

    assert embedder.prepare_cover(
        str(supported), allowed_mime_types=allowed
    ).mime_type == "image/webp"
    with pytest.raises(CoverPreparationError, match="unsupported format"):
        embedder.prepare_cover(str(unsupported), allowed_mime_types=allowed)


def test_square_cover_uses_centered_padding_without_distortion(tmp_path):
    cover_path = tmp_path / "wide.png"
    save_image(cover_path, "PNG", size=(80, 40), color="red")
    embedder = CoverEmbedder(max_bytes=100_000)

    prepared = embedder.prepare_square_cover(
        str(cover_path),
        allowed_mime_types={"image/jpeg", "image/png", "image/webp"},
    )

    assert prepared.dimensions == (80, 80)
    assert prepared.mime_type == "image/jpeg"
    with Image.open(BytesIO(prepared.data)) as square:
        assert square.size == (80, 80)
        top = square.getpixel((40, 5))
        center = square.getpixel((40, 40))
        assert top[0] < 80 and top[1] < 80 and top[2] < 80
        assert center[0] > 180 and center[1] < 100 and center[2] < 100


@mock.patch("autodrome.services.cover_embedder.MP3")
def test_embed_cover_uses_prepared_bytes_and_mime(mock_mp3):
    audio = mock.MagicMock()
    audio.tags = mock.MagicMock()
    mock_mp3.return_value = audio
    prepared = PreparedCover(
        data=b"PNGDATA",
        mime_type="image/png",
        original_size=7,
        dimensions=(32, 32),
        optimized=False,
    )

    CoverEmbedder(max_bytes=100).embed_cover("/fake/song.mp3", prepared)

    embedded = audio.tags.add.call_args.args[0]
    assert embedded.mime == "image/png"
    assert embedded.data == b"PNGDATA"
    audio.save.assert_called_once_with()


@mock.patch("autodrome.services.cover_embedder.MP3")
def test_embed_cover_handles_existing_id3_tags(mock_mp3):
    audio = mock.MagicMock()
    audio.tags = mock.MagicMock()
    audio.add_tags.side_effect = error("Already exists")
    mock_mp3.return_value = audio
    prepared = PreparedCover(
        data=b"JPEGDATA",
        mime_type="image/jpeg",
        original_size=8,
        dimensions=(32, 32),
        optimized=False,
    )

    CoverEmbedder(max_bytes=100).embed_cover("/fake/song.mp3", prepared)

    audio.tags.add.assert_called_once()
    audio.save.assert_called_once_with()
