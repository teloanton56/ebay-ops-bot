import asyncio
from pathlib import Path

from fastapi.testclient import TestClient

from app.config import get_settings
from app.main import app
from app.services import db
from app.services.cj_landed import evaluate_route, route_requirements, save_cj_product_link, select_cj_route
from app.services.ebay_shop_spy import _browse_seller_items
from app.services.profit import calculate_profit, order_fee_for_price
from app.services.risk import assess_product

ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def product_payload(**overrides):
    data = {"supplier_sku": "CJ-US-TEST", "title": "Car seat organizer", "description": "Generic car organizer sourced through CJ Dropshipping.", "supplier_cost": 6.0, "shipping_cost": 4.0, "stock": 25, "shipping_days": 5, "target_price": 30.0, "category_id": "6028", "condition": "NEW", "marketplace_id": "EBAY_US", "currency": "USD", "images": ["https://example.com/image.jpg"], "aspects": {"Type": ["Organizer"]}, "supplier_id": None, "product_status": "À tester"}
    data.update(overrides)
    return data


def test_operating_profile_is_hard_locked_to_ebay_us_usd(monkeypatch):
    monkeypatch.setenv("EBAY_MARKETPLACE_ID", "EBAY_FR")
    monkeypatch.setenv("EBAY_CURRENCY", "EUR")
    get_settings.cache_clear()
    settings = get_settings()
    assert settings.ebay_marketplace_id == "EBAY_US"
    assert settings.ebay_currency == "USD"
    assert settings.ebay_locale == "en-US"
    assert settings.default_ebay_fee_percent == 13.6


def test_ebay_us_order_fee_switches_at_ten_dollars():
    assert order_fee_for_price(10.00) == 0.30
    assert order_fee_for_price(10.01) == 0.40
    profit = calculate_profit({"supplier_cost": 3, "shipping_cost": 2}, 20)
    assert profit["currency"] == "USD"
    assert profit["fixed_fee"] == 0.40
    assert profit["estimated_ebay_fee"] == 2.72


def test_cj_route_policy_is_us_first_and_cn_is_stricter():
    us = route_requirements("US")
    cn = route_requirements("CN")
    assert us == {"min_margin_percent": 20.0, "min_profit": 5.0, "min_stock": 10, "max_shipping_days": 7}
    assert cn == {"min_margin_percent": 30.0, "min_profit": 8.0, "min_stock": 20, "max_shipping_days": 12}
    routes = {"US": {"warehouse": "US", "supplier_cost": 6, "shipping_cost": 4, "stock": 25, "shipping_days": 5}, "CN": {"warehouse": "CN", "supplier_cost": 4, "shipping_cost": 5, "stock": 40, "shipping_days": 10}}
    selected = select_cj_route(routes, reference_price=30)
    assert selected["warehouse"] == "US" and selected["eligible"] is True


def test_china_route_is_only_eligible_with_stricter_economics():
    good = evaluate_route({"warehouse": "CN", "supplier_cost": 4, "shipping_cost": 5, "stock": 40, "shipping_days": 10}, 30)
    bad_profit = evaluate_route({"warehouse": "CN", "supplier_cost": 8, "shipping_cost": 6, "stock": 40, "shipping_days": 10}, 20)
    bad_delay = evaluate_route({"warehouse": "CN", "supplier_cost": 4, "shipping_cost": 5, "stock": 40, "shipping_days": 14}, 30)
    assert good["eligible"] is True and good["profit"]["estimated_profit"] >= 8 and good["profit"]["margin_percent"] >= 30
    assert bad_profit["eligible"] is False and bad_delay["eligible"] is False


def test_risk_engine_uses_route_specific_thresholds():
    cn_product = product_payload(supplier_sku="CJ-CN-TEST", supplier_cost=4, shipping_cost=5, stock=30, shipping_days=10, target_price=30)
    save_cj_product_link("CJ-CN-TEST", {"pid": "PID-CN", "variant_id": "VID-CN", "warehouse": "CN", "risk_flags": []})
    risk = assess_product(cn_product)
    assert risk["pass"] is True and risk["route"]["warehouse"] == "CN" and risk["route"]["requirements"]["max_shipping_days"] == 12
    low_profit = assess_product({**cn_product, "target_price": 20})
    assert low_profit["pass"] is False and any("Profit estimé" in block for block in low_profit["blocks"])
    us_product = product_payload(supplier_sku="CJ-US-SLOW", shipping_days=8)
    save_cj_product_link("CJ-US-SLOW", {"pid": "PID-US", "variant_id": "VID-US", "warehouse": "US", "risk_flags": []})
    us_risk = assess_product(us_product)
    assert us_risk["pass"] is False and any("Délai 8j > maximum 7j" in block for block in us_risk["blocks"])


