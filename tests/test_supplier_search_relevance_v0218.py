import asyncio
from pathlib import Path

from app.routers.supplier_flow import _cj_group
from app.services.cj import CJClient
from app.services import aliexpress_dropship_search as ali_search
from app.services.supplier_relevance import (
    rank_supplier_results,
    supplier_relevance_score,
    supplier_result_is_relevant,
)


ROOT = Path(__file__).resolve().parents[1]


def test_pokemon_rejects_unrelated_supplier_products():
    assert supplier_result_is_relevant(
        "pokemon",
        "240W Nylon USB Type C Super Fast Charging Cable For Samsung Xiaomi",
    ) is False
    assert supplier_result_is_relevant(
        "pokemon",
        "Rotatable 3in1 Ceiling Fan with Remote Control Lighting Lamp",
    ) is False
    assert supplier_result_is_relevant(
        "pokemon",
        "Stylus Pen for Apple Pencil with LED Power Indicator",
    ) is False


def test_pokemon_accepts_real_matches_and_ignores_accents():
    assert supplier_result_is_relevant("pokemon", "Pokémon Pikachu Trading Card Binder") is True
    assert supplier_relevance_score("pokemon", "Pokémon Pikachu Trading Card Binder") == 1.0


def test_multiword_search_requires_a_meaningful_product_match():
    assert supplier_result_is_relevant("phone holder", "USB phone fast charger cable") is False
    assert supplier_result_is_relevant("phone holder", "Universal phone mount for car dashboard") is True


def test_rank_supplier_results_keeps_only_relevant_titles_and_sorts_them():
    rows = [
        {"name": "USB C charger cable", "id": 1},
        {"name": "Pokemon card binder Pikachu", "id": 2},
        {"name": "Pokemon", "id": 3},
        {"name": "Ceiling fan remote", "id": 4},
    ]
    ranked, rejected = rank_supplier_results("pokemon", rows, limit=20)
    assert [row["id"] for row in ranked] == [3, 2]
    assert rejected == 2
    assert all(row["match_strength"] >= 0.85 for row in ranked)


def test_cj_compare_fetches_wider_pool_and_filters_irrelevant_results(monkeypatch):
    monkeypatch.setattr(CJClient, "status", lambda self: {"connected": True})

    async def fake_search(self, **kwargs):
        assert kwargs["keyword"] == "pokemon"
        assert kwargs["size"] == 50
        assert kwargs["order_by"] == 0
        return {
            "products": [
                {
                    "cj_pid": "BAD-1",
                    "sku": "BAD-1",
                    "name": "240W USB Type C charging cable",
                    "price_usd": 1.99,
                    "stock": 100,
                    "listed_num": 30,
                },
                {
                    "cj_pid": "GOOD-1",
                    "sku": "GOOD-1",
                    "name": "Pokemon Pikachu card storage binder",
                    "price_usd": 4.99,
                    "stock": 80,
                    "listed_num": 12,
                },
            ],
        }

    monkeypatch.setattr(CJClient, "search_products", fake_search)
    group, errors = asyncio.run(_cj_group("pokemon"))
    assert errors == []
    assert group is not None
    assert [row["supplier_sku"] for row in group["products"]] == ["GOOD-1"]
    assert group["filtered_out"] == 1
    assert group["products"][0]["match_strength"] == 1.0


def test_aliexpress_search_uses_wider_pool_without_sales_sort_and_filters(monkeypatch):
    monkeypatch.setattr(ali_search, "aliexpress_connection_status", lambda: {"connected": True})

    async def fake_search(self, keyword, page_size=20):
        assert keyword == "pokemon"
        assert page_size == 50
        return [
            {
                "itemId": "BAD-ALI",
                "title": "Stylus Pen for Apple Pencil 2026",
                "targetSalePrice": "4.19",
                "targetOriginalPriceCurrency": "EUR",
            },
            {
                "itemId": "GOOD-ALI",
                "title": "Pokemon Pikachu collectible card album binder",
                "targetSalePrice": "6.25",
                "targetOriginalPriceCurrency": "EUR",
            },
        ]

    monkeypatch.setattr(ali_search.AliExpressDropshipSearchClient, "search", fake_search)
    offers, errors = asyncio.run(ali_search.aliexpress_dropship_supplier_offers("pokemon"))
    assert errors == []
    assert [row["supplier_sku"] for row in offers] == ["GOOD-ALI"]
    assert offers[0]["match_strength"] == 1.0


def test_aliexpress_text_search_does_not_force_sales_sort_anymore():
    source = (ROOT / "app/services/aliexpress_dropship_search.py").read_text(encoding="utf-8")
    assert '"sort": "salesDesc"' not in source
    assert "page_size=50" in source


def test_v0218_ui_exposes_relevance_and_cache_version():
    main = (ROOT / "app/main.py").read_text(encoding="utf-8")
    worker = (ROOT / "app/static/service-worker.js").read_text(encoding="utf-8")
    ui = (ROOT / "app/static/supplier_flow_v2.js").read_text(encoding="utf-8")
    assert 'VERSION = "0.21.8"' in main
    assert "opsbot-v0.21.8-shell" in worker
    assert "Pertinence ${Math.round(relevance * 100)}%" in ui
    assert "hors sujet masqué(s)" in ui
