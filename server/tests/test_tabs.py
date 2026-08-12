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
