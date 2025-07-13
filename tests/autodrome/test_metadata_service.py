import pytest
from unittest.mock import MagicMock
from autodrome.metadata_service import MetadataService
from autodrome.models.release import Release

def test_search_releases_returns_correct_releases():
    mock_http_client = MagicMock()
    mock_http_client.get.return_value = {
        "releases": [
            {
                "id": "release1",
                "title": "Test Album",
                "date": "2020-01-01",
                "artist-credit": [{"name": "Test Artist"}]
            }
        ]
    }
    
    service = MetadataService(http_client=mock_http_client)
    
    service.get_tracks = MagicMock(return_value=[])
    
    releases = service.search_releases("Test Artist", "Test Album")
    
    assert isinstance(releases, list)
    assert len(releases) == 1
    release = releases[0]
    assert isinstance(release, Release)
    assert release.id == "release1"
    assert release.title == "Test Album"
    assert release.date == "2020-01-01"
    assert release.artist == "Test Artist"
    assert release.tracks == []

def test_search_releases_handles_empty_response():
    mock_http_client = MagicMock()
    mock_http_client.get.return_value = {}
    
    service = MetadataService(http_client=mock_http_client)
    service.get_tracks = MagicMock(return_value=[])
    
    releases = service.search_releases(None, None)
    
    assert releases == []
