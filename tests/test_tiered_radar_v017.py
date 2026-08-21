import asyncio

from fastapi.testclient import TestClient

from app.config import get_settings
from app.main import app
from app.services import radar_quota, tiered_radar
from app.services.radar_quota import _parse_browse_limits, quota_status, reserve_browse_calls
from app.services.radar_runtime import (
    DEFAULT_RADAR_SETTINGS,
    estimate_daily_browse_calls,
    load_radar_settings,
    save_radar_settings,
)


def test_default_tiered_radar_profile_matches_target_capacity():
    settings = load_radar_settings()
    estimate = estimate_daily_browse_calls(settings)

    assert settings == DEFAULT_RADAR_SETTINGS
    assert settings["quick_minutes"] == 30
    assert settings["full_hours"] == 4
    assert settings["candidate_pool"] == 200
    assert settings["deep_candidates"] == 25
    assert settings["social_confirmations"] == 8
    assert estimate == {
        "quick_runs_per_day": 48,
        "full_runs_per_day": 6,
        "quick_calls_per_day": 1440,
        "full_calls_per_day": 396,
        "estimated_calls_per_day": 1836,
    }


def test_tiered_radar_settings_are_persistent_and_clamped():
    saved = save_radar_settings(
        {
            "quick_minutes": 1,
            "full_hours": 99,
            "candidate_pool": 500,
            "deep_candidates": 400,
            "social_confirmations": 40,
            "quick_opportunities": 100,
            "quota_reserve_percent": 2,
            "browse_daily_budget": 200,
        }
    )

    assert saved["quick_minutes"] == 15
    assert saved["full_hours"] == 24
    assert saved["candidate_pool"] == 200
    assert saved["deep_candidates"] == 50
    assert saved["social_confirmations"] == 10
    assert saved["quick_opportunities"] == 50
    assert saved["quota_reserve_percent"] == 10
    assert saved["browse_daily_budget"] == 1000
    assert load_radar_settings() == saved


def test_developer_analytics_parser_uses_most_constrained_browse_resource():
    parsed = _parse_browse_limits(
        {
            "rateLimits": [
                {
                    "apiContext": "buy",
                    "apiName": "browse",
                    "apiVersion": "v1",
                    "resources": [
                        {
                            "name": "item_summary",
                            "rates": [
                                {
                                    "limit": 5000,
                                    "remaining": 4300,
                                    "count": 700,
                                    "reset": "2026-08-22T00:00:00.000Z",
                                    "timeWindow": 86400,
                                }
                            ],
                        },
                        {
                            "name": "item",
                            "rates": [
                                {
                                    "limit": 5000,
                                    "remaining": 3900,
                                    "count": 1100,
                                    "reset": "2026-08-22T00:00:00.000Z",
                                    "timeWindow": 86400,
                                }
                            ],
                        },
                    ],
                }
            ]
        }
    )

    assert parsed is not None
    assert parsed["resource"] == "item"
    assert parsed["limit"] == 5000
    assert parsed["remaining"] == 3900
    assert len(parsed["resources"]) == 2


def test_quota_guard_falls_back_to_local_budget_and_reserves_calls(monkeypatch):
    async def unavailable():
        raise RuntimeError("analytics disabled")

    monkeypatch.setattr(radar_quota, "_fetch_actual_snapshot", unavailable)

    before = asyncio.run(quota_status(force=True))
    after = asyncio.run(reserve_browse_calls(66, "test-full"))

    assert before["source"] == "LOCAL_BUDGET"
    assert before["limit"] == 5000
    assert before["reserve_calls"] == 1000
    assert before["usable_remaining"] == 4000
    assert after["local_reserved"] == 66
    assert after["usable_remaining"] == 3934
    assert after["reserved_for_run"] == 66


