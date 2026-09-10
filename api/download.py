from fastapi import APIRouter, File, HTTPException, Request, UploadFile, status

from autodrome.models.requests import (
    AlbumDestinationRequest,
    DownloadRequest,
    PlaylistPreflightRequest,
    YoutubeCoverRequest,
)
from autodrome.http_client_async import UpstreamServiceError
from autodrome.services.cover_selection import CoverSelectionError

download_router = APIRouter()


@download_router.post("/", status_code=status.HTTP_202_ACCEPTED)
async def download(payload: DownloadRequest, request: Request):
    job_payload = payload.model_dump(mode="json")
    job_id = await _queue_operation(request.app.state.queue_manager.enqueue(job_payload))
    return {"status": "queued", "job_id": job_id}


async def _queue_operation(operation):
    try:
        return await operation
    except KeyError as error:
        raise HTTPException(status_code=404, detail="Download job not found") from error
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except OSError as error:
        raise HTTPException(
            status_code=503, detail="Queue storage unavailable. Processing may be paused; fix storage and try again."
        ) from error


@download_router.delete("/history")
async def clear_history(request: Request):
    removed = await _queue_operation(request.app.state.queue_manager.clear_history())
    return {"removed": removed}


@download_router.delete("/jobs/{job_id}")
async def delete_job(job_id: str, request: Request):
    await _queue_operation(request.app.state.queue_manager.delete_job(job_id))
    return {"status": "deleted", "job_id": job_id}


@download_router.post("/jobs/{job_id}/cancel")
async def cancel_job(job_id: str, request: Request):
    await _queue_operation(request.app.state.queue_manager.cancel_job(job_id))
    return {"status": "cancelled", "job_id": job_id}


@download_router.post("/jobs/{job_id}/retry", status_code=status.HTTP_202_ACCEPTED)
async def retry_job(job_id: str, request: Request):
    new_job_id = await _queue_operation(request.app.state.queue_manager.retry_job(job_id))
    return {"status": "queued", "job_id": new_job_id}


@download_router.post("/preflight")
async def playlist_preflight(payload: PlaylistPreflightRequest, request: Request):
    try:
        return await request.app.state.downloader_controller.downloader.get_playlist_manifest(
            payload.playlist_url, payload.track_count
        )
    except (RuntimeError, ValueError) as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except Exception as error:
        raise HTTPException(status_code=502, detail="Could not extract playlist manifest. Try again.") from error


@download_router.post("/destination")
async def album_destination(payload: AlbumDestinationRequest, request: Request):
    return request.app.state.downloader_controller.organizer.inspect_album_destination(
        payload.artist,
        payload.album,
    )


@download_router.post("/covers/manual", status_code=status.HTTP_201_CREATED)
async def upload_manual_cover(request: Request, cover: UploadFile = File(...)):
    maximum = request.app.state.config.max_cover_upload_bytes
    content = await cover.read(maximum + 1)
    try:
        return request.app.state.cover_selection.store_manual(content)
    except CoverSelectionError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@download_router.post("/covers/youtube", status_code=status.HTTP_201_CREATED)
async def prepare_youtube_cover(payload: YoutubeCoverRequest, request: Request):
    try:
        return await request.app.state.cover_selection.store_youtube(
            payload.thumbnail_url
        )
    except CoverSelectionError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except UpstreamServiceError as error:
        raise HTTPException(
            status_code=502,
            detail="Could not prepare the selected YouTube thumbnail. Choose another cover option.",
        ) from error
