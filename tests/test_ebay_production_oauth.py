from fastapi.testclient import TestClient

from app.config import Settings, get_settings
from app.main import app
from app.routers import settings as settings_router


def test_production_app_id_forces_production_hosts():
    settings = Settings(
        ebay_env="sandbox",
        ebay_client_id="example-ebaybot-PRD-123456789",
    )
    assert settings.ebay_effective_env == "production"
    assert settings.ebay_auth_base == "https://auth.ebay.com"
    assert settings.ebay_api_base == "https://api.ebay.com"


def test_sandbox_app_id_forces_sandbox_hosts():
    settings = Settings(
        ebay_env="production",
        ebay_client_id="example-ebaybot-SBX-123456789",
    )
    assert settings.ebay_effective_env == "sandbox"
    assert settings.ebay_auth_base == "https://auth.sandbox.ebay.com"
    assert settings.ebay_api_base == "https://api.sandbox.ebay.com"


def test_dashboard_allows_production_selection():
    html = TestClient(app).get("/").text
    assert '<option value="production">Production</option>' in html
    assert 'value="production" disabled' not in html


def test_saving_prd_key_persists_production_environment(tmp_path, monkeypatch):
    env_path = tmp_path / "runtime.env"
    monkeypatch.setattr(settings_router, "ENV_PATH", env_path)
    monkeypatch.setenv("APP_RUNTIME_ENV_PATH", str(env_path))
    get_settings.cache_clear()

    payload = settings_router.EbaySettingsIn(
        client_id="example-ebaybot-PRD-123456789",
        client_secret="secret",
        runame="example-runame",
        environment="sandbox",
        marketplace_id="EBAY_FR",
        currency="EUR",
    )
    result = settings_router.save_ebay_settings(payload)

    assert result["environment"] == "production"
    assert "EBAY_ENV=production" in env_path.read_text(encoding="utf-8")
    get_settings.cache_clear()