def test_products_api_hides_legacy_fr_catalogue_and_forces_usd():
    legacy_id = db.upsert_product(product_payload(supplier_sku="OLD-FR-1", marketplace_id="EBAY_FR", currency="EUR"))
    assert legacy_id
    with TestClient(app) as client:
        created = client.post("/api/products", json=product_payload(supplier_sku="CJ-NEW-US-1", marketplace_id="EBAY_FR", currency="EUR"))
        assert created.status_code == 200
        listing = client.get("/api/products")
    rows = listing.json()
    assert len(rows) == 1
    assert rows[0]["supplier_sku"] == "CJ-NEW-US-1"
    assert rows[0]["marketplace_id"] == "EBAY_US" and rows[0]["currency"] == "USD"


def test_retired_sources_are_rejected_by_active_api():
    with TestClient(app) as client:
        ali = client.post("/api/supplier-flow/add", json={"provider": "aliexpress", "supplier_sku": "ALI-1", "name": "Example", "price": 5})
        social = client.post("/api/connections/signals/scan", json={"keyword": "organizer", "sources": ["youtube", "tiktok"], "country": "US"})
        discover = client.post("/api/radar/discover", json={"country": "US"})
        connections = client.get("/api/connections")
    assert ali.status_code == 410 and social.status_code == 410 and discover.status_code == 410
    assert connections.json()["operating_mode"] == "EBAY_US_CJ_ONLY" and connections.json()["sources"] == []


def test_settings_api_ignores_old_marketplace_and_currency():
    with TestClient(app) as client:
        response = client.post("/api/settings/ebay", json={"environment": "sandbox", "marketplace_id": "EBAY_FR", "currency": "EUR"})
        current = client.get("/api/settings/ebay")
    assert response.json()["marketplace_id"] == "EBAY_US" and response.json()["currency"] == "USD"
    assert current.json()["marketplace_id"] == "EBAY_US" and current.json()["currency"] == "USD"


def test_shop_spy_browse_call_is_for_ebay_us(monkeypatch):
    captured = {}
    async def fake_public_request(self, method, path, *, params=None, json_body=None, marketplace_id=None):
        captured.update({"method": method, "path": path, "marketplace_id": marketplace_id, "params": params})
        return {"total": 0, "itemSummaries": []}
    monkeypatch.setattr("app.services.ebay.EbayClient.public_request", fake_public_request)
    asyncio.run(_browse_seller_items("example_seller", 25))
    assert captured["marketplace_id"] == "EBAY_US"
    assert "sellers:{example_seller}" in captured["params"]["filter"]


def test_main_and_pwa_do_not_load_old_multi_source_radar():
    main = read("app/main.py")
    service_worker = read("app/static/service-worker.js")
    version = main.split('VERSION = "', 1)[1].split('"', 1)[0]
    assert version == "0.24.0"
    assert "auto_radar.router" not in main and "auto_radar.js" not in main and "tiered_radar.js" not in main
    assert f"opsbot-v{version}-shell" in service_worker
    assert "auto_radar.js" not in service_worker and "tiered_radar.js" not in service_worker


def test_active_sourcing_frontend_names_only_cj():
    active = read("app/static/simple_ui.js").lower()
    dashboard = read("app/templates/dashboard.html").lower()
    assert "cj dropshipping" in dashboard
    assert "aliexpress" not in active and "amazon" not in active
    assert "youtube" not in dashboard and "tiktok" not in dashboard
    assert "chercher sur cj" in active


def test_listing_and_supplier_refresh_require_route_specific_locations():
    ebay_router = read("app/routers/ebay.py")
    refresh = read("app/services/supplier_refresh.py")
    listing = read("app/services/ebay_us_listing.py")
    assert "EBAY_CJ_US_LOCATION_KEY" in read("app/config.py")
    assert "EBAY_CJ_CN_LOCATION_KEY" in read("app/config.py")
    assert "location_key_for_warehouse" in ebay_router
    assert "Merchant location eBay manquante" in ebay_router
    assert "refuse de basculer automatiquement" in refresh
    assert 'marketplaceId": "EBAY_US"' in listing and '"currency": "USD"' in listing


def test_scheduler_refreshes_cj_and_never_syncs_legacy_fr_products():
    scheduler = read("app/services/scheduler.py")
    automation = read("app/routers/automation.py")
    assert "refresh_product_from_supplier" in scheduler
    assert 'product.get("marketplace_id") != "EBAY_US"' in scheduler
    assert 'product.get("currency") != "USD"' in scheduler
    assert "refresh_product_from_supplier" in automation
    assert '"USD"' in automation
