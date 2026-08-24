from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_legacy_cleanup_file_is_deleted():
    assert not (ROOT / "app/static/provider_cleanup.js").exists()
    main = (ROOT / "app/main.py").read_text(encoding="utf-8")
    dashboard = (ROOT / "app/templates/dashboard.html").read_text(encoding="utf-8")
    assert "provider_cleanup.js" not in main
    assert "provider_cleanup.js" not in dashboard


def test_old_sources_are_absent_from_active_dashboard():
    dashboard = (ROOT / "app/templates/dashboard.html").read_text(encoding="utf-8").lower()
    for retired in ("amazon", "aliexpress", "tiktok", "youtube", "etsy", "dropxl"):
        assert retired not in dashboard


def test_no_startup_compatibility_script_is_reintroduced():
    main = (ROOT / "app/main.py").read_text(encoding="utf-8")
    assert "runtime_compat.js" not in main
    assert 'VERSION = "' in main


def test_current_service_worker_caches_only_guided_shell_and_cleans_old_caches():
    main = (ROOT / "app/main.py").read_text(encoding="utf-8")
    worker = (ROOT / "app/static/service-worker.js").read_text(encoding="utf-8")
    version = main.split('VERSION = "', 1)[1].split('"', 1)[0]
    assert f"opsbot-v{version}-shell" in worker
    assert f"/static/simple_ui.js?v={version}" in worker
    assert f"/static/simple_ui.css?v={version}" in worker
    assert "provider_cleanup.js" not in worker
    assert "workflow_cleanup.js" not in worker
    assert "caches.delete(key)" in worker
