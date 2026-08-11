"""REST-API. Elke client (web, Lite, iOS, Kobo) hangt aan dit contract."""

from fastapi import APIRouter

from bookpal.api import books, libraries, lite, progress, series, system

router = APIRouter()
router.include_router(system.router)
router.include_router(libraries.router)
router.include_router(series.router)
router.include_router(books.router)
router.include_router(progress.router)
router.include_router(lite.router)

__all__ = ["router"]
