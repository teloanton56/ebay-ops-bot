import asyncio
from pathlib import Path
from types import SimpleNamespace

from app.services import margin_hunter


ROOT = Path(__file__).resolve().parents[1]


def test_cost_ratio_scoring_rewards_sub_30_percent_landed_cost():
    assert margin_hunter._cost_ratio_points(20) == 20.0
    assert margin_hunter._cost_ratio_points(30) == 15.0
    assert margin_hunter._cost_ratio_points(45) < 8.0
    assert margin_hunter._cost_ratio_points(60) == 0.0


def test_aliexpress_candidate_never_claims_verified_margin_without_shipping():
    market = {"competition_points": 12.0, "demand_points": 8.0}
    offers = [{
        "supplier_sku": "ALI-1",
        "name": "Car seat gap organizer storage box",
        "product_cost": 4.0,
        "currency": "EUR",
        "match_strength": 1.0,
        "rating": 4.8,
        "image_url": "https://example.test/a.jpg",
        "source_url": "https://example.test/a",
        "shipping_cost": None,
        "shipping_days": None,
    }]
    rows = margin_hunter._ali_candidates(offers, reference_price=24.99, market=market)
    assert len(rows) == 1
    row = rows[0]
    assert row["verified"] is False
    assert row["margin_percent"] is None
    assert row["landed_cost"] is None
    assert row["goal_hit"] is False
    assert row["score"] <= 72
    assert row["shipping_budget_to_30"] > 0
    assert row["verdict"] == "À CONFIRMER"


def test_cj_candidate_uses_real_france_freight_and_can_hit_margin_goal(monkeypatch):
    class FakeCJ:
        async def product_detail(self, pid):
            assert pid == "PID-1"
            return {
                "variants": [{
                    "vid": "VID-1",
                    "sku": "CJ-V1",
                    "name": "Car organizer black",
                    "price_usd": 3.0,
                    "stock": 100,
                    "image_url": "https://example.test/cj.jpg",
                    "inventories": [{"country_code": "FR", "stock": 100}],
                }]
            }

        async def freight_options(self, vid, start_country="CN", destination_country="FR"):
            assert vid == "VID-1"
            assert start_country == "FR"
            assert destination_country == "FR"
            return [
                {"name": "Fast", "price_usd": 2.0, "delivery_days": "3-5"},
                {"name": "Slow", "price_usd": 1.0, "delivery_days": "9-12"},
            ]

    market = {"competition_points": 12.0, "demand_points": 8.0}
    product = {
        "cj_pid": "PID-1",
        "sku": "CJ-1",
        "name": "Car organizer storage box",
        "price_usd": 3.0,
        "stock": 100,
        "match_strength": 1.0,
    }
    candidate, error = asyncio.run(margin_hunter._deep_cj_candidate(
        FakeCJ(),
        product,
        exchange_rate=1.0,
        reference_price=25.0,
        market=market,
        semaphore=asyncio.Semaphore(1),
    ))
    assert error is None
    assert candidate is not None
    assert candidate["verified"] is True
    assert candidate["supplier_cost"] == 3.0
    assert candidate["shipping_cost"] == 2.0
    assert candidate["landed_cost"] == 5.0
    assert candidate["cost_ratio_percent"] == 20.0
    assert candidate["shipping_days"] == 5
    assert candidate["margin_percent"] is not None
    assert candidate["estimated_profit"] is not None
    assert candidate["goal_hit"] is True
    assert candidate["verdict"] == "PRIORITÉ"


def test_margin_hunter_requires_real_ebay_production(monkeypatch):
    fake = SimpleNamespace(
        ebay_effective_env="sandbox",
        ebay_client_id="SBX-key",
        ebay_client_secret="secret",
    )
    monkeypatch.setattr(margin_hunter, "get_settings", lambda: fake)
    try:
        asyncio.run(margin_hunter.hunt_margin_opportunities("car organizer"))
    except ValueError as exc:
        assert "eBay Production" in str(exc)
    else:
        raise AssertionError("Margin Hunter must refuse Sandbox market data")


def test_margin_hunter_is_registered_in_radar_and_ui():
    router = (ROOT / "app/routers/radar.py").read_text(encoding="utf-8")
    ui = (ROOT / "app/static/margin_hunter.js").read_text(encoding="utf-8")
    main = (ROOT / "app/main.py").read_text(encoding="utf-8")
    assert '@router.post("/margin-hunter")' in router
    assert "/api/radar/margin-hunter" in ui
    assert "Objectif : coût livré ≤ 30 % du prix eBay" in ui
    assert "margin_hunter.js" in main


def test_v0219_cache_contains_margin_hunter():
    main = (ROOT / "app/main.py").read_text(encoding="utf-8")
    worker = (ROOT / "app/static/service-worker.js").read_text(encoding="utf-8")
    assert 'VERSION = "0.21.10"' in main
    assert "opsbot-v0.21.10-shell" in worker
    assert "/static/margin_hunter.js?v=0.21.10" in worker
