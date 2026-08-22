import asyncio
import re
from pathlib import Path
from types import SimpleNamespace

from app.services import ebay_shop_spy


ROOT = Path(__file__).resolve().parents[1]


def test_extract_seller_username_from_raw_and_store_urls():
    assert ebay_shop_spy.extract_seller_username("lestylediscount") == "lestylediscount"
    assert ebay_shop_spy.extract_seller_username("@lestylediscount") == "lestylediscount"
    assert ebay_shop_spy.extract_seller_username("https://www.ebay.com/str/lestylediscount") == "lestylediscount"
    assert ebay_shop_spy.extract_seller_username("https://www.ebay.com/usr/lestylediscount") == "lestylediscount"
    assert ebay_shop_spy.extract_seller_username("https://www.ebay.com/sch/i.html?_ssn=lestylediscount") == "lestylediscount"
    exact = "https://www.ebay.com/sch/i.html?_ssn=style_discount&store_name=lestylediscount&_oac=1"
    assert ebay_shop_spy.extract_seller_username(exact) == "style_discount"


def test_shop_analysis_uses_current_browse_seller_filter_on_ebay_us(monkeypatch):
    monkeypatch.setattr(
        ebay_shop_spy,
        "get_settings",
        lambda: SimpleNamespace(
            ebay_effective_env="production",
            ebay_client_id="client-app-id",
            ebay_client_secret="client-secret",
        ),
    )

    async def fake_public_request(self, method, path, *, params=None, marketplace_id=None):
        assert method == "GET"
        assert path == "/buy/browse/v1/item_summary/search"
        assert marketplace_id == "EBAY_US"
        assert params["category_ids"] == "0"
        assert params["filter"] == "sellers:{style_discount},buyingOptions:{AUCTION|FIXED_PRICE|BEST_OFFER}"
        assert params["limit"] == 50
        assert params["offset"] == 0
        assert params["fieldgroups"] == "EXTENDED"
        assert "q" not in params
        return {
            "total": 2,
            "itemSummaries": [
                {
                    "itemId": "v1|1|0",
                    "legacyItemId": "1",
                    "title": "Car organizer",
                    "price": {"value": "19.99", "currency": "USD"},
                    "shippingOptions": [{"shippingCost": {"value": "0.00", "currency": "USD"}}],
                    "seller": {
                        "username": "style_discount",
                        "feedbackScore": 19000,
                        "feedbackPercentage": "99.9",
                        "sellerAccountType": "BUSINESS",
                    },
                    "image": {"imageUrl": "https://example.test/organizer.jpg"},
                    "itemWebUrl": "https://www.ebay.com/itm/1",
                    "itemLocation": {"country": "US", "city": "Miami"},
                    "condition": "New",
                },
                {
                    "itemId": "v1|2|0",
                    "legacyItemId": "2",
                    "title": "Car organizer 2",
                    "price": {"value": "29.99", "currency": "USD"},
                    "watchCount": 17,
                    "seller": {"username": "style_discount"},
                    "image": {"imageUrl": "https://example.test/organizer2.jpg"},
                    "itemWebUrl": "https://www.ebay.com/itm/2",
                    "itemLocation": {"country": "US"},
                },
            ],
        }

    monkeypatch.setattr(ebay_shop_spy.EbayClient, "public_request", fake_public_request)
    data = asyncio.run(ebay_shop_spy.analyze_ebay_shop("style_discount", limit=50))
    assert data["active_listings_total"] == 2
    assert data["sample_size"] == 2
    assert data["median_price"] == 24.99
    assert data["watchers_available"] is True
    assert data["seller"]["username"] == "style_discount"
    assert data["seller"]["feedback_score"] == 19000
    assert data["listings"][0]["buyer_total"] == 19.99
    assert data["listings"][0]["shipping_cost"] == 0.0
    assert "sales" not in data["listings"][0]
    assert "Browse" in data["note"]
    assert "nombre de ventes par annonce" in data["note"]
    assert "aucune vente n'est inventée" in data["note"]


def test_shop_spy_source_has_no_decommissioned_finding_dependency():
    source = (ROOT / "app/services/ebay_shop_spy.py").read_text(encoding="utf-8")
    assert "svcs.ebay.com" not in source
    assert "findItemsAdvanced" not in source
    assert 'BROWSE_ROOT_CATEGORY = "0"' in source
    assert '"/buy/browse/v1/item_summary/search"' in source
    assert "AUCTION|FIXED_PRICE|BEST_OFFER" in source


def test_shop_spy_frontend_has_us_to_cj_compare_and_add_flow():
    ui = (ROOT / "app/static/shop_spy.js").read_text(encoding="utf-8")
    main = (ROOT / "app/main.py").read_text(encoding="utf-8")
    worker = (ROOT / "app/static/service-worker.js").read_text(encoding="utf-8")
    version_match = re.search(r'VERSION = "([^"]+)"', main)
    assert version_match
    version = version_match.group(1)
    assert "Spy eBay Shop" in ui
    assert "eBay US" in ui
    assert "Comparer avec CJ" in ui
    assert "/api/shop-spy/analyze" in ui
    assert "/api/shop-spy/compare" in ui
    assert "/api/supplier-flow/add" in ui
    assert "Ventes" in ui and "Non exposées" in ui
    assert "AliExpress" not in ui
    assert "shop_spy.router" in main
    assert "shop_spy.js" in main
    assert f"opsbot-v{version}-shell" in worker
    assert f"/static/shop_spy.js?v={version}" in worker
