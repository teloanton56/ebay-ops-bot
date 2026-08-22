import re
from pathlib import Path

from app.services.product_research import build_product_research_summary


def test_product_research_scores_ebay_us_market_structure_only():
    markets = [{"source": "EBAY", "marketplace": "EBAY_US", "marketplace_name": "eBay United States", "total_results": 250, "median_price": 29.90, "currency": "USD", "sellers_sample": 40, "top_seller_share": 25.0, "listing_change_percent": 6.0}]
    summary = build_product_research_summary(markets)
    assert summary["method"] == "EBAY_US_MARKET_STRUCTURE_V1"
    assert summary["score"] == 71
    assert summary["verdict"] == "MARCHÉ INTÉRESSANT"
    assert summary["confidence"] == "Moyenne"
    assert summary["demand_proxy"]["label"] == "Non mesurée"
    assert summary["competition"]["label"] == "Modérée"
    assert summary["reference_price"]["value"] == 29.90
    assert summary["reference_price"]["currency"] == "USD"
    assert summary["reference_price"]["marketplace"] == "eBay United States"
    assert summary["search_volume_exact"] is None


def test_product_research_is_explicit_when_demand_data_is_not_public():
    markets = [{"source": "EBAY", "marketplace": "EBAY_US", "marketplace_name": "eBay United States", "total_results": 45, "median_price": 24.90, "currency": "USD", "sellers_sample": 20, "top_seller_share": 8.0, "listing_change_percent": None}]
    summary = build_product_research_summary(markets)
    assert summary["score"] == 73
    assert summary["confidence"] == "Faible"
    assert summary["demand_proxy"]["score"] is None
    assert any("Historique eBay US" in item for item in summary["missing_signals"])
    assert "ne prétend pas mesurer les recherches ou les ventes" in summary["meaning"]


def test_product_research_logic_remains_backend_but_guided_assets_are_current():
    main = Path("app/main.py").read_text(encoding="utf-8")
    dashboard = Path("app/templates/dashboard.html").read_text(encoding="utf-8")
    worker = Path("app/static/service-worker.js").read_text(encoding="utf-8")
    match = re.search(r'^VERSION = "([^"]+)"$', main, re.MULTILINE)
    assert match is not None
    version = match.group(1)
    assert "product_research.js" not in main
    assert "product_research.js" not in dashboard
    assert f"opsbot-v{version}-shell" in worker
    assert f"simple_ui.js?v={version}" in worker
    assert "Radar eBay US" in dashboard
    assert "Chercher sur CJ" in Path("app/static/simple_ui.js").read_text(encoding="utf-8")
