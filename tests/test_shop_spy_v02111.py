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
    monkeypatch.setattr(ebay_shop_spy, "get_settings", lambda: SimpleNamespace(ebay_effective_env="production", ebay_client_id="client-app-id", ebay_client_secret="client-secret"))
    async def fake_public_request(self, method, path, *, params=None, marketplace_id=None):
        assert method == "GET" and path == "/buy/browse/v1/item_summary/search" and marketplace_id == "EBAY_US"
        assert params["filter"] == "sellers:{style_discount},buyingOptions:{AUCTION|FIXED_PRICE|BEST_OFFER}"
        return {"total": 2, "itemSummaries": [
            {"itemId": "v1|1|0", "legacyItemId": "1", "title": "Car organizer", "price": {"value": "19.99", "currency": "USD"}, "shippingOptions": [{"shippingCost": {"value": "0.00", "currency": "USD"}}], "seller": {"username": "style_discount", "feedbackScore": 19000, "feedbackPercentage": "99.9", "sellerAccountType": "BUSINESS"}, "image": {"imageUrl": "https://example.test/organizer.jpg"}, "itemWebUrl": "https://www.ebay.com/itm/1", "itemLocation": {"country": "US", "city": "Miami"}, "condition": "New"},
            {"itemId": "v1|2|0", "legacyItemId": "2", "title": "Car organizer 2", "price": {"value": "29.99", "currency": "USD"}, "watchCount": 17, "seller": {"username": "style_discount"}, "image": {"imageUrl": "https://example.test/organizer2.jpg"}, "itemWebUrl": "https://www.ebay.com/itm/2", "itemLocation": {"country": "US"}},
        ]}
    monkeypatch.setattr(ebay_shop_spy.EbayClient, "public_request", fake_public_request)
    data = asyncio.run(ebay_shop_spy.analyze_ebay_shop("style_discount", limit=50))
    assert data["active_listings_total"] == 2
    assert data["median_price"] == 24.99
    assert data["seller"]["username"] == "style_discount"
    assert data["listings"][0]["buyer_total"] == 19.99
    assert "sales" not in data["listings"][0]
    assert "aucune vente n'est inventée" in data["note"]


def test_shop_spy_source_has_no_decommissioned_finding_dependency():
    source = (ROOT / "app/services/ebay_shop_spy.py").read_text(encoding="utf-8")
    assert "svcs.ebay.com" not in source
    assert "findItemsAdvanced" not in source
    assert 'BROWSE_ROOT_CATEGORY = "0"' in source
    assert '"/buy/browse/v1/item_summary/search"' in source


def test_shop_spy_backend_remains_available_but_separate_ui_is_dormant():
    ui = (ROOT / "app/static/shop_spy.js").read_text(encoding="utf-8")
    main = (ROOT / "app/main.py").read_text(encoding="utf-8")
    dashboard = (ROOT / "app/templates/dashboard.html").read_text(encoding="utf-8")
    worker = (ROOT / "app/static/service-worker.js").read_text(encoding="utf-8")
    version_match = re.search(r'VERSION = "([^"]+)"', main)
    assert version_match
    version = version_match.group(1)
    assert "Spy eBay Shop" in ui and "Comparer avec CJ" in ui
    assert "shop_spy.router" in main
    assert "shop_spy.js" not in main
    assert "shop_spy.js" not in dashboard
    assert f"opsbot-v{version}-shell" in worker
    assert "shop_spy.js" not in worker
