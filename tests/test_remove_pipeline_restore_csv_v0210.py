from pathlib import Path


def test_pipeline_frontend_removed():
    main = Path('app/main.py').read_text(encoding='utf-8')
    provider = Path('app/static/provider_cleanup.js').read_text(encoding='utf-8')
    workflow = Path('app/static/workflow_cleanup.js').read_text(encoding='utf-8')

    assert 'opportunity_center.js' not in main
    assert 'opportunity_center.css' not in main
    assert 'ensurePipelineSection' not in provider
    assert "pipeline:" not in workflow
    assert "'pipeline', 'catalog'" not in workflow
    # Selectors that remove stale/cached Pipeline DOM are allowed and intentional.
    assert "document.querySelector('[data-section=\"pipeline\"]')?.remove()" in workflow
    assert "document.querySelector('#section-pipeline')?.remove()" in workflow


def test_manual_supplier_csv_is_restored_at_bottom():
    provider = Path('app/static/provider_cleanup.js').read_text(encoding='utf-8')

    assert "restoreManualSupplierBlock" in provider
    assert "section.appendChild(manual)" in provider
    assert "Ajouter un fournisseur manuel ou importer un CSV" in provider
    assert "section.querySelector('#section-suppliers .supplier-directory')?.remove()" not in provider


def test_current_version_keeps_pipeline_assets_out_of_pwa():
    main = Path('app/main.py').read_text(encoding='utf-8')
    worker = Path('app/static/service-worker.js').read_text(encoding='utf-8')

    assert 'VERSION = "0.21.9"' in main
    assert "opsbot-v0.21.9-shell" in worker
    assert 'opportunity_center.js' not in worker
    assert 'opportunity_center.css' not in worker
