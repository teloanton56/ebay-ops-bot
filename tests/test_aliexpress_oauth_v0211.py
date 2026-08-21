from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_aliexpress_uses_modern_overseas_oauth_and_dropshipper_api():
    oauth = (ROOT / "app/services/aliexpress_modern_oauth.py").read_text(encoding="utf-8")
    search = (ROOT / "app/services/aliexpress_dropship_search.py").read_text(encoding="utf-8")
    status = (ROOT / "app/services/marketplace_supplier_sources.py").read_text(encoding="utf-8")
    assert "https://api-sg.aliexpress.com/oauth/authorize" in oauth
    assert 'TOKEN_PATH = "/auth/token/create"' in oauth
    assert "ALIEXPRESS_SYNC_ENDPOINT = \"https://api-sg.aliexpress.com/sync\"" in search
    assert 'ALIEXPRESS_TEXT_SEARCH_METHOD = "aliexpress.ds.text.search"' in search
    assert '"oauth_authorized"' in status


def test_connections_exposes_aliexpress_authorize_and_callback():
    source = (ROOT / "app/routers/connections.py").read_text(encoding="utf-8")
    assert '/aliexpress/authorize' in source
    assert '/aliexpress/callback' in source
    assert "Autorisez maintenant votre compte AliExpress" in source
    assert "await modern_exchange_aliexpress_authorization" in source
    assert "await modern_test_aliexpress_connection()" in source


def test_aliexpress_ui_has_explicit_authorization_step():
    source = (ROOT / "app/static/provider_cleanup.js").read_text(encoding="utf-8")
    assert "data-authorize-aliexpress" in source
    assert "Autoriser AliExpress" in source
    assert "/api/connections/aliexpress/authorize" in source
    assert "Enregistrer les clés" in source


def test_current_version_registers_aliexpress_assets():
    main = (ROOT / "app/main.py").read_text(encoding="utf-8")
    sw = (ROOT / "app/static/service-worker.js").read_text(encoding="utf-8")
    assert 'VERSION = "0.21.7"' in main
    assert "opsbot-v0.21.7-shell" in sw
    assert "/static/provider_cleanup.js?v=0.21.7" in sw
    assert "/static/supplier_flow_v2.js?v=0.21.7" in sw
