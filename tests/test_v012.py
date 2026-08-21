from fastapi.testclient import TestClient

from app.main import app
from app.services import db
from app.services.connections import extract_trend_themes
from app.services.radar import build_rfq_message


client = TestClient(app)


def test_trend_extraction_counts_public_metadata_without_claiming_sales():
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


def test_supplier_hub_is_limited_to_active_api_sources():
    db.init_db()
    payload = client.get("/api/suppliers/hub").json()
    ids = {row["id"] for row in payload["providers"]}
    assert ids == {"cj", "amazon", "aliexpress"}
    assert payload["dry_run"] is True


def test_factory_discovery_can_prepare_an_official_directory_search():
    db.init_db()
    response = client.post("/api/suppliers/factory-discovery", json={"query": "portable fan"})
    assert response.status_code == 200
    payload = response.json()
    assert payload["query"] == "portable fan"
    assert {row["name"] for row in payload["directories"]} == {
        "Alibaba.com", "Global Sources", "Made-in-China", "Europages"
    }
    assert "n'invente" in payload["automatic_limits"]


def test_rfq_draft_can_be_deleted():
    db.init_db()
    factory_id = db.save_factory_lead({"company": "Factory v012", "country": "CN"})
    rfq_id = db.save_rfq({"factory_id": factory_id, "product_query": "Desk organizer",
                          "quantities": "10, 50", "specifications": "Sample first",
                          "message": build_rfq_message("Factory v012", "Desk organizer", "10, 50")})
    response = client.delete(f"/api/radar/rfqs/{rfq_id}")
    assert response.status_code == 200
    assert not any(row["id"] == rfq_id for row in db.list_rfqs())


def test_analyzed_cj_candidate_can_enter_products_in_dry_run():
    db.init_db()
    candidate_id = db.save_cj_candidate({"cj_pid": "CJ-V012-UNIQUE", "sku": "CJ-V012-SKU",
                                         "name": "Portable fan v012", "price_usd": 4.5,
                                         "stock": 25, "image_url": "https://example.test/fan.jpg"})
    db.save_cj_candidate_analysis(candidate_id, {
        "supplier_cost_eur": 4.1, "shipping_cost_eur": 2.9, "landed_cost_eur": 7,
        "suggested_price_eur": 24.9, "estimated_profit_eur": 8,
        "variant": {"sku": "CJ-V012-SKU", "stock": 25},
        "shipping": {"delivery_days": "6-9", "name": "CJPacket"},
    }, [])
    response = client.post(f"/api/cj/candidates/{candidate_id}/add-product")
    assert response.status_code == 200
    payload = response.json()
    product = db.get_product(payload["product_id"])
    supplier = db.get_supplier(product["supplier_id"])
    assert payload["dry_run"] is True
    assert product["shipping_cost"] == 2.9
    assert product["shipping_days"] == 9
    assert supplier["provider_code"] == "cj"


def test_connected_supplier_offer_can_enter_products_for_later_validation():
    db.init_db()
    response = client.post("/api/products/from-supplier-offer", json={
        "provider": "dropxl", "supplier_sku": "DX-V012", "name": "Storage box v012",
        "price": 12.5, "currency": "EUR", "stock": 18,
    })
    assert response.status_code == 200
    payload = response.json()
    product = db.get_product(payload["product_id"])
    supplier = db.get_supplier(product["supplier_id"])
    assert payload["dry_run"] is True
    assert supplier["provider_code"] == "dropxl"
    assert product["shipping_days"] == 99
    assert product["product_status"] == "À tester"


def test_csv_template_is_a_real_download_and_ui_has_guided_hubs():
    response = client.get("/sample_supplier.csv")
    assert response.status_code == 200
    assert "attachment" in response.headers["content-disposition"]
    assert "supplier_sku" in response.text
    html = client.get("/").text
    assert 'id="autoTrendResults"' in html
    assert 'id="supplierProviderGrid"' in html
    assert 'id="productOpportunityArea"' in html
    assert 'data-tip=' in html
    assert 'id="radarSupplierForm"' not in html
