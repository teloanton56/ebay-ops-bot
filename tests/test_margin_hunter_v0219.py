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


def test_cj_us_candidate_uses_real_us_freight_and_hits_margin_goal():
    class FakeCJ:
        async def product_detail(self, pid):
            return {"pid": pid, "name": "Car organizer", "risk_flags": [], "variants": [{"vid": "VID-1", "sku": "CJ-V1", "name": "Car organizer black", "price_usd": 3.0, "stock": 100, "image_url": "https://example.test/cj.jpg", "inventories": [{"country_code": "US", "stock": 100}]}]}
        async def product_inventory(self, pid):
            return {"pid": pid, "product_inventories": [{"country_code": "US", "stock": 100}], "variant_inventories": {"VID-1": [{"country_code": "US", "stock": 100, "storage_ids": []}]}}
        async def freight_options(self, vid, *, start_country, destination_country, storage_ids=None):
            assert start_country == "US" and destination_country == "US"
            return [{"name": "US Fast", "price_usd": 2.0, "delivery_days": "3-5 Days"}, {"name": "US Slow", "price_usd": 1.0, "delivery_days": "8-10 Days"}]
    market = {"competition_points": 12.0, "demand_points": 8.0}
    product = {"cj_pid": "PID-1", "sku": "CJ-1", "name": "Car organizer storage box", "price_usd": 3.0, "stock": 100, "match_strength": 1.0}
    candidate, error = asyncio.run(margin_hunter._deep_cj_candidate(FakeCJ(), product, reference_price=25.0, market=market, semaphore=asyncio.Semaphore(1)))
    assert error is None
    assert candidate["warehouse"] == "US"
    assert candidate["landed_cost"] == 5.0
    assert candidate["shipping_days"] == 5
    assert candidate["route_eligible"] is True
    assert candidate["goal_hit"] is True
    assert candidate["verdict"] == "PRIORITÉ US"


def test_cj_china_candidate_is_allowed_only_under_stricter_thresholds():
    class FakeCJ:
        async def product_detail(self, pid):
            return {"pid": pid, "name": "Replacement knob", "risk_flags": [], "variants": [{"vid": "VID-CN", "sku": "CJ-CN", "name": "Replacement knob", "price_usd": 3.0, "stock": 50, "inventories": [{"country_code": "CN", "stock": 50}]}]}
        async def product_inventory(self, pid):
            return {"pid": pid, "product_inventories": [{"country_code": "CN", "stock": 50}], "variant_inventories": {"VID-CN": [{"country_code": "CN", "stock": 50, "storage_ids": []}]}}
        async def freight_options(self, vid, *, start_country, destination_country, storage_ids=None):
            assert start_country == "CN" and destination_country == "US"
            return [{"name": "CJ Packet", "price_usd": 4.0, "delivery_days": "8-10 Days"}]
    product = {"cj_pid": "PID-CN", "sku": "CJ-CN", "name": "Replacement knob", "price_usd": 3.0, "stock": 50, "match_strength": 1.0}
    market = {"competition_points": 8.0, "demand_points": 0.0}
    good, error = asyncio.run(margin_hunter._deep_cj_candidate(FakeCJ(), product, reference_price=30.0, market=market, semaphore=asyncio.Semaphore(1)))
    assert error is None and good["route_eligible"] is True and good["verdict"] == "CHINE RENTABLE"
    weak, error = asyncio.run(margin_hunter._deep_cj_candidate(FakeCJ(), product, reference_price=14.0, market=market, semaphore=asyncio.Semaphore(1)))
    assert error is None and weak["route_eligible"] is False and weak["goal_hit"] is False
    assert weak["score"] <= 54 and weak["verdict"] == "REJETER"


def test_margin_hunter_requires_real_ebay_production(monkeypatch):
    fake = SimpleNamespace(ebay_effective_env="sandbox", ebay_client_id="SBX-key", ebay_client_secret="secret")
    monkeypatch.setattr(margin_hunter, "get_settings", lambda: fake)
    try:
        asyncio.run(margin_hunter.hunt_margin_opportunities("car organizer"))
    except ValueError as exc:
        assert "eBay Production" in str(exc)
    else:
        raise AssertionError("Margin Hunter must refuse Sandbox market data")


def test_margin_hunter_is_ebay_us_cj_only_in_backend_and_guided_ui():
    router = (ROOT / "app/routers/radar.py").read_text(encoding="utf-8")
    service = (ROOT / "app/services/margin_hunter.py").read_text(encoding="utf-8")
    dashboard = (ROOT / "app/templates/dashboard.html").read_text(encoding="utf-8")
    main = (ROOT / "app/main.py").read_text(encoding="utf-8")
    assert '@router.post("/margin-hunter")' in router
    assert 'analyze_ebay_market(keyword, "EBAY_US")' in service
    assert "aliexpress" not in service.lower() and "amazon" not in service.lower()
    assert "Radar eBay US" in dashboard and "CJ Dropshipping" in dashboard
    assert "margin_hunter.js" not in main


def test_margin_hunter_legacy_ui_is_not_cached_in_v024():
    main = (ROOT / "app/main.py").read_text(encoding="utf-8")
    worker = (ROOT / "app/static/service-worker.js").read_text(encoding="utf-8")
    version = main.split('VERSION = "', 1)[1].split('"', 1)[0]
    assert f"opsbot-v{version}-shell" in worker
    assert "margin_hunter.js" not in worker
    assert f"/static/simple_ui.js?v={version}" in worker
