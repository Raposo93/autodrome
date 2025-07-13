from flask import Blueprint, request, jsonify
from autodrome.http_client import HTTP_client
from autodrome.metadata_service import MetadataService
from autodrome.logger import logger

tracks_bp = Blueprint("tracks", __name__)
metadata_service = MetadataService(http_client=HTTP_client())

@tracks_bp.route("/")

def tracks():
    release_id = request.args.get("release_id", "")
    if not release_id:
        return jsonify({"error": "Missing 'release_id' parameter"}), 400
    try:
        tracks = metadata_service.get_tracks(release_id)
        tracks_json = [t.__dict__ for t in tracks]
        return jsonify(tracks_json)
    except Exception as e:
        logger.error(f"Error fetching tracks: {e}")
        return jsonify({"error": str(e)}), 500
