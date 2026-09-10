from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse

from autodrome.logger import logger
from autodrome.http_client_async import UpstreamServiceError
from autodrome.models.requests import SearchRequest

search_router = APIRouter()


def _upstream_error_response(error: UpstreamServiceError) -> JSONResponse:
    logger.warning(f"Search upstream failure: {error}")
    return JSONResponse(
        status_code=502,
        content={"error": str(error), "provider": error.provider},
    )

@search_router.get("/")
async def combined_search(
    request: Request,
    search: Annotated[SearchRequest, Query()],
):
    try:
        controller = request.app.state.search_controller
        results = await controller.search(
            search.artist or "",
            search.album or "",
            result_limit=search.result_limit,
            max_tracks=search.max_tracks,
        )
        if len(results.get("errors", {})) == 2:
            return JSONResponse(
                status_code=502,
                content={**results, "error": "Both search providers failed"},
            )
        return JSONResponse(content=results)
    except UpstreamServiceError as e:
        return _upstream_error_response(e)
    except Exception:
        logger.exception("Unexpected error in combined search")
        return JSONResponse(
            status_code=500,
            content={"error": "Unexpected search failure"},
        )


@search_router.get("/releases/{release_id}")
async def release_details(release_id: UUID, request: Request):
    try:
        controller = request.app.state.search_controller
        details = await controller.get_release_details(str(release_id))
        return JSONResponse(content=details)
    except UpstreamServiceError as e:
        return _upstream_error_response(e)
    except Exception:
        logger.exception(f"Unexpected error loading release {release_id}")
        return JSONResponse(
            status_code=500,
            content={"error": f"Unexpected failure loading release {release_id}"},
        )
