import asyncio
import aiohttp
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.search import search_router
from api.download import download_router

from autodrome.http_client_async import AsyncHttpClient
from autodrome.controllers.search_controller import SearchController
from autodrome.controllers.downloader_controller import DownloaderController
from autodrome.services.download_queue import DownloadQueueManager
from autodrome.metadata_service import MetadataService
from autodrome.services.organizer import Organizer
from autodrome.yt_downloader import YTDownloader


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Crear sesión HTTP reutilizable
    aiohttp_session = aiohttp.ClientSession()
    app.state.aiohttp_session = aiohttp_session

    # Crear cliente y controlador con esa sesión
    http_client = AsyncHttpClient(session=aiohttp_session)
    search_controller = SearchController(http_client=http_client)
    downloader_controller = DownloaderController(
        downloader=YTDownloader(),
        organizer=Organizer(),
        metadata_service=MetadataService(http_client=http_client),
        http_client=http_client,
    )
    queue_manager = DownloadQueueManager(downloader_controller)

    # Guardar en estado de la app
    app.state.http_client = http_client
    app.state.search_controller = search_controller
    app.state.downloader_controller = downloader_controller
    app.state.queue_manager = queue_manager

    # Iniciar el worker de la cola
    if not queue_manager._worker_running:
        asyncio.create_task(queue_manager._worker())  # enqueue vacío solo para lanzar el worker

    yield

    # Al cerrar, cerrar la sesión http
    await aiohttp_session.close()


app = FastAPI(lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Ajustar esto en producción
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(search_router, prefix="/api/search")
app.include_router(download_router, prefix="/api/download")
