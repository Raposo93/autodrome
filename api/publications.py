from fastapi import APIRouter, HTTPException, Query, Request

from autodrome.services.publication_catalog import PublicationCatalogError


publication_router = APIRouter()


def _read(operation):
    try:
        return operation()
    except KeyError as error:
        raise HTTPException(status_code=404, detail="Publication not found") from error
    except PublicationCatalogError as error:
        raise HTTPException(
            status_code=503,
            detail="Publication history is temporarily unavailable.",
        ) from error


@publication_router.get("/")
async def list_publications(
    request: Request,
    limit: int = Query(100, ge=1, le=1000),
    destination: str | None = Query(None, min_length=1, max_length=511),
    release_id: str | None = Query(None, min_length=1, max_length=255),
):
    return _read(
        lambda: request.app.state.publication_controller.list_publications(
            limit,
            destination=destination,
            release_id=release_id,
        )
    )


@publication_router.get("/{publication_id}")
async def get_publication(publication_id: str, request: Request):
    return _read(
        lambda: request.app.state.publication_controller.get_publication(
            publication_id
        )
    )


@publication_router.post("/{publication_id}/recreate")
async def recreate_publication(publication_id: str, request: Request):
    try:
        return await request.app.state.publication_controller.recreate_review(
            publication_id
        )
    except KeyError as error:
        raise HTTPException(status_code=404, detail="Publication not found") from error
    except PublicationCatalogError as error:
        raise HTTPException(
            status_code=503,
            detail="Publication history is temporarily unavailable.",
        ) from error
