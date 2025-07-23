from typing import List
from fastapi import WebSocket
import asyncio
import logging

logger = logging.getLogger(__name__)

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
            logger.warning("Trying to disconnect websocket that was not connected")

    async def broadcast(self, message: dict) -> None:
        logger.debug(f"Broadcasting to {len(self.active_connections)} clients")
        disconnected = []
        for connection in self.active_connections:
            try:
                await connection.send_json(message)
                if client := connection.client:
                    logger.debug(f"Broadcasted message to {client.host}")
                else:
                    logger.debug("Broadcasted message to unknown client (no address)")

            except Exception as e:
                logger.warning(f"WebSocket connection lost: {e}")
                disconnected.append(connection)
        for conn in disconnected:
            self.disconnect(conn)
