from flask import Flask
from api.search import search_bp
from api.download import download_bp
from flask_cors import CORS


app = Flask(__name__)
# Configure CORS in production mode
CORS(app, resources={r"/api/*": {"origins": "*"}}, supports_credentials=True)

app.register_blueprint(search_bp, url_prefix='/api/search')
app.register_blueprint(download_bp, url_prefix='/api/download')

if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)

