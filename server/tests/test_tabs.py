"""Tabs en slimme collecties: CRUD + de series die hun regel oplevert."""

from __future__ import annotations

from fastapi.testclient import TestClient


class TestTabsCrud:
    def test_create_list_and_get(self, client: TestClient):
        created = client.post(
            "/api/tabs",
            json={"name": "Strips", "rule": {"extension": {"in": ["cbz", "cbr"]}}},
        )
        assert created.status_code == 201
        tab_id = created.json()["id"]

        listed = client.get("/api/tabs").json()
        assert [t["name"] for t in listed] == ["Strips"]

        fetched = client.get(f"/api/tabs/{tab_id}").json()
        assert fetched["rule"] == {"extension": {"in": ["cbz", "cbr"]}}
        assert fetched["view_mode"] == "grid"

    def test_defaults(self, client: TestClient):
        created = client.post("/api/tabs", json={"name": "Alles"})
        body = created.json()
        assert body["rule"] == {}
        assert body["enabled"] is True
        assert body["position"] == 0

    def test_list_is_ordered_by_position(self, client: TestClient):
        client.post("/api/tabs", json={"name": "B", "position": 2})
        client.post("/api/tabs", json={"name": "A", "position": 1})
        names = [t["name"] for t in client.get("/api/tabs").json()]
        assert names == ["A", "B"]

    def test_update(self, client: TestClient):
        tab_id = client.post("/api/tabs", json={"name": "Oud"}).json()["id"]
        updated = client.patch(f"/api/tabs/{tab_id}", json={"name": "Nieuw", "position": 5})
        assert updated.status_code == 200
        assert updated.json()["name"] == "Nieuw"
        assert updated.json()["position"] == 5

    def test_delete(self, client: TestClient):
        tab_id = client.post("/api/tabs", json={"name": "Weg"}).json()["id"]
        assert client.delete(f"/api/tabs/{tab_id}").status_code == 204
        assert client.get(f"/api/tabs/{tab_id}").status_code == 404

    def test_unknown_tab_is_404(self, client: TestClient):
        assert client.get("/api/tabs/999").status_code == 404

    def test_invalid_rule_is_rejected_on_create(self, client: TestClient):
        response = client.post("/api/tabs", json={"name": "Kapot", "rule": {"nope": {"eq": 1}}})
        assert response.status_code == 400

    def test_invalid_rule_is_rejected_on_update(self, client: TestClient):
        tab_id = client.post("/api/tabs", json={"name": "Ok"}).json()["id"]
        response = client.patch(
            f"/api/tabs/{tab_id}", json={"name": "Ok", "rule": {"and": "not-a-list"}}
        )
        assert response.status_code == 400
        # De oude regel blijft staan.
        assert client.get(f"/api/tabs/{tab_id}").json()["rule"] == {}


class TestTabSeries:
    def test_tab_series_applies_the_rule(self, scanned: TestClient):
        tab_id = scanned.post(
            "/api/tabs", json={"name": "Manga", "rule": {"origin_region": {"eq": "japan"}}}
        ).json()["id"]
        result = scanned.get(f"/api/tabs/{tab_id}/series").json()
        assert [item["title"] for item in result["items"]] == ["Tesuto"]
        assert result["total"] == 1

    def test_tab_series_combines_rule_with_search(self, scanned: TestClient):
        tab_id = scanned.post(
            "/api/tabs", json={"name": "Strips", "rule": {"extension": {"in": ["cbz"]}}}
        ).json()["id"]
        result = scanned.get(f"/api/tabs/{tab_id}/series", params={"search": "storm"}).json()
        assert [item["title"] for item in result["items"]] == ["Storm"]

    def test_empty_rule_returns_everything(self, scanned: TestClient):
        tab_id = scanned.post("/api/tabs", json={"name": "Alles"}).json()["id"]
        result = scanned.get(f"/api/tabs/{tab_id}/series").json()
        assert result["total"] == 4

    def test_unknown_tab_is_404(self, scanned: TestClient):
        assert scanned.get("/api/tabs/999/series").status_code == 404


class TestCollectionsCrud:
    def test_create_and_list(self, client: TestClient):
        created = client.post(
            "/api/collections", json={"name": "Favorieten", "rule": {"tag": {"eq": "favoriet"}}}
        )
        assert created.status_code == 201
        assert created.json()["smart"] is True

        listed = client.get("/api/collections").json()
        assert [c["name"] for c in listed] == ["Favorieten"]

    def test_update_and_delete(self, client: TestClient):
        collection_id = client.post("/api/collections", json={"name": "X"}).json()["id"]
        updated = client.patch(f"/api/collections/{collection_id}", json={"name": "Y"})
        assert updated.json()["name"] == "Y"
        assert client.delete(f"/api/collections/{collection_id}").status_code == 204
        assert client.get(f"/api/collections/{collection_id}").status_code == 404

    def test_invalid_rule_rejected(self, client: TestClient):
        response = client.post("/api/collections", json={"name": "Kapot", "rule": {"x": {"eq": 1}}})
        assert response.status_code == 400


class TestCollectionSeries:
    def test_collection_series_applies_the_rule(self, scanned: TestClient):
        collection_id = scanned.post(
            "/api/collections",
            json={"name": "Europa", "rule": {"origin_region": {"eq": "europe"}}},
        ).json()["id"]
        result = scanned.get(f"/api/collections/{collection_id}/series").json()
        assert [item["title"] for item in result["items"]] == ["Storm"]


