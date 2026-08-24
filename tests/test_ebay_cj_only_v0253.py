import asyncio
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services import db, opportunity_monitor, opportunity_suppliers
from app.services.cj import CJError
from app.services.cj_landed import load_cj_product_link, resolve_cj_landed_routes, save_cj_product_link
from app.services.ebay_shop_spy import _normalize_browse_listing
from app.services.ebay import EbayClient, EbayError
from app.services.opportunity_suppliers import _score_offer
from app.services.radar import analyze_ebay_market
from app.services.supplier_refresh import is_verified_cj_product


ROOT = Path(__file__).resolve().parents[1]


def test_v0253_health_and_pwa_version_match():
    with TestClient(app) as client:
        health = client.get("/health")
    assert health.status_code == 200
    assert health.json() == {
        "ok": True,
        "version": "0.25.3",
        "demo_mode": True,
        "mode": "local",
        "operating_mode": "EBAY_US_CJ_ONLY",
        "marketplace": "EBAY_US",
        "currency": "USD",
        "destination_country": "US",
    }
    worker = (ROOT / "app/static/service-worker.js").read_text(encoding="utf-8")
    assert "opsbot-v0.25.3-shell" in worker
    assert "/static/simple_ui.js?v=0.25.3" in worker


def test_removed_integrations_have_no_module_asset_or_route():
    removed = [
        "app/routers/connections.py",
        "app/services/connections.py",
        "app/services/marketplace_supplier_sources.py",
        "app/services/aliexpress_dropship_search.py",
        "app/services/aliexpress_modern_oauth.py",
        "app/static/app.js",
        "app/static/provider_cleanup.js",
        "app/static/workflow_cleanup.js",
        "sample_supplier.csv",
    ]
    assert all(not (ROOT / path).exists() for path in removed)

    with TestClient(app) as client:
        assert client.get("/api/connections").status_code == 404
        assert client.post("/api/radar/discover", json={"country": "US"}).status_code == 404
        assert client.post("/api/opportunity-center/workflows/1/amazon").status_code == 404


def test_active_runtime_has_no_forbidden_integration_reference():
    active_files = [
        path for path in (ROOT / "app").rglob("*")
        if path.is_file() and path.suffix in {".py", ".js", ".css", ".html", ".json"}
    ]
    forbidden = ("amazon", "aliexpress", "dropxl", "tiktok", "youtube", "ebay_fr")
    for path in active_files:
        source = path.read_text(encoding="utf-8").casefold()
        assert not any(value in source for value in forbidden), path.relative_to(ROOT)


def test_sales_channels_expose_ebay_us_only():
    with TestClient(app) as client:
        response = client.get("/api/sales-channels")
    assert response.status_code == 200
    payload = response.json()
    assert payload["recommended_next"] is None
    assert [row["id"] for row in payload["channels"]] == ["ebay"]
    assert payload["channels"][0]["name"] == "eBay US"
    assert payload["operating_mode"] == "EBAY_US_CJ_ONLY"


def test_radar_rejects_legacy_marketplace_fields_before_calling_ebay():
    with TestClient(app) as client:
        response = client.post(
            "/api/radar/scan",
            json={"keyword": "car organizer", "marketplaces": ["OTHER"]},
        )
    assert response.status_code == 422


def test_example_environment_is_usd_ebay_us_only():
    example = (ROOT / ".env.example").read_text(encoding="utf-8")
    assert "EBAY_LOCALE=en-US" in example
    assert "EBAY_MARKETPLACE_ID=EBAY_US" in example
    assert "EBAY_CURRENCY=USD" in example
    assert "MIN_PROFIT_USD=5.0" in example
    assert "CJ_US_MIN_PROFIT_USD=5.0" in example
    assert "CJ_CN_MIN_PROFIT_USD=8.0" in example
    forbidden = ("AMAZON_", "ALIEXPRESS_", "DROPXL_", "TIKTOK_", "YOUTUBE_")
    assert not any(value in example for value in forbidden)


