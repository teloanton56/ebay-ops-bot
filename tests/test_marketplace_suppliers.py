import asyncio

from app.services.aliexpress_dropship_search import (
    AliExpressDropshipSearchClient,
    aliexpress_dropship_supplier_offers,
)
from app.services.marketplace_supplier_sources import amazon_supplier_offers


def test_amazon_supplier_offers_normalize_catalog(monkeypatch):
    monkeypatch.setattr(
        "app.services.marketplace_supplier_sources.connection_status",
        lambda provider: {"connected": provider == "amazon"},
    )

    async def fake_search(self, keyword, marketplace="AMAZON_FR", page_size=20, include_pricing=True):
        return {
            "products": [
                {
                    "asin": "B0TEST123",
                    "title": "Ventilateur portable rechargeable",
                    "price": 12.49,
                    "currency": "EUR",
                    "image_url": "https://example.test/amazon.jpg",
                    "url": "https://www.amazon.fr/dp/B0TEST123",
                    "offer_count": 5,
                    "sales_rank": 850,
                }
            ]
        }

    monkeypatch.setattr(
        "app.services.marketplace_supplier_sources.AmazonRadarClient.search_catalog",
        fake_search,
    )
    offers, errors = asyncio.run(amazon_supplier_offers("ventilateur portable"))
    assert errors == []
    assert len(offers) == 1
    offer = offers[0]
    assert offer["provider_code"] == "amazon"
    assert offer["supplier_sku"] == "B0TEST123"
    assert offer["product_cost"] == 12.49
    assert offer["shipping_known"] is False
    assert offer["sales_rank"] == 850


def test_aliexpress_dropship_offers_normalize_text_search(monkeypatch):
    monkeypatch.setattr(
        "app.services.aliexpress_dropship_search.aliexpress_connection_status",
        lambda: {"connected": True},
    )

    async def fake_search(self, keyword, page_size=10):
        return [
            {
                "itemId": 123456789,
                "title": "Portable USB desk fan",
                "itemMainPic": "//example.test/aliexpress.jpg",
                "itemUrl": "https://www.aliexpress.com/item/123456789.html",
                "targetSalePrice": "6.95",
                "targetOriginalPriceCurrency": "EUR",
                "score": "4.7",
                "orders": "321",
            }
        ]

    monkeypatch.setattr(AliExpressDropshipSearchClient, "search", fake_search)
    offers, errors = asyncio.run(aliexpress_dropship_supplier_offers("portable fan"))
    assert errors == []
    assert len(offers) == 1
    offer = offers[0]
    assert offer["provider_code"] == "aliexpress"
    assert offer["supplier_sku"] == "123456789"
    assert offer["product_cost"] == 6.95
    assert offer["currency"] == "EUR"
    assert offer["shipping_cost"] is None
    assert offer["shipping_days"] is None
    assert offer["shipping_known"] is False
    assert offer["rating"] == 4.7


def test_aliexpress_dropship_signature_is_stable(monkeypatch):
    monkeypatch.setattr(
        "app.services.aliexpress_dropship_search.load_aliexpress_credentials",
        lambda: {"app_key": "key", "app_secret": "secret", "access_token": "token"},
    )
    client = AliExpressDropshipSearchClient()
    first = client._sign({"app_key": "key", "method": "demo", "keyword": "fan"})
    second = client._sign({"keyword": "fan", "method": "demo", "app_key": "key"})
    assert first == second
    assert len(first) == 64