class TestGroups:
    """De grove indeling boeken/strips/manga, als balk boven de bibliotheek.

    De `scanned`-collectie heeft precies één van elk: Storm (Dupuis, dus
    Europa), Tesuto (manga-vlag, dus Japan) en twee boeken (epub en pdf).
    """

    def _titles(self, client: TestClient, groep: str | None = None) -> list[str]:
        query = f"?group={groep}" if groep else ""
        return sorted(s["title"] for s in client.get(f"/api/series{query}").json()["items"])

    def test_without_a_group_you_get_everything(self, scanned: TestClient):
        assert len(self._titles(scanned)) == 4

    def test_comics_exclude_manga(self, scanned: TestClient):
        assert self._titles(scanned, "strips") == ["Storm"]

    def test_manga_is_the_japanese_half(self, scanned: TestClient):
        assert self._titles(scanned, "manga") == ["Tesuto"]

    def test_books_are_everything_that_is_not_a_comic(self, scanned: TestClient):
        assert self._titles(scanned, "boeken") == ["Een Testboek", "Een Testdocument"]

    def test_the_total_counts_the_group_and_not_the_library(self, scanned: TestClient):
        # Anders klopt het paginanummer niet zodra de collectie groter is dan
        # één pagina — precies het geval waarin naschiften in de client stukgaat.
        assert scanned.get("/api/series?group=manga").json()["total"] == 1

    def test_an_unknown_group_is_a_bad_request(self, scanned: TestClient):
        assert scanned.get("/api/series?group=onzin").status_code == 422

    def test_a_tab_and_a_group_narrow_each_other(self, scanned: TestClient):
        """De balk staat bóven de tabs, dus hij hoort te combineren."""
        tab = scanned.post(
            "/api/tabs", json={"name": "Alle strips", "rule": {"extension": {"in": ["cbz", "cbr"]}}}
        ).json()["id"]
        beide = scanned.get(f"/api/tabs/{tab}/series").json()
        assert sorted(s["title"] for s in beide["items"]) == ["Storm", "Tesuto"]

        alleen_manga = scanned.get(f"/api/tabs/{tab}/series?group=manga").json()
        assert [s["title"] for s in alleen_manga["items"]] == ["Tesuto"]
        assert alleen_manga["total"] == 1


class TestDrukwerkGroepen:
    """Tijdschriften en drukwerk zijn categorie 4 en 5.

    De bibliotheekmap is het signaal en niet de inhoud: een tijdschrift is net
    zo goed een pdf als een roman, en de herkomst zegt er niets over.
    """

    def _root(self, client: TestClient, naam: str, pad: str, bestanden: dict[str, bytes]) -> int:
        from pathlib import Path

        map_ = Path(pad)
        map_.mkdir(parents=True, exist_ok=True)
        for naam_, inhoud in bestanden.items():
            (map_ / naam_).write_bytes(inhoud)
        antwoord = client.post("/api/libraries", json={"name": naam, "path": str(map_)})
        root_id = antwoord.json()["id"]
        client.post(f"/api/libraries/{root_id}/scan")
        return root_id

    def _titels(self, client: TestClient, groep: str) -> list[str]:
        return sorted(s["title"] for s in client.get(f"/api/series?group={groep}").json()["items"])

    def test_a_magazine_root_is_its_own_group(self, scanned: TestClient, tmp_path, monkeypatch):
        """Op de map en niet op de titel: hoe een blad heet doet er voor de
        indeling niet toe, waar het staat wel."""
        from bookpal.library import groups
        from tests.fixtures import make_pdf

        pad = str(tmp_path / "bladen")
        monkeypatch.setitem(groups._MAP_GROEPEN, groups.SeriesGroup.TIJDSCHRIFTEN, pad)
        map_ = tmp_path / "bladen" / "Power Unlimited"
        map_.mkdir(parents=True)
        for nummer in ("001", "002", "003"):
            make_pdf(map_ / f"{nummer}.pdf", pages=1)
        root = scanned.post("/api/libraries", json={"name": "Bladen", "path": pad}).json()["id"]
        scanned.post(f"/api/libraries/{root}/scan")

        bladen = scanned.get("/api/series?group=tijdschriften").json()["items"]
        assert bladen, "de bladenmap levert geen enkele reeks op"
        assert {s["id"] for s in bladen} == {
            s["id"] for s in scanned.get(f"/api/series?root_id={root}").json()["items"]
        }

    def test_a_magazine_never_shows_up_under_books(
        self, scanned: TestClient, tmp_path, monkeypatch
    ):
        """Anders staat een Lego-catalogus tussen je romans."""
        from bookpal.library import groups
        from tests.fixtures import make_pdf

        pad = str(tmp_path / "bladen")
        monkeypatch.setitem(groups._MAP_GROEPEN, groups.SeriesGroup.TIJDSCHRIFTEN, pad)
        map_ = tmp_path / "bladen" / "Power Unlimited"
        map_.mkdir(parents=True)
        make_pdf(map_ / "001.pdf", pages=1)
        make_pdf(map_ / "002.pdf", pages=1)
        root = scanned.post("/api/libraries", json={"name": "Bladen", "path": pad}).json()["id"]
        scanned.post(f"/api/libraries/{root}/scan")

        assert "Power Unlimited" not in self._titels(scanned, "boeken")

    def test_the_existing_groups_are_unchanged(self, scanned: TestClient):
        assert self._titels(scanned, "strips") == ["Storm"]
        assert self._titels(scanned, "manga") == ["Tesuto"]
        assert self._titels(scanned, "boeken") == ["Een Testboek", "Een Testdocument"]

    def test_an_unknown_group_is_still_a_bad_request(self, scanned: TestClient):
        assert scanned.get("/api/series?group=onzin").status_code == 422
