import asyncio
from pathlib import Path
from types import SimpleNamespace

from app.services import ebay_shop_spy


ROOT = Path(__file__).resolve().parents[1]


def test_extract_seller_username_from_raw_and_store_urls():
    assert ebay_shop_spy.extract_seller_username("lestylediscount") == "lestylediscount"
    assert ebay_shop_spy.extract_seller_username("@lestylediscount") == "lestylediscount"
    assert ebay_shop_spy.extract_seller_username("https://www.ebay.fr/str/lestylediscount") == "lestylediscount"
    assert ebay_shop_spy.extract_seller_username("https://www.ebay.fr/usr/lestylediscount") == "lestylediscount"
    assert ebay_shop_spy.extract_seller_username("https://www.ebay.fr/sch/i.html?_ssn=lestylediscount") == "lestylediscount"


def test_shop_analysis_uses_official_seller_filter_and_does_not_invent_sales(monkeypatch):
    monkeypatch.setattr(
        ebay_shop_spy,
        "get_settings",
        lambda: SimpleNamespace(
            ebay_effective_env="production",
            ebay_client_id="client",
            ebay_client_secret="secret",
        ),
    )

    async def fake_public_request(self, method, path, *, params=None, marketplace_id=None):
        assert method == "GET"
        assert path == "/buy/browse/v1/item_summary/search"
        assert params["filter"] == "sellers:{lestylediscount},deliveryCountry:FR"
        assert marketplace_id == "EBAY_FR"
        return {
            "total": 2,
            "itemSummaries": [
                {
                    "itemId": "v1|1|0",
                    "legacyItemId": "1",
                    "title": "Mini camera WiFi",
                    "price": {"value": "10.99", "currency": "EUR"},
                    "shippingOptions": [{"shippingCost": {"value": "0.00", "currency": "EUR"}}],
                    "seller": {
                        "username": "lestylediscount",
                        "feedbackScore": 19000,
                        "feedbackPercentage": "99.9",
                        "sellerAccountType": "BUSINESS",
                    },
                    "image": {"imageUrl": "https://example.test/camera.jpg"},
                    "itemWebUrl": "https://www.ebay.fr/itm/1",
                    "itemLocation": {"country": "FR", "city": "Faremoutiers"},
                },
                {
                    "itemId": "v1|2|0",
                    "legacyItemId": "2",
                    "title": "Mini camera WiFi 2",
                    "price": {"value": "14.99", "currency": "EUR"},
                    "watchCount": 17,
                    "seller": {"username": "lestylediscount"},
                    "image": {"imageUrl": "https://example.test/camera2.jpg"},
                    "itemWebUrl": "https://www.ebay.fr/itm/2",
                    "itemLocation": {"country": "FR"},
                },
            ],
        }

    monkeypatch.setattr(ebay_shop_spy.EbayClient, "public_request", fake_public_request)
    data = asyncio.run(ebay_shop_spy.analyze_ebay_shop("lestylediscount", limit=50))
    assert data["active_listings_total"] == 2
    assert data["sample_size"] == 2
    assert data["median_price"] == 12.99
    assert data["watchers_available"] is True
    assert data["seller"]["username"] == "lestylediscount"
    assert data["listings"][0]["buyer_total"] == 10.99
    assert "sales" not in data["listings"][0]
    assert "volume de ventes par annonce n'est pas exposé" in data["note"]


def test_shop_spy_frontend_has_real_tab_compare_and_add_flow():
    ui = (ROOT / "app/static/shop_spy.js").read_text(encoding="utf-8")
    main = (ROOT / "app/main.py").read_text(encoding="utf-8")
    worker = (ROOT / "app/static/service-worker.js").read_text(encoding="utf-8")
    assert "Spy eBay Shop" in ui
    assert 'data-section = \'shop-spy\'' in ui or "dataset.section = 'shop-spy'" in ui
    assert "/api/shop-spy/analyze" in ui
    assert "/api/shop-spy/compare" in ui
    assert "/api/supplier-flow/add" in ui
    assert "Signal ventes" in ui
    assert "Non exposé" in ui
    assert "shop_spy.router" in main
    assert "shop_spy.js" in main
    assert "/static/shop_spy.js?v=0.21.11" in worker
