import asyncio
import inspect

from fastapi.testclient import TestClient

import app.routers.radar as radar_router
from app.config import get_settings
from app.main import app
from app.services import db
from app.services.connections import (AmazonRadarClient, connection_status,
                                      save_credentials, test_provider as verify_provider)


def amazon_catalog_payload():
    marketplace_id = AmazonRadarClient.marketplaces["AMAZON_FR"]["id"]
    return {
        "numberOfResults": 321,
        "items": [{
            "asin": "B0AMAZON42",
            "summaries": [{"marketplaceId": marketplace_id, "itemName": "Ventilateur portable", "brand": "Example"}],
            "images": [{"marketplaceId": marketplace_id, "images": [
                {"variant": "MAIN", "link": "https://images.example.test/fan.jpg"}
            ]}],
            "classifications": [{"marketplaceId": marketplace_id, "classifications": [
                {"displayName": "Ventilateurs de table"}
            ]}],
            "salesRanks": [{"marketplaceId": marketplace_id,
                              "classificationRanks": [{"rank": 42, "title": "Ventilateurs"}],
                              "displayGroupRanks": [{"rank": 120, "title": "Maison"}]}],
        }],
    }


def test_amazon_catalog_and_optional_pricing_are_normalized_without_private_metrics():
    result = AmazonRadarClient.normalize_catalog(amazon_catalog_payload(), "AMAZON_FR")
    assert result["total"] == 321
    product = result["products"][0]
    assert product["asin"] == "B0AMAZON42"
    assert product["sales_rank"] == 42
    assert product["category"] == "Ventilateurs de table"
    assert product["url"] == "https://www.amazon.fr/dp/B0AMAZON42"
    assert product["price"] is None

    AmazonRadarClient.apply_pricing(result["products"], {"payload": [{
        "ASIN": "B0AMAZON42",
        "Product": {"CompetitivePricing": {
            "CompetitivePrices": [{"Price": {"LandedPrice": {"Amount": 19.99, "CurrencyCode": "EUR"}}}],
            "NumberOfOfferListings": [{"Count": 7}],
        }},
    }]})
    assert product["price"] == 19.99
    assert product["offer_count"] == 7


def test_amazon_connection_is_verified_only_after_a_real_catalog_test(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "amazon.db"))
    monkeypatch.setenv("APP_ENCRYPTION_KEY", "amazon-test-encryption-key-123456789")
    get_settings.cache_clear()
    db.init_db()
    save_credentials("amazon", {
        "client_id": "amazon-client-test",
        "client_secret": "amazon-secret-test",
        "refresh_token": "Atzr|amazon-refresh-test",
    })
    assert connection_status("amazon")["configured"] is True
    assert connection_status("amazon")["connected"] is False

    async def fake_test(self):
        return {"ok": True, "observed": 1}

    monkeypatch.setattr(AmazonRadarClient, "test", fake_test)
    asyncio.run(verify_provider("amazon"))
    assert connection_status("amazon")["connected"] is True
    get_settings.cache_clear()


def test_amazon_radar_can_run_without_ebay_production(monkeypatch):
    monkeypatch.setattr(radar_router, "source_statuses", lambda: [
        {"id": "ebay", "ready": False},
        {"id": "amazon", "ready": True},
    ])

    async def fake_amazon(keyword, marketplace):
        return {
            "keyword": keyword, "source": "AMAZON", "marketplace": marketplace,
            "marketplace_name": "Amazon France", "total_results": 321,
            "currency": "EUR", "median_price": None, "offers_sample": 0,
            "ranked_products": 1, "best_sales_rank": 42, "pricing_available": False,
            "history_available": False, "listing_change_percent": None, "items": [],
        }

    monkeypatch.setattr(radar_router, "analyze_amazon_market", fake_amazon)
    response = TestClient(app).post("/api/radar/scan", json={
        "keyword": "portable fan", "marketplaces": [], "amazon_marketplaces": ["AMAZON_FR"],
    })
    assert response.status_code == 200
    payload = response.json()
    assert payload["markets"][0]["source"] == "AMAZON"
    assert payload["markets"][0]["best_sales_rank"] == 42


def test_amazon_radar_ui_is_explicitly_read_only():
    html = TestClient(app).get("/").text
    assert 'data-provider="amazon"' in html
    assert 'name="refresh_token"' in html
    assert 'name="amazon_market" value="AMAZON_FR"' in html
    assert "Lecture seule Radar" in html
    assert "aucune opération Amazon d’écriture" in html


def test_amazon_client_has_no_catalog_order_or_listing_write_operation():
    source = inspect.getsource(AmazonRadarClient)
    assert "client.get(" in source
    assert "client.post(self.token_url" in source  # OAuth token exchange only.
    for forbidden in ("client.put(", "client.patch(", "client.delete(", "/orders", "/feeds", "/listings"):
        assert forbidden not in source
