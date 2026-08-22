from app.config import get_settings
from app.routers.research import _require_real_market
from app.services.radar import source_statuses


def _production_keys_with_stale_sandbox_env(monkeypatch):
    monkeypatch.setenv("EBAY_ENV", "sandbox")
    monkeypatch.setenv("EBAY_CLIENT_ID", "test-app-PRD-123456")
    monkeypatch.setenv("EBAY_CLIENT_SECRET", "test-production-secret")
    get_settings.cache_clear()


def test_radar_accepts_production_app_id_even_if_saved_env_is_stale(monkeypatch):
    _production_keys_with_stale_sandbox_env(monkeypatch)

    ebay = next(row for row in source_statuses() if row["id"] == "ebay")

    assert get_settings().ebay_effective_env == "production"
    assert ebay["configured"] is True
    assert ebay["ready"] is True
    assert ebay["status"] == "Ready"
    get_settings.cache_clear()


def test_research_guard_uses_effective_production_environment(monkeypatch):
    _production_keys_with_stale_sandbox_env(monkeypatch)

    settings = _require_real_market()

    assert settings.ebay_effective_env == "production"
    assert settings.ebay_marketplace_id == "EBAY_US"
    assert settings.ebay_currency == "USD"
    get_settings.cache_clear()
