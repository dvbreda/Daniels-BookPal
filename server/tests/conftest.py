from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from bookpal import db as db_module
from bookpal.config import settings
from bookpal.main import app
from bookpal.models import LibraryRoot, OriginRegion
from tests.fixtures import comicinfo_xml, make_cbz, make_epub, make_pdf


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


@pytest.fixture
def client(temp_settings: Path) -> Iterator[TestClient]:
    db_module.init_db()
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def library(tmp_path: Path) -> Path:
    root = tmp_path / "collectie"
    make_cbz(
        root / "strips" / "Storm 01.cbz",
        pages=5,
        comicinfo=comicinfo_xml(series="Storm", number="1", publisher="Dupuis"),
    )
    make_cbz(
        root / "strips" / "Storm 02.cbz",
        pages=3,
        comicinfo=comicinfo_xml(series="Storm", number="2", publisher="Dupuis"),
    )
    make_cbz(
        root / "manga" / "Tesuto 01.cbz",
        pages=4,
        comicinfo=comicinfo_xml(series="Tesuto", number="1", manga="YesAndRightToLeft"),
    )
    make_epub(root / "boeken" / "Een Testboek.epub")
    make_pdf(root / "boeken" / "Een Testdocument.pdf", pages=2)
    return root


@pytest.fixture
def scanned(client: TestClient, library: Path) -> TestClient:
    response = client.post("/api/libraries", json={"name": "Collectie", "path": str(library)})
    assert response.status_code == 201
    root_id = response.json()["id"]
    scan = client.post(f"/api/libraries/{root_id}/scan")
    assert scan.status_code == 200, scan.text
    assert scan.json()["added"] == 5
    return client
