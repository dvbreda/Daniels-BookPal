from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from bookpal import db as db_module
from bookpal.config import settings
from bookpal.models import LibraryRoot, OriginRegion


@pytest.fixture
def temp_settings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """Elke test krijgt een eigen database en cachemap."""
    data_dir = tmp_path / "data"
    monkeypatch.setattr(settings, "data_dir", data_dir)
    monkeypatch.setattr(settings, "cache_dir", data_dir / "cache")
    db_module.reset_engine()
    settings.ensure_dirs()
    yield data_dir
    db_module.reset_engine()


@pytest.fixture
def session(temp_settings: Path) -> Iterator[Session]:
    db_module.init_db()
    with db_module.session_scope() as sess:
        yield sess


@pytest.fixture
def library_root(tmp_path: Path) -> Path:
    root = tmp_path / "library"
    root.mkdir(parents=True, exist_ok=True)
    return root


def make_root(
    session: Session,
    path: Path,
    name: str = "Test",
    *,
    default_region: OriginRegion | None = None,
    default_language: str | None = None,
) -> LibraryRoot:
    root = LibraryRoot(
        name=name,
        path=str(path),
        default_origin_region=default_region,
        default_origin_language=default_language,
    )
    session.add(root)
    session.flush()
    return root
