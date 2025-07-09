import os
import logging
from dotenv import load_dotenv
from autodrome.logger import logger

class Config:
    def __init__(self):
        load_dotenv()
        self.google_api_key = os.getenv("GOOGLE_API_KEY")
        self.contact_email = os.getenv("CONTACT_EMAIL")
        self.version = os.getenv("VERSION")
        self.user_agent = f"{self.version} ({self.contact_email})"
        self.library_path = os.getenv("LIBRARY_PATH", "library")


        log_level_str = os.getenv("LOG_LEVEL", "INFO").upper()
        log_level = getattr(logging, log_level_str, logging.INFO)

        logger.setLevel(log_level)
        # logger.info(f"Config loaded. User-Agent: {self.user_agent}")
        # logger.info(f"Library path: {self.library_path}")

