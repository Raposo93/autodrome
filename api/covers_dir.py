from flask import send_from_directory, Blueprint
import os

covers_dir_bp = Blueprint("cover_dir", __name__)
COVERS_DIR = os.path.abspath("covers")

@covers_dir_bp.route("/<path:filename>")
def serve_cover(filename):
    return send_from_directory(COVERS_DIR, filename)
