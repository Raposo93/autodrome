import asyncio

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from autodrome.logger import logger
from autodrome.security import token_matches

websocket_router = APIRouter()
HEARTBEAT_TIMEOUT_SECONDS = 30


@websocket_router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    app = websocket.scope["app"]
    settings = app.state.config
    if settings.requires_api_token and not token_matches(
        settings.api_token, websocket.query_params.get("token")
    ):
        await websocket.close(code=1008, reason="A valid API token is required")
        return

    ws_manager = app.state.queue_manager.websocket_manager
    connected = False
    try:
        await ws_manager.connect(websocket)
        connected = True
        await websocket.send_json(app.state.queue_manager.snapshot())
        logger.info(f"WebSocket connected: {websocket.client}")
        while True:
            try:
                message = await asyncio.wait_for(
                    websocket.receive_text(),
                    timeout=HEARTBEAT_TIMEOUT_SECONDS,
                )
            except asyncio.TimeoutError:
                await websocket.send_json({"type": "heartbeat"})
                continue

            if message == "ping":
                await websocket.send_json({"type": "pong"})
    except WebSocketDisconnect:
        logger.info(f"WebSocket disconnected: {websocket.client}")
    except Exception as e:
        logger.warning(f"Unexpected WebSocket error: {e}")
    finally:
        if connected:
            ws_manager.disconnect(websocket)


@websocket_router.get("/ping")
async def ping():
    return {"msg": "pong"}
