from typing import Annotated

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse

from autodrome.logger import logger
from autodrome.models.requests import SearchRequest

search_router = APIRouter()

@search_router.get("/")
async def combined_search(
    request: Request,
    search: Annotated[SearchRequest, Query()],
):
    try:
        controller = request.app.state.search_controller
        results = await controller.search(search.artist or "", search.album or "")
        return JSONResponse(content=results)
    except Exception as e:
        logger.error(f"Error in combined search: {e}")
        return JSONResponse(status_code=500, content={"error": str(e)})
