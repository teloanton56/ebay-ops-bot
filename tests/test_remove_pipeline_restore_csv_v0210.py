from pathlib import Path


def test_pipeline_frontend_removed():
    main = Path('app/main.py').read_text(encoding='utf-8')

    assert 'opportunity_center.js' not in main
    assert 'opportunity_center.css' not in main
    assert not Path('app/static/opportunity_center.js').exists()
    assert not Path('app/static/opportunity_center.css').exists()
    assert not Path('app/static/provider_cleanup.js').exists()
    assert not Path('app/static/workflow_cleanup.js').exists()


def test_manual_supplier_csv_is_hidden_in_cj_only_mode():
    suppliers = Path('app/routers/suppliers.py').read_text(encoding='utf-8')
    dashboard = Path('app/templates/dashboard.html').read_text(encoding='utf-8')

    assert '@router.get("/directory")' not in suppliers
    assert 'manual-supplier-fallback' not in dashboard
    assert 'supplier-directory' not in dashboard


def test_current_version_keeps_pipeline_assets_out_of_pwa():
    main = Path('app/main.py').read_text(encoding='utf-8')
    worker = Path('app/static/service-worker.js').read_text(encoding='utf-8')
    version = main.split('VERSION = "', 1)[1].split('"', 1)[0]

    assert f"opsbot-v{version}-shell" in worker
    assert 'opportunity_center.js' not in worker
    assert 'opportunity_center.css' not in worker
