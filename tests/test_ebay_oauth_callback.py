from fastapi.testclient import TestClient

from app.config import get_settings
from app.main import app
from app.services.cloud_auth import public_path
from app.services.ebay import EbayClient


def test_ebay_oauth_callback_is_public_but_other_auth_api_is_private():
    assert public_path("/api/auth/ebay/callback") is True
    assert public_path("/api/auth/ebay/status") is False


def test_ebay_oauth_callback_completes_without_dashboard_session(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "oauth-callback.db"))
    monkeypatch.setenv("APP_ACCESS_MODE", "cloud")
    monkeypatch.setenv("APP_ADMIN_EMAIL", "owner@example.com")
    monkeypatch.setenv("APP_ADMIN_PASSWORD", "a-secure-test-password")
    monkeypatch.setenv("APP_SESSION_SECRET", "s" * 40)
    monkeypatch.setenv("APP_ENCRYPTION_KEY", "test-encryption-key")
    get_settings.cache_clear()

    called = {}

    async def fake_exchange_code(self, code, state):
        called["code"] = code
        called["state"] = state

    monkeypatch.setattr(EbayClient, "exchange_code", fake_exchange_code)

    with TestClient(app) as client:
        response = client.get(
            "/api/auth/ebay/callback",
            params={"code": "authorization-code", "state": "oauth-state"},
        )

    assert response.status_code == 200
    assert "Compte eBay connecté" in response.text
    assert called == {"code": "authorization-code", "state": "oauth-state"}
    get_settings.cache_clear()
