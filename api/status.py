from fastapi import APIRouter, Request


status_router = APIRouter()


@status_router.get("/")
async def system_status(request: Request):
    return await request.app.state.system_status.snapshot()
