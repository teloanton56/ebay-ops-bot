from fastapi.testclient import TestClient

from app.main import app
from app.services import db
from app.services.connections import extract_trend_themes
from app.services.radar import build_rfq_message


client = TestClient(app)


def test_trend_extraction_remains_legacy_metadata_only():
    videos = [
        {"title": "Portable fan for summer", "tags": ["portable fan", "home"], "views": 100_000},
        {"title": "Best portable fan setup", "tags": ["portable fan", "desk"], "views": 80_000},
        {"title": "Mini portable fan review", "tags": ["portable fan"], "views": 60_000},
    ]
    themes = extract_trend_themes(videos)
    portable = next(row for row in themes if row["keyword"] == "portable fan")
    assert portable["mentions"] == 3
    assert portable["signal_score"] <= 100
    assert "pas volume de recherche ni ventes" in portable["meaning"]


def test_supplier_hub_is_cj_only():
    db.init_db()
    payload = client.get("/api/suppliers/hub").json()
    assert {row["id"] for row in payload["providers"]} == {"cj"}
    assert payload["operating_mode"] == "EBAY_US_CJ_ONLY"
    assert payload["manual"] == []
    assert payload["dry_run"] is True


def test_factory_discovery_is_legacy_and_not_part_of_active_flow():
    response = client.post("/api/suppliers/factory-discovery", json={"query": "portable fan"})
    assert response.status_code == 200
    payload = response.json()
    assert payload["query"] == "portable fan"
    assert payload["legacy"] is True
    assert {row["name"] for row in payload["directories"]} == {"Alibaba.com"}


def test_rfq_draft_can_be_deleted():
    db.init_db()
    factory_id = db.save_factory_lead({"company": "Factory v012", "country": "CN"})
    rfq_id = db.save_rfq({
        "factory_id": factory_id,
        "product_query": "Desk organizer",
        "quantities": "10, 50",
        "specifications": "Sample first",
        "message": build_rfq_message("Factory v012", "Desk organizer", "10, 50"),
    })
    response = client.delete(f"/api/radar/rfqs/{rfq_id}")
    assert response.status_code == 200
    assert not any(row["id"] == rfq_id for row in db.list_rfqs())


def test_old_eur_cj_candidate_analysis_cannot_enter_us_catalog():
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


def test_retired_supplier_offer_is_rejected():
    response = client.post("/api/products/from-supplier-offer", json={
        "provider": "dropxl",
        "supplier_sku": "DX-V012",
        "name": "Storage box v012",
        "price": 12.5,
        "currency": "EUR",
        "stock": 18,
    })
    assert response.status_code == 410
    assert "CJ" in response.text


def test_legacy_csv_download_may_remain_but_active_ui_hides_manual_import():
    response = client.get("/sample_supplier.csv")
    assert response.status_code == 200
    assert "attachment" in response.headers["content-disposition"]
    assert "supplier_sku" in response.text
    cleanup = open("app/static/provider_cleanup.js", encoding="utf-8").read()
    assert "manual-supplier-fallback" in cleanup
    assert "importer csv" in cleanup.lower()
