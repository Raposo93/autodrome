import asyncio

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from autodrome.logger import logger

websocket_router = APIRouter()

@websocket_router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    app = websocket.scope["app"]
    ws_manager = app.state.queue_manager.websocket_manager
    await ws_manager.connect(websocket)
    await websocket.send_json(app.state.queue_manager.snapshot())
    logger.info(f"WebSocket connected: {websocket.client}")
    try:
        while True:
            await asyncio.sleep(90)  # Keep the connection alive
    except WebSocketDisconnect:
        logger.info(f"WebSocket disconnected: {websocket.client}")
        ws_manager.disconnect(websocket)
    except Exception as e:
        logger.warning(f"Unexpected WebSocket error: {e}")
        ws_manager.disconnect(websocket)

@websocket_router.get("/ping")
async def ping():
    return {"msg": "pong"}
