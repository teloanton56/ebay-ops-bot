from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_cleanup_keeps_required_legacy_hooks_hidden_not_active():
    source = (ROOT / "app/static/provider_cleanup.js").read_text(encoding="utf-8")
    assert "function hide(node)" in source
    for marker in (
        "#supplierKpis",
        ".supplier-network",
        ".niche-directory-panel",
        ".factory-discovery-panel",
        ".radar-factory-grid",
        "#radarSources",
        ".supplier-directory",
    ):
        assert marker in source
    assert "hide(section.querySelector('#supplierKpis'))" in source
    assert "hide(section.querySelector('#radarSources')?.closest('.panel'))" in source


def test_cleanup_explicitly_retires_old_sources():
    source = (ROOT / "app/static/provider_cleanup.js").read_text(encoding="utf-8").lower()
    for retired in ("amazon", "aliexpress", "tiktok", "youtube", "etsy", "dropxl"):
        assert retired in source
    assert "removeRetiredCards" in (ROOT / "app/static/provider_cleanup.js").read_text(encoding="utf-8")


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
