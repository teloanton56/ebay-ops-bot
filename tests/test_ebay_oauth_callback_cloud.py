from fastapi.testclient import TestClient

from app.config import get_settings
from app.main import app
from app.services.cloud_auth import public_path


def _configure_cloud(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "oauth-callback.db"))
    monkeypatch.setenv("APP_ACCESS_MODE", "cloud")
    monkeypatch.setenv("APP_ADMIN_EMAIL", "owner@example.com")
    monkeypatch.setenv("APP_ADMIN_PASSWORD", "a-secure-test-password")
    monkeypatch.setenv("APP_SESSION_SECRET", "s" * 40)
    monkeypatch.setenv("APP_ENCRYPTION_KEY", "test-encryption-key")
    get_settings.cache_clear()


def test_ebay_oauth_callback_is_public_but_other_auth_api_stays_private(monkeypatch, tmp_path):
    _configure_cloud(monkeypatch, tmp_path)

    assert public_path("/api/auth/ebay/callback") is True
    assert public_path("/api/auth/ebay/status") is False

    with TestClient(app) as client:
        callback = client.get("/api/auth/ebay/callback")
        status = client.get("/api/auth/ebay/status")

    # Missing OAuth code reaches FastAPI validation instead of cloud-session middleware.
    assert callback.status_code == 422
    assert status.status_code == 401
    assert status.json()["detail"] == "Session expirée. Reconnectez-vous."
    get_settings.cache_clear()


def test_oauth_callback_fix_release_is_versioned():
    assert app.version == "0.15.3"
