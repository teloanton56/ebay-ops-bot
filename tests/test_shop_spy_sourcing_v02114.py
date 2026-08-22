import asyncio

from app.services import shop_spy_sourcing
from app.services.sourcing_queries import build_supplier_search_queries


EBAY_TITLE = "✅ Testeur Détecteur Diamant Pierre Précieuse V2 Professionnel Bijoux Outil Stylo"


def test_long_french_ebay_title_builds_short_supplier_queries():
    queries = build_supplier_search_queries(EBAY_TITLE)
    assert queries[0] == "tester detector diamond gemstone"
    assert queries[1] == "testeur detecteur diamant pierre"
    assert queries[-1] == EBAY_TITLE
    assert "professionnel" not in queries[0]
    assert "outil" not in queries[0]


def test_shop_spy_compare_finds_cj_equivalent_with_targeted_queries(monkeypatch):
    cj_queries = []

    class FakeCJClient:
        def status(self):
            return {"connected": True}

        async def search_products(self, *, keyword, size, min_stock, order_by):
            cj_queries.append(keyword)
            if keyword == "tester detector diamond gemstone":
                return {
                    "products": [{
                        "cj_pid": "cj-diamond-1",
                        "sku": "CJ-DIAMOND-1",
                        "name": "Portable Diamond Tester Pen Gemstone Detector",
                        "price_usd": 2.5,
                        "stock": 100,
                        "image_url": "https://example.test/cj.jpg",
                    }]
                }
            return {"products": []}

    async def fake_deep_cj_candidate(client, product, **kwargs):
        return ({
            "provider": "CJ",
            "verified": True,
            "goal_hit": True,
            "score": 88.0,
            "warehouse": "US",
            "supplier_sku": product["sku"],
            "name": product["name"],
            "quality_evidence": [],
        }, None)

    monkeypatch.setattr(shop_spy_sourcing, "CJClient", FakeCJClient)
    monkeypatch.setattr(shop_spy_sourcing, "_deep_cj_candidate", fake_deep_cj_candidate)

    data = asyncio.run(shop_spy_sourcing.compare_shop_listing(EBAY_TITLE, 19.99, limit=8))

    assert data["search_queries"][0] == "tester detector diamond gemstone"
    assert cj_queries[0] == "tester detector diamond gemstone"
    assert data["marketplace"] == "EBAY_US"
    assert data["currency"] == "USD"
    assert {row["provider"] for row in data["candidates"]} == {"CJ"}
    assert all(row.get("matched_query") == "tester detector diamond gemstone" for row in data["candidates"])
    assert "AliExpress" not in shop_spy_sourcing.__dict__
