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


def test_catalog_sync_tracks_every_supplier_flow_add_and_refreshes_on_products_navigation():
    source = (ROOT / "app/static/catalog_sync.js").read_text(encoding="utf-8")
    assert "url.pathname === '/api/supplier-flow/add'" in source
    assert "sessionStorage.setItem(DIRTY_KEY, '1')" in source
    assert '[data-section="catalog"], [data-go="catalog"]' in source
    assert "window.location.reload()" in source
    assert "refreshVisibleCounts" in source


def test_catalog_sync_is_loaded_and_pwa_cache_matches_current_version():
    main = (ROOT / "app/main.py").read_text(encoding="utf-8")
    worker = (ROOT / "app/static/service-worker.js").read_text(encoding="utf-8")
    version = main.split('VERSION = "', 1)[1].split('"', 1)[0]
    assert 'catalog_sync.js?v={VERSION}' in main
    assert f"opsbot-v{version}-shell" in worker
    assert f"/static/catalog_sync.js?v={version}" in worker
