from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from autodrome.metadata_service import MetadataService
from autodrome.yt_downloader import YTDownloader
from autodrome.services.organizer import Organizer
from autodrome.logger import logger
from autodrome.controllers.downloader_controller import DownloaderController

download_router = APIRouter()


@download_router.post("/")
async def download(request: Request):
    body = await request.json()
    playlist_url = body["playlist_url"]
    artist = body["artist"]
    album = body["album"]
    release_id = body["release_id"]
    track_count = body.get("track_count")

    payload = {
        "playlist_url": playlist_url,
        "artist": artist,
        "album": album,
        "release_id": release_id,
        "track_count": track_count,
    }

    await request.app.state.queue_manager.enqueue(payload)
    return {"status": "queued"}
