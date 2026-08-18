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
