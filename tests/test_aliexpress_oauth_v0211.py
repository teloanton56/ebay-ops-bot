from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_aliexpress_uses_oauth_and_dropshipper_api():
    source = (ROOT / "app/services/marketplace_supplier_sources.py").read_text(encoding="utf-8")
    assert "ALIEXPRESS_OAUTH_AUTHORIZE" in source
    assert "ALIEXPRESS_OAUTH_TOKEN" in source
    assert "exchange_aliexpress_authorization" in source
    assert '"session"' in source
    assert 'aliexpress.ds.recommend.feed.get' in source
    assert '"oauth_authorized"' in source


def test_connections_exposes_aliexpress_authorize_and_callback():
    source = (ROOT / "app/routers/connections.py").read_text(encoding="utf-8")
    assert '/aliexpress/authorize' in source
    assert '/aliexpress/callback' in source
    assert "Autorisez maintenant votre compte AliExpress" in source
    assert "await exchange_aliexpress_authorization" in source
    assert "await test_aliexpress_connection()" in source


def test_aliexpress_ui_has_explicit_authorization_step():
    source = (ROOT / "app/static/provider_cleanup.js").read_text(encoding="utf-8")
    assert "data-authorize-aliexpress" in source
    assert "Autoriser AliExpress" in source
    assert "/api/connections/aliexpress/authorize" in source
    assert "Enregistrer les clés" in source


def test_version_and_cache_bumped():
    main = (ROOT / "app/main.py").read_text(encoding="utf-8")
    sw = (ROOT / "app/static/service-worker.js").read_text(encoding="utf-8")
    assert 'VERSION = "0.21.1"' in main
    assert "opsbot-v0.21.1-shell" in sw
    assert "/static/provider_cleanup.js?v=0.21.1" in sw
