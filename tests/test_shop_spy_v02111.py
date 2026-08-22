import asyncio
import re
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
    exact = "https://www.ebay.fr/sch/i.html?_ssn=style_discount&store_name=lestylediscount&_oac=1&_trksid=p4429486.m3561.l161211"
    assert ebay_shop_spy.extract_seller_username(exact) == "style_discount"


def test_shop_analysis_uses_finding_seller_filter_without_keyword(monkeypatch):
    monkeypatch.setattr(
        ebay_shop_spy,
        "get_settings",
        lambda: SimpleNamespace(
            ebay_effective_env="production",
            ebay_client_id="client-app-id",
        ),
    )

    payload = {
        "findItemsAdvancedResponse": [{
            "ack": ["Success"],
            "paginationOutput": [{"totalEntries": ["2"], "totalPages": ["1"]}],
            "searchResult": [{
                "@count": "2",
                "item": [
                    {
                        "itemId": ["1"],
                        "title": ["Mini camera WiFi"],
                        "galleryURL": ["https://example.test/camera.jpg"],
                        "viewItemURL": ["https://www.ebay.fr/itm/1"],
                        "country": ["FR"],
                        "location": ["Faremoutiers"],
                        "condition": [{"conditionDisplayName": ["Neuf"]}],
                        "listingInfo": [{"startTime": ["2026-01-01T00:00:00.000Z"]}],
                        "sellingStatus": [{"currentPrice": [{"@currencyId": "EUR", "__value__": "10.99"}]}],
                        "shippingInfo": [{"shippingServiceCost": [{"@currencyId": "EUR", "__value__": "0.00"}]}],
                        "sellerInfo": [{
                            "sellerUserName": ["style_discount"],
                            "feedbackScore": ["19000"],
                            "positiveFeedbackPercent": ["99.9"],
                        }],
                    },
                    {
                        "itemId": ["2"],
                        "title": ["Mini camera WiFi 2"],
                        "galleryURL": ["https://example.test/camera2.jpg"],
                        "viewItemURL": ["https://www.ebay.fr/itm/2"],
                        "country": ["FR"],
                        "sellingStatus": [{"currentPrice": [{"@currencyId": "EUR", "__value__": "14.99"}]}],
                        "shippingInfo": [{"shippingServiceCost": [{"@currencyId": "EUR", "__value__": "0.00"}]}],
                        "sellerInfo": [{"sellerUserName": ["style_discount"]}],
                    },
                ],
            }],
        }]
    }

    class FakeResponse:
        status_code = 200
        is_error = False

        def json(self):
            return payload

    class FakeAsyncClient:
        def __init__(self, *args, **kwargs):
            assert kwargs.get("timeout") == 45

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def get(self, url, *, params=None):
            assert url == ebay_shop_spy.FINDING_ENDPOINT
            assert params["OPERATION-NAME"] == "findItemsAdvanced"
            assert params["SECURITY-APPNAME"] == "client-app-id"
            assert params["GLOBAL-ID"] == "EBAY-FR"
            assert params["itemFilter(0).name"] == "Seller"
            assert params["itemFilter(0).value(0)"] == "style_discount"
            assert params["itemFilter(1).name"] == "LocatedIn"
            assert params["itemFilter(1).value(0)"] == "WorldWide"
            assert params["paginationInput.entriesPerPage"] == "50"
            assert "q" not in params
            assert "keywords" not in params
            assert "category_ids" not in params
            return FakeResponse()

    monkeypatch.setattr(ebay_shop_spy.httpx, "AsyncClient", FakeAsyncClient)
    data = asyncio.run(ebay_shop_spy.analyze_ebay_shop("style_discount", limit=50))
    assert data["active_listings_total"] == 2
    assert data["sample_size"] == 2
    assert data["median_price"] == 12.99
    assert data["watchers_available"] is False
    assert data["seller"]["username"] == "style_discount"
    assert data["seller"]["feedback_score"] == 19000
    assert data["seller"]["feedback_percent"] == 99.9
    assert data["listings"][0]["buyer_total"] == 10.99
    assert data["listings"][0]["shipping_cost"] == 0.0
    assert "sales" not in data["listings"][0]
    assert "findItemsAdvanced" in data["note"]
    assert "volume de ventes par annonce" in data["note"]


def test_shop_spy_frontend_has_real_tab_compare_and_add_flow():
    ui = (ROOT / "app/static/shop_spy.js").read_text(encoding="utf-8")
    main = (ROOT / "app/main.py").read_text(encoding="utf-8")
    worker = (ROOT / "app/static/service-worker.js").read_text(encoding="utf-8")
    version_match = re.search(r'VERSION = "([^"]+)"', main)
    assert version_match
    version = version_match.group(1)
    assert "Spy eBay Shop" in ui
    assert 'data-section = \'shop-spy\'' in ui or "dataset.section = 'shop-spy'" in ui
    assert "/api/shop-spy/analyze" in ui
    assert "/api/shop-spy/compare" in ui
    assert "/api/supplier-flow/add" in ui
    assert "Signal ventes" in ui
    assert "Non exposé" in ui
    assert "shop_spy.router" in main
    assert "shop_spy.js" in main
    assert f"opsbot-v{version}-shell" in worker
    assert f"/static/shop_spy.js?v={version}" in worker
