import asyncio
from pathlib import Path

from fastapi.testclient import TestClient

from app.config import get_settings
from app.main import app
from app.services import db
from app.services.connections import YouTubeClient


def test_youtube_discovery_targets_recent_commerce_shorts_and_removes_noise(tmp_path, monkeypatch):
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
        assert path == "/videos"
        assert params["part"] == "snippet,statistics,contentDetails"
        return {"items": [
            {
                "id": "commerce-1",
                "snippet": {
                    "title": "Mini portable blender #dropshipping",
                    "description": "A useful kitchen find #ecommerce #productfinds",
                    "tags": ["portable blender", "kitchen"], "channelTitle": "Product Lab",
                    "publishedAt": "2026-08-17T10:00:00Z", "thumbnails": {},
                },
                "contentDetails": {"duration": "PT35S"},
                "statistics": {"viewCount": "150000", "likeCount": "9000", "commentCount": "400"},
            },
            {
                "id": "commerce-2",
                "snippet": {
                    "title": "Portable blender for smoothies #amazonfinds",
                    "description": "Product demo #tiktokmademebuyit",
                    "tags": ["portable blender"], "channelTitle": "Useful Finds",
                    "publishedAt": "2026-08-18T10:00:00Z", "thumbnails": {},
                },
                "contentDetails": {"duration": "PT1M12S"},
                "statistics": {"viewCount": "90000", "likeCount": "5000", "commentCount": "210"},
            },
            {
                "id": "gaming",
                "snippet": {
                    "title": "Roblox Minecraft trailer #shorts", "description": "Gaming teaser",
                    "tags": ["roblox", "minecraft"], "channelTitle": "Game Channel", "thumbnails": {},
                },
                "contentDetails": {"duration": "PT25S"},
                "statistics": {"viewCount": "9999999"},
            },
            {
                "id": "too-long",
                "snippet": {
                    "title": "Portable vacuum #ecommerce", "description": "Product find",
                    "tags": ["portable vacuum"], "channelTitle": "Long Video", "thumbnails": {},
                },
                "contentDetails": {"duration": "PT3M15S"},
                "statistics": {"viewCount": "500000"},
            },
        ]}

    monkeypatch.setattr(YouTubeClient, "_get", fake_get)
    result = asyncio.run(YouTubeClient().discover("FR"))

    assert len(search_params) == 2
    assert all(params["type"] == "video" and params["videoDuration"] == "short" for params in search_params)
    assert all(params["order"] == "viewCount" and params["publishedAfter"].endswith("Z") for params in search_params)
    assert all(params["maxResults"] == 25 for params in search_params)
    assert result["source"] == "YOUTUBE_SHORTS_COMMERCE"
    assert result["searched_count"] == 4
    assert result["observed_count"] == 2
    assert {item["video_id"] for item in result["items"]} == {"commerce-1", "commerce-2"}
    assert all(item["duration_seconds"] <= 180 for item in result["items"])
    assert any(theme["keyword"] == "portable blender" for theme in result["themes"])
    assert not any("roblox" in theme["keyword"] or "minecraft" in theme["keyword"] for theme in result["themes"])
    assert not any("dropshipping" in theme["keyword"] or "ecommerce" in theme["keyword"] for theme in result["themes"])
    assert db.list_trend_discoveries()[0]["source"] == "YOUTUBE_SHORTS_COMMERCE"
    get_settings.cache_clear()


def test_radar_ui_explains_commerce_short_scope_and_view_limitations():
    html = TestClient(app).get("/").text
    assert "SHORTS E-COMMERCE" in html
    assert "#dropshipping" in html
    assert "Le gaming et les bandes-annonces générales sont écartés" in html
    script = Path("app/static/app.js").read_text(encoding="utf-8")
    assert "Les vues Shorts comptent les démarrages et relectures, pas des ventes" in script
