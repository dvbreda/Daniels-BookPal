"""Wikipedia-achtergrond bij een serie.

Zonder net: `search` wordt vervangen. Een test die Wikipedia opvraagt faalt
zodra je in de trein zit en zegt bovendien niets over wat deze route zelf doet
— dat is termen kiezen, talen proberen en dubbelen weglaten.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from bookpal.db import session_scope
from bookpal.models import Series
from bookpal.wiki import WikiError, WikiHit


@pytest.fixture
def storm(scanned: TestClient) -> int:
    with session_scope() as s:
        reeks = s.scalar(select(Series).where(Series.title == "Storm"))
        reeks.authors = ["Don Lawrence", "Martin Lodewijk"]
        s.commit()
        return reeks.id


def _nep(monkeypatch, antwoorden: dict[tuple[str, str], list[WikiHit] | Exception]):
    def zoek(query: str, *, lang: str = "nl", limit: int = 5) -> list[WikiHit]:
        uitkomst = antwoorden.get((query, lang), [])
        if isinstance(uitkomst, Exception):
            raise uitkomst
        return uitkomst

    monkeypatch.setattr("bookpal.api.wiki.search", zoek)


def _hit(titel: str, taal: str = "nl") -> WikiHit:
    return WikiHit(title=titel, key=titel.replace(" ", "_"), description=None, lang=taal)


class TestVoorSerie:
    def test_the_series_and_its_makers_are_looked_up(self, scanned, storm, monkeypatch):
        _nep(monkeypatch, {
            ("Storm", "nl"): [_hit("Storm (stripreeks)")],
            ("Don Lawrence", "nl"): [_hit("Don Lawrence")],
            ("Martin Lodewijk", "nl"): [_hit("Martin Lodewijk")],
        })
        gevonden = scanned.get(f"/api/wiki/for-series/{storm}").json()
        assert [g["rol"] for g in gevonden] == ["reeks", "maker", "maker"]
        assert gevonden[0]["title"] == "Storm (stripreeks)"

    def test_english_is_the_fallback(self, scanned, storm, monkeypatch):
        """Over een Nederlandse reeks staat soms alleen daar iets, en andersom."""
        _nep(monkeypatch, {("Storm", "en"): [_hit("Storm (comics)", "en")]})
        gevonden = scanned.get(f"/api/wiki/for-series/{storm}").json()
        assert gevonden[0]["lang"] == "en"

    def test_a_maker_without_an_article_does_not_break_the_rest(
        self, scanned, storm, monkeypatch
    ):
        """Een tekenaar zonder artikel is de normaalste zaak."""
        _nep(monkeypatch, {
            ("Storm", "nl"): [_hit("Storm (stripreeks)")],
            ("Don Lawrence", "nl"): WikiError("niets"),
            ("Martin Lodewijk", "nl"): [_hit("Martin Lodewijk")],
        })
        titels = [g["title"] for g in scanned.get(f"/api/wiki/for-series/{storm}").json()]
        assert titels == ["Storm (stripreeks)", "Martin Lodewijk"]

    def test_the_same_article_is_not_offered_twice(self, scanned, storm, monkeypatch):
        _nep(monkeypatch, {
            ("Storm", "nl"): [_hit("Don Lawrence")],
            ("Don Lawrence", "nl"): [_hit("Don Lawrence")],
        })
        gevonden = scanned.get(f"/api/wiki/for-series/{storm}").json()
        assert len(gevonden) == 1

    def test_nothing_found_is_an_empty_list_and_not_an_error(
        self, scanned, storm, monkeypatch
    ):
        _nep(monkeypatch, {})
        antwoord = scanned.get(f"/api/wiki/for-series/{storm}")
        assert antwoord.status_code == 200
        assert antwoord.json() == []

    def test_an_unknown_series_is_a_404(self, scanned):
        assert scanned.get("/api/wiki/for-series/99999").status_code == 404
