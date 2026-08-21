from pathlib import Path


def test_workflow_cleanup_targets_core_dropshipping_flow():
    source = Path('app/static/workflow_cleanup.js').read_text(encoding='utf-8')
    assert "CJ · Amazon · AliExpress" in source
    assert "checklist de lancement" in source
    assert "que voulez-vous faire" in source
    assert "input[name=\"radar_source\"][value=\"etsy\"]" in source
    assert "section.querySelector('.opportunity-inbox')?.remove()" in source
    assert "['overview', 'radar', 'suppliers', 'catalog', 'ebay', 'support', 'finance', 'connections', 'settings', 'help']" in source
    assert "'pipeline', 'catalog'" not in source


def test_supplier_match_is_limited_to_three_active_suppliers():
    source = Path('app/routers/radar.py').read_text(encoding='utf-8')
    assert 'amazon_supplier_offers' in source
    assert 'aliexpress_supplier_offers' in source
    assert 'Connectez CJ, Amazon ou AliExpress' in source
    assert 'Comparaison limitée aux trois fournisseurs actifs du bot' in source
    assert 'DropXL' not in source


def test_current_workflow_is_registered_in_pwa():
    main = Path('app/main.py').read_text(encoding='utf-8')
    worker = Path('app/static/service-worker.js').read_text(encoding='utf-8')
    assert 'VERSION = "0.21.8"' in main
    assert 'workflow_cleanup.js' in main
    assert "opsbot-v0.21.8-shell" in worker
    assert '/static/workflow_cleanup.js?v=0.21.8' in worker
