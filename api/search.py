from flask import Blueprint, request, jsonify
from autodrome.metadata_service import MetadataService
from autodrome.yt_api import YTApi
from autodrome.logger import logger

search_bp = Blueprint("search", __name__)
metadata_service = MetadataService()
yt_api = YTApi()

@search_bp.route("/")
def combined_search():
    artist = request.args.get("artist", "").strip()
    album = request.args.get("album", "").strip()

    if not artist and not album:
        return jsonify({"error": "Missing 'artist' or 'album' parameter"}), 400

    try:
        query = f"{artist} {album}".strip()
        playlists = []
        if query:
            playlists_results = yt_api.search_playlist(query)
            playlists = [p.__dict__ for p in playlists_results]

        releases = []
        if artist or album:
            # Nota: metadata_service puede necesitar ambos, si no, adapta ahí la función
            releases_results = metadata_service.search_releases(artist, album)
            releases = [r.__dict__ for r in releases_results]

        return jsonify({
            "playlists": playlists,
            "releases": releases
        })

    except Exception as e:
        logger.error(f"Error in combined search: {e}")
        return jsonify({"error": str(e)}), 500
