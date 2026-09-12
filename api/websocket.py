import asyncio

from fastapi import (
    APIRouter,
    HTTPException,
    Request,
    Response,
    WebSocket,
    WebSocketDisconnect,
)

from autodrome.logger import logger
from autodrome.services.websocket_tickets import WebSocketTicketCapacityError

websocket_router = APIRouter()
HEARTBEAT_TIMEOUT_SECONDS = 30


@websocket_router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    app = websocket.scope["app"]
    settings = app.state.config
    if settings.requires_api_token and not app.state.websocket_ticket_store.consume(
        websocket.query_params.get("ticket")
    ):
        await websocket.close(code=1008, reason="A valid WebSocket ticket is required")
        return

    ws_manager = app.state.queue_manager.websocket_manager
    connected = False
    try:
        await ws_manager.connect(websocket)
        connected = True
        await websocket.send_json(app.state.queue_manager.snapshot())
        if app.state.queue_manager.storage_error:
            await websocket.send_json(app.state.queue_manager.processing_status())
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


@websocket_router.post("/api/auth/ws-ticket", status_code=201)
async def issue_websocket_ticket(request: Request, response: Response):
    store = request.app.state.websocket_ticket_store
    try:
        ticket = store.issue()
    except WebSocketTicketCapacityError as error:
        raise HTTPException(
            status_code=503,
            detail="WebSocket ticket capacity temporarily exhausted",
        ) from error
    response.headers["Cache-Control"] = "no-store"
    return {"ticket": ticket, "expires_in": store.ttl_seconds}


@websocket_router.get("/ping")
async def ping():
    return {"msg": "pong"}
