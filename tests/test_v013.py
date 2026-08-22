from fastapi.testclient import TestClient

from app.config import get_settings
from app.main import app
from app.routers import settings as settings_router
from app.services import db


client = TestClient(app)


def test_risk_settings_are_reloaded_and_return_applied_values(tmp_path, monkeypatch):
    monkeypatch.setattr(settings_router, "ENV_PATH", tmp_path / ".env")
    monkeypatch.setenv("MIN_MARGIN_PERCENT", "15")
    get_settings.cache_clear()
    response = client.post("/api/settings/risk", json={
        "ebay_fee_percent": 13.6, "ad_rate_percent": 3, "fixed_fee": 0.40,
        "return_reserve_percent": 2, "min_margin_percent": 24,
        "min_profit_eur": 5, "min_stock": 8, "max_shipping_days": 6,
        "max_supplier_price_jump_percent": 18,
    })
    assert response.status_code == 200
    assert response.json()["applied"]["min_margin_percent"] == 24
    assert client.get("/api/settings/risk").json()["min_stock"] == 8
    get_settings.cache_clear()


def test_product_score_is_automatic_for_active_us_catalog():
    db.init_db()
    product_id = db.upsert_product({
        "supplier_sku": "V013-SCORE-CJ-US",
        "title": "CJ scored product",
        "description": "CJ product with confirmed US landed cost.",
        "supplier_cost": 5,
        "shipping_cost": 2,
        "stock": 25,
        "shipping_days": 5,
        "target_price": 24.9,
        "images": ["https://example.test/product.jpg"],
        "category_id": "123",
        "aspects": {"Brand": ["Unbranded"]},
        "supplier_id": db.ensure_provider_supplier("cj", "CJ Dropshipping", "US"),
        "product_status": "À tester",
        "marketplace_id": "EBAY_US",
        "currency": "USD",
    })
    payload = client.get(f"/api/products/{product_id}").json()
    assert payload["marketplace_id"] == "EBAY_US"
    assert payload["currency"] == "USD"
    assert payload["product_score"]["score"] > 0
    assert payload["product_score"]["source"] == "CATALOGUE_LOCAL_US"
    assert payload["product_score"]["market_score"] is None


def test_niche_supplier_directory_remains_legacy_but_filterable():
    payload = client.get("/api/suppliers/directory?category=Beaut%C3%A9").json()
    assert payload["total"] >= 3
    assert payload["legacy"] is True
    assert all("Beauté" in row["categories"] for row in payload["results"])


def test_support_case_draft_is_local_and_deletable():
    db.init_db()
    created = client.post("/api/support/cases", json={
        "marketplace": "EBAY", "order_ref": "ORDER-V013", "buyer_alias": "client-test",
        "subject": "Colis en retard", "category": "Retard de livraison",
        "priority": "Haute", "status": "Nouveau", "customer_message": "Où est mon colis ?",
    })
    assert created.status_code == 200
    case_id = created.json()["id"]
    draft = client.post(f"/api/support/cases/{case_id}/draft-response").json()
    assert draft["sent"] is False
    assert client.delete(f"/api/support/cases/{case_id}").status_code == 200


def test_single_channel_ui_hides_legacy_sales_channel_panel():
    cleanup = open("app/static/provider_cleanup.js", encoding="utf-8").read()
    workflow = open("app/static/workflow_cleanup.js", encoding="utf-8").read()
    assert "sales-channel-panel" in cleanup
    assert "eBay US" in workflow
    assert "CJ Dropshipping" in workflow
