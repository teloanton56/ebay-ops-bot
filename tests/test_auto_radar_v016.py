from pathlib import Path

from fastapi.testclient import TestClient

from app.config import get_settings
from app.main import app
from app.services.auto_radar import (
    _upsert_opportunity,
    dismiss_auto_opportunity,
    extract_candidate_phrases,
    list_auto_opportunities,
    score_auto_opportunity,
    select_discovery_categories,
)
from app.services.db import init_db, list_alerts


def test_category_selection_prefers_commercial_families_and_excludes_vehicles():
    tree = {
        "rootCategoryNode": {
            "childCategoryTreeNodes": [
                {"category": {"categoryId": "1", "categoryName": "Maison et jardin"}},
                {"category": {"categoryId": "2", "categoryName": "Auto, moto - pièces et accessoires"}},
                {"category": {"categoryId": "3", "categoryName": "Véhicules"}},
                {"category": {"categoryId": "4", "categoryName": "Animaux"}},
                {"category": {"categoryId": "5", "categoryName": "Beauté et parfums"}},
            ]
        }
    }

    selected = select_discovery_categories(tree, limit=4)

    assert {row["id"] for row in selected} == {"1", "2", "4", "5"}
    assert all(row["id"] != "3" for row in selected)


def test_candidate_extraction_uses_repetition_and_best_selling_signal():
    browse_rows = [
        {
            "category": {"name": "Maison"},
            "sort": "best_match",
            "items": [
                {"title": "Ventilateur portable rechargeable silencieux", "seller": {"username": "a"}},
                {"title": "Ventilateur portable rechargeable de bureau", "seller": {"username": "b"}},
                {"title": "Support téléphone voiture magnétique", "seller": {"username": "c"}},
            ],
        },
        {
            "category": {"name": "Maison"},
            "sort": "newlyListed",
            "items": [
                {"title": "Ventilateur portable rechargeable compact", "seller": {"username": "d"}},
            ],
        },
    ]
    marketing_rows = [
        {
            "category": {"name": "Maison"},
            "products": [{"title": "Ventilateur portable rechargeable", "epid": "123"}],
        }
    ]

    candidates = extract_candidate_phrases(browse_rows, marketing_rows, limit=4)

    assert candidates
    assert candidates[0]["keyword"] in {"ventilateur portable rechargeable", "ventilateur portable"}
    assert candidates[0]["marketing_rank"] == 1
    assert "eBay Best Selling" in candidates[0]["sources"]


def test_score_stays_explainable_and_rewards_real_demand_evidence():
    candidate = {"keyword": "ventilateur portable", "marketing_rank": 2, "sources": ["eBay Best Selling"]}
    measurement = {
        "total_results": 320,
        "top_seller_share": 10,
        "recent_listing_share": 42,
        "fixed_price_share": 90,
        "median_price": 29.9,
        "currency": "EUR",
        "sellers_sample": 25,
        "sold_quantity": 240,
        "sales_velocity": 4.2,
        "listing_age_days": 57,
        "history_available": True,
    }
    social = {
        "results": [
            {
                "source": "YOUTUBE",
                "observed_count": 12,
                "metrics": [
                    {"label": "Vues médianes", "value": 18000},
                    {"label": "Meilleure vidéo", "value": 160000},
                ],
                "items": [],
            }
        ]
    }

    strong = score_auto_opportunity(candidate, measurement, social)
    weak = score_auto_opportunity(
        {"keyword": "objet inconnu", "marketing_rank": None, "sources": []},
        {**measurement, "sold_quantity": None, "sales_velocity": None, "history_available": False},
        None,
    )

    assert strong["score"] >= 75
    assert strong["verdict"] == "À TESTER"
    assert strong["social_score"] > 0
    assert weak["score"] < strong["score"]
    assert "volume exact" in strong["meaning"].lower()


def test_opportunity_is_persisted_alerted_once_and_can_be_dismissed(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "auto-radar.db"))
    monkeypatch.setenv("APP_ACCESS_MODE", "local")
    get_settings.cache_clear()
    init_db()

    candidate = {
        "keyword": "ventilateur portable",
        "category_name": "Maison",
        "sources": ["eBay Best Selling", "eBay Best Match"],
        "sample_title": "Ventilateur portable",
    }
    measurement = {
        "representative_title": "Ventilateur portable rechargeable",
        "total_results": 210,
        "median_price": 24.9,
        "currency": "EUR",
        "sellers_sample": 18,
        "top_seller_share": 9,
        "sold_quantity": 180,
        "sales_velocity": 3.4,
        "recent_listing_share": 35,
        "item_url": "https://www.ebay.fr/itm/example",
        "image_url": "https://i.ebayimg.com/example.jpg",
    }
    score = {
        "score": 82,
        "verdict": "À TESTER",
        "confidence": "Élevée",
        "demand_score": 30,
        "competition_score": 22,
        "momentum_score": 8,
        "market_quality_score": 9,
        "social_score": 9,
        "factors": [],
    }

    first, first_alert = _upsert_opportunity(candidate, measurement, score, {"results": []}, "EBAY_FR")
    second, second_alert = _upsert_opportunity(candidate, measurement, score, {"results": []}, "EBAY_FR")

    assert first_alert is True
    assert second_alert is False
    assert first["id"] == second["id"]
    assert len(list_auto_opportunities()) == 1
    assert any(alert["kind"] == "RADAR_OPPORTUNITY" for alert in list_alerts())
    assert dismiss_auto_opportunity(first["id"]) is True
    assert list_auto_opportunities() == []
    get_settings.cache_clear()


def test_current_auto_radar_assets_and_routes_are_loaded():
    html = TestClient(app).get("/").text
    worker = Path("app/static/service-worker.js").read_text(encoding="utf-8")
    scheduler = Path("app/services/scheduler.py").read_text(encoding="utf-8")

    assert app.version == "0.17.0"
    assert "auto_radar.css" in html
    assert "auto_radar.js" in html
    assert "tiered_radar.css" in html
    assert "tiered_radar.js" in html
    assert "opsbot-v0.17.0-shell" in worker
    assert "notificationclick" in worker
    assert "YouTubeClient().discover" not in scheduler
    assert "scheduled_radar_quick" in scheduler
    assert "scheduled_radar_full" in scheduler
