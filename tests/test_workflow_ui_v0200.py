from pathlib import Path


def test_guided_dashboard_is_single_channel_single_supplier_flow():
    dashboard = Path('app/templates/dashboard.html').read_text(encoding='utf-8')
    source = Path('app/static/simple_ui.js').read_text(encoding='utf-8')
    assert "eBay US → CJ → Produit rentable" in dashboard
    assert "Radar eBay US" in dashboard
    assert "CJ Dropshipping" in dashboard
    assert "eBay US" in dashboard
    for retired in ("TikTok", "YouTube", "Amazon", "AliExpress"):
        assert retired not in dashboard
    assert "runRadar" in source
    assert "searchCj" in source
    assert "loadProducts" in source


def test_supplier_match_is_limited_to_cj():
    source = Path('app/routers/radar.py').read_text(encoding='utf-8')
    assert "CJClient" in source
    assert "Connectez CJ avant de rechercher un fournisseur" in source
    assert "amazon_supplier_offers" not in source
    assert "aliexpress" not in source.lower()
    assert "DropXL" not in source


def test_current_guided_workflow_is_registered_in_pwa():
    main = Path('app/main.py').read_text(encoding='utf-8')
    worker = Path('app/static/service-worker.js').read_text(encoding='utf-8')
    version = main.split('VERSION = "', 1)[1].split('"', 1)[0]
    assert 'workflow_cleanup.js' not in main
    assert f"opsbot-v{version}-shell" in worker
    assert f'/static/simple_ui.js?v={version}' in worker
