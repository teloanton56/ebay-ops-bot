import os


def _load_env_file(path: str = ".env") -> None:
    from pathlib import Path
    if not path:
        return
    p = Path(path)
    if not p.is_file():
        return
    for raw in p.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key, value = key.strip(), value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


_load_env_file()
_load_env_file(os.getenv("APP_RUNTIME_ENV_PATH", ""))

from dataclasses import dataclass, field
from functools import lru_cache


def _env(name: str, default: str = ""):
    return field(default_factory=lambda: os.getenv(name, default))


def _env_bool(name: str, default: str = "false"):
    return field(default_factory=lambda: _b(name, default))


def _env_float(name: str, default: str):
    return field(default_factory=lambda: float(os.getenv(name, default)))


def _env_int(name: str, default: str):
    return field(default_factory=lambda: int(os.getenv(name, default)))


def _b(name: str, default: str = "false") -> bool:
    return os.getenv(name, default).lower() == "true"


@dataclass(frozen=True)
class Settings:
    app_env: str = _env("APP_ENV", "development")
    app_base_url: str = _env("APP_BASE_URL", "http://127.0.0.1:8765")
    app_access_mode: str = _env("APP_ACCESS_MODE", "local")
    app_allowed_hosts: str = _env("APP_ALLOWED_HOSTS", "")
    app_admin_email: str = _env("APP_ADMIN_EMAIL", "")
    app_admin_password: str = _env("APP_ADMIN_PASSWORD", "")
    app_session_secret: str = _env("APP_SESSION_SECRET", "")
    app_session_days: int = _env_int("APP_SESSION_DAYS", "30")
    app_encryption_key: str = _env("APP_ENCRYPTION_KEY")
    app_runtime_env_path: str = _env("APP_RUNTIME_ENV_PATH", ".env")
    database_path: str = _env("DATABASE_PATH", "./ebay_bot.db")
    demo_mode: bool = _env_bool("DEMO_MODE", "true")
    backup_enabled: bool = _env_bool("BACKUP_ENABLED", "true")
    backup_retention: int = _env_int("BACKUP_RETENTION", "14")

    ebay_write_enabled: bool = _env_bool("EBAY_WRITE_ENABLED", "false")
    ebay_publish_enabled: bool = _env_bool("EBAY_PUBLISH_ENABLED", "false")
    ebay_env: str = _env("EBAY_ENV", "sandbox")
    ebay_client_id: str = _env("EBAY_CLIENT_ID")
    ebay_client_secret: str = _env("EBAY_CLIENT_SECRET")
    ebay_runame: str = _env("EBAY_RUNAME")

    # v0.23 operating profile: one market, one currency, one supplier.
    # These are intentionally not environment-overridable so stale Render values
    # from the former France configuration cannot silently switch the bot back.
    ebay_locale: str = "en-US"
    ebay_marketplace_id: str = "EBAY_US"
    ebay_currency: str = "USD"

    ebay_account_deletion_endpoint: str = _env(
        "EBAY_ACCOUNT_DELETION_ENDPOINT",
        "https://ebay-ops-bot.onrender.com/api/ebay/account-deletion",
    )
    ebay_account_deletion_verification_token: str = _env("EBAY_ACCOUNT_DELETION_VERIFICATION_TOKEN", "")

    ebay_payment_policy_id: str = _env("EBAY_PAYMENT_POLICY_ID")
    ebay_return_policy_id: str = _env("EBAY_RETURN_POLICY_ID")
    ebay_fulfillment_policy_id: str = _env("EBAY_FULFILLMENT_POLICY_ID")

    # eBay item location must match the actual CJ dispatch country. Configure
    # real merchant location keys before enabling writes; no fake US location is used.
    ebay_cj_us_location_key: str = _env("EBAY_CJ_US_LOCATION_KEY", "")
    ebay_cj_cn_location_key: str = _env("EBAY_CJ_CN_LOCATION_KEY", "")
    ebay_merchant_location_key: str = _env("EBAY_MERCHANT_LOCATION_KEY", "")
    ebay_location_country: str = "US"
    ebay_location_postal_code: str = _env("EBAY_LOCATION_POSTAL_CODE")
    ebay_location_city: str = _env("EBAY_LOCATION_CITY")

    # Conservative eBay US baseline for a new/Starter seller in most categories.
    # The pricing engine can later replace this with category-specific fees.
    default_ebay_fee_percent: float = _env_float("DEFAULT_EBAY_FEE_PERCENT", "13.6")
    default_ad_rate_percent: float = _env_float("DEFAULT_AD_RATE_PERCENT", "3.0")
    default_fixed_fee: float = _env_float("DEFAULT_FIXED_FEE", "0.40")
    ebay_low_order_fee: float = _env_float("EBAY_LOW_ORDER_FEE", "0.30")
    ebay_standard_order_fee: float = _env_float("EBAY_STANDARD_ORDER_FEE", "0.40")
    default_return_reserve_percent: float = _env_float("DEFAULT_RETURN_RESERVE_PERCENT", "2.0")

    # Global catalogue safety floor. CJ route-specific thresholds below are stricter.
    min_margin_percent: float = _env_float("MIN_MARGIN_PERCENT", "20.0")
    min_profit_eur: float = _env_float("MIN_PROFIT_EUR", "5.0")
    min_stock: int = _env_int("MIN_STOCK", "10")
    max_shipping_days: int = _env_int("MAX_SHIPPING_DAYS", "7")
    max_supplier_price_jump_percent: float = _env_float("MAX_SUPPLIER_PRICE_JUMP_PERCENT", "20.0")

    # CJ US-first route policy.
    cj_us_min_margin_percent: float = _env_float("CJ_US_MIN_MARGIN_PERCENT", "20.0")
    cj_us_min_profit_usd: float = _env_float("CJ_US_MIN_PROFIT_USD", "5.0")
    cj_us_min_stock: int = _env_int("CJ_US_MIN_STOCK", "10")
    cj_us_max_shipping_days: int = _env_int("CJ_US_MAX_SHIPPING_DAYS", "7")

    # China is a fallback only when the economics compensate for the slower route.
    cj_cn_min_margin_percent: float = _env_float("CJ_CN_MIN_MARGIN_PERCENT", "30.0")
    cj_cn_min_profit_usd: float = _env_float("CJ_CN_MIN_PROFIT_USD", "8.0")
    cj_cn_min_stock: int = _env_int("CJ_CN_MIN_STOCK", "20")
    cj_cn_max_shipping_days: int = _env_int("CJ_CN_MAX_SHIPPING_DAYS", "12")

    scheduler_enabled: bool = _env_bool("SCHEDULER_ENABLED", "false")
    scheduler_sync_minutes: int = _env_int("SCHEDULER_SYNC_MINUTES", "30")
    auto_analysis_enabled: bool = _env_bool("AUTO_ANALYSIS_ENABLED", "true")
    auto_analysis_minutes: int = _env_int("AUTO_ANALYSIS_MINUTES", "60")
    radar_auto_enabled: bool = _env_bool("RADAR_AUTO_ENABLED", "true")
    radar_auto_hours: int = _env_int("RADAR_AUTO_HOURS", "6")

    @property
    def cloud_mode(self) -> bool:
        return self.app_access_mode.strip().lower() == "cloud"

    @property
    def min_profit_amount(self) -> float:
        """Currency-neutral alias retained while legacy DB/settings names are migrated."""
        return self.min_profit_eur

    @property
    def ebay_effective_env(self) -> str:
        client_id = self.ebay_client_id.strip().upper()
        if "-PRD-" in client_id:
            return "production"
        if "-SBX-" in client_id:
            return "sandbox"
        return "production" if self.ebay_env == "production" else "sandbox"

    @property
    def ebay_api_base(self) -> str:
        return "https://api.sandbox.ebay.com" if self.ebay_effective_env == "sandbox" else "https://api.ebay.com"

    @property
    def ebay_auth_base(self) -> str:
        return "https://auth.sandbox.ebay.com" if self.ebay_effective_env == "sandbox" else "https://auth.ebay.com"

    @property
    def ebay_oauth_scopes(self) -> list[str]:
        return [
            "https://api.ebay.com/oauth/api_scope/sell.account",
            "https://api.ebay.com/oauth/api_scope/sell.inventory",
            "https://api.ebay.com/oauth/api_scope/sell.fulfillment",
        ]


@lru_cache
def get_settings() -> Settings:
    return Settings()
