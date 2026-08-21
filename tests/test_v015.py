from pathlib import Path

from app.services.radar import build_product_research_summary


def test_product_research_combines_measured_market_signals():
    markets = [
        {
            "source": "EBAY",
            "marketplace": "EBAY_FR",
            "marketplace_name": "eBay France",
            "total_results": 250,
            "median_price": 29.90,
            "currency": "EUR",
            "sellers_sample": 40,
            "top_seller_share": 25.0,
            "listing_change_percent": 6.0,
        },
        {
            "source": "AMAZON",
            "marketplace": "AMAZON_FR",
            "marketplace_name": "Amazon France",
            "total_results": 80,
            "median_price": 31.50,
            "currency": "EUR",
            "best_sales_rank": 4200,
            "listing_change_percent": 2.0,
        },
    ]

    summary = build_product_research_summary(markets)

    assert summary["method"] == "MARKET_PROXY_V1"
    assert summary["score"] >= 75
    assert summary["verdict"] == "À TESTER"
    assert summary["confidence"] == "Élevée"
    assert summary["demand_proxy"]["label"] == "Bon"
    assert summary["competition"]["label"] == "Modérée"
    assert summary["reference_price"]["value"] == 29.90
    assert summary["reference_price"]["marketplace"] == "eBay France"
    assert summary["trend"]["label"] == "Offre stable"
    assert summary["search_volume_exact"] is None
    assert any("Volume exact" in item for item in summary["missing_signals"])


def test_product_research_never_calls_ebay_listing_count_demand():
    markets = [
        {
            "source": "EBAY",
            "marketplace": "EBAY_FR",
            "marketplace_name": "eBay France",
            "total_results": 45,
            "median_price": 24.90,
            "currency": "EUR",
            "sellers_sample": 20,
            "top_seller_share": 8.0,
            "listing_change_percent": None,
        }
    ]

    summary = build_product_research_summary(markets)

    assert summary["score"] == 100
    assert summary["verdict"] == "À CREUSER"
    assert summary["confidence"] == "Faible"
    assert summary["demand_proxy"]["label"] == "À confirmer"
    assert any("Demande Amazon" in item for item in summary["missing_signals"])
    assert "volume de recherche" in summary["meaning"].lower()


def test_v015_assets_are_loaded_and_cache_versioned():
    main = Path("app/main.py").read_text(encoding="utf-8")
    worker = Path("app/static/service-worker.js").read_text(encoding="utf-8")
    script = Path("app/static/product_research.js").read_text(encoding="utf-8")

    assert 'VERSION = "0.15.0"' in main
    assert "product_research.css" in main
    assert "product_research.js" in main
    assert "opsbot-v0.15.0-shell" in worker
    assert "product_research.js?v=0.15.0" in worker
    assert "Trouver les fournisseurs" in script
    assert "Volume de recherche exact" in script
