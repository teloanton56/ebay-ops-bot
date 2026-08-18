from pathlib import Path

from fastapi.testclient import TestClient

from app.config import get_settings
from app.main import app
from app.services import db
from app.services.backups import create_backup, list_backups, resolve_backup
from app.services.cloud_auth import create_session, session_email


def test_signed_cloud_session_expires_or_detects_tampering(monkeypatch):
    monkeypatch.setenv("APP_ACCESS_MODE", "cloud")
    monkeypatch.setenv("APP_ADMIN_EMAIL", "owner@example.test")
    monkeypatch.setenv("APP_ADMIN_PASSWORD", "a-safe-password")
    monkeypatch.setenv("APP_SESSION_SECRET", "s" * 40)
    monkeypatch.setenv("APP_ENCRYPTION_KEY", "e" * 40)
    get_settings.cache_clear()
    settings = get_settings()
    token = create_session(settings.app_admin_email, settings)
    assert session_email(token, settings) == "owner@example.test"
    assert session_email(token + "x", settings) is None
    get_settings.cache_clear()


def test_cloud_dashboard_requires_login_and_sets_secure_cookie(monkeypatch):
    monkeypatch.setenv("APP_ACCESS_MODE", "cloud")
    monkeypatch.setenv("APP_ADMIN_EMAIL", "owner@example.test")
    monkeypatch.setenv("APP_ADMIN_PASSWORD", "a-safe-password")
    monkeypatch.setenv("APP_SESSION_SECRET", "s" * 40)
    monkeypatch.setenv("APP_ENCRYPTION_KEY", "e" * 40)
    get_settings.cache_clear()
    client = TestClient(app, base_url="https://testserver")
    blocked = client.get("/", follow_redirects=False)
    assert blocked.status_code == 303
    assert blocked.headers["location"] == "/login"
    assert "ACCÈS SÉCURISÉ" in client.get("/login").text
    login = client.post(
        "/api/cloud/login",
        data={"email": "owner@example.test", "password": "a-safe-password"},
        headers={"Origin": "https://testserver"},
        follow_redirects=False,
    )
    assert login.status_code == 303
    assert "HttpOnly" in login.headers["set-cookie"]
    assert "Secure" in login.headers["set-cookie"]
    dashboard = client.get("/")
    assert dashboard.status_code == 200
    assert "Cloud synchronisé" in dashboard.text
    get_settings.cache_clear()


def test_sqlite_backup_is_valid_and_path_is_bounded(tmp_path, monkeypatch):
    database = tmp_path / "cloud.db"
    monkeypatch.setenv("DATABASE_PATH", str(database))
    monkeypatch.setenv("BACKUP_RETENTION", "2")
    get_settings.cache_clear()
    db.init_db()
    db.kv_set("backup-test", "ok")
    created = create_backup()
    assert created["size_bytes"] > 0
    assert len(list_backups()) == 1
    assert resolve_backup(created["name"]) == Path(tmp_path / "backups" / created["name"])
    assert resolve_backup("../cloud.db") is None
    get_settings.cache_clear()


def test_pwa_files_do_not_cache_private_api_or_dashboard():
    manifest = Path("app/static/manifest.webmanifest").read_text(encoding="utf-8")
    worker = Path("app/static/service-worker.js").read_text(encoding="utf-8")
    html = TestClient(app).get("/").text
    assert '"display": "standalone"' in manifest
    assert "url.pathname.startsWith('/api/')" in worker
    assert "url.pathname === '/'" in worker
    assert 'rel="manifest"' in html
    assert 'id="installAppButton"' in html


def test_help_page_explains_the_workflow_and_team_safety(monkeypatch):
    monkeypatch.setenv("APP_ACCESS_MODE", "local")
    get_settings.cache_clear()
    html = TestClient(app).get("/").text
    assert 'data-section="help"' in html
    assert 'id="section-help"' in html
    assert "Une opportunité doit franchir six étapes" in html
    assert "score produit /100" in html
    assert "un seul compte administrateur" in html
    assert 'id="exportDiagnostic"' in html
    get_settings.cache_clear()


def test_secure_diagnostic_excludes_credentials_and_private_records(tmp_path, monkeypatch):
    private_values = {
        "APP_ADMIN_EMAIL": "owner-private@example.test",
        "APP_ADMIN_PASSWORD": "SUPER_PRIVATE_PASSWORD_5931",
        "APP_SESSION_SECRET": "SESSION_PRIVATE_5931" * 3,
        "APP_ENCRYPTION_KEY": "ENCRYPTION_PRIVATE_5931" * 3,
        "EBAY_CLIENT_ID": "EBAY_CLIENT_PRIVATE_5931",
        "EBAY_CLIENT_SECRET": "EBAY_SECRET_PRIVATE_5931",
        "EBAY_RUNAME": "EBAY_RUNAME_PRIVATE_5931",
        "YOUTUBE_API_KEY": "YOUTUBE_PRIVATE_5931",
        "AMAZON_SP_API_CLIENT_ID": "AMAZON_CLIENT_PRIVATE_5931",
        "AMAZON_SP_API_CLIENT_SECRET": "AMAZON_SECRET_PRIVATE_5931",
        "AMAZON_SP_API_REFRESH_TOKEN": "Atzr|AMAZON_REFRESH_PRIVATE_5931",
    }
    monkeypatch.setenv("APP_ACCESS_MODE", "local")
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "private-cloud.db"))
    for name, value in private_values.items():
        monkeypatch.setenv(name, value)
    get_settings.cache_clear()
    db.init_db()

    response = TestClient(app).get("/api/ui/diagnostic-export")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain")
    assert "attachment" in response.headers["content-disposition"]
    assert "DIAGNOSTIC SÉCURISÉ" in response.text
    assert "Version : 0.14.2" in response.text
    assert "Ce rapport exclut les mots de passe" in response.text
    assert "Produits : 0" in response.text
    assert str((tmp_path / "private-cloud.db").resolve()) not in response.text
    for value in private_values.values():
        assert value not in response.text
    get_settings.cache_clear()
