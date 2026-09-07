import aiohttp
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from api.search import search_router
from api.download import download_router
from api.websocket import websocket_router

from autodrome.http_client_async import AsyncHttpClient
from autodrome.controllers.search_controller import SearchController
from autodrome.controllers.downloader_controller import DownloaderController
from autodrome.services import websocket_manager
from autodrome.services.download_queue import DownloadQueueManager
from autodrome.metadata_service import MetadataService
from autodrome.services.organizer import Organizer
from autodrome.yt_downloader import YTDownloader
from autodrome import config
from autodrome.security import extract_bearer_token, token_matches


conf = config.Config()


@asynccontextmanager
async def lifespan(app: FastAPI):
    conf.validate()
    aiohttp_session = aiohttp.ClientSession()
    app.state.aiohttp_session = aiohttp_session

    http_client = AsyncHttpClient(session=aiohttp_session)
    search_controller = SearchController(http_client=http_client)
    downloader_controller = DownloaderController(
        downloader=YTDownloader(download_concurrency=conf.download_concurrency),
        organizer=Organizer(),
        metadata_service=MetadataService(http_client=http_client),
        http_client=http_client,
    )
    ws_manager = websocket_manager.WebSocketManager()
    queue_manager = DownloadQueueManager(
        downloader_controller,
        ws_manager,
        state_path=conf.queue_state_path,
    )

    app.state.http_client = http_client
    app.state.config = conf
    app.state.search_controller = search_controller
    app.state.downloader_controller = downloader_controller
    app.state.queue_manager = queue_manager

    queue_manager.start()

    try:
        yield
    finally:
        await queue_manager.stop()
        await aiohttp_session.close()


app = FastAPI(lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=conf.cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["Authorization", "Content-Type"],
)


@app.middleware("http")
async def authenticate_external_api(request: Request, call_next):
    if (
        conf.requires_api_token
        and request.method != "OPTIONS"
        and request.url.path.startswith("/api/")
    ):
        provided_token = extract_bearer_token(request.headers.get("Authorization"))
        if not token_matches(conf.api_token, provided_token):
            return JSONResponse(
                status_code=401,
                content={"detail": "A valid bearer token is required"},
                headers={"WWW-Authenticate": "Bearer"},
            )
    return await call_next(request)

app.include_router(search_router, prefix="/api/search")
app.include_router(download_router, prefix="/api/download")
app.include_router(websocket_router)
