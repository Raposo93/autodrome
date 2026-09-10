import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock, call
from types import SimpleNamespace

import aiohttp

from autodrome.http_client_async import AsyncHttpClient, UpstreamServiceError


def async_response_context(response):
    context = MagicMock()
    context.__aenter__ = AsyncMock(return_value=response)
    context.__aexit__ = AsyncMock(return_value=None)
    return context


def response_with_error(status):
    response = MagicMock()
    response.raise_for_status.side_effect = aiohttp.ClientResponseError(
        request_info=MagicMock(),
        history=(),
        status=status,
        message="upstream failure",
    )
    return response


class BlockingResponseContext:
    def __init__(self, tracker, entered, release):
        self.tracker = tracker
        self.entered = entered
        self.release = release

    async def __aenter__(self):
        self.tracker["active"] += 1
        self.tracker["maximum"] = max(
            self.tracker["maximum"], self.tracker["active"]
        )
        self.entered.set()
        await self.release.wait()
        response = MagicMock()
        response.json = AsyncMock(return_value={"status": "ok"})
        return response

    async def __aexit__(self, exc_type, exc, traceback):
        self.tracker["active"] -= 1


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

    async def test_probe_checks_reachability_without_reading_a_body(self):
        response = MagicMock()
        self.session.head.return_value = async_response_context(response)

        result = await self.client.probe(
            "https://example.test/discovery", timeout=3, provider="YouTube"
        )

        self.assertIsNone(result)
        self.session.head.assert_called_once_with(
            "https://example.test/discovery",
            headers=self.client.headers,
            timeout=3,
        )
        response.raise_for_status.assert_called_once_with()

    async def test_get_retries_429_with_exponential_backoff(self):
        sleep = AsyncMock()
        client = AsyncHttpClient(session=self.session, sleep=sleep)
        success = MagicMock()
        success.json = AsyncMock(return_value={"status": "ok"})
        self.session.get.side_effect = [
            async_response_context(response_with_error(429)),
            async_response_context(success),
        ]

        result = await client.get(
            "https://example.test/ws/2/release/",
            context="searching releases",
        )

        self.assertEqual(result, {"status": "ok"})
        self.assertEqual(self.session.get.call_count, 2)
        sleep.assert_awaited_once_with(0.25)

    async def test_get_retries_5xx_then_returns_sanitized_error(self):
        sleep = AsyncMock()
        client = AsyncHttpClient(session=self.session, sleep=sleep)
        self.session.get.side_effect = [
            async_response_context(response_with_error(503)),
            async_response_context(response_with_error(503)),
            async_response_context(response_with_error(503)),
        ]

        with self.assertRaisesRegex(
            UpstreamServiceError,
            "External service failed while loading release release-1: "
            "HTTP 503 after 3 attempts",
        ):
            await client.get(
                "https://example.test/ws/2/release/release-1",
                context="loading release release-1",
            )

        self.assertEqual(sleep.await_args_list, [call(0.25), call(0.5)])

    async def test_timeout_is_retried_and_does_not_expose_query_secrets(self):
        sleep = AsyncMock()
        client = AsyncHttpClient(session=self.session, sleep=sleep)
        self.session.get.side_effect = asyncio.TimeoutError()

        with self.assertRaises(UpstreamServiceError) as raised:
            await client.get(
                "https://www.googleapis.com/youtube/v3/search",
                params={"key": "super-secret"},
                context="searching playlists",
            )

        message = str(raised.exception)
        self.assertEqual(
            message,
            "YouTube failed while searching playlists: request timed out "
            "after 3 attempts",
        )
        self.assertNotIn("super-secret", message)
        self.assertEqual(self.session.get.call_count, 3)

    async def test_non_transient_http_error_is_not_retried(self):
        response = response_with_error(400)
        self.session.get.return_value = async_response_context(response)

        with self.assertRaisesRegex(UpstreamServiceError, "HTTP 400"):
            await self.client.get("https://example.test/api")

        self.session.get.assert_called_once()

    async def test_provider_concurrency_is_limited(self):
        tracker = {"active": 0, "maximum": 0}
        entered = asyncio.Event()
        release = asyncio.Event()
        self.session.get.side_effect = lambda *args, **kwargs: BlockingResponseContext(
            tracker, entered, release
        )
        client = AsyncHttpClient(
            session=self.session,
            provider_limits={"MusicBrainz": 1},
        )

        first = asyncio.create_task(
            client.get("https://musicbrainz.org/ws/2/release/1")
        )
        await entered.wait()
        second = asyncio.create_task(
            client.get("https://musicbrainz.org/ws/2/release/2")
        )
        await asyncio.sleep(0)

        self.assertEqual(self.session.get.call_count, 1)
        self.assertEqual(tracker["maximum"], 1)

        release.set()
        await asyncio.gather(first, second)
        self.assertEqual(tracker["maximum"], 1)

    async def test_musicbrainz_spaces_concurrent_starts_and_retries(self):
        now = [0.0]
        starts = []

        async def sleep(delay):
            now[0] += delay
            await asyncio.sleep(0)

        success = MagicMock()
        success.json = AsyncMock(return_value={"releases": []})
        responses = iter([response_with_error(503), success, success])

        def request(*args, **kwargs):
            starts.append((now[0], kwargs["timeout"]))
            return async_response_context(next(responses))

        self.session.get.side_effect = request
        client = AsyncHttpClient(
            session=self.session, clock=lambda: now[0], sleep=sleep,
            provider_limits={"MusicBrainz": 2},
            settings=SimpleNamespace(
                musicbrainz_timeout_seconds=35,
                musicbrainz_max_attempts=2,
                musicbrainz_retry_base_seconds=0.25,
            ),
        )
        results = await asyncio.gather(
            client.get("https://musicbrainz.org/ws/2/release/1"),
            client.get("https://musicbrainz.org/ws/2/release/2"),
        )
        self.assertEqual(results, [{"releases": []}, {"releases": []}])
        self.assertEqual(len(starts), 3)
        self.assertTrue(all(b[0] - a[0] >= 1 for a, b in zip(starts, starts[1:])))
        self.assertTrue(all(timeout == 35 for _, timeout in starts))

    async def test_musicbrainz_configured_timeout_attempts_and_backoff(self):
        now = [0.0]
        delays = []

        async def sleep(delay):
            delays.append(delay)
            now[0] += delay

        self.session.get.side_effect = asyncio.TimeoutError()
        client = AsyncHttpClient(
            session=self.session, clock=lambda: now[0], sleep=sleep,
            settings=SimpleNamespace(
                musicbrainz_timeout_seconds=42,
                musicbrainz_max_attempts=4,
                musicbrainz_retry_base_seconds=2,
            ),
        )
        with self.assertRaises(UpstreamServiceError) as raised:
            await client.get("https://musicbrainz.org/ws/2/release/")
        self.assertEqual(raised.exception.attempts, 4)
        self.assertEqual(raised.exception.reason, "request timed out")
        self.assertEqual(delays, [2, 4, 8])
        self.assertTrue(all(c.kwargs["timeout"] == 42 for c in self.session.get.call_args_list))

    async def test_slow_musicbrainz_and_other_providers_do_not_wait(self):
        now = [0.0]
        sleep = AsyncMock()
        response = MagicMock()
        response.json = AsyncMock(return_value={})
        self.session.get.return_value = async_response_context(response)
        client = AsyncHttpClient(session=self.session, clock=lambda: now[0], sleep=sleep)
        await client.get("https://musicbrainz.org/ws/2/release/")
        await client.get("https://coverartarchive.org/release/1")
        await client.get("https://www.googleapis.com/youtube/v3/search")
        now[0] += 2
        await client.get("https://musicbrainz.org/ws/2/release/", timeout=7)
        sleep.assert_not_awaited()
        self.assertEqual(self.session.get.call_args.kwargs["timeout"], 7)
        self.assertEqual(self.session.get.call_args_list[1].kwargs["timeout"], 10)

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
