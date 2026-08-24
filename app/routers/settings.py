import os
from pathlib import Path
from typing import Literal

from cryptography.fernet import Fernet
from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.config import get_settings
from app.services.cj_landed import route_requirements
from app.services.ebay import EbayClient

router = APIRouter(prefix="/api/settings", tags=["Settings"])
ENV_PATH = Path(os.getenv("APP_RUNTIME_ENV_PATH", ".env"))


def _read_env() -> dict[str, str]:
    out: dict[str, str] = {}
    if not ENV_PATH.exists():
        return out
    for raw in ENV_PATH.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        out[key.strip()] = value.strip().strip('"').strip("'")
    return out


def _write_env(updates: dict[str, str]) -> None:
    data = _read_env()
    data.update(updates)
    preferred = [
        "APP_BASE_URL", "APP_ENCRYPTION_KEY", "DEMO_MODE", "EBAY_ENV", "EBAY_CLIENT_ID", "EBAY_CLIENT_SECRET",
        "EBAY_RUNAME", "EBAY_MARKETPLACE_ID", "EBAY_CURRENCY", "EBAY_WRITE_ENABLED", "EBAY_PUBLISH_ENABLED",
        "EBAY_CJ_US_LOCATION_KEY", "EBAY_CJ_CN_LOCATION_KEY",
        "DEFAULT_EBAY_FEE_PERCENT", "DEFAULT_AD_RATE_PERCENT", "EBAY_LOW_ORDER_FEE", "EBAY_STANDARD_ORDER_FEE",
        "DEFAULT_RETURN_RESERVE_PERCENT", "MIN_MARGIN_PERCENT", "MIN_PROFIT_USD", "MIN_STOCK", "MAX_SHIPPING_DAYS",
        "CJ_US_MIN_MARGIN_PERCENT", "CJ_US_MIN_PROFIT_USD", "CJ_US_MIN_STOCK", "CJ_US_MAX_SHIPPING_DAYS",
        "CJ_CN_MIN_MARGIN_PERCENT", "CJ_CN_MIN_PROFIT_USD", "CJ_CN_MIN_STOCK", "CJ_CN_MAX_SHIPPING_DAYS",
        "MAX_SUPPLIER_PRICE_JUMP_PERCENT",
    ]
    keys = preferred + sorted(key for key in data if key not in preferred)
    ENV_PATH.parent.mkdir(parents=True, exist_ok=True)
    ENV_PATH.write_text("\n".join(f"{key}={data[key]}" for key in keys if key in data) + "\n", encoding="utf-8")
    try:
        ENV_PATH.chmod(0o600)
    except OSError:
        pass
    for key, value in updates.items():
        os.environ[key] = value
    get_settings.cache_clear()
    EbayClient._app_token_cache = None
    EbayClient._app_token_expires = None


def _masked(value: str, visible: int = 5) -> str:
    if not value:
        return ""
    if len(value) <= visible * 2:
        return "•" * len(value)
    return value[:visible] + "…" + value[-visible:]


def _environment_for_client_id(client_id: str, requested: str) -> str:
    normalized = client_id.strip().upper()
    if "-PRD-" in normalized:
        return "production"
    if "-SBX-" in normalized:
        return "sandbox"
    return "production" if requested == "production" else "sandbox"


class EbaySettingsIn(BaseModel):
    client_id: str | None = None
    client_secret: str | None = None
    runame: str | None = None
    environment: Literal["sandbox", "production"] = "sandbox"
    marketplace_id: Literal["EBAY_US"] = "EBAY_US"
    currency: Literal["USD"] = "USD"


class RiskSettingsIn(BaseModel):
    ebay_fee_percent: float = Field(ge=0, le=50)
    ad_rate_percent: float = Field(ge=0, le=50)
    fixed_fee: float = Field(ge=0, le=50)
    return_reserve_percent: float = Field(ge=0, le=50)
    min_margin_percent: float = Field(ge=0, le=100)
    min_profit_usd: float = Field(ge=0)
    min_stock: int = Field(ge=0)
    max_shipping_days: int = Field(ge=0, le=90)
    max_supplier_price_jump_percent: float = Field(ge=0, le=500)


