from fastapi import APIRouter, Request, status

from autodrome.models.requests import DownloadRequest

download_router = APIRouter()


@download_router.post("/", status_code=status.HTTP_202_ACCEPTED)
async def download(payload: DownloadRequest, request: Request):
    job_payload = payload.model_dump(mode="json")
    job_id = await request.app.state.queue_manager.enqueue(job_payload)
    return {"status": "queued", "job_id": job_id}
