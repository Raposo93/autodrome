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

    def ping(self) -> bool:
        return bool(self.client.ping())

    def set_release(self, release_id: str, release_data: Dict[str, Any]) -> None:
        """Guarda en Redis la info de un release como JSON serializado."""
        try:
            json_data = json.dumps(release_data)
            self.client.set(f"release:{release_id}", json_data)
        except Exception as e:
            logger.warning(f"Could not save release {release_id} to Redis cache: {e}")

    def get_release(self, release_id: str) -> Optional[Dict[str, Any]]:
        """Obtiene del cache Redis la info de un release, o None si no existe."""
        try:
            json_data = self.client.get(f"release:{release_id}")
            if json_data:
                return json.loads(json_data)
            return None
        except Exception as e:
            logger.warning(f"Could not retrieve release {release_id} from Redis cache: {e}")
            return None
