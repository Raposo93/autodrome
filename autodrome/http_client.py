from autodrome import config
import requests
from autodrome.logger import logger

conf = config.Config()

class HttpClient:
    def __init__(self, api_key: str = None):
        self.api_key = api_key
        self.headers = {
            "User-Agent": conf.user_agent
        }

    def get(self, url: str, params: dict = None, timeout: int = 10) -> dict:
        try:
            response = requests.get(url, headers=self.headers, params=params, timeout=timeout)
            response.raise_for_status()
            return response.json()
        except requests.RequestException as e:
            logger.error(f"HTTP GET failed: {e} - URL: {url} - Params: {params}")
            raise

    def get_binary(self, url: str, timeout: int = 10) -> requests.Response:
        try:
            response = requests.get(url, headers=self.headers, stream=True, timeout=timeout)
            response.raise_for_status()
            return response
        except requests.RequestException as e:
            logger.error(f"HTTP GET (binary) failed: {e} - URL: {url}")
            raise
        
