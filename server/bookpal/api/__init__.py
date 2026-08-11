"""REST-API. Elke client (web, Lite, iOS, Kobo) hangt aan dit contract."""

from fastapi import APIRouter

from bookpal.api import (
    books,
    collections,
    libraries,
    lite,
    opds,
    progress,
    series,
    sources,
    system,
    tabs,
    trackers,
    translate,
)

router = APIRouter()
router.include_router(system.router)
router.include_router(libraries.router)
router.include_router(series.router)
router.include_router(books.router)
router.include_router(progress.router)
router.include_router(tabs.router)
router.include_router(collections.router)
router.include_router(sources.router)
router.include_router(trackers.router)
router.include_router(translate.router)
router.include_router(translate.settings_router)
router.include_router(lite.router)
router.include_router(opds.router)

__all__ = ["router"]