@router.get("/ebay")
def ebay_settings():
    settings = get_settings()
    missing = []
    if not settings.ebay_client_id:
        missing.append("Client ID")
    if not settings.ebay_client_secret:
        missing.append("Client Secret")
    if not settings.ebay_runame:
        missing.append("RuName")
    return {
        "configured": not missing,
        "missing": missing,
        "environment": settings.ebay_effective_env,
        "marketplace_id": "EBAY_US",
        "currency": "USD",
        "locale": "en-US",
        "client_id_masked": _masked(settings.ebay_client_id),
        "runame_masked": _masked(settings.ebay_runame),
        "has_client_secret": bool(settings.ebay_client_secret),
        "connected": EbayClient().token_status().get("connected", False),
        "operating_mode": "EBAY_US_CJ_ONLY",
    }


@router.post("/ebay")
def save_ebay_settings(payload: EbaySettingsIn):
    current = _read_env()
    encryption_key = current.get("APP_ENCRYPTION_KEY") or os.getenv("APP_ENCRYPTION_KEY") or Fernet.generate_key().decode()
    client_id = (payload.client_id or "").strip() or current.get("EBAY_CLIENT_ID", "")
    client_secret = (payload.client_secret or "").strip() or current.get("EBAY_CLIENT_SECRET", "")
    runame = (payload.runame or "").strip() or current.get("EBAY_RUNAME", "")
    environment = _environment_for_client_id(client_id, payload.environment)

    _write_env({
        "APP_ENCRYPTION_KEY": encryption_key,
        "EBAY_CLIENT_ID": client_id,
        "EBAY_CLIENT_SECRET": client_secret,
        "EBAY_RUNAME": runame,
        "EBAY_ENV": environment,
        "EBAY_MARKETPLACE_ID": "EBAY_US",
        "EBAY_CURRENCY": "USD",
        "DEMO_MODE": "true",
        "EBAY_WRITE_ENABLED": "false",
        "EBAY_PUBLISH_ENABLED": "false",
    })
    configured = bool(client_id and client_secret and runame)
    return {
        "saved": True,
        "configured": configured,
        "environment": environment,
        "marketplace_id": "EBAY_US",
        "currency": "USD",
        "message": f"Configuration eBay US {environment} sauvegardée. Les écritures et publications restent verrouillées.",
    }


@router.get("/risk")
def get_risk_settings():
    settings = get_settings()
    return {
        "ebay_fee_percent": settings.default_ebay_fee_percent,
        "ad_rate_percent": settings.default_ad_rate_percent,
        "fixed_fee": settings.ebay_standard_order_fee,
        "return_reserve_percent": settings.default_return_reserve_percent,
        "min_margin_percent": settings.min_margin_percent,
        "min_profit_usd": settings.min_profit_amount,
        "min_stock": settings.min_stock,
        "max_shipping_days": settings.max_shipping_days,
        "max_supplier_price_jump_percent": settings.max_supplier_price_jump_percent,
        "currency": "USD",
        "us_route": route_requirements("US"),
        "cn_route": route_requirements("CN"),
    }


@router.post("/risk")
def save_risk_settings(payload: RiskSettingsIn):
    _write_env({
        "DEFAULT_EBAY_FEE_PERCENT": str(payload.ebay_fee_percent),
        "DEFAULT_AD_RATE_PERCENT": str(payload.ad_rate_percent),
        "EBAY_STANDARD_ORDER_FEE": str(payload.fixed_fee),
        "DEFAULT_RETURN_RESERVE_PERCENT": str(payload.return_reserve_percent),
        "MIN_MARGIN_PERCENT": str(payload.min_margin_percent),
        "MIN_PROFIT_USD": str(payload.min_profit_usd),
        "MIN_STOCK": str(payload.min_stock),
        "MAX_SHIPPING_DAYS": str(payload.max_shipping_days),
        "MAX_SUPPLIER_PRICE_JUMP_PERCENT": str(payload.max_supplier_price_jump_percent),
    })
    return {"saved": True, "message": "Règles générales eBay US mises à jour.", "applied": get_risk_settings()}
