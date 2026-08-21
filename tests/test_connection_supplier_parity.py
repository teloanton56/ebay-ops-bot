from pathlib import Path

from app.services.marketplace_supplier_sources import (
    AliExpressSupplierClient,
    aliexpress_connection_status,
)


def test_aliexpress_connection_status_requires_verified_credentials(monkeypatch):
    monkeypatch.setattr(
        "app.services.marketplace_supplier_sources.load_aliexpress_credentials",
        lambda: {
            "app_key": "demo-key",
            "app_secret": "demo-secret",
            "verified_at": "2026-08-21T20:00:00+00:00",
            "last_error": "",
        },
    )
    status = aliexpress_connection_status()
    assert status["configured"] is True
    assert status["connected"] is True
    assert status["supplier"] is True
    assert status["capabilities"]["search"] is True
    assert status["capabilities"]["margin_analysis"] is True


def test_aliexpress_client_reads_native_saved_credentials(monkeypatch):
    monkeypatch.setattr(
        "app.services.marketplace_supplier_sources.load_aliexpress_credentials",
        lambda: {"app_key": "saved-key", "app_secret": "saved-secret", "tracking_id": "track"},
    )
    client = AliExpressSupplierClient()
    assert client.configured is True
    assert client.app_key == "saved-key"
    assert client.app_secret == "saved-secret"
    assert client.tracking_id == "track"


def test_connections_ui_groups_real_suppliers_and_removes_old_blocks():
    cleanup = Path("app/static/provider_cleanup.js").read_text(encoding="utf-8")
    router = Path("app/routers/connections.py").read_text(encoding="utf-8")
    suppliers = Path("app/routers/suppliers.py").read_text(encoding="utf-8")

    assert "native-aliexpress-card" in cleanup
    assert 'data-provider="aliexpress"' in cleanup
    assert "FOURNISSEUR API" in cleanup
    assert "catalogues et production" in cleanup
    assert "[data-provider-card=\"etsy\"],[data-provider-card=\"dropxl\"]" in cleanup
    assert "fournisseurs accompagnés" in cleanup and "head.remove()" in cleanup

    assert 'hidden = {"etsy", "dropxl", "printful", "printify", "gelato"}' in router
    assert '"assisted_suppliers": []' in router
    assert "aliexpress_connection_status()" in router
    assert 'provider == "aliexpress"' in router

    assert '"supplier": True' in suppliers
    assert '"name": "Amazon France"' in suppliers
    assert "aliexpress_supplier_status()" in suppliers
