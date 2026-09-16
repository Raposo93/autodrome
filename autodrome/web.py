"""FastAPI application and lifecycle for the installed Autodrome service."""

from contextlib import asynccontextmanager
from pathlib import Path

import aiohttp
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from api.download import download_router
from api.frontend import FrontendFiles
from api.publications import publication_router
from api.search import search_router
from api.status import status_router
from api.websocket import websocket_router
from autodrome import config
from autodrome.controllers.downloader_controller import DownloaderController
from autodrome.controllers.search_controller import SearchController
from autodrome.controllers.publication_controller import PublicationController
from autodrome.http_client_async import AsyncHttpClient
from autodrome.metadata_service import MetadataService
from autodrome.security import extract_bearer_token, token_matches
from autodrome.services import websocket_manager
from autodrome.services.cover_selection import CoverSelectionService
from autodrome.services.download_queue import DownloadQueueManager
from autodrome.services.organizer import Organizer
from autodrome.services.publication_catalog import PublicationCatalog
from autodrome.services.redis_cache import NullCache, RedisCache
from autodrome.services.system_status import SystemStatusService
from autodrome.services.websocket_tickets import WebSocketTicketStore
from autodrome.yt_downloader import YTDownloader
from autodrome.version import build_commit


FRONTEND_DIRECTORY = Path(__file__).resolve().parent / "static"
conf = config.Config()


@asynccontextmanager
async def lifespan(app: FastAPI):
    conf.validate()
    aiohttp_session = aiohttp.ClientSession()
    app.state.aiohttp_session = aiohttp_session

    http_client = AsyncHttpClient(session=aiohttp_session, settings=conf)
    redis_cache = RedisCache() if conf.redis_enabled else NullCache()
    metadata_service = MetadataService(
        http_client=http_client,
        redis_cache=redis_cache,
        cover_art_cache_path=conf.cover_art_cache_path,
    )
    search_controller = SearchController(
        http_client=http_client,
        metadata_service=metadata_service,
    )
    organizer = Organizer()
    publication_catalog = PublicationCatalog(conf.publication_catalog_path)
    cover_selection = CoverSelectionService(
        http_client=http_client,
        embedder=organizer.cover_embedder,
        storage_dir=conf.cover_storage_path,
    )
    downloader_controller = DownloaderController(
        downloader=YTDownloader(
            download_concurrency=conf.download_concurrency,
            deno_path=conf.yt_dlp_deno_path,
        ),
        organizer=organizer,
        metadata_service=metadata_service,
        http_client=http_client,
        cover_selection=cover_selection,
        publication_catalog=publication_catalog,
        application_version=conf.version,
        build_commit=build_commit(),
    )
    publication_controller = PublicationController(
        catalog=publication_catalog,
        downloader=downloader_controller.downloader,
        metadata_service=metadata_service,
    )
    ws_manager = websocket_manager.WebSocketManager()
    queue_manager = DownloadQueueManager(
        downloader_controller,
        ws_manager,
        state_path=conf.queue_state_path,
        cover_selection=cover_selection,
    )
    system_status = SystemStatusService(
        settings=conf,
        http_client=http_client,
        redis_cache=redis_cache,
        queue_manager=queue_manager,
    )

    app.state.http_client = http_client
    app.state.config = conf
    app.state.search_controller = search_controller
    app.state.downloader_controller = downloader_controller
    app.state.publication_controller = publication_controller
    app.state.cover_selection = cover_selection
    app.state.queue_manager = queue_manager
    app.state.system_status = system_status
    app.state.websocket_ticket_store = WebSocketTicketStore()

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
    allow_methods=["GET", "POST", "DELETE"],
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
app.include_router(status_router, prefix="/api/status")
app.include_router(publication_router, prefix="/api/publications")


@app.get("/api/auth")
async def auth_status():
    return {"authenticated": True}


app.mount(
    "/",
    FrontendFiles(directory=FRONTEND_DIRECTORY, check_dir=False),
)
