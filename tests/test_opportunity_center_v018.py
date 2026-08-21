import json
from pathlib import Path

import pytest

from app.config import get_settings
from app.services import db
from app.services.auto_radar import _ensure_tables as ensure_radar_tables
from app.services.opportunity_center import (
    _score_offer,
    _update_workflow,
    amazon_intelligence,
    build_risk_report,
    ensure_workflow,
    get_workflow,
    launch_readiness,
    prepare_listing_draft,
    select_supplier_offer,
    verify_latest_backup,
)


def configure(tmp_path, monkeypatch):
    monkeypatch.setenv("APP_ACCESS_MODE", "local")
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "center.db"))
    monkeypatch.setenv("APP_RUNTIME_ENV_PATH", str(tmp_path / "runtime.env"))
    monkeypatch.setenv("APP_ENCRYPTION_KEY", "MDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDA=")
    monkeypatch.setenv("EBAY_ENV", "production")
    monkeypatch.setenv("EBAY_CLIENT_ID", "example-PRD-client")
    monkeypatch.setenv("EBAY_CLIENT_SECRET", "secret")
    get_settings.cache_clear()
    db.init_db()


def create_opportunity():
    ensure_radar_tables()
    now = db.utc_now()
    with db.conn() as database:
        columns = {row["name"] for row in database.execute("PRAGMA table_info(radar_opportunities)")}
        if "opportunity_key" in columns and "payload_json" in columns:
            cursor = database.execute(
                """
                INSERT INTO radar_opportunities(
                    opportunity_key,marketplace,keyword,title,category_id,category_name,score,
                    verdict,confidence,demand_score,competition_score,momentum_score,
                    market_quality_score,social_score,total_results,median_price,currency,
                    sellers_sample,top_seller_share,sold_quantity,sales_velocity,
                    recent_listing_share,item_url,image_url,sources_json,factors_json,
                    social_json,payload_json,first_seen_at,last_seen_at,dismissed
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    "test-opportunity", "EBAY_FR", "ventilateur portable",
                    "Ventilateur portable rechargeable silencieux", "", "Maison", 82,
                    "À TESTER", "Élevée", 30, 22, 8, 9, 5, 240, 29.9, "EUR",
                    25, 8, 180, 3.0, 30, "https://www.ebay.fr/itm/example",
                    "https://i.ebayimg.com/example.jpg", "[]", "[]", "{}", "{}",
                    now, now, 0,
                ),
            )
        else:
            cursor = database.execute(
                """
                INSERT INTO radar_opportunities(
                    opportunity_key,keyword,title,family,category_id,category_name,marketplace,score,
                    demand_score,competition_score,momentum_score,price_score,confidence,verdict,
                    demand_evidence,estimated_sold,sales_velocity,active_listings,sellers_sample,
                    top_seller_share,median_price,currency,image_url,item_url,evidence_json,social_json,
                    first_seen_at,last_seen_at
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    "test-opportunity", "ventilateur portable",
                    "Ventilateur portable rechargeable silencieux", "Maison", "", "Maison",
                    "EBAY_FR", 82, 30, 22, 8, 9, "Élevée", "À TESTER", 3, 180, 3.0,
                    240, 25, 8, 29.9, "EUR", "https://i.ebayimg.com/example.jpg",
                    "https://www.ebay.fr/itm/example", "[]", "[]", now, now,
                ),
            )
        opportunity_id = int(cursor.lastrowid)
        return dict(database.execute("SELECT * FROM radar_opportunities WHERE id=?", (opportunity_id,)).fetchone())


def strong_offer():
    return _score_offer({
        "provider": "Fournisseur test", "provider_code": "manual", "supplier_sku": "TEST-1",
        "variant_id": "", "name": "Ventilateur portable rechargeable", "product_cost": 7.0,
        "shipping_cost": 3.0, "currency": "EUR", "stock": 40, "shipping_days": 4,
        "warehouse": "FR", "image_url": "https://example.test/image.jpg",
        "reliability_score": 90, "compliance_flags": [],
        "evidence": ["prix", "stock", "transport", "conformité"], "shipping_known": True,
    }, 29.9)


def test_offer_scoring_requires_landed_cost_and_rewards_viable_margin(tmp_path, monkeypatch):
    configure(tmp_path, monkeypatch)
    viable = strong_offer()
    unknown = _score_offer({
        "provider": "Inconnu", "provider_code": "manual", "supplier_sku": "X",
        "name": "Ventilateur", "product_cost": 6, "shipping_cost": None,
        "stock": 20, "shipping_days": 4, "shipping_known": False,
        "evidence": [], "compliance_flags": [],
    }, 29.9)
    assert viable["eligible"] is True
    assert viable["landed_cost"] == 10.0
    assert viable["profit"]["margin_percent"] > 15
    assert unknown["eligible"] is False
    assert "Coût livré inconnu" in unknown["blocks"]