def test_manual_product_and_csv_paths_are_removed():
    paths = app.openapi()["paths"]
    assert "post" not in paths["/api/products"]
    assert "/api/products/from-supplier-offer" not in paths
    assert "/api/products/import-csv" not in paths
    assert "/api/products/import-csv/{supplier_id}" not in paths
    assert "/sample_supplier.csv" not in paths
    assert "/api/products/load-demo" not in paths
    assert "/api/ebay/inventory-location" not in paths
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    assert "sample_supplier.csv" not in dockerfile


def test_removed_discovery_factory_and_rfq_storage_is_not_created():
    with db.conn() as database:
        tables = {
            row[0]
            for row in database.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
    assert not {"trend_discoveries", "factory_leads", "rfq_requests"} & tables
    assert not hasattr(db, "save_trend_discovery")
    assert not hasattr(db, "save_factory_lead")
    assert not hasattr(db, "save_rfq")


def test_ebay_client_rejects_non_us_marketplace_before_network_access():
    with pytest.raises(EbayError, match="EBAY_US"):
        asyncio.run(EbayClient().public_request("GET", "/buy/browse/v1/item_summary/search", marketplace_id="OTHER"))


def test_cj_links_require_a_us_destination_and_usd_currency():
    sku = "V0253-STRICT-CJ-LINK"
    route = {
        "pid": "PID-V0253",
        "variant_id": "VID-V0253",
        "warehouse": "US",
        "destination_country": "US",
        "currency": "USD",
    }
    with pytest.raises(ValueError, match="US.*USD"):
        save_cj_product_link(sku, {**route, "destination_country": "GB", "currency": "GBP"})
    with pytest.raises(CJError, match="uniquement US"):
        asyncio.run(resolve_cj_landed_routes(object(), "PID-V0253", destination_country="GB"))

    save_cj_product_link(sku, route)
    assert load_cj_product_link(sku)["destination_country"] == "US"
    assert load_cj_product_link(sku)["currency"] == "USD"
    assert is_verified_cj_product(
        {
            "supplier_sku": sku,
            "marketplace_id": "EBAY_US",
            "currency": "USD",
        },
        {"provider_code": "cj"},
    ) is True


def test_supplier_flow_schema_rejects_non_cj_or_non_usd_payloads():
    base = {
        "provider": "cj",
        "supplier_sku": "SKU-1",
        "name": "Car organizer",
        "price": 8,
        "currency": "USD",
        "cj_pid": "PID-1",
    }
    with TestClient(app) as client:
        assert client.post("/api/supplier-flow/add", json={**base, "provider": "other"}).status_code == 422
        assert client.post("/api/supplier-flow/add", json={**base, "currency": "GBP"}).status_code == 422
        support = client.post("/api/support/cases", json={
            "marketplace": "OTHER",
            "subject": "Outside active marketplace",
        })
        assert support.status_code == 422


def test_radar_uses_only_usd_prices(monkeypatch):
    async def fake_search(self, query, limit=20, marketplace_id=None, category_id=None):
        assert marketplace_id == "EBAY_US"
        return {
            "total": 2,
            "itemSummaries": [
                {"title": "USD item", "price": {"value": "30", "currency": "USD"}},
                {"title": "Other currency", "price": {"value": "10", "currency": "GBP"}},
            ],
        }

    monkeypatch.setattr(EbayClient, "search_items", fake_search)
    result = asyncio.run(analyze_ebay_market("car organizer"))
    assert result["marketplace"] == "EBAY_US"
    assert result["currency"] == "USD"
    assert result["median_price"] == 30
    assert [row["title"] for row in result["items"]] == ["USD item"]


def test_shop_spy_rejects_non_usd_listing_or_shipping_prices():
    base = {
        "title": "Car organizer",
        "price": {"value": "20", "currency": "USD"},
        "shippingOptions": [{"shippingCost": {"value": "4", "currency": "USD"}}],
    }
    assert _normalize_browse_listing(base, 1)["buyer_total"] == 24
    assert _normalize_browse_listing({**base, "price": {"value": "20", "currency": "GBP"}}, 1) is None
    assert _normalize_browse_listing({
        **base,
        "shippingOptions": [{"shippingCost": {"value": "4", "currency": "GBP"}}],
    }, 1) is None


def test_cj_offer_scoring_enforces_usd_us_destination_and_route_thresholds():
    base = {
        "provider": "CJ Dropshipping",
        "provider_code": "cj",
        "supplier_sku": "CJ-TEST-1",
        "cj_pid": "PID-TEST-1",
        "variant_id": "VID-1",
        "product_cost": 8,
        "shipping_cost": 4,
        "shipping_known": True,
        "currency": "USD",
        "stock": 30,
        "shipping_days": 5,
        "warehouse": "US",
        "destination_country": "US",
        "image_url": "https://example.test/item.jpg",
        "evidence": ["stock", "freight", "variant"],
        "match_strength": 1,
        "compliance_flags": [],
    }
    us = _score_offer(base, 39.99)
    assert us["eligible"] is True
    assert us["currency"] == "USD"
    assert us["requirements"]["min_profit"] == 5

    cn = _score_offer({**base, "warehouse": "CN", "stock": 25, "shipping_days": 10}, 39.99)
    assert cn["eligible"] is True
    assert cn["requirements"]["min_margin_percent"] == 30
    assert cn["requirements"]["min_profit"] == 8

    rejected = _score_offer({**base, "currency": "GBP", "destination_country": "GB"}, 39.99)
    assert rejected["eligible"] is False
    assert any("USD" in block for block in rejected["blocks"])
    assert any("US" in block for block in rejected["blocks"])


def test_opportunity_cj_lookup_uses_us_destination_and_usd(monkeypatch):
    monkeypatch.setattr(
        opportunity_suppliers.CJClient,
        "status",
        lambda self: {"connected": True},
    )

    async def fake_search(self, **kwargs):
        return {
            "products": [
                {
                    "cj_pid": "PID-US-1",
                    "sku": "CJ-US-1",
                    "name": "Car organizer",
                    "price_usd": 7.5,
                    "image_url": "https://example.test/cj.jpg",
                }
            ]
        }

    captured = {}

    async def fake_resolve(client, pid, **kwargs):
        captured.update(kwargs)
        return {
            "pid": pid,
            "variant_id": "VID-US-1",
            "variant_sku": "CJ-US-1-A",
            "variant_name": "Car organizer black",
            "product_name": "Car organizer",
            "supplier_cost": 7.5,
            "shipping_cost": 4.2,
            "stock": 50,
            "shipping_days": 4,
            "freight_name": "USPS",
            "warehouse": "US",
            "image_url": "https://example.test/cj.jpg",
            "risk_flags": [],
        }

    monkeypatch.setattr(opportunity_suppliers.CJClient, "search_products", fake_search)
    monkeypatch.setattr(opportunity_suppliers, "resolve_cj_landed_offer", fake_resolve)
    offers, errors = asyncio.run(opportunity_suppliers._cj_offers("car organizer", 34.99))

    assert errors == []
    assert captured["destination_country"] == "US"
    assert captured["reference_price"] == 34.99
    assert offers[0]["provider_code"] == "cj"
    assert offers[0]["currency"] == "USD"
    assert offers[0]["destination_country"] == "US"
    assert offers[0]["warehouse"] == "US"


def test_opportunity_monitor_never_switches_cj_warehouse_silently(monkeypatch):
    monkeypatch.setattr(opportunity_monitor.CJClient, "status", lambda self: {"connected": True})

    async def fake_resolve(*args, **kwargs):
        assert kwargs["preferred_warehouse"] == "US"
        return {
            "pid": "PID-MONITOR",
            "variant_id": "VID-MONITOR",
            "warehouse": "CN",
            "destination_country": "US",
            "currency": "USD",
            "supplier_cost": 5,
            "shipping_cost": 5,
            "stock": 50,
            "shipping_days": 9,
        }

    monkeypatch.setattr(opportunity_monitor, "resolve_cj_landed_offer", fake_resolve)
    selected = {
        "provider_code": "cj",
        "cj_pid": "PID-MONITOR",
        "variant_id": "VID-MONITOR",
        "warehouse": "US",
        "destination_country": "US",
        "currency": "USD",
    }
    refreshed, warnings = asyncio.run(
        opportunity_monitor._refresh_selected_offer({"selected_offer": selected}, 39.99)
    )
    assert refreshed["warehouse"] == "US"
    assert any("refuse de changer silencieusement" in warning for warning in warnings)
