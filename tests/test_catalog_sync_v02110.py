from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app


ROOT = Path(__file__).resolve().parents[1]


def test_retired_marketplace_supplier_cannot_enter_active_catalog():
    with TestClient(app) as client:
        response = client.post("/api/supplier-flow/add", json={
            "provider": "retired",
            "supplier_sku": "SYNC-V02110",
            "name": "Retired marketplace regression product",
            "price": 4.5,
            "currency": "GBP",
            "stock": 12,
        })
    assert response.status_code == 422


def test_legacy_catalog_sync_module_stays_dormant_but_new_ui_refreshes_products():
    legacy = (ROOT / "app/static/catalog_sync.js").read_text(encoding="utf-8")
    current = (ROOT / "app/static/simple_ui.js").read_text(encoding="utf-8")
    main = (ROOT / "app/main.py").read_text(encoding="utf-8")
    worker = (ROOT / "app/static/service-worker.js").read_text(encoding="utf-8")
    assert "url.pathname === '/api/supplier-flow/add'" in legacy
    assert "loadProducts" in current
    assert "refreshProducts" in current
    assert "catalog_sync.js" not in main
    assert "catalog_sync.js" not in worker


def test_current_guided_ui_is_loaded_and_pwa_cache_matches_current_version():
    main = (ROOT / "app/main.py").read_text(encoding="utf-8")
    dashboard = (ROOT / "app/templates/dashboard.html").read_text(encoding="utf-8")
    worker = (ROOT / "app/static/service-worker.js").read_text(encoding="utf-8")
    version = main.split('VERSION = "', 1)[1].split('"', 1)[0]
    assert "simple_ui.js" in dashboard
    assert f"opsbot-v{version}-shell" in worker
    assert f"/static/simple_ui.js?v={version}" in worker
