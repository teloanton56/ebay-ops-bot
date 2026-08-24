from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app
from app.services import db
from app.services.cj_landed import save_cj_product_link
from app.services.listing_generator import optimize_title


ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_radar_ui_is_visual_and_decision_first():
    ui = read("app/static/simple_ui.js")
    css = read("app/static/simple_ui.css")
    assert "potentiel marché" in ui.lower()
    assert "score-gauge" in ui
    assert "Demande" in ui
    assert "Concurrence" in ui
    assert "Rentabilité" in ui
    assert "Vérifier la marge chez CJ" in ui
    assert ".score-gauge" in css
    assert ".signal-grid" in css


def test_cj_flow_has_one_click_analyze_and_import_without_navigation():
    ui = read("app/static/simple_ui.js")
    assert "Analyser + importer" in ui
    assert "quickImportCj" in ui
    assert "/api/cj/candidates" in ui
    assert "/analyze" in ui
    assert "/add-product" in ui
    quick_block = ui.split("async function quickImportCj", 1)[1].split("async function optimizeProduct", 1)[0]
    assert "show('catalog')" not in quick_block


def test_all_inclusive_margin_is_exposed_on_active_products():
    db.init_db()
    supplier_id = db.ensure_provider_supplier("cj", "CJ Dropshipping", "US")
    product_id = db.upsert_product({
        "supplier_sku": "V025-MARGIN-1",
        "title": "Car organizer",
        "description": "",
        "supplier_cost": 6.0,
        "shipping_cost": 4.0,
        "stock": 25,
        "shipping_days": 5,
        "target_price": 29.99,
        "marketplace_id": "EBAY_US",
        "currency": "USD",
        "images": [],
        "aspects": {},
        "supplier_id": supplier_id,
        "product_status": "À tester",
    })
    save_cj_product_link("V025-MARGIN-1", {
        "pid": "PID-V025-MARGIN-1",
        "variant_id": "VID-V025-MARGIN-1",
        "warehouse": "US",
        "destination_country": "US",
        "currency": "USD",
        "risk_flags": [],
    })
    with TestClient(app) as client:
        row = client.get(f"/api/products/{product_id}").json()
        simulation = client.get(f"/api/products/{product_id}/margin").json()

    profit = row["profit"]
    assert profit["supplier_cost"] == 6.0
    assert profit["shipping_cost"] == 4.0
    assert profit["estimated_ebay_fee"] is not None
    assert profit["estimated_ad_fee"] is not None
    assert profit["returns_reserve"] is not None
    assert profit["fixed_fee"] is not None
    assert simulation["marketplace"] == "EBAY_US"
    assert simulation["currency"] == "USD"
    assert simulation["fee_model"]["promoted_listings_percent"] >= 0


def test_ebay_seo_uses_only_relevant_market_hints_without_replacing_identity():
    title = optimize_title(
        "Wireless Car Charger New Product",
        market_keywords=["magnetic wireless car charger", "Lasko pedestal fan S16200"],
    )
    assert len(title) <= 80
    assert title.startswith("Wireless Car Charger")
    assert "magnetic" in title.lower()
    assert "Lasko" not in title
    assert "S16200" not in title
    assert "Product" not in title

    products_router = read("app/routers/products.py")
    ui = read("app/static/simple_ui.js")
    assert '/{product_id}/optimize-ebay' in products_router
    assert "eBay US relevant query only" in products_router
    assert "aucun titre concurrent complet n'est copié" in products_router
    assert "Optimiser pour eBay" in ui


def test_pwa_and_ui_versions_follow_v0253():
    main = read("app/main.py")
    worker = read("app/static/service-worker.js")
    assert 'VERSION = "0.25.3"' in main
    assert "opsbot-v0.25.3-shell" in worker
    assert "/static/simple_ui.js?v=0.25.3" in worker
    assert "/static/simple_ui.css?v=0.25.3" in worker
