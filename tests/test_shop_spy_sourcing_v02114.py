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


def test_shop_spy_compare_finds_equivalents_with_targeted_queries(monkeypatch):
    cj_queries = []
    ali_queries = []

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

        async def usd_to_eur(self):
            return {"rate": 1.0}

    async def fake_deep_cj_candidate(client, product, **kwargs):
        return ({
            "provider": "CJ",
            "verified": True,
            "goal_hit": True,
            "score": 88.0,
            "supplier_sku": product["sku"],
            "name": product["name"],
            "quality_evidence": [],
        }, None)

    async def fake_aliexpress_offers(keyword):
        ali_queries.append(keyword)
        if keyword == "tester detector diamond gemstone":
            return ([{
                "provider": "AliExpress",
                "provider_code": "aliexpress",
                "supplier_sku": "ALI-DIAMOND-1",
                "name": "Diamond Tester Pen High Accuracy Gemstone Detector",
                "product_cost": 3.2,
                "shipping_cost": None,
                "currency": "EUR",
                "stock": None,
                "shipping_days": None,
                "warehouse": "CN/EU selon annonce",
                "image_url": "https://example.test/ali.jpg",
                "source_url": "https://example.test/ali",
                "match_strength": 0.92,
                "rating": 4.8,
            }], [])
        return ([], [{
            "source": "AliExpress",
            "message": f"Aucun produit pertinent trouvé pour « {keyword} »",
        }])

    monkeypatch.setattr(shop_spy_sourcing, "CJClient", FakeCJClient)
    monkeypatch.setattr(shop_spy_sourcing, "_deep_cj_candidate", fake_deep_cj_candidate)
    monkeypatch.setattr(shop_spy_sourcing, "aliexpress_dropship_supplier_offers", fake_aliexpress_offers)

    data = asyncio.run(shop_spy_sourcing.compare_shop_listing(EBAY_TITLE, 19.99, limit=8))

    assert data["search_queries"][0] == "tester detector diamond gemstone"
    assert cj_queries[0] == "tester detector diamond gemstone"
    assert ali_queries[0] == "tester detector diamond gemstone"
    providers = {row["provider"] for row in data["candidates"]}
    assert providers == {"CJ", "AliExpress"}
    assert all(row.get("matched_query") == "tester detector diamond gemstone" for row in data["candidates"])
    assert not any("Aucun produit pertinent" in row.get("message", "") for row in data["errors"])
