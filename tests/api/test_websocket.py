import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import WebSocketDisconnect

from api.websocket import websocket_endpoint
from autodrome.services.websocket_manager import WebSocketManager


class TestWebSocketEndpoint(unittest.IsolatedAsyncioTestCase):
    async def test_reload_receives_snapshot_for_running_job(self):
        websocket = MagicMock()
        websocket.send_json = AsyncMock()
        websocket.receive_text = AsyncMock(side_effect=WebSocketDisconnect())
        websocket.client = MagicMock()
        websocket_manager = MagicMock()
        websocket_manager.connect = AsyncMock()
        queue_manager = MagicMock()
        queue_manager.websocket_manager = websocket_manager
        queue_manager.snapshot.return_value = [
            {"job_id": "job-1", "status": "running"}
        ]
        websocket.scope = {"app": MagicMock()}
        websocket.scope["app"].state.queue_manager = queue_manager
        websocket.scope["app"].state.config.requires_api_token = False

        await websocket_endpoint(websocket)

        websocket_manager.connect.assert_awaited_once_with(websocket)
        websocket.send_json.assert_awaited_once_with(
            [{"job_id": "job-1", "status": "running"}]
        )
        websocket_manager.disconnect.assert_called_once_with(websocket)

    async def test_heartbeat_messages_keep_connection_alive(self):
        websocket = MagicMock()
        websocket.send_json = AsyncMock()
        websocket.receive_text = AsyncMock(
            side_effect=["ping", WebSocketDisconnect()]
        )
        websocket.client = MagicMock()
        websocket_manager = MagicMock()
        websocket_manager.connect = AsyncMock()
        queue_manager = MagicMock()
        queue_manager.websocket_manager = websocket_manager
        queue_manager.snapshot.return_value = []
        websocket.scope = {"app": MagicMock()}
        websocket.scope["app"].state.queue_manager = queue_manager
        websocket.scope["app"].state.config.requires_api_token = False

        await websocket_endpoint(websocket)

        self.assertEqual(
            websocket.send_json.await_args_list,
            [unittest.mock.call([]), unittest.mock.call({"type": "pong"})],
        )
        websocket_manager.disconnect.assert_called_once_with(websocket)

    @patch("api.websocket.HEARTBEAT_TIMEOUT_SECONDS", 0.001)
    async def test_silent_client_is_probed_and_cleaned_up(self):
        receive_count = 0

        async def receive_text():
            nonlocal receive_count
            receive_count += 1
            if receive_count == 1:
                await asyncio.sleep(1)
            raise WebSocketDisconnect()

        websocket = MagicMock()
        websocket.accept = AsyncMock()
        websocket.send_json = AsyncMock()
        websocket.receive_text = receive_text
        websocket.client = MagicMock()
        websocket_manager = WebSocketManager()
        queue_manager = MagicMock()
        queue_manager.websocket_manager = websocket_manager
        queue_manager.snapshot.return_value = []
        websocket.scope = {"app": MagicMock()}
        websocket.scope["app"].state.queue_manager = queue_manager
        websocket.scope["app"].state.config.requires_api_token = False

        await websocket_endpoint(websocket)

        self.assertEqual(
            websocket.send_json.await_args_list,
            [unittest.mock.call([]), unittest.mock.call({"type": "heartbeat"})],
        )
        websocket.accept.assert_awaited_once_with()
        self.assertEqual(websocket_manager.active_connections, [])

    async def test_external_connection_rejects_invalid_token(self):
        websocket = MagicMock()
        websocket.close = AsyncMock()
        websocket.query_params = {}
        websocket.scope = {"app": MagicMock()}
        websocket.scope["app"].state.config.requires_api_token = True
        websocket.scope["app"].state.config.api_token = "a" * 32

        await websocket_endpoint(websocket)

        websocket.close.assert_awaited_once_with(
            code=1008, reason="A valid API token is required"
        )


if __name__ == "__main__":
    unittest.main()
