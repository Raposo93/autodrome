from fastapi import APIRouter, Request, status

download_router = APIRouter()


@download_router.post("/", status_code=status.HTTP_202_ACCEPTED)
async def download(request: Request):
    body = await request.json()
    playlist_url = body["playlist_url"]
    artist = body["artist"]
    album = body["album"]
    release_id = body["release_id"]
    track_count = body.get("track_count")

    payload = {
        "playlist_url": playlist_url,
        "artist": artist,
        "album": album,
        "release_id": release_id,
        "track_count": track_count,
    }

    job_id = await request.app.state.queue_manager.enqueue(payload)
    return {"status": "queued", "job_id": job_id}
