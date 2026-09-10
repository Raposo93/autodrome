from fastapi import APIRouter, HTTPException, Request, status

from autodrome.models.requests import (
    AlbumDestinationRequest,
    DownloadRequest,
    PlaylistPreflightRequest,
)

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
