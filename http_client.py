import config
import requests

conf = config.Config()

class HTTP_client:
    def __init__(self, api_key=None):
        self.api_key = api_key
        self.headers = {
            "User-Agent": conf.user_agent
        }        
    
    def get(self, url, params=None, timeout=10):
        response = requests.get(url, headers=self.headers, params=params, timeout=timeout)
        response.raise_for_status()
        return response.json()
    
    def get_binary(self, url, timeout=10):
        response = requests.get(url, headers=self.headers, stream=True, timeout=timeout)
        response.raise_for_status()
        return response
        
########################        
# http_client = HTTP_client(conf.google_api_key)
# print("API key:", http_client.api_key)
# print("User agent:", http_client.user_agent)