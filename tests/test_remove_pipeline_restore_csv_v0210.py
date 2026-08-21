from pathlib import Path


def test_pipeline_frontend_removed():
    main = Path('app/main.py').read_text(encoding='utf-8')
    provider = Path('app/static/provider_cleanup.js').read_text(encoding='utf-8')
    workflow = Path('app/static/workflow_cleanup.js').read_text(encoding='utf-8')

    assert 'opportunity_center.js' not in main
    assert 'opportunity_center.css' not in main
    assert 'ensurePipelineSection' not in provider
    assert "data-section=\"pipeline\"" not in workflow


def test_manual_supplier_csv_is_restored_at_bottom():
    provider = Path('app/static/provider_cleanup.js').read_text(encoding='utf-8')

    assert "restoreManualSupplierBlock" in provider
    assert "section.appendChild(manual)" in provider
    assert "Ajouter un fournisseur manuel ou importer un CSV" in provider
    assert "section.querySelector('#section-suppliers .supplier-directory')?.remove()" not in provider


def test_version_and_cache_are_v0210():
    main = Path('app/main.py').read_text(encoding='utf-8')
    worker = Path('app/static/service-worker.js').read_text(encoding='utf-8')

    assert 'VERSION = "0.21.0"' in main
    assert "opsbot-v0.21.0-shell" in worker
    assert 'opportunity_center.js' not in worker
