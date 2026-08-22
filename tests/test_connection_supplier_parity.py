from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app


ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_supplier_hub_exposes_exactly_one_active_provider():
    with TestClient(app) as client:
        response = client.get("/api/suppliers/hub")
    assert response.status_code == 200
    data = response.json()
    assert data["operating_mode"] == "EBAY_US_CJ_ONLY"
    assert [provider["id"] for provider in data["providers"]] == ["cj"]
    assert data["providers"][0]["name"] == "CJ Dropshipping"
    assert data["providers"][0]["capabilities"]["us_warehouse_first"] is True
    assert data["providers"][0]["capabilities"]["china_fallback"] is True


def test_generic_connections_surface_has_no_marketplace_or_social_sources():
    with TestClient(app) as client:
        response = client.get("/api/connections")
    assert response.status_code == 200
    data = response.json()
    assert data["operating_mode"] == "EBAY_US_CJ_ONLY"
    assert data["sources"] == []
    assert data["restricted"] == []
    assert data["assisted_suppliers"] == []


def test_retired_marketplace_connections_cannot_be_reenabled():
    with TestClient(app) as client:
        for provider in ("aliexpress", "amazon", "youtube", "tiktok"):
            save = client.post(f"/api/connections/{provider}", json={})
            test = client.post(f"/api/connections/{provider}/test")
            assert save.status_code == 410
            assert test.status_code == 410


def test_frontend_removes_retired_sources_and_keeps_cj_ebay_copy():
    cleanup = read("app/static/provider_cleanup.js").lower()
    workflow = read("app/static/workflow_cleanup.js").lower()
    connections = read("app/routers/connections.py").lower()
    suppliers = read("app/routers/suppliers.py").lower()

    for retired in ("amazon", "aliexpress", "youtube", "tiktok"):
        assert retired in cleanup
        assert retired in connections
    assert "cj dropshipping" in workflow
    assert "ebay us" in workflow
    assert '"providers": [provider]' in suppliers
    assert '"operating_mode": "ebay_us_cj_only"' in suppliers