def test_workflow_supplier_selection_and_risk_pipeline(tmp_path, monkeypatch):
    configure(tmp_path, monkeypatch)
    opportunity = create_opportunity()
    workflow = ensure_workflow(opportunity["id"])
    offer = strong_offer()
    snapshot = {"offers": [offer], "observed_at": "now", "errors": []}
    _update_workflow(workflow["id"], supplier_snapshot_json=json.dumps(snapshot))
    selected = select_supplier_offer(workflow["id"], offer["offer_key"])
    report = build_risk_report(workflow["id"])
    assert selected["stage"] == "MARGIN_VALIDATED"
    assert report["pass"] is True
    assert get_workflow(workflow["id"])["stage"] == "RISK_VALIDATED"


@pytest.mark.asyncio
async def test_amazon_confirmation_classifies_multi_market_signal(tmp_path, monkeypatch):
    configure(tmp_path, monkeypatch)
    opportunity = create_opportunity()
    workflow = ensure_workflow(opportunity["id"])
    monkeypatch.setattr("app.services.opportunity_market.connection_status", lambda provider: {"connected": provider == "amazon"})

    async def fake_search(self, keyword, marketplace="AMAZON_FR", page_size=20, include_pricing=True):
        return {
            "total": 2, "pricing_available": True,
            "products": [
                {"asin": "A1", "title": "Ventilateur portable", "sales_rank": 900, "price": 28.9, "offer_count": 4, "brand": "A"},
                {"asin": "A2", "title": "Ventilateur bureau", "sales_rank": 2400, "price": 31.0, "offer_count": 6, "brand": "B"},
            ],
        }

    monkeypatch.setattr("app.services.opportunity_market.AmazonRadarClient.search_catalog", fake_search)
    result = await amazon_intelligence(workflow["id"])
    assert result["signal"] == "CONFIRMED_MULTI_MARKET"
    assert result["best_sales_rank"] == 900
    assert result["offer_count_total"] == 10


@pytest.mark.asyncio
async def test_listing_draft_remains_local_and_records_missing_aspects(tmp_path, monkeypatch):
    configure(tmp_path, monkeypatch)
    opportunity = create_opportunity()
    workflow = ensure_workflow(opportunity["id"])
    offer = strong_offer()
    _update_workflow(workflow["id"], supplier_snapshot_json=json.dumps({"offers": [offer]}))
    select_supplier_offer(workflow["id"], offer["offer_key"])
    build_risk_report(workflow["id"])

    async def fake_suggestions(self, query, marketplace_id=None):
        return {"categorySuggestions": [{"category": {"categoryId": "20649", "categoryName": "Ventilateurs"}}]}
    async def fake_aspects(self, category_id, marketplace_id=None):
        return {"aspects": [{"localizedAspectName": "Marque", "aspectConstraint": {"aspectRequired": True}}]}

    monkeypatch.setattr("app.services.opportunity_listing.EbayClient.get_category_suggestions", fake_suggestions)
    monkeypatch.setattr("app.services.opportunity_listing.EbayClient.get_item_aspects", fake_aspects)
    listing = await prepare_listing_draft(workflow["id"])
    assert listing["dry_run"] is True
    assert listing["category_id"] == "20649"
    assert listing["required_aspects_missing"] == ["Marque"]
    assert db.get_listing_for_product(listing["product_id"])["status"] == "PREPARED_DRY_RUN"


def test_backup_integrity_and_global_readiness_remain_dry_run(tmp_path, monkeypatch):
    configure(tmp_path, monkeypatch)
    backup = verify_latest_backup(create=True)
    readiness = launch_readiness()
    assert backup["ok"] is True
    assert readiness["backup"]["ok"] is True
    assert next(row for row in readiness["checks"] if row["id"] == "dry_run")["done"] is True


def test_v018_assets_routes_and_monitor_job_are_registered():
    main = Path("app/main.py").read_text(encoding="utf-8")
    worker = Path("app/static/service-worker.js").read_text(encoding="utf-8")
    scheduler = Path("app/services/scheduler.py").read_text(encoding="utf-8")
    router = Path("app/routers/opportunity_center.py").read_text(encoding="utf-8")
    assert 'VERSION = "0.18.0"' in main
    assert "opportunity_center.css" in main and "opportunity_center.js" in main
    assert "opportunity_center.router" in main
    assert "opsbot-v0.18.0-shell" in worker
    assert "opportunity-monitor" in scheduler and "monitor_enabled_workflows" in scheduler
    assert '/api/opportunity-center' in router
