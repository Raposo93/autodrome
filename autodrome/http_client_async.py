import aiohttp
from autodrome import config

conf = config.Config()

class AsyncHttpClient:
    def __init__(self, api_key: str = None, session: aiohttp.ClientSession = None):
        self.api_key = api_key
        self.session = session
        self._own_session = False
        self.headers = {"User-Agent": conf.user_agent}
        
    async def __aenter__(self):
        if not self.session:
            self.session = aiohttp.ClientSession()
            self._own_session = True
        return self
    
    async def __aexit__(self, exc_type, exc, tb):
        if self._own_session and self.session:
            await self.session.close()

    async def get(self, url: str, params: dict = None, timeout: int = 10) -> dict:
        async with self.session.get(url, headers=self.headers, params=params, timeout=timeout) as resp:
            resp.raise_for_status()
            return await resp.json()

    async def post(self, url: str, data=None, json=None, timeout: int = 10) -> dict:
        async with self.session.post(url, headers=self.headers, data=data, json=json, timeout=timeout) as resp:
            resp.raise_for_status()
            return await resp.json()

    async def get_binary(self, url: str, timeout: int = 10) -> bytes:
        async with self.session.get(url, headers=self.headers, timeout=timeout) as resp:
            resp.raise_for_status()
            return await resp.read()
