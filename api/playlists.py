from flask import Blueprint, request, jsonify
from autodrome.http_client import HTTP_client
from autodrome.yt_api import YTApi
from autodrome.logger import logger

playlists_bp = Blueprint("playlists", __name__)
yt_api = YTApi(http_client=HTTP_client)

@playlists_bp.route("/")
def playlists():
    query = request.args.get("q", "")
    if not query:
        return jsonify({"error": "Missing query parameter 'q'"}), 400
    try:
        results = yt_api.search_playlist(query)
        playlists_json = [p.__dict__ for p in results]
        return jsonify(playlists_json)
    except Exception as e:
        logger.error(f"Error fetching playlists: {e}")
        return jsonify({"error": str(e)}), 500
