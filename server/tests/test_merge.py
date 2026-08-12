"""Twee series samenvoegen. Uitgangspunt: er mag niets verloren gaan."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from bookpal.library.merge import MergeError, merge, suggest
from bookpal.models import Book, BookKind, Series, Source, Subscription


def _series(session: Session, titel: str, **velden) -> Series:
    series = Series(title=titel, sort_title=titel.lower(), **velden)
    session.add(series)
    session.flush()
    return series


def _books(session: Session, series: Series, aantal: int) -> None:
    for index in range(aantal):
        session.add(
            Book(
                series_id=series.id,
                kind=BookKind.COMIC,
                title=f"Deel {index + 1}",
                number=str(index + 1),
                sort_number=float(index + 1),
            )
        )
    session.flush()


class TestMerge:
    def test_the_books_move_over(self, session: Session):
        blijver = _series(session, "Crayon Shin-chan")
        opgaand = _series(session, "Crayon Shin-Chan")
        _books(session, blijver, 3)
        _books(session, opgaand, 5)

        merge(session, blijver, opgaand)

        assert len(list(session.scalars(select(Book).where(Book.series_id == blijver.id)))) == 8

    def test_the_absorbed_series_is_gone(self, session: Session):
        blijver = _series(session, "A")
        opgaand = _series(session, "A ")
        weg_id = opgaand.id
        merge(session, blijver, opgaand)
        assert session.get(Series, weg_id) is None

    def test_a_series_cannot_swallow_itself(self, session: Session):
        series = _series(session, "A")
        with pytest.raises(MergeError):
            merge(session, series, series)

    def test_an_empty_field_never_overwrites_a_filled_one(self, session: Session):
        """Bij een lokale map + abonnement zou je anders de bron kwijt zijn."""
        blijver = _series(session, "A", summary=None, publisher=None)
        opgaand = _series(session, "A", summary="Een samenvatting", publisher="Uitgever")

        merge(session, blijver, opgaand)

        assert blijver.summary == "Een samenvatting"
        assert blijver.publisher == "Uitgever"

    def test_the_keepers_own_value_wins(self, session: Session):
        blijver = _series(session, "A", summary="Van de blijver")
        opgaand = _series(session, "A", summary="Van de ander")
        merge(session, blijver, opgaand)
        assert blijver.summary == "Van de blijver"

    def test_authors_and_tags_are_combined(self, session: Session):
        blijver = _series(session, "A", authors=["Usui"], tags=["humor"])
        opgaand = _series(session, "A", authors=["Tekenaar"], tags=["school"])
        merge(session, blijver, opgaand)
        assert sorted(blijver.authors) == ["Tekenaar", "Usui"]
        assert sorted(blijver.tags) == ["humor", "school"]

    def test_tracker_ids_come_along(self, session: Session):
        """De lokale kant heeft ze meestal niet; de bron-kant wel."""
        blijver = _series(session, "A")
        opgaand = _series(session, "A", tracker_ids={"mal": "2435"})
        merge(session, blijver, opgaand)
        assert blijver.tracker_ids["mal"] == "2435"

    def test_the_subscription_moves_over(self, session: Session):
        bron = Source(type="mangadex", name="MD")
        session.add(bron)
        session.flush()
        blijver = _series(session, "A")
        opgaand = _series(session, "A", source_id=bron.id, source_ref="abc")
        session.add(Subscription(source_id=bron.id, series_id=opgaand.id))
        session.flush()

        merge(session, blijver, opgaand)

        abo = session.scalar(select(Subscription).where(Subscription.series_id == blijver.id))
        assert abo is not None
        assert blijver.source_id == bron.id
        assert blijver.source_ref == "abc"

    def test_two_subscriptions_do_not_both_survive(self, session: Session):
        """Twee abonnementen op één serie zou dubbel downloaden."""
        bron = Source(type="mangadex", name="MD")
        session.add(bron)
        session.flush()
        blijver = _series(session, "A", source_id=bron.id)
        opgaand = _series(session, "A", source_id=bron.id)
        session.add(Subscription(source_id=bron.id, series_id=blijver.id))
        session.add(Subscription(source_id=bron.id, series_id=opgaand.id))
        session.flush()

        merge(session, blijver, opgaand)

        abos = list(
            session.scalars(select(Subscription).where(Subscription.series_id == blijver.id))
        )
        assert len(abos) == 1


class TestSuggest:
    def test_case_and_punctuation_differences_are_found(self, session: Session):
        _series(session, "Crayon Shin-chan")
        _series(session, "Crayon Shin-Chan")
        session.commit()

        paren = suggest(session)
        assert len(paren) == 1

    def test_the_one_with_a_source_is_kept(self, session: Session):
        """Die houdt het abonnement; de ander levert meestal alleen bestanden."""
        bron = Source(type="mangadex", name="MD")
        session.add(bron)
        session.flush()
        _series(session, "Crayon Shin-Chan")
        met_bron = _series(session, "Crayon Shin-chan", source_id=bron.id)
        session.commit()

        keep, _absorb = suggest(session)[0]
        assert keep.id == met_bron.id

    def test_different_series_are_not_suggested(self, session: Session):
        _series(session, "Oishinbo")
        _series(session, "Shinya Shokudo")
        session.commit()
        assert suggest(session) == []


class TestApi:
    def test_merging_via_the_api(self, client: TestClient, session: Session):
        blijver = _series(session, "Crayon Shin-chan")
        opgaand = _series(session, "Crayon Shin-Chan")
        _books(session, opgaand, 4)
        session.commit()

        response = client.post(
            f"/api/series/{blijver.id}/merge", json={"absorb_id": opgaand.id}
        )
        assert response.status_code == 200
        assert response.json()["book_count"] == 4

    def test_merging_an_unknown_series_is_a_404(self, client: TestClient, session: Session):
        blijver = _series(session, "A")
        session.commit()
        response = client.post(f"/api/series/{blijver.id}/merge", json={"absorb_id": 9999})
        assert response.status_code == 404

    def test_suggestions_are_offered(self, client: TestClient, session: Session):
        _series(session, "Crayon Shin-chan")
        _series(session, "Crayon Shin-Chan")
        session.commit()

        body = client.get("/api/series/merge/suggestions").json()
        assert len(body) == 1
        assert body[0]["keep_title"].lower() == "crayon shin-chan"
