"""OPDS 1.2: catalogfeed voor apps die dat al spreken."""

from __future__ import annotations

from fastapi.testclient import TestClient
from lxml import etree

ATOM_NS = "http://www.w3.org/2005/Atom"


def _entries(xml_bytes: bytes) -> list[etree._Element]:
    root = etree.fromstring(xml_bytes)
    return root.findall(f"{{{ATOM_NS}}}entry")


class TestOpdsRoot:
    def test_root_is_a_navigation_feed(self, scanned: TestClient):
        response = scanned.get("/opds")
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("application/atom+xml")
        root = etree.fromstring(response.content)
        assert root.tag == f"{{{ATOM_NS}}}feed"

    def test_root_lists_series_as_subsections(self, scanned: TestClient):
        response = scanned.get("/opds")
        entries = _entries(response.content)
        titles = {e.findtext(f"{{{ATOM_NS}}}title") for e in entries}
        assert titles == {"Storm", "Tesuto", "Een Testboek", "Een Testdocument"}
        for entry in entries:
            link = entry.find(f"{{{ATOM_NS}}}link")
            assert link.get("rel") == "subsection"
            assert link.get("href").startswith("/opds/series/")

    def test_pagination_link(self, scanned: TestClient):
        response = scanned.get("/opds", params={"limit": 2})
        root = etree.fromstring(response.content)
        rels = {
            link.get("rel")
            for link in root.findall(f"{{{ATOM_NS}}}link")
        }
        assert "next" in rels
        assert "previous" not in rels


class TestOpdsSeries:
    def _series_id(self, client: TestClient, title: str) -> int:
        return next(
            item["id"]
            for item in client.get("/api/series").json()["items"]
            if item["title"] == title
        )

    def test_series_feed_is_acquisition(self, scanned: TestClient):
        series_id = self._series_id(scanned, "Storm")
        response = scanned.get(f"/opds/series/{series_id}")
        assert response.status_code == 200
        entries = _entries(response.content)
        assert len(entries) == 2

    def test_entry_has_acquisition_and_thumbnail_links(self, scanned: TestClient):
        series_id = self._series_id(scanned, "Storm")
        response = scanned.get(f"/opds/series/{series_id}")
        entry = _entries(response.content)[0]
        links = entry.findall(f"{{{ATOM_NS}}}link")
        rels = {link.get("rel") for link in links}
        assert "http://opds-spec.org/acquisition" in rels
        assert "http://opds-spec.org/image/thumbnail" in rels

        acquisition = next(
            link for link in links if link.get("rel") == "http://opds-spec.org/acquisition"
        )
        assert acquisition.get("type") == "application/vnd.comicbook+zip"
        assert acquisition.get("href").endswith("/file")

    def test_acquisition_link_is_downloadable(self, scanned: TestClient):
        series_id = self._series_id(scanned, "Storm")
        feed = scanned.get(f"/opds/series/{series_id}")
        href = _entries(feed.content)[0].find(f"{{{ATOM_NS}}}link").get("href")
        download = scanned.get(href)
        assert download.status_code == 200
        assert download.content.startswith(b"PK")

    def test_epub_gets_epub_media_type(self, scanned: TestClient):
        series_id = self._series_id(scanned, "Een Testboek")
        entry = _entries(scanned.get(f"/opds/series/{series_id}").content)[0]
        acquisition = next(
            link
            for link in entry.findall(f"{{{ATOM_NS}}}link")
            if link.get("rel") == "http://opds-spec.org/acquisition"
        )
        assert acquisition.get("type") == "application/epub+zip"

    def test_unknown_series_is_404(self, scanned: TestClient):
        assert scanned.get("/opds/series/9999").status_code == 404
