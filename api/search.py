from flask import Blueprint, request, jsonify
from autodrome.controllers.search_controller import SearchController
from autodrome.logger import logger

search_bp = Blueprint("search", __name__)
controller = SearchController()

@search_bp.route("/")
def combined_search():
    artist = request.args.get("artist", "").strip()
    album = request.args.get("album", "").strip()

    if not artist and not album:
        return jsonify({"error": "Missing 'artist' or 'album' parameter"}), 400

    try:
        results = controller.search(artist, album)
        return jsonify(results)
    except Exception as e:
        logger.error(f"Error in combined search: {e}")
        return jsonify({"error": str(e)}), 500
