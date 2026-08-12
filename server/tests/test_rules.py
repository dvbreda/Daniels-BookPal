"""De regel-engine (ontwerp 2) — de belangrijkste reden om dit vroeg goed te
zetten, dus per veld en combinator uitgetest."""

from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from bookpal.db import current_user
from bookpal.models import Book, BookKind, File, LibraryRoot, OriginRegion, Progress, Series
from bookpal.tabs import RuleError, compile_rule


def _series(session: Session, **kwargs: object) -> Series:
    defaults = {"title": "S", "sort_title": "s", "origin_region": OriginRegion.UNKNOWN}
    defaults.update(kwargs)
    series = Series(**defaults)
    session.add(series)
    session.flush()
    return series


def _book(
    session: Session, series: Series, *, extension: str | None = None, **kwargs: object
) -> Book:
    file_row = None
    if extension is not None:
        file_row = File(
            library_root_id=kwargs.pop("library_root_id", None) or _ensure_root(session).id,
            path=f"/tmp/{series.id}-{extension}-{id(kwargs)}",
            size=1,
            mtime=0.0,
            extension=extension,
        )
        session.add(file_row)
        session.flush()
    defaults: dict[str, object] = {
        "series_id": series.id,
        "kind": BookKind.COMIC,
        "title": "B",
        "file_id": file_row.id if file_row else None,
    }
    defaults.update(kwargs)
    book = Book(**defaults)
    session.add(book)
    session.flush()
    return book


def _ensure_root(session: Session) -> LibraryRoot:
    root = session.scalar(select(LibraryRoot))
    if root is None:
        root = LibraryRoot(name="R", path="/tmp/r")
        session.add(root)
        session.flush()
    return root


def _titles(session: Session, rule: dict) -> set[str]:
    user = current_user(session)
    condition = compile_rule(rule, user=user)
    rows = session.scalars(select(Series).where(condition)).all()
    return {s.title for s in rows}


class TestEmptyRule:
    def test_empty_rule_matches_everything(self, session: Session):
        _series(session, title="A")
        _series(session, title="B")
        assert _titles(session, {}) == {"A", "B"}


class TestScalarFields:
    def test_origin_region_eq(self, session: Session):
        _series(session, title="Europa", origin_region=OriginRegion.EUROPE)
        _series(session, title="Japan", origin_region=OriginRegion.JAPAN)
        rule = {"origin_region": {"eq": "europe"}}
        assert _titles(session, rule) == {"Europa"}

    def test_origin_region_in(self, session: Session):
        _series(session, title="Europa", origin_region=OriginRegion.EUROPE)
        _series(session, title="Japan", origin_region=OriginRegion.JAPAN)
        _series(session, title="Korea", origin_region=OriginRegion.KOREA)
        rule = {"origin_region": {"in": ["europe", "japan"]}}
        assert _titles(session, rule) == {"Europa", "Japan"}

    def test_publisher_contains(self, session: Session):
        _series(session, title="Dupuis-serie", publisher="Dupuis Benelux")
        _series(session, title="Andere", publisher="Kodansha")
        rule = {"publisher": {"contains": "dupuis"}}
        assert _titles(session, rule) == {"Dupuis-serie"}

    def test_root_eq(self, session: Session):
        root_a = LibraryRoot(name="A", path="/tmp/a")
        root_b = LibraryRoot(name="B", path="/tmp/b")
        session.add_all([root_a, root_b])
        session.flush()
        _series(session, title="InA", library_root_id=root_a.id)
        _series(session, title="InB", library_root_id=root_b.id)
        rule = {"root": {"eq": root_a.id}}
        assert _titles(session, rule) == {"InA"}

    def test_series_eq(self, session: Session):
        target = _series(session, title="Target")
        _series(session, title="Other")
        rule = {"series": {"eq": target.id}}
        assert _titles(session, rule) == {"Target"}

    def test_unknown_operator_raises(self, session: Session):
        with pytest.raises(RuleError):
            compile_rule({"origin_region": {"gt": "europe"}}, user=current_user(session))


class TestBookLevelFields:
    def test_extension_normalizes_dot(self, session: Session):
        cbz = _series(session, title="CBZ")
        _book(session, cbz, extension=".cbz")
        epub = _series(session, title="EPUB")
        _book(session, epub, extension=".epub")
        rule = {"extension": {"in": ["cbz", "cbr"]}}
        assert _titles(session, rule) == {"CBZ"}

    def test_kind_eq(self, session: Session):
        comic = _series(session, title="Strip")
        _book(session, comic, kind=BookKind.COMIC)
        epub = _series(session, title="Boek")
        _book(session, epub, kind=BookKind.EPUB)
        rule = {"kind": {"eq": "epub"}}
        assert _titles(session, rule) == {"Boek"}

    def test_source_local_vs_remote(self, session: Session):
        local = _series(session, title="Lokaal")
        _book(session, local, extension=".cbz")
        neither = _series(session, title="ZonderBestandOfBron")
        _book(session, neither)  # geen file, geen source
        assert _titles(session, {"source": {"eq": "local"}}) == {"Lokaal"}
        assert _titles(session, {"source": {"eq": "remote"}}) == set()


