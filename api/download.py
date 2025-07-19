from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from autodrome.metadata_service import MetadataService
from autodrome.yt_downloader import YTDownloader
from autodrome.services.organizer import Organizer
from autodrome.logger import logger
from autodrome.controllers.downloader_controller import DownloaderController
from autodrome.http_client_async import AsyncHttpClient

download_router = APIRouter()

# controller = DownloaderController(
#     downloader=YTDownloader(),
#     metadata_service=MetadataService(http_client=AsyncHttpClient()),
#     organizer=Organizer()
# )

@download_router.post("/")
async def download(request: Request):
    try:
        body = await request.json()
        playlist_url = body["playlist_url"]
        artist = body["artist"]
        album = body["album"]
        release_id = body["release_id"]
        track_count = body.get("track_count")

        controller = request.app.state.downloader_controller
        result = await controller.download_and_tag(playlist_url, artist, album, release_id, track_count)
        return JSONResponse(content=result)

    except Exception as e:
        logger.error(f"Download endpoint error: {e}")
        logger.info(f"body:{body}")

        return JSONResponse(status_code=500, content={"error": str(e)})
