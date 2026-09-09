from fastapi import APIRouter, HTTPException, Request, status

from autodrome.models.requests import DownloadRequest

download_router = APIRouter()


@download_router.post("/", status_code=status.HTTP_202_ACCEPTED)
async def download(payload: DownloadRequest, request: Request):
    job_payload = payload.model_dump(mode="json")
    job_id = await _history_operation(request.app.state.queue_manager.enqueue(job_payload))
    return {"status": "queued", "job_id": job_id}


async def _history_operation(operation):
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
    removed = await _history_operation(request.app.state.queue_manager.clear_history())
    return {"removed": removed}


@download_router.delete("/jobs/{job_id}")
async def delete_job(job_id: str, request: Request):
    await _history_operation(request.app.state.queue_manager.delete_job(job_id))
    return {"status": "deleted", "job_id": job_id}


@download_router.post("/jobs/{job_id}/retry", status_code=status.HTTP_202_ACCEPTED)
async def retry_job(job_id: str, request: Request):
    new_job_id = await _history_operation(request.app.state.queue_manager.retry_job(job_id))
    return {"status": "queued", "job_id": new_job_id}
