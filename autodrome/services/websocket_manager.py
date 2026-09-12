import asyncio
from typing import List

from fastapi import WebSocket

from autodrome.logger import logger


class WebSocketManager:
    def __init__(self) -> None:
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket) -> None:
        logger.debug(f"WebSocket connecting: {websocket.client}")
        await websocket.accept()
        self.active_connections.append(websocket)
        logger.debug(f"Client connected. Total: {len(self.active_connections)}")


    def disconnect(self, websocket: WebSocket) -> None:
        try:
            self.active_connections.remove(websocket)
        except ValueError:
            logger.debug("websocket_disconnect_ignored reason=not_connected")

    async def broadcast(self, message: dict) -> None:
        logger.debug(f"Broadcasting to {len(self.active_connections)} clients")
        disconnected = []
        for connection in self.active_connections:
            try:
                await connection.send_json(message)
                if client := connection.client:
                    logger.debug("websocket_message_sent client=%s", client.host)
                else:
                    logger.debug("Broadcasted message to unknown client (no address)")

            except Exception as e:
                logger.debug("websocket_connection_lost reason=%s", type(e).__name__)
                disconnected.append(connection)
        for conn in disconnected:
            self.disconnect(conn)
