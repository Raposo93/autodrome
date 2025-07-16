from flask import Blueprint, request, jsonify
from autodrome.http_client import HTTP_client
from autodrome.metadata_service import MetadataService
from autodrome.yt_downloader import YTDownloader
from autodrome.services.organizer import Organizer
from autodrome.logger import logger
from autodrome.controllers.downloader_controller import DownloaderController

download_bp = Blueprint("download", __name__)

controller = DownloaderController(
    downloader=YTDownloader(),
    metadata_service=MetadataService(http_client=HTTP_client()),
    organizer=Organizer()
)

@download_bp.route("/", methods=["POST"])
def download():
    data = request.json
    playlist_url = data.get("playlist_url")
    artist = data.get("artist")
    album = data.get("album")
    release_id = data.get("release_id")
    track_count = data.get("track_count")


    if not playlist_url:
        return jsonify({"error": "Missing playlist_url"}), 400
    
    try:
        controller.download_and_tag(playlist_url, artist, album, release_id, track_count)
        return jsonify({"status": "success", "message": "Playlist downloaded and tagged"})
    except Exception as e:
        logger.error(f"Download error: {e}")
        return jsonify({"error": str(e)}), 500
