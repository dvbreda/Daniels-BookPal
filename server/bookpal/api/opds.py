"""OPDS 1.2: catalogfeed voor apps die dat al spreken (Chunky, KyBook, ...).

Klein en goedkoop vangnet naast de eigen web-app en Lite (docs/architectuur.md).
Twee niveaus: een navigatiefeed met series, en per serie een acquisitiefeed met
de boeken erin — elk entry linkt naar het bronbestand via
``/api/books/{id}/file``, precies zoals de web-app dat al ophaalt.
"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response
from lxml import etree
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from bookpal.db import get_session
from bookpal.models import File, Series

from . import deps

router = APIRouter(prefix="/opds", tags=["opds"])

ATOM_NS = "http://www.w3.org/2005/Atom"
NSMAP = {None: ATOM_NS}

NAV_TYPE = "application/atom+xml;profile=opds-catalog;kind=navigation"
ACQ_TYPE = "application/atom+xml;profile=opds-catalog;kind=acquisition"

_ACQUISITION_TYPES: dict[str, str] = {
    ".cbz": "application/vnd.comicbook+zip",
    ".cbr": "application/x-cbr",
    ".cb7": "application/x-cb7",
    ".epub": "application/epub+zip",
    ".pdf": "application/pdf",
}


def _el(parent: etree._Element, tag: str, text: str | None = None, **attrib: str) -> etree._Element:
    child = etree.SubElement(parent, f"{{{ATOM_NS}}}{tag}", attrib=attrib)
    if text is not None:
        child.text = text
    return child


def _feed(*, feed_id: str, title: str, self_href: str, kind_type: str) -> etree._Element:
    feed = etree.Element(f"{{{ATOM_NS}}}feed", nsmap=NSMAP)
    _el(feed, "id", feed_id)
    _el(feed, "title", title)
    _el(feed, "updated", datetime.now().astimezone().isoformat(timespec="seconds"))
    _el(feed, "link", rel="self", href=self_href, type=kind_type)
    _el(feed, "link", rel="start", href="/opds", type=NAV_TYPE)
    return feed


def _xml_response(feed: etree._Element) -> Response:
    body = etree.tostring(feed, xml_declaration=True, encoding="utf-8", pretty_print=True)
    return Response(content=body, media_type="application/atom+xml")


@router.get("")
def opds_root(
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
    session: Session = Depends(get_session),
) -> Response:
    """Eén niveau: alle series. Tabs (M3) groeperen dit later verder."""
    total = int(session.scalar(select(func.count(Series.id))) or 0)
    rows = session.scalars(
        select(Series).order_by(Series.sort_title).offset(offset).limit(limit)
    ).all()

    feed = _feed(
        feed_id="urn:bookpal:root",
        title="Daniels BookPal",
        self_href="/opds",
        kind_type=NAV_TYPE,
    )
    if offset + limit < total:
        href = f"/opds?offset={offset + limit}&limit={limit}"
        _el(feed, "link", rel="next", href=href, type=NAV_TYPE)
    if offset > 0:
        prev_offset = max(0, offset - limit)
        href = f"/opds?offset={prev_offset}&limit={limit}"
        _el(feed, "link", rel="previous", href=href, type=NAV_TYPE)

    for series in rows:
        entry = _el(feed, "entry")
        _el(entry, "id", f"urn:bookpal:series:{series.id}")
        _el(entry, "title", series.title)
        _el(entry, "updated", series.created_at.astimezone().isoformat(timespec="seconds"))
        _el(entry, "link", rel="subsection", href=f"/opds/series/{series.id}", type=ACQ_TYPE)
    return _xml_response(feed)


@router.get("/series/{series_id}")
def opds_series(series_id: int, session: Session = Depends(get_session)) -> Response:
    series = deps.get_series(session, series_id)
    books = list(series.books)
    extensions = {
        row.id: row.extension
        for row in session.scalars(
            select(File).where(File.id.in_([b.file_id for b in books if b.file_id]))
        )
    }

    feed = _feed(
        feed_id=f"urn:bookpal:series:{series.id}",
        title=series.title,
        self_href=f"/opds/series/{series.id}",
        kind_type=ACQ_TYPE,
    )

    for book in books:
        entry = _el(feed, "entry")
        _el(entry, "id", f"urn:bookpal:book:{book.id}")
        _el(entry, "title", book.title if not book.number else f"{book.number} — {book.title}")
        _el(entry, "updated", book.added_at.astimezone().isoformat(timespec="seconds"))
        if book.file_id and (extension := extensions.get(book.file_id)):
            media_type = _ACQUISITION_TYPES.get(extension, "application/octet-stream")
            _el(
                entry,
                "link",
                rel="http://opds-spec.org/acquisition",
                href=f"/api/books/{book.id}/file",
                type=media_type,
            )
        _el(
            entry,
            "link",
            rel="http://opds-spec.org/image/thumbnail",
            href=f"/api/books/{book.id}/cover?profile=thumb",
            type="image/webp",
        )
    return _xml_response(feed)
