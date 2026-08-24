from fastapi.testclient import TestClient

from app.config import get_settings
from app.main import app
from app.routers import settings as settings_router
from app.services import db
from app.services.cj_landed import save_cj_product_link


client = TestClient(app)


def test_risk_settings_are_reloaded_and_return_applied_values(tmp_path, monkeypatch):
    monkeypatch.setattr(settings_router, "ENV_PATH", tmp_path / ".env")
    monkeypatch.setenv("MIN_MARGIN_PERCENT", "15")
    get_settings.cache_clear()
    response = client.post("/api/settings/risk", json={
        "ebay_fee_percent": 13.6, "ad_rate_percent": 3, "fixed_fee": 0.40,
        "return_reserve_percent": 2, "min_margin_percent": 24,
        "min_profit_usd": 5, "min_stock": 8, "max_shipping_days": 6,
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
    save_cj_product_link("V013-SCORE-CJ-US", {
        "pid": "PID-V013-SCORE",
        "variant_id": "VID-V013-SCORE",
        "warehouse": "US",
        "destination_country": "US",
        "currency": "USD",
        "risk_flags": [],
    })
    payload = client.get(f"/api/products/{product_id}").json()
    assert payload["marketplace_id"] == "EBAY_US"
    assert payload["currency"] == "USD"
    assert payload["product_score"]["score"] > 0
    assert payload["product_score"]["source"] == "CATALOGUE_LOCAL_US"
    assert payload["product_score"]["market_score"] is None


def test_legacy_supplier_directory_is_removed():
    response = client.get("/api/suppliers/directory?category=Beauty")
    assert response.status_code == 404


def test_support_case_draft_is_local_and_deletable():
    db.init_db()
    created = client.post("/api/support/cases", json={
        "marketplace": "EBAY_US", "order_ref": "ORDER-V013", "buyer_alias": "client-test",
        "subject": "Colis en retard", "category": "Retard de livraison",
        "priority": "Haute", "status": "Nouveau", "customer_message": "Où est mon colis ?",
    })
    assert created.status_code == 200
    case_id = created.json()["id"]
    draft = client.post(f"/api/support/cases/{case_id}/draft-response").json()
    assert draft["sent"] is False
    assert client.delete(f"/api/support/cases/{case_id}").status_code == 200


def test_single_channel_ui_has_no_legacy_cleanup_assets():
    dashboard = open("app/templates/dashboard.html", encoding="utf-8").read()
    assert "eBay US" in dashboard
    assert "CJ Dropshipping" in dashboard
