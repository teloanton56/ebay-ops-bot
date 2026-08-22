import asyncio
from pathlib import Path

import pytest
from fastapi import HTTPException

from app.routers.supplier_flow import OfferIn, add_offer


ROOT = Path(__file__).resolve().parents[1]


def test_retired_marketplace_supplier_cannot_enter_active_catalog():
    with pytest.raises(HTTPException) as exc:
        asyncio.run(add_offer(OfferIn(
            provider="AliExpress",
            supplier_sku="SYNC-V02110",
            name="Retired marketplace regression product",
            price=4.5,
            shipping_cost=None,
            currency="EUR",
            stock=12,
            shipping_days=None,
            image_url="",
            source_url="",
        )))
    assert exc.value.status_code == 410
    assert "uniquement CJ" in str(exc.value.detail)


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
