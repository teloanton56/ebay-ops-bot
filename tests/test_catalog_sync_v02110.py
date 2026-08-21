import asyncio
from pathlib import Path

from app.routers.supplier_flow import OfferIn, add_offer
from app.services.db import delete_product, init_db, list_products


ROOT = Path(__file__).resolve().parents[1]


def _cleanup_test_product() -> None:
    for product in list_products():
        if product.get("supplier_sku") == "ALI-SYNC-V02110":
            delete_product(int(product["id"]))


def test_supplier_flow_add_is_persisted_in_products_catalog():
    init_db()
    _cleanup_test_product()
    try:
        result = asyncio.run(add_offer(OfferIn(
            provider="AliExpress",
            supplier_sku="SYNC-V02110",
            name="Catalog sync regression product",
            price=4.5,
            shipping_cost=None,
            currency="EUR",
            stock=12,
            shipping_days=None,
            image_url="",
            source_url="",
        )))
        products = list_products()
        saved = next((row for row in products if row.get("id") == result.get("product_id")), None)
        assert saved is not None
        assert saved["supplier_sku"] == "ALI-SYNC-V02110"
        assert saved["title"] == "Catalog sync regression product"
    finally:
        _cleanup_test_product()


def test_catalog_sync_tracks_every_supplier_flow_add_and_refreshes_on_products_navigation():
    source = (ROOT / "app/static/catalog_sync.js").read_text(encoding="utf-8")
    assert "url.pathname === '/api/supplier-flow/add'" in source
    assert "sessionStorage.setItem(DIRTY_KEY, '1')" in source
    assert '[data-section="catalog"], [data-go="catalog"]' in source
    assert "window.location.reload()" in source
    assert "refreshVisibleCounts" in source


def test_v02110_loads_catalog_sync_and_updates_pwa_cache():
    main = (ROOT / "app/main.py").read_text(encoding="utf-8")
    worker = (ROOT / "app/static/service-worker.js").read_text(encoding="utf-8")
    assert 'VERSION = "0.21.10"' in main
    assert 'catalog_sync.js?v={VERSION}' in main
    assert "opsbot-v0.21.10-shell" in worker
    assert "/static/catalog_sync.js?v=0.21.10" in worker
