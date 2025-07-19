from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from autodrome.controllers.search_controller import SearchController
from autodrome.logger import logger

search_router = APIRouter()

@search_router.get("/")
async def combined_search(request: Request):
    artist = request.query_params.get("artist", "").strip()
    album = request.query_params.get("album", "").strip()

    if not artist and not album:
        return JSONResponse(status_code=400, content={"error": "Missing 'artist' or 'album' parameter"})

    try:
        controller = request.app.state.search_controller
        results = await controller.search(artist, album)
        return JSONResponse(content=results)
    except Exception as e:
        logger.error(f"Error in combined search: {e}")
        return JSONResponse(status_code=500, content={"error": str(e)})
