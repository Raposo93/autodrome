import asyncio
import os
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from autodrome.http_client_async import UpstreamServiceError
from autodrome.metadata_service import CoverArtCacheError, MetadataService


def service_for(cache_path):
    return MetadataService(
        http_client=AsyncMock(get_binary=AsyncMock(return_value=b"cover data")),
        cover_art_cache_path=str(cache_path),
    )


def test_download_creates_runtime_cache_outside_read_only_package(tmp_path):
    installed = tmp_path / "site-packages"
    package = installed / "autodrome"
    package.mkdir(parents=True)
    module = package / "metadata_service.py"
    module.touch()
    cache = tmp_path / "runtime" / "cache" / "cover-art"
    module.chmod(0o444)
    package.chmod(0o555)
    installed.chmod(0o555)
    try:
        with patch("autodrome.metadata_service.__file__", str(module)):
            service = service_for(cache)
            assert not cache.exists()
            assert service.get_cover_path("release-1") == str(cache / "release-1.jpg")
            assert not cache.exists()

            path = asyncio.run(service.get_cover_art("release-1"))

        assert Path(path).read_bytes() == b"cover data"
        assert cache.stat().st_uid == os.getuid()
        assert Path(path).stat().st_uid == os.getuid()
        assert list(installed.iterdir()) == [package]
        assert list(package.iterdir()) == [module]
        assert list(cache.iterdir()) == [Path(path)]
    finally:
        installed.chmod(0o755)
        package.chmod(0o755)
        module.chmod(0o644)


def test_cached_cover_is_reused_without_network_or_writes(tmp_path):
    cached = tmp_path / "release-1.jpg"
    cached.write_bytes(b"cached cover")
    service = service_for(tmp_path)
    tmp_path.chmod(0o555)
    try:
        assert asyncio.run(service.get_cover_art("release-1")) == str(cached)
        assert cached.read_bytes() == b"cached cover"
        service.http_client.get_binary.assert_not_awaited()
    finally:
        tmp_path.chmod(0o755)


@pytest.mark.skipif(os.getuid() == 0, reason="Root bypasses directory permissions")
@pytest.mark.parametrize("existing_cache", [False, True])
def test_unwritable_cache_has_actionable_local_error(tmp_path, existing_cache):
    cache = tmp_path if existing_cache else tmp_path / "cover-art"
    service = service_for(cache)
    tmp_path.chmod(0o555)
    try:
        with pytest.raises(CoverArtCacheError) as raised:
            asyncio.run(service.get_cover_art("release-1"))

        assert str(cache) in str(raised.value)
        assert "COVER_ART_CACHE_PATH" in str(raised.value)
        assert "runtime user write access" in str(raised.value)
        assert isinstance(raised.value.__cause__, PermissionError)
        assert list(tmp_path.iterdir()) == []
    finally:
        tmp_path.chmod(0o755)


def test_failed_atomic_publish_leaves_no_partial_cached_cover(tmp_path):
    service = service_for(tmp_path)
    with patch(
        "autodrome.metadata_service.os.replace",
        side_effect=PermissionError("cache publication denied"),
    ), pytest.raises(CoverArtCacheError, match="cache publication denied"):
        asyncio.run(service.get_cover_art("release-1"))

    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("status", [404, 503])
def test_upstream_absence_and_failure_do_not_create_cache(tmp_path, status):
    # Even an invalid local directory must not mask a CAA 404/provider failure.
    blocked_parent = tmp_path / "file"
    blocked_parent.touch()
    service = service_for(blocked_parent / "cover-art")
    error = UpstreamServiceError(
        provider="Cover Art Archive",
        context="downloading front cover for release release-1",
        reason=f"HTTP {status}",
        status=status,
    )
    service.http_client.get_binary.side_effect = error

    if status == 404:
        assert asyncio.run(service.get_cover_art("release-1")) is None
    else:
        with pytest.raises(UpstreamServiceError) as raised:
            asyncio.run(service.get_cover_art("release-1"))
        assert raised.value is error
    assert list(tmp_path.iterdir()) == [blocked_parent]


@pytest.mark.parametrize("release_id", ["", ".", "..", "../outside", "/absolute", "a/b", "a\\b", "a\0b"])
def test_release_id_cannot_escape_cache(tmp_path, release_id):
    service = service_for(tmp_path / "cache")
    with pytest.raises(ValueError, match="single path component"):
        asyncio.run(service.get_cover_art(release_id))
    service.http_client.get_binary.assert_not_awaited()
    assert list(tmp_path.iterdir()) == []
