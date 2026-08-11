"""REST-API. Elke client (web, Lite, iOS, Kobo) hangt aan dit contract."""

from fastapi import APIRouter

from bookpal.api import books, libraries, progress, series, system

router = APIRouter()
router.include_router(system.router)
router.include_router(libraries.router)
router.include_router(series.router)
router.include_router(books.router)
router.include_router(progress.router)

__all__ = ["router"]
