# autodrome/services/download_queue.py

import asyncio
from typing import Dict, Optional

from autodrome.controllers.downloader_controller import DownloaderController
from autodrome.logger import logger


class DownloadQueueManager:
    REQUIRED_KEYS = {"playlist_url", "artist", "album", "release_id"}

    def __init__(self, downloader: DownloaderController):
        self.queue = asyncio.Queue()
        self.downloader = downloader
        self._worker_running = False
        self.worker_task = None


    async def enqueue(self, payload: Dict):
        missing = self.REQUIRED_KEYS - payload.keys()
        if missing:
            logger.error(f"Payload is missing required keys: {missing}")
            return

        await self.queue.put(payload)
        logger.info(f"Playlist enqueued: {payload.get('album')}")
        if not self._worker_running:
            asyncio.create_task(self._worker())

    async def _worker(self):
        self._worker_running = True
        logger.info("DownloadQueueManager: worker started")
        while True:
            item = await self.queue.get()
            try:
                logger.debug(f"Processing playlist: {item.get('album')}")

                playlist_url = item["playlist_url"]
                artist = item["artist"]
                album = item["album"]
                release_id = item["release_id"]
                track_count = item.get("track_count")

                logger.info(f"playlist_url: {playlist_url}")
                logger.info(f"artist: {artist}")
                logger.info(f"album: {album}")
                logger.info(f"release_id: {release_id}")
                logger.info(f"track_count: {track_count}")

                await self.downloader.download_and_tag(
                    playlist_url=playlist_url,
                    artist=artist,
                    album=album,
                    release_id=release_id,
                    track_count=track_count
                )
                logger.info(f"Completed playlist: {album}")
            except Exception as e:
                logger.error(f"Error processing playlist: {e}")
            finally:
                self.queue.task_done()