class TestTag:
    def test_tag_eq_matches_membership(self, session: Session):
        _series(session, title="Getagd", tags=["favoriet", "compleet"])
        _series(session, title="Ongetagd", tags=[])
        rule = {"tag": {"eq": "favoriet"}}
        assert _titles(session, rule) == {"Getagd"}

    def test_tag_in_matches_any(self, session: Session):
        _series(session, title="A", tags=["x"])
        _series(session, title="B", tags=["y"])
        _series(session, title="C", tags=["z"])
        rule = {"tag": {"in": ["x", "y"]}}
        assert _titles(session, rule) == {"A", "B"}


class TestCombinators:
    def test_and(self, session: Session):
        _series(session, title="Match", origin_region=OriginRegion.EUROPE, publisher="Dupuis")
        _series(session, title="WrongRegion", origin_region=OriginRegion.JAPAN, publisher="Dupuis")
        _series(session, title="WrongPublisher", origin_region=OriginRegion.EUROPE, publisher="X")
        rule = {
            "and": [
                {"origin_region": {"eq": "europe"}},
                {"publisher": {"eq": "Dupuis"}},
            ]
        }
        assert _titles(session, rule) == {"Match"}

    def test_or(self, session: Session):
        _series(session, title="A", origin_region=OriginRegion.EUROPE)
        _series(session, title="B", origin_region=OriginRegion.JAPAN)
        _series(session, title="C", origin_region=OriginRegion.KOREA)
        rule = {"or": [{"origin_region": {"eq": "europe"}}, {"origin_region": {"eq": "japan"}}]}
        assert _titles(session, rule) == {"A", "B"}

    def test_not(self, session: Session):
        _series(session, title="A", origin_region=OriginRegion.EUROPE)
        _series(session, title="B", origin_region=OriginRegion.JAPAN)
        rule = {"not": {"origin_region": {"eq": "europe"}}}
        assert _titles(session, rule) == {"B"}

    def test_nested(self, session: Session):
        _series(session, title="Match", origin_region=OriginRegion.EUROPE, publisher="Dupuis")
        _series(session, title="AlsoMatch", origin_region=OriginRegion.JAPAN, publisher="Shueisha")
        _series(session, title="No", origin_region=OriginRegion.KOREA, publisher="X")
        rule = {
            "or": [
                {"and": [{"origin_region": {"eq": "europe"}}, {"publisher": {"eq": "Dupuis"}}]},
                {"and": [{"origin_region": {"eq": "japan"}}, {"publisher": {"eq": "Shueisha"}}]},
            ]
        }
        assert _titles(session, rule) == {"Match", "AlsoMatch"}

    def test_empty_and_matches_everything(self, session: Session):
        _series(session, title="A")
        assert _titles(session, {"and": []}) == {"A"}

    def test_empty_or_matches_nothing(self, session: Session):
        _series(session, title="A")
        assert _titles(session, {"or": []}) == set()


class TestReadingStatus:
    def _book_with_file(self, session: Session, series: Series) -> Book:
        return _book(session, series, extension=".cbz")

    def test_unread_has_no_progress(self, session: Session):
        series = _series(session, title="Onbegonnen")
        self._book_with_file(session, series)
        assert _titles(session, {"reading_status": {"eq": "unread"}}) == {"Onbegonnen"}

    def test_reading_has_partial_progress(self, session: Session):
        series = _series(session, title="Bezig")
        book = self._book_with_file(session, series)
        user = current_user(session)
        session.add(Progress(user_id=user.id, book_id=book.id, percent=40.0, finished=False))
        session.flush()
        assert _titles(session, {"reading_status": {"eq": "reading"}}) == {"Bezig"}
        assert _titles(session, {"reading_status": {"eq": "unread"}}) == set()

    def test_finished_requires_every_book_finished(self, session: Session):
        series = _series(session, title="Klaar")
        book1 = self._book_with_file(session, series)
        book2 = self._book_with_file(session, series)
        user = current_user(session)
        session.add(Progress(user_id=user.id, book_id=book1.id, percent=100.0, finished=True))
        session.add(Progress(user_id=user.id, book_id=book2.id, percent=50.0, finished=False))
        session.flush()
        # Eén deel nog niet uit: nog "reading", niet "finished".
        assert _titles(session, {"reading_status": {"eq": "finished"}}) == set()

        session.query(Progress).filter_by(book_id=book2.id).update(
            {"finished": True, "percent": 100.0}
        )
        session.flush()
        assert _titles(session, {"reading_status": {"eq": "finished"}}) == {"Klaar"}


class TestValidation:
    def test_unknown_field_raises(self, session: Session):
        with pytest.raises(RuleError):
            compile_rule({"nonsense": {"eq": "x"}}, user=current_user(session))

    def test_malformed_node_raises(self, session: Session):
        with pytest.raises(RuleError):
            compile_rule({"and": "not-a-list"}, user=current_user(session))

    def test_multi_key_node_raises(self, session: Session):
        with pytest.raises(RuleError):
            compile_rule({"and": [], "or": []}, user=current_user(session))
