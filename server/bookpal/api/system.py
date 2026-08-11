"""Status, beeldprofielen en cachebeheer."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from bookpal.db import get_session
from bookpal.images import PROFILES, cache_size_bytes, clear_cache, prune_cache
from bookpal.models import Book, LibraryRoot, Series
from bookpal.schemas import ProfileOut

router = APIRouter(prefix="/api", tags=["system"])


class HealthOut(BaseModel):
    status: str
    version: str
    roots: int
    series: int
    books: int
    cache_mb: float


@router.get("/health", response_model=HealthOut)
def health(session: Session = Depends(get_session)) -> HealthOut:
    return HealthOut(
        status="ok",
        version="0.1.0",
        roots=int(session.scalar(select(func.count(LibraryRoot.id))) or 0),
        series=int(session.scalar(select(func.count(Series.id))) or 0),
        books=int(session.scalar(select(func.count(Book.id))) or 0),
        cache_mb=round(cache_size_bytes() / (1024 * 1024), 2),
    )


@router.get("/profiles", response_model=list[ProfileOut])
def list_profiles() -> list[ProfileOut]:
    """De beeldprofielen die clients kunnen opvragen.

    De web-app kiest hieruit op schermbreedte; de Kobo-app straks op paneeltype.
    """
    return [
        ProfileOut(
            name=profile.name,
            max_width=profile.max_width,
            max_height=profile.max_height,
            format=profile.format,
            grayscale=profile.grayscale,
        )
        for profile in sorted(PROFILES.values(), key=lambda p: p.name)
    ]


class CacheActionOut(BaseModel):
    removed: int
    cache_mb: float


@router.post("/cache/prune", response_model=CacheActionOut)
def prune() -> CacheActionOut:
    removed = prune_cache()
    return CacheActionOut(removed=removed, cache_mb=round(cache_size_bytes() / (1024 * 1024), 2))


@router.delete("/cache", response_model=CacheActionOut)
def clear() -> CacheActionOut:
    clear_cache()
    return CacheActionOut(removed=0, cache_mb=0.0)
