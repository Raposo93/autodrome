import json
import redis
from typing import Optional, Dict, Any
from autodrome.logger import logger

class RedisCache:
    def __init__(self, host: str = 'localhost', port: int = 6379, db: int = 0):
        self.client = redis.Redis(host=host, port=port, db=db, decode_responses=True)

    def set_release(self, release_id: str, release_data: Dict[str, Any]) -> None:
        """Guarda en Redis la info de un release como JSON serializado."""
        try:
            json_data = json.dumps(release_data)
            self.client.set(f"release:{release_id}", json_data)
        except Exception as e:
            logger.error(f"Error saving release {release_id} to cache: {e}")
            pass

    def get_release(self, release_id: str) -> Optional[Dict[str, Any]]:
        """Obtiene del cache Redis la info de un release, o None si no existe."""
        try:
            json_data = self.client.get(f"release:{release_id}")
            if json_data:
                return json.loads(json_data)
            return None
        except Exception as e:
            logger.error(f"Error retrieving release {release_id} from cache: {e}")
            return None
