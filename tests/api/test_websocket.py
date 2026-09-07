import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import WebSocketDisconnect

from api.websocket import websocket_endpoint


class TestWebSocketEndpoint(unittest.IsolatedAsyncioTestCase):
    @patch("api.websocket.asyncio.sleep", new_callable=AsyncMock)
    async def test_connection_receives_current_queue_snapshot(self, sleep):
        sleep.side_effect = WebSocketDisconnect()
        websocket = MagicMock()
        websocket.send_json = AsyncMock()
        websocket.client = MagicMock()
        websocket_manager = MagicMock()
        websocket_manager.connect = AsyncMock()
        queue_manager = MagicMock()
        queue_manager.websocket_manager = websocket_manager
        queue_manager.snapshot.return_value = [
            {"job_id": "job-1", "status": "interrupted"}
        ]
        websocket.scope = {"app": MagicMock()}
        websocket.scope["app"].state.queue_manager = queue_manager

        await websocket_endpoint(websocket)

        websocket_manager.connect.assert_awaited_once_with(websocket)
        websocket.send_json.assert_awaited_once_with(
            [{"job_id": "job-1", "status": "interrupted"}]
        )
        websocket_manager.disconnect.assert_called_once_with(websocket)


if __name__ == "__main__":
    unittest.main()
