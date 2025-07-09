from flask import Blueprint, request, jsonify
from autodrome.metadata_service import MetadataService
from autodrome.yt_downloader import YTDownloader
from autodrome.organizer import Organizer
from autodrome.logger import logger

download_bp = Blueprint("download", __name__)

metadata_service = MetadataService()
yt_downloader = YTDownloader()
organizer = Organizer()

@download_bp.route("/", methods=["POST"])
def download():
    data = request.json
    playlist_url = data.get("playlist_url")
    artist = data.get("artist")
    album = data.get("album")
    release_id = data.get("release_id")
    track_count = data.get("track_count")  # <- Aquí


    if not all([playlist_url, artist, album, release_id]):
        return jsonify({"error": "Missing required parameters"}), 400

    try:
        tracks = metadata_service.get_tracks(release_id)

        with yt_downloader.create_temp_folder() as tmpdir:
            yt_downloader.download_playlist(playlist_url, tmpdir, total=track_count)
            cover_path = metadata_service.get_cover_art(release_id)  # Ajusta para que devuelva path local o None
            organizer.tag_and_rename(tmpdir, artist, album, tracks, cover_path)
            organizer.move_to_library(tmpdir, artist, album)

        return jsonify({"status": "success", "message": "Playlist downloaded and tagged"})
    except Exception as e:
        logger.error(f"Download error: {e}")
        return jsonify({"error": str(e)}), 500
