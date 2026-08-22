from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app
from app.services.radar_quota import _parse_browse_limits
from app.services.radar_runtime import DEFAULT_RADAR_SETTINGS, estimate_daily_browse_calls, load_radar_settings


def test_legacy_tiered_radar_profile_can_still_be_read_without_being_active():
    settings = load_radar_settings()
    estimate = estimate_daily_browse_calls(settings)
    assert settings == DEFAULT_RADAR_SETTINGS
    assert estimate["estimated_calls_per_day"] > 0


def test_developer_analytics_parser_keeps_working_for_future_use():
    parsed = _parse_browse_limits({
        "rateLimits": [{
            "apiContext": "buy",
            "apiName": "browse",
            "apiVersion": "v1",
            "resources": [{
                "name": "item",
                "rates": [{"limit": 5000, "remaining": 3900, "count": 1100, "timeWindow": 86400}],
            }],
        }],
    })
    assert parsed is not None
    assert parsed["resource"] == "item"
    assert parsed["remaining"] == 3900


def test_tiered_radar_api_and_assets_are_not_active_in_us_cj_mode():
    client = TestClient(app)
    response = client.get("/api/radar/auto/settings")
    html = client.get("/").text
    main = Path("app/main.py").read_text(encoding="utf-8")
    worker = Path("app/static/service-worker.js").read_text(encoding="utf-8")

    assert response.status_code == 404
    assert "tiered_radar.router" not in main
    assert "tiered_radar.js" not in html
    assert "tiered_radar.css" not in html
    assert "tiered_radar.js" not in worker
    assert "tiered_radar.css" not in worker


def test_social_discovery_assets_are_not_loaded():
    main = Path("app/main.py").read_text(encoding="utf-8")
    scheduler = Path("app/services/scheduler.py").read_text(encoding="utf-8")
    assert "auto_radar.js" not in main
    assert "tiered_radar.js" not in main
    assert "YouTubeClient" not in scheduler
    assert "TikTok" not in scheduler
