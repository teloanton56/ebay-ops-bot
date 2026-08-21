import asyncio

from app.services.marketplace_supplier_sources import (
    AliExpressSupplierClient,
    aliexpress_supplier_offers,
    amazon_supplier_offers,
)


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


def test_aliexpress_supplier_offers_normalize_affiliate_response(monkeypatch):
    monkeypatch.setenv("ALIEXPRESS_APP_KEY", "test-key")
    monkeypatch.setenv("ALIEXPRESS_APP_SECRET", "test-secret")

    async def fake_search(self, keyword, page_size=10):
        return {
            "aliexpress_affiliate_product_query_response": {
                "resp_result": {
                    "result": {
                        "products": {
                            "product": [
                                {
                                    "product_id": 123456789,
                                    "product_title": "Portable USB desk fan",
                                    "product_main_image_url": "https://example.test/aliexpress.jpg",
                                    "product_detail_url": "https://www.aliexpress.com/item/123456789.html",
                                    "target_sale_price": "6.95",
                                    "target_sale_price_currency": "EUR",
                                    "ship_to_days": "7",
                                    "shop_id": 98765,
                                    "shop_url": "https://www.aliexpress.com/store/98765",
                                }
                            ]
                        }
                    }
                }
            }
        }

    monkeypatch.setattr(AliExpressSupplierClient, "search", fake_search)
    offers, errors = asyncio.run(aliexpress_supplier_offers("portable fan"))
    assert errors == []
    assert len(offers) == 1
    offer = offers[0]
    assert offer["provider_code"] == "aliexpress"
    assert offer["supplier_sku"] == "123456789"
    assert offer["product_cost"] == 6.95
    assert offer["currency"] == "EUR"
    assert offer["shipping_days"] == 7
    assert offer["shipping_known"] is False


def test_aliexpress_signature_is_stable(monkeypatch):
    monkeypatch.setenv("ALIEXPRESS_APP_KEY", "key")
    monkeypatch.setenv("ALIEXPRESS_APP_SECRET", "secret")
    client = AliExpressSupplierClient()
    first = client._sign({"app_key": "key", "method": "demo", "keywords": "fan"})
    second = client._sign({"keywords": "fan", "method": "demo", "app_key": "key"})
    assert first == second
    assert len(first) == 32
