import unittest
from unittest.mock import AsyncMock, MagicMock

import aiohttp

from autodrome.http_client_async import AsyncHttpClient


def async_response_context(response):
    context = MagicMock()
    context.__aenter__ = AsyncMock(return_value=response)
    context.__aexit__ = AsyncMock(return_value=None)
    return context


class TestAsyncHttpClient(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.session = MagicMock()
        self.client = AsyncHttpClient(session=self.session)

    async def test_get_returns_json_response(self):
        response = MagicMock()
        response.json = AsyncMock(return_value={"status": "ok"})
        self.session.get.return_value = async_response_context(response)

        result = await self.client.get("https://example.test/api")

        self.assertEqual(result, {"status": "ok"})
        self.session.get.assert_called_once_with(
            "https://example.test/api",
            headers=self.client.headers,
            params=None,
            timeout=10,
        )
        response.raise_for_status.assert_called_once_with()

    async def test_get_propagates_http_error(self):
        response = MagicMock()
        response.raise_for_status.side_effect = aiohttp.ClientError("failed")
        self.session.get.return_value = async_response_context(response)

        with self.assertRaisesRegex(aiohttp.ClientError, "failed"):
            await self.client.get("https://example.test/api")

    async def test_post_returns_json_response(self):
        response = MagicMock()
        response.json = AsyncMock(return_value={"created": True})
        self.session.post.return_value = async_response_context(response)

        result = await self.client.post(
            "https://example.test/api", json={"name": "Album"}
        )

        self.assertEqual(result, {"created": True})
        self.session.post.assert_called_once_with(
            "https://example.test/api",
            headers=self.client.headers,
            data=None,
            json={"name": "Album"},
            timeout=10,
        )

    async def test_get_binary_returns_response_bytes(self):
        response = MagicMock()
        response.read = AsyncMock(return_value=b"image")
        self.session.get.return_value = async_response_context(response)

        result = await self.client.get_binary("https://example.test/image.jpg")

        self.assertEqual(result, b"image")
        response.raise_for_status.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
