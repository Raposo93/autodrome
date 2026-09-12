import json
import redis
from typing import Any, Dict, Optional, Protocol
from autodrome.logger import logger


class ReleaseCache(Protocol):
    """Best-effort cache contract used by release metadata workflows."""

    def set_release(self, release_id: str, release_data: Dict[str, Any]) -> None:
        ...

    def get_release(self, release_id: str) -> Optional[Dict[str, Any]]:
        ...


class NullCache:
    """Disabled cache implementation that performs no I/O."""

    def set_release(self, release_id: str, release_data: Dict[str, Any]) -> None:
        return None

    def get_release(self, release_id: str) -> Optional[Dict[str, Any]]:
        return None

    def ping(self) -> bool:
        return False


class RedisCache:
    """Best-effort Redis cache whose failures never block the primary workflow."""

    def __init__(
        self,
        host: str = "localhost",
        port: int = 6379,
        db: int = 0,
        client=None,
    ):
        self.client = client if client is not None else redis.Redis(
            host=host,
            port=port,
            db=db,
            decode_responses=True,
            socket_connect_timeout=2,
            socket_timeout=2,
        )
        self._unavailable = False

    def ping(self) -> bool:
        return bool(self.client.ping())

    def set_release(self, release_id: str, release_data: Dict[str, Any]) -> None:
        """Guarda en Redis la info de un release como JSON serializado."""
        try:
            json_data = json.dumps(release_data)
            self.client.set(f"release:{release_id}", json_data)
            self._report_recovered()
        except Exception as e:
            self._report_unavailable(e)

    def get_release(self, release_id: str) -> Optional[Dict[str, Any]]:
        """Obtiene del cache Redis la info de un release, o None si no existe."""
        try:
            json_data = self.client.get(f"release:{release_id}")
            self._report_recovered()
            if json_data:
                return json.loads(json_data)
            return None
        except Exception as e:
            self._report_unavailable(e)
            return None

    def _report_unavailable(self, error: Exception) -> None:
        if isinstance(error, (ConnectionError, redis.exceptions.ConnectionError)):
            reason = "connection_failed"
        elif isinstance(error, (TimeoutError, redis.exceptions.TimeoutError)):
            reason = "timeout"
        else:
            reason = type(error).__name__
        if not self._unavailable:
            self._unavailable = True
            logger.warning(
                "redis_unavailable reason=%s",
                reason,
            )
        else:
            logger.debug("redis_operation_failed reason=%s", reason)

    def _report_recovered(self) -> None:
        if self._unavailable:
            self._unavailable = False
            logger.info("redis_recovered")
