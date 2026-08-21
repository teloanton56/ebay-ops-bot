from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_runtime_compat_is_loaded_before_legacy_app():
    main = (ROOT / "app/main.py").read_text(encoding="utf-8")
    compat = 'runtime_compat.js?v={VERSION}'
    legacy = 'app.js?v={VERSION}'
    assert compat in main
    assert main.index(compat) < main.index(legacy)


def test_runtime_compat_covers_removed_dashboard_targets():
    source = (ROOT / "app/static/runtime_compat.js").read_text(encoding="utf-8")
    required_ids = {
        "supplierDirectoryNote",
        "supplierDirectoryResults",
        "supplierDirectoryCategory",
        "supplierDirectoryCatalog",
        "supplierDirectoryQuery",
        "supplierKpis",
        "supplierProviderGrid",
        "factoryList",
        "rfqFactory",
        "rfqList",
        "radarSources",
    }
    for target in required_ids:
        assert target in source
    assert "MutationObserver" in source


def test_v0215_cache_contains_runtime_compat():
    main = (ROOT / "app/main.py").read_text(encoding="utf-8")
    worker = (ROOT / "app/static/service-worker.js").read_text(encoding="utf-8")
    assert 'VERSION = "0.21.5"' in main
    assert "opsbot-v0.21.5-shell" in worker
    assert "/static/runtime_compat.js?v=0.21.5" in worker
