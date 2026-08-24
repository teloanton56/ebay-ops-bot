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


def test_generic_connections_surface_is_removed():
    with TestClient(app) as client:
        response = client.get("/api/connections")
    assert response.status_code == 404


def test_retired_marketplace_connections_cannot_be_reenabled():
    with TestClient(app) as client:
        for provider in ("aliexpress", "amazon", "youtube", "tiktok"):
            save = client.post(f"/api/connections/{provider}", json={})
            test = client.post(f"/api/connections/{provider}/test")
            assert save.status_code == 404
            assert test.status_code == 404


def test_frontend_cleanup_shims_are_deleted_and_supplier_hub_is_cj_only():
    suppliers = read("app/routers/suppliers.py").lower()

    assert not (ROOT / "app/static/provider_cleanup.js").exists()
    assert not (ROOT / "app/static/workflow_cleanup.js").exists()
    assert not (ROOT / "app/routers/connections.py").exists()
    assert '"providers": [provider]' in suppliers
    assert '"operating_mode": "ebay_us_cj_only"' in suppliers
