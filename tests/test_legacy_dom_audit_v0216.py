from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_cleanup_hides_legacy_panels_instead_of_removing_them():
    source = (ROOT / "app/static/provider_cleanup.js").read_text(encoding="utf-8")
    assert "function hideLegacyPanel" in source
    protected = [
        "sales-channel-panel",
        "supplier-network",
        "niche-directory-panel",
        "factory-discovery-panel",
        "radar-factory-grid",
        "#radarSources",
    ]
    for marker in protected:
        assert marker in source
    assert "hideLegacyPanel(document.querySelector('#section-ebay .sales-channel-panel'))" in source
    assert "hideLegacyPanel(document.querySelector('#section-suppliers .supplier-network'))" in source
    assert "hideLegacyPanel(document.querySelector('#section-suppliers .niche-directory-panel'))" in source
    assert "hideLegacyPanel(document.querySelector('#section-suppliers .factory-discovery-panel'))" in source
    assert "hideLegacyPanel(document.querySelector('#section-suppliers .radar-factory-grid'))" in source
    assert "hideLegacyPanel(document.querySelector('#section-radar #radarSources')?.closest('.panel'))" in source


def test_supplier_kpis_are_preserved_for_legacy_refreshes():
    source = (ROOT / "app/static/workflow_cleanup.js").read_text(encoding="utf-8")
    assert "section.querySelector('#supplierKpis')?.remove()" not in source
    assert "supplierKpis.hidden = true" in source
    assert "supplierKpis.dataset.legacyHidden = '1'" in source


def test_no_startup_compatibility_script_is_reintroduced():
    main = (ROOT / "app/main.py").read_text(encoding="utf-8")
    assert "runtime_compat.js" not in main
    assert 'VERSION = "0.21.6"' in main


def test_v0216_service_worker_keeps_known_good_cache_logic():
    worker = (ROOT / "app/static/service-worker.js").read_text(encoding="utf-8")
    assert "opsbot-v0.21.6-shell" in worker
    assert "/static/provider_cleanup.js?v=0.21.6" in worker
    assert "/static/workflow_cleanup.js?v=0.21.6" in worker
    assert "caches.delete(key)" in worker
