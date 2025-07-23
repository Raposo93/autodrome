# autodrome/services/download_queue.py

import asyncio
from typing import Dict, Optional

from autodrome.controllers.downloader_controller import DownloaderController
from autodrome.logger import logger


class DownloadQueueManager:
    REQUIRED_KEYS = {"playlist_url", "artist", "album", "release_id"}

    def __init__(self, downloader: DownloaderController, websocket_manager):
        self.queue: asyncio.Queue[Dict] = asyncio.Queue()
        self._queue_snapshot: list[Dict] = []
        self.downloader = downloader
        self._worker_running = False
        self.worker_task = None
        self.websocket_manager = websocket_manager


    async def enqueue(self, payload: Dict):
        
        if missing:= self.REQUIRED_KEYS - payload.keys():
            logger.error(f"Payload is missing required keys: {missing}")
            return
        
        await self.queue.put(payload)
        self._queue_snapshot.append(payload)
        
        queue_list = list(self._queue_snapshot)
        await self.websocket_manager.broadcast(queue_list)
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
                
                await self.downloader.download_and_tag(
                    playlist_url=playlist_url,
                    artist=artist,
                    album=album,
                    release_id=release_id,
                    track_count=track_count
                )
                logger.info(f"Completed playlist: {album}")
                self._queue_snapshot = [q for q in self._queue_snapshot if q != item]
                queue_list = list(self._queue_snapshot)
                await self.websocket_manager.broadcast(queue_list)
            except Exception as e:
                logger.error(f"Error processing playlist: {e}")
            finally:
                self.queue.task_done()
