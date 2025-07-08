from flask import Flask, send_from_directory
from api.search import search_bp       # nuevo blueprint para búsqueda combinada
from api.tracks import tracks_bp
# from api.cover_art import cover_art_bp
from api.download import download_bp
from api.covers_dir import covers_dir_bp
from flask_cors import CORS
import os


app = Flask(__name__)
CORS(app)

COVERS_DIR = os.path.abspath("covers")

app.register_blueprint(search_bp, url_prefix='/api/search')
app.register_blueprint(tracks_bp, url_prefix='/api/tracks')
app.register_blueprint(download_bp, url_prefix='/api/download')
app.register_blueprint(covers_dir_bp, url_prefix='/api/covers_dir')

if __name__ == "__main__":
    app.run(debug=True, port=5000)