def test_full_scan_collects_200_then_deeply_measures_25_and_confirms_8(monkeypatch):
    monkeypatch.setenv("EBAY_CLIENT_ID", "Anton-PRD-client")
    monkeypatch.setenv("EBAY_CLIENT_SECRET", "secret")
    monkeypatch.setenv("EBAY_ENV", "production")
    get_settings.cache_clear()
    save_radar_settings(DEFAULT_RADAR_SETTINGS)

    captured = {"candidate_limit": 0, "measured": 0, "social": 0, "reserved": 0}

    class FakeClient:
        async def get_application_token(self):
            return "token"

    async def fake_reserve(count, purpose, force_actual=False):
        captured["reserved"] = count
        return {"remaining": 4900, "reserved_for_run": count, "purpose": purpose}

    async def fake_tree(client, market):
        return {}

    def fake_categories(tree, limit):
        return [{"id": str(index), "name": f"Cat {index}", "group": f"Cat {index}"} for index in range(limit)]

    async def fake_browse(client, category, market, sort=None):
        return {"category": category, "sort": sort or "best_match", "items": []}

    async def fake_marketing(client, category, market):
        return {"category": category, "products": []}

    def fake_extract(browse_rows, marketing_rows, limit):
        captured["candidate_limit"] = limit
        return [
            {
                "keyword": f"produit test {index}",
                "category_name": "Maison",
                "marketing_rank": index + 1,
                "sources": ["eBay Best Match"],
                "sample_title": f"Produit test {index}",
                "sample_image": "",
            }
            for index in range(limit)
        ]

    async def fake_measure(client, candidate, market):
        captured["measured"] += 1
        return {
            "representative_title": candidate["sample_title"],
            "total_results": 250,
            "median_price": 29.9,
            "currency": "EUR",
            "sellers_sample": 20,
            "top_seller_share": 10,
            "recent_listing_share": 30,
            "fixed_price_share": 90,
            "sold_quantity": 120,
            "sales_velocity": 2.5,
            "listing_age_days": 48,
            "history_available": True,
            "item_url": "",
            "image_url": "",
        }

    async def fake_social(candidate, sources, country):
        captured["social"] += 1
        return {"keyword": candidate["keyword"], "results": [], "errors": []}

    def fake_upsert(candidate, measurement, score, social, market):
        return ({"id": captured["measured"], "keyword": candidate["keyword"], "score": score["score"]}, False)

    monkeypatch.setattr(tiered_radar, "EbayClient", FakeClient)
    monkeypatch.setattr(tiered_radar, "reserve_browse_calls", fake_reserve)
    monkeypatch.setattr(tiered_radar, "_start_run", lambda trigger, market: 1)
    monkeypatch.setattr(tiered_radar, "_finish_run", lambda *args, **kwargs: None)
    monkeypatch.setattr(tiered_radar, "_load_category_tree", fake_tree)
    monkeypatch.setattr(tiered_radar, "select_discovery_categories", fake_categories)
    monkeypatch.setattr(tiered_radar, "_browse_category", fake_browse)
    monkeypatch.setattr(tiered_radar, "_marketing_products", fake_marketing)
    monkeypatch.setattr(tiered_radar, "extract_candidate_phrases", fake_extract)
    monkeypatch.setattr(tiered_radar, "_measure_candidate", fake_measure)
    monkeypatch.setattr(tiered_radar, "connection_statuses", lambda: [{"id": "youtube", "connected": True}])
    monkeypatch.setattr(tiered_radar, "_confirm_social", fake_social)
    monkeypatch.setattr(tiered_radar, "_upsert_opportunity", fake_upsert)

    result = asyncio.run(tiered_radar.run_full_radar(trigger="manual-full"))

    assert result["status"] == "COMPLETED"
    assert result["candidates_collected"] == 200
    assert result["candidates_measured"] == 25
    assert result["social_confirmations"] == 8
    assert captured == {"candidate_limit": 200, "measured": 25, "social": 8, "reserved": 66}
    get_settings.cache_clear()


def test_tiered_radar_settings_api_and_assets_are_available():
    client = TestClient(app)
    response = client.get("/api/radar/auto/settings")
    html = client.get("/").text
    version = app.version

    assert response.status_code == 200
    assert response.json()["settings"]["quick_minutes"] == 30
    assert response.json()["settings"]["candidate_pool"] == 200
    assert f"tiered_radar.css?v={version}" in html
    assert f"tiered_radar.js?v={version}" in html
