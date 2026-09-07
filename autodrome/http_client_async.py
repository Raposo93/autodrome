import asyncio
from typing import Awaitable, Callable, Dict, Optional, TypeVar
from urllib.parse import urlsplit

import aiohttp

from autodrome import config
from autodrome.logger import logger


conf = config.Config()
ResponseValue = TypeVar("ResponseValue")


class UpstreamServiceError(RuntimeError):
    def __init__(
        self,
        provider: str,
        context: str,
        reason: str,
        attempts: int = 1,
        status: Optional[int] = None,
    ) -> None:
        self.provider = provider
        self.context = context
        self.reason = reason
        self.attempts = attempts
        self.status = status
        attempt_detail = f" after {attempts} attempts" if attempts > 1 else ""
        super().__init__(
            f"{provider} failed while {context}: {reason}{attempt_detail}"
        )


class AsyncHttpClient:
    DEFAULT_PROVIDER_LIMITS = {
        "MusicBrainz": 1,
        "Cover Art Archive": 2,
        "YouTube": 4,
        "External service": 4,
    }

    def __init__(
        self,
        api_key: Optional[str] = None,
        session: Optional[aiohttp.ClientSession] = None,
        provider_limits: Optional[Dict[str, int]] = None,
        max_attempts: int = 3,
        retry_base_seconds: float = 0.25,
        sleep: Optional[Callable[[float], Awaitable[None]]] = None,
    ) -> None:
        self.api_key = api_key
        self.session = session
        self._own_session = False
        self.headers = {"User-Agent": conf.user_agent}
        self.provider_limits = {
            **self.DEFAULT_PROVIDER_LIMITS,
            **(provider_limits or {}),
        }
        if any(limit < 1 for limit in self.provider_limits.values()):
            raise ValueError("Provider concurrency limits must be positive")
        if max_attempts < 1:
            raise ValueError("max_attempts must be positive")
        if retry_base_seconds < 0:
            raise ValueError("retry_base_seconds cannot be negative")
        self.max_attempts = max_attempts
        self.retry_base_seconds = retry_base_seconds
        self._sleep = sleep or asyncio.sleep
        self._provider_semaphores: Dict[str, asyncio.Semaphore] = {}

    async def __aenter__(self):
        if not self.session:
            self.session = aiohttp.ClientSession()
            self._own_session = True
        return self

    async def __aexit__(self, exc_type, exc, tb):
        if self._own_session and self.session:
            await self.session.close()

    async def get(
        self,
        url: str,
        params: Optional[dict] = None,
        timeout: int = 10,
        provider: Optional[str] = None,
        context: str = "performing a GET request",
    ) -> dict:
        return await self._request(
            "get",
            url,
            lambda response: response.json(),
            params=params,
            timeout=timeout,
            provider=provider,
            context=context,
        )

    async def post(
        self,
        url: str,
        data=None,
        json=None,
        timeout: int = 10,
        provider: Optional[str] = None,
        context: str = "performing a POST request",
    ) -> dict:
        return await self._request(
            "post",
            url,
            lambda response: response.json(),
            data=data,
            json=json,
            timeout=timeout,
            provider=provider,
            context=context,
        )

    async def get_binary(
        self,
        url: str,
        timeout: int = 10,
        provider: Optional[str] = None,
        context: str = "downloading binary content",
    ) -> bytes:
        return await self._request(
            "get",
            url,
            lambda response: response.read(),
            timeout=timeout,
            provider=provider,
            context=context,
        )

    async def _request(
        self,
        method_name: str,
        url: str,
        read_response: Callable[[aiohttp.ClientResponse], Awaitable[ResponseValue]],
        *,
        provider: Optional[str],
        context: str,
        timeout: int,
        **request_kwargs,
    ) -> ResponseValue:
        if self.session is None:
            raise RuntimeError("AsyncHttpClient requires an active HTTP session")

        provider_name = provider or self._provider_for_url(url)
        semaphore = self._provider_semaphores.setdefault(
            provider_name,
            asyncio.Semaphore(
                self.provider_limits.get(
                    provider_name,
                    self.provider_limits["External service"],
                )
            ),
        )

        async with semaphore:
            for attempt in range(1, self.max_attempts + 1):
                try:
                    request = getattr(self.session, method_name)
                    async with request(
                        url,
                        headers=self.headers,
                        timeout=timeout,
                        **request_kwargs,
                    ) as response:
                        response.raise_for_status()
                        return await read_response(response)
                except Exception as error:
                    status = getattr(error, "status", None)
                    retryable = self._is_retryable(error, status)
                    if retryable and attempt < self.max_attempts:
                        delay = self.retry_base_seconds * (2 ** (attempt - 1))
                        status_context = (
                            f"HTTP {status}" if status is not None else "timeout"
                        )
                        logger.warning(
                            f"{provider_name} {status_context} while {context}; "
                            f"retrying in {delay:.2f}s "
                            f"({attempt + 1}/{self.max_attempts})"
                        )
                        await self._sleep(delay)
                        continue

                    reason = self._safe_reason(error, status)
                    raise UpstreamServiceError(
                        provider=provider_name,
                        context=context,
                        reason=reason,
                        attempts=attempt,
                        status=status,
                    ) from error

        raise AssertionError("unreachable")

    @staticmethod
    def _is_retryable(error: Exception, status: Optional[int]) -> bool:
        return (
            status == 429
            or (isinstance(status, int) and 500 <= status < 600)
            or isinstance(
                error,
                (
                    asyncio.TimeoutError,
                    aiohttp.ServerTimeoutError,
                    aiohttp.ClientConnectionError,
                ),
            )
        )

    @staticmethod
    def _safe_reason(error: Exception, status: Optional[int]) -> str:
        if status is not None:
            return f"HTTP {status}"
        if isinstance(error, (asyncio.TimeoutError, aiohttp.ServerTimeoutError)):
            return "request timed out"
        if isinstance(error, aiohttp.ClientConnectionError):
            return "connection failed"
        if isinstance(error, aiohttp.ClientError):
            return "HTTP client error"
        return "unexpected response error"

    @staticmethod
    def _provider_for_url(url: str) -> str:
        hostname = (urlsplit(url).hostname or "").lower()
        if hostname == "musicbrainz.org" or hostname.endswith(".musicbrainz.org"):
            return "MusicBrainz"
        if hostname == "coverartarchive.org" or hostname.endswith(
            ".coverartarchive.org"
        ):
            return "Cover Art Archive"
        if hostname == "googleapis.com" or hostname.endswith(".googleapis.com"):
            return "YouTube"
        return "External service"
