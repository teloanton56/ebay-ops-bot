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
        "ebay_fee_percent": 12, "ad_rate_percent": 3, "fixed_fee": 0.35,
        "return_reserve_percent": 2, "min_margin_percent": 24,
        "min_profit_eur": 5, "min_stock": 8, "max_shipping_days": 6,
        "max_supplier_price_jump_percent": 18,
    })
    assert response.status_code == 200
    assert response.json()["applied"]["min_margin_percent"] == 24
    assert client.get("/api/settings/risk").json()["min_stock"] == 8
    get_settings.cache_clear()


def test_product_score_is_automatic_and_separate_from_market_score():
    db.init_db()
    product_id = db.upsert_product({
        "supplier_sku": "V013-SCORE-CJ", "title": "CJ scored product",
        "description": "Produit fournisseur importé avec coût et transport confirmés.",
        "supplier_cost": 5, "shipping_cost": 2, "stock": 25, "shipping_days": 5,
        "target_price": 24.9, "images": ["https://example.test/product.jpg"],
        "category_id": "123", "aspects": {"Marque": ["Générique"]},
        "supplier_id": db.ensure_provider_supplier("cj", "CJ Dropshipping", "CN"),
        "product_status": "À tester",
    })
    payload = client.get(f"/api/products/{product_id}").json()
    assert payload["product_score"]["score"] > 0
    assert payload["product_score"]["source"] == "CATALOGUE_LOCAL"
    assert payload["product_score"]["market_score"] is None
    assert "ne prétend pas mesurer" in payload["product_score"]["meaning"]


def test_niche_supplier_directory_is_filterable():
    payload = client.get("/api/suppliers/directory?category=Beaut%C3%A9").json()
    assert payload["total"] >= 3
    assert all("Beauté" in row["categories"] for row in payload["results"])
    assert any(row["catalog_level"] in {"csv", "feed", "request"} for row in payload["results"])


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
    assert "retard" in draft["draft"].lower()
    assert client.delete(f"/api/support/cases/{case_id}").status_code == 200


def test_sales_channels_and_new_ui_are_present():
    channels = client.get("/api/sales-channels").json()
    assert channels["recommended_next"] == "cdiscount"
    assert {"ebay", "cdiscount", "kaufland", "amazon", "tiktok_shop", "etsy"} <= {
        row["id"] for row in channels["channels"]
    }
    html = client.get("/").text
    assert 'id="section-support"' in html
    assert 'id="supplierDirectoryResults"' in html
    assert 'id="salesChannelGrid"' in html
