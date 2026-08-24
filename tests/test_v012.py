from fastapi.testclient import TestClient

from app.main import app
from app.services import db


client = TestClient(app)


def test_supplier_hub_is_cj_only():
    db.init_db()
    payload = client.get("/api/suppliers/hub").json()
    assert [row["id"] for row in payload["providers"]] == ["cj"]
    assert payload["operating_mode"] == "EBAY_US_CJ_ONLY"
    assert payload["dry_run"] is True


def test_legacy_supplier_and_factory_routes_are_gone():
    assert client.get("/api/suppliers").status_code == 404
    assert client.get("/api/suppliers/directory").status_code == 404
    assert client.post("/api/suppliers/factory-discovery", json={"query": "portable fan"}).status_code == 404
    assert client.get("/api/radar/factories").status_code == 404
    assert client.get("/api/radar/rfqs").status_code == 404


def test_old_regional_cj_candidate_analysis_cannot_enter_us_catalog():
    db.init_db()
    candidate_id = db.save_cj_candidate({
        "cj_pid": "CJ-V012-UNIQUE",
        "sku": "CJ-V012-SKU",
        "name": "Portable fan v012",
        "price_usd": 4.5,
        "stock": 25,
        "image_url": "https://example.test/fan.jpg",
    })
    db.save_cj_candidate_analysis(candidate_id, {
        "supplier_cost_eur": 4.1,
        "shipping_cost_eur": 2.9,
        "landed_cost_eur": 7,
        "suggested_price_eur": 24.9,
        "estimated_profit_eur": 8,
        "variant": {"sku": "CJ-V012-SKU", "stock": 25},
        "shipping": {"delivery_days": "6-9", "name": "CJPacket"},
    }, [])
    response = client.post(f"/api/cj/candidates/{candidate_id}/add-product")
    assert response.status_code == 400


def test_generic_supplier_offer_path_is_removed():
    response = client.post("/api/products/from-supplier-offer", json={
        "provider": "external",
        "supplier_sku": "OUTSIDE-V012",
        "name": "Storage box v012",
        "price": 12.5,
        "currency": "USD",
        "stock": 18,
    })
    assert response.status_code == 405
