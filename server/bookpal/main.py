"""FastAPI-applicatie."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from bookpal.api import router
from bookpal.config import settings
from bookpal.db import init_db
from bookpal.formats import book_cache
from bookpal.sources.worker import start_worker, stop_worker
from bookpal.trackers.scheduler import stop_all as stop_tracker_scheduler

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)

# De gebouwde web-app, als die er is. In ontwikkeling draait Vite apart.
WEB_DIST = Path(__file__).resolve().parent.parent.parent / "web" / "dist"


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    settings.ensure_dirs()
    init_db()
    logger.info("BookPal gestart — data in %s", settings.data_dir.resolve())
    start_worker()
    yield
    stop_worker()
    stop_tracker_scheduler()
    book_cache.clear()


app = FastAPI(
    title="Daniels BookPal",
    version="0.1.0",
    description="Bibliotheekserver voor comics, manga en boeken.",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)


def mount_web() -> None:
    """Serveer de gebouwde web-app als die naast de server staat."""
    if not WEB_DIST.is_dir():
        return

    app.mount("/assets", StaticFiles(directory=WEB_DIST / "assets"), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa(full_path: str) -> FileResponse:
        # Alles wat geen API of bestand is, gaat naar de app zelf: de router
        # draait in de browser.
        candidate = WEB_DIST / full_path
        if full_path and candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(WEB_DIST / "index.html")


mount_web()
