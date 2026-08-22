from pathlib import Path


def test_workflow_cleanup_targets_single_channel_single_supplier_flow():
    source = Path('app/static/workflow_cleanup.js').read_text(encoding='utf-8')
    assert "eBay US → CJ → cash-flow" in source
    assert "checklist de lancement" in source
    assert "que voulez-vous faire" in source
    assert "['overview', 'radar', 'shop-spy', 'suppliers', 'catalog', 'ebay', 'support', 'finance', 'connections', 'settings', 'help']" in source
    assert "Radar US" in source
    assert "CJ Dropshipping" in source
    assert "eBay US" in source
    assert "TikTok" not in source
    assert "YouTube" not in source
    assert "Amazon" not in source
    assert "AliExpress" not in source


def test_supplier_match_is_limited_to_cj():
    source = Path('app/routers/radar.py').read_text(encoding='utf-8')
    assert "CJClient" in source
    assert "Connectez CJ avant de rechercher un fournisseur" in source
    assert "amazon_supplier_offers" not in source
    assert "aliexpress" not in source.lower()
    assert "DropXL" not in source


def test_current_workflow_is_registered_in_pwa():
    main = Path('app/main.py').read_text(encoding='utf-8')
    worker = Path('app/static/service-worker.js').read_text(encoding='utf-8')
    version = main.split('VERSION = "', 1)[1].split('"', 1)[0]
    assert 'workflow_cleanup.js' in main
    assert f"opsbot-v{version}-shell" in worker
    assert f'/static/workflow_cleanup.js?v={version}' in worker
