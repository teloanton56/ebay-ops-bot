from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app


ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_v023_removes_social_and_tiered_radar_from_active_shell():
    html = TestClient(app).get("/").text
    worker = read("app/static/service-worker.js")
    main = read("app/main.py")

    assert "auto_radar.js" not in html
    assert "tiered_radar.js" not in html
    assert "auto_radar.css" not in html
    assert "tiered_radar.css" not in html
    assert "auto_radar.js" not in worker
    assert "tiered_radar.js" not in worker
    assert "auto_radar.router" not in main


def test_removed_discovery_endpoints_are_absent():
    with TestClient(app) as client:
        discover = client.post("/api/radar/discover", json={"country": "US"})
        signals = client.post(
            "/api/connections/signals/scan",
            json={"keyword": "car organizer", "sources": ["youtube", "tiktok"], "country": "US"},
        )

    assert discover.status_code == 404
    assert signals.status_code == 404


def test_scheduler_has_no_background_social_or_multisource_radar_jobs():
    scheduler = read("app/services/scheduler.py")
    assert "scheduled_radar_quick" not in scheduler
    assert "scheduled_radar_full" not in scheduler
    assert "YouTube" not in scheduler
    assert "TikTok" not in scheduler
    assert "analyze_amazon_market" not in scheduler
    assert "sync-cj-ebay-us" in scheduler


def test_radar_sources_are_only_ebay_us_and_cj():
    with TestClient(app) as client:
        response = client.get("/api/radar/sources")
    assert response.status_code == 200
    rows = response.json()
    assert [row["id"] for row in rows] == ["ebay", "cj"]
    assert rows[0]["name"] == "eBay US"
    assert rows[1]["name"] == "CJ Dropshipping"


def test_active_radar_scan_rejects_legacy_marketplace_arrays(monkeypatch):
    from app.routers import radar as radar_router

    async def fake_ebay(keyword, marketplace):
        assert keyword == "car organizer"
        assert marketplace == "EBAY_US"
        return {
            "keyword": keyword,
            "source": "EBAY",
            "marketplace": "EBAY_US",
            "total_results": 120,
            "currency": "USD",
            "median_price": 29.99,
            "min_price": 19.99,
            "max_price": 39.99,
            "sellers_sample": 25,
            "top_seller_share": 8.0,
            "listing_change_percent": None,
        }

    monkeypatch.setattr(radar_router, "analyze_ebay_market", fake_ebay)
    with TestClient(app) as client:
        response = client.post(
            "/api/radar/scan",
            json={
                "keyword": "car organizer",
                "marketplaces": ["EBAY_FR", "EBAY_DE"],
                "amazon_marketplaces": ["AMAZON_FR"],
            },
        )

    assert response.status_code == 422
