import asyncio
from io import BytesIO
from unittest.mock import AsyncMock

import pytest
from PIL import Image

from autodrome.services.cover_embedder import CoverEmbedder
from autodrome.services.cover_selection import (
    CoverSelectionError,
    CoverSelectionService,
)
from autodrome.url_safety import validate_youtube_thumbnail_url


def image_bytes(image_format="PNG", size=(80, 40), color="red"):
    output = BytesIO()
    Image.new("RGB", size, color).save(output, format=image_format)
    return output.getvalue()


def service(tmp_path, *, response=None, max_upload_bytes=100_000):
    http_client = AsyncMock()
    http_client.get_binary.return_value = response or image_bytes()
    return CoverSelectionService(
        http_client=http_client,
        embedder=CoverEmbedder(max_bytes=100_000),
        storage_dir=str(tmp_path),
        max_upload_bytes=max_upload_bytes,
    )


def test_manual_cover_validates_real_mime_and_can_be_loaded_for_retry(tmp_path):
    selection = service(tmp_path)

    stored = selection.store_manual(image_bytes("WEBP", size=(32, 48)))
    prepared = selection.load_prepared(stored["cover_id"])

    assert stored["mime_type"] == "image/webp"
    assert stored["width"] == 32
    assert stored["height"] == 48
    assert prepared.data == (tmp_path / f'{stored["cover_id"]}.cover').read_bytes()


@pytest.mark.parametrize(
    ("content", "message"),
    [
        (b"", "empty"),
        (b"not an image", "damaged or unsupported"),
        (image_bytes("BMP"), "valid JPEG, PNG, or WebP"),
    ],
)
def test_manual_cover_rejects_invalid_content_before_storage(tmp_path, content, message):
    selection = service(tmp_path)

    with pytest.raises(CoverSelectionError, match=message):
        selection.store_manual(content)

    assert list(tmp_path.iterdir()) == []


def test_manual_cover_rejects_upload_over_limit(tmp_path):
    selection = service(tmp_path, max_upload_bytes=10)

    with pytest.raises(CoverSelectionError, match="upload limit"):
        selection.store_manual(image_bytes())


def test_youtube_cover_downloads_exact_url_and_adds_centered_square_padding(tmp_path):
    selection = service(tmp_path)
    url = "https://i.ytimg.com/vi/video-id/mqdefault.jpg"

    stored = asyncio.run(selection.store_youtube(url))
    prepared = selection.load_prepared(stored["cover_id"])

    selection.http_client.get_binary.assert_awaited_once_with(
        url,
        timeout=10,
        provider="YouTube",
        context="downloading the selected playlist thumbnail",
        allow_redirects=False,
    )
    assert stored["width"] == stored["height"] == 80
    with Image.open(BytesIO(prepared.data)) as image:
        assert image.size == (80, 80)
        assert image.getpixel((40, 5))[0] < 80
        assert image.getpixel((40, 40))[0] > 180


def test_load_rejects_missing_or_symlinked_selected_cover(tmp_path):
    selection = service(tmp_path)
    cover_id = "12345678-1234-1234-1234-123456789abc"

    with pytest.raises(CoverSelectionError, match="no longer available"):
        selection.load_prepared(cover_id)

    outside = tmp_path.parent / "outside.png"
    outside.write_bytes(image_bytes())
    (tmp_path / f"{cover_id}.cover").symlink_to(outside)
    with pytest.raises(CoverSelectionError, match="no longer available"):
        selection.load_prepared(cover_id)


@pytest.mark.parametrize(
    "url",
    [
        "http://i.ytimg.com/vi/id/image.jpg",
        "https://localhost/image.jpg",
        "https://i.ytimg.com.evil.test/image.jpg",
        "https://user@i.ytimg.com/image.jpg",
        "https://i.ytimg.com:444/image.jpg",
    ],
)
def test_youtube_thumbnail_url_rejects_unsafe_destinations(url):
    with pytest.raises(ValueError, match="YouTube|allowed"):
        validate_youtube_thumbnail_url(url)


def test_youtube_thumbnail_url_accepts_official_https_hosts():
    assert validate_youtube_thumbnail_url(
        "https://img.youtube.com/vi/id/maxresdefault.jpg"
    ) == "https://img.youtube.com/vi/id/maxresdefault.jpg"
