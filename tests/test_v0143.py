import asyncio
from pathlib import Path

from app.config import get_settings
from app.services import db
from app.services.connections import YouTubeClient


def test_youtube_discovery_legacy_module_still_filters_noise(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "shorts.db"))
    get_settings.cache_clear()
    db.init_db()
    search_params = []

    async def fake_get(self, path, params):
        if path == "/search":
            search_params.append(params)
            if "#ecommerce" in params["q"]:
                return {"items": [{"id": {"videoId": "commerce-1"}}, {"id": {"videoId": "gaming"}}]}
            return {"items": [{"id": {"videoId": "commerce-2"}}, {"id": {"videoId": "too-long"}}]}
        return {"items": [
            {"id": "commerce-1", "snippet": {"title": "Mini portable blender #dropshipping", "description": "A useful kitchen find #ecommerce #productfinds", "tags": ["portable blender", "kitchen"], "channelTitle": "Product Lab", "publishedAt": "2026-08-17T10:00:00Z", "thumbnails": {}}, "contentDetails": {"duration": "PT35S"}, "statistics": {"viewCount": "150000", "likeCount": "9000", "commentCount": "400"}},
            {"id": "commerce-2", "snippet": {"title": "Portable blender for smoothies #amazonfinds", "description": "Product demo #tiktokmademebuyit", "tags": ["portable blender"], "channelTitle": "Useful Finds", "publishedAt": "2026-08-18T10:00:00Z", "thumbnails": {}}, "contentDetails": {"duration": "PT1M12S"}, "statistics": {"viewCount": "90000", "likeCount": "5000", "commentCount": "210"}},
            {"id": "gaming", "snippet": {"title": "Roblox Minecraft trailer #shorts", "description": "Gaming teaser", "tags": ["roblox", "minecraft"], "channelTitle": "Game Channel", "thumbnails": {}}, "contentDetails": {"duration": "PT25S"}, "statistics": {"viewCount": "9999999"}},
            {"id": "too-long", "snippet": {"title": "Portable vacuum #ecommerce", "description": "Product find", "tags": ["portable vacuum"], "channelTitle": "Long Video", "thumbnails": {}}, "contentDetails": {"duration": "PT3M15S"}, "statistics": {"viewCount": "500000"}},
        ]}

    monkeypatch.setattr(YouTubeClient, "_get", fake_get)
    result = asyncio.run(YouTubeClient().discover("FR"))
    assert len(search_params) == 2
    assert result["source"] == "YOUTUBE_SHORTS_COMMERCE"
    assert result["observed_count"] == 2
    assert any(theme["keyword"] == "portable blender" for theme in result["themes"])
    get_settings.cache_clear()


def test_v024_active_radar_ui_excludes_social_short_scope():
    dashboard = Path("app/templates/dashboard.html").read_text(encoding="utf-8")
    main = Path("app/main.py").read_text(encoding="utf-8")
    assert "SHORTS E-COMMERCE" not in dashboard
    assert "YouTube" not in dashboard
    assert "TikTok" not in dashboard
    assert "Radar eBay US" in dashboard
    assert "simple_ui.js" not in main or "provider_cleanup.js" not in main
