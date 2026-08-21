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
    assert 'VERSION = "' in main


def test_current_service_worker_keeps_known_good_cache_logic():
    main = (ROOT / "app/main.py").read_text(encoding="utf-8")
    worker = (ROOT / "app/static/service-worker.js").read_text(encoding="utf-8")
    version = main.split('VERSION = "', 1)[1].split('"', 1)[0]
    assert f"opsbot-v{version}-shell" in worker
    assert f"/static/provider_cleanup.js?v={version}" in worker
    assert f"/static/workflow_cleanup.js?v={version}" in worker
    assert "caches.delete(key)" in worker
