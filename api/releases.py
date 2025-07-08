from flask import Blueprint, request, jsonify
from autodrome.metadata_service import MetadataService
from autodrome.logger import logger

releases_bp = Blueprint("releases", __name__)
metadata_service = MetadataService()

@releases_bp.route("/")
def releases():
    artist = request.args.get("artist", "")
    album = request.args.get("album", "")
    if not artist or not album:
        return jsonify({"error": "Missing 'artist' or 'album' parameter"}), 400
    try:
        results = metadata_service.search_releases(artist, album)
        releases_json = [r.__dict__ for r in results]
        return jsonify(releases_json)
    except Exception as e:
        logger.error(f"Error fetching releases: {e}")
        return jsonify({"error": str(e)}), 500