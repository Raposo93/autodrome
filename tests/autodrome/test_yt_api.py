import pytest
from unittest.mock import MagicMock
from autodrome.yt_api import YTApi
from autodrome.models.playlist import Playlist

@pytest.fixture
def mock_http_client():
    client = MagicMock()
    return client

def test_search_playlist_returns_playlists(mock_http_client):
    mock_response = {
        "items": [
            {
                "id": {"playlistId": "PL123"},
                "snippet": {
                    "title": "Test Playlist",
                    "channelTitle": "Test Channel",
                    "thumbnails": {
                        "medium": {"url": "http://image.url/thumbnail.jpg"}
                    }
                }
            }
        ]
    }

    mock_count_response = {
        "items": [
            {
                "contentDetails": {"itemCount": 42}
            }
        ]
    }

    mock_http_client.get.side_effect = [mock_response, mock_count_response]

    api = YTApi(mock_http_client)
    results = api.search_playlist("test query")

    assert len(results) == 1
    playlist = results[0]
    assert isinstance(playlist, Playlist)
    assert playlist.id == "PL123"
    assert playlist.title == "Test Playlist"
    assert playlist.channel == "Test Channel"
    assert playlist.thumbnail == "http://image.url/thumbnail.jpg"
    assert playlist.track_count == 42
    assert playlist.url == "https://www.youtube.com/playlist?list=PL123"

def test_search_playlist_handles_empty_response(mock_http_client):
    mock_http_client.get.return_value = {}

    api = YTApi(mock_http_client)
    results = api.search_playlist("empty")

    assert results == []

def test_search_playlist_handles_missing_playlist_id(mock_http_client):
    # Respuesta con item sin playlistId
    mock_response = {
        "items": [
            {
                "id": {},
                "snippet": {"title": "No ID", "channelTitle": "Channel"}
            }
        ]
    }

    mock_http_client.get.return_value = mock_response

    api = YTApi(mock_http_client)
    results = api.search_playlist("missing id")

    assert results == []

def test_get_track_count_handles_error(mock_http_client):
    mock_http_client.get.side_effect = Exception("API error")

    api = YTApi(mock_http_client)
    count = api._get_track_count("any_id")

    assert count is None
