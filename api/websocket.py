from fastapi import WebSocket, APIRouter, WebSocketDisconnect, Request, Depends
from autodrome.logger import logger
import asyncio

websocket_router = APIRouter()

def get_request(websocket: WebSocket):
    # Hack: WebSocket.scope contains the app
    class DummyRequest:
        def __init__(self, scope):
            self.app = scope["app"]
    return DummyRequest(websocket.scope)

@websocket_router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    app = websocket.scope["app"]
    ws_manager = app.state.queue_manager.websocket_manager
    await ws_manager.connect(websocket)
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


async def broadcast_queue(queue, request: Request):
    message = [q.to_dict() for q in queue]
    ws_manager = request.app.state.queue_manager.websocket_manager
    await ws_manager.broadcast(message)

@websocket_router.get("/ping")
async def ping():
    return {"msg": "pong"}
