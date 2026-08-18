import os
from pathlib import Path
from typing import Literal

from cryptography.fernet import Fernet
from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.config import get_settings
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
        k, v = line.split("=", 1)
        out[k.strip()] = v.strip().strip('"').strip("'")
    return out


def _write_env(updates: dict[str, str]) -> None:
    data = _read_env()
    data.update(updates)
    preferred = [
        "APP_BASE_URL", "APP_ENCRYPTION_KEY", "DEMO_MODE", "EBAY_ENV", "EBAY_CLIENT_ID", "EBAY_CLIENT_SECRET",
        "EBAY_RUNAME", "EBAY_MARKETPLACE_ID", "EBAY_CURRENCY", "EBAY_WRITE_ENABLED", "EBAY_PUBLISH_ENABLED",
        "DEFAULT_EBAY_FEE_PERCENT", "DEFAULT_AD_RATE_PERCENT", "DEFAULT_FIXED_FEE",
        "DEFAULT_RETURN_RESERVE_PERCENT", "MIN_MARGIN_PERCENT", "MIN_PROFIT_EUR", "MIN_STOCK",
        "MAX_SHIPPING_DAYS", "MAX_SUPPLIER_PRICE_JUMP_PERCENT",
    ]
    keys = preferred + sorted(k for k in data if k not in preferred)
    ENV_PATH.parent.mkdir(parents=True, exist_ok=True)
    ENV_PATH.write_text("\n".join(f"{k}={data[k]}" for k in keys if k in data) + "\n", encoding="utf-8")
    try:
        ENV_PATH.chmod(0o600)
    except OSError:
        pass
    for k, v in updates.items():
        os.environ[k] = v
    get_settings.cache_clear()
    EbayClient._app_token_cache = None
    EbayClient._app_token_expires = None


def _masked(value: str, visible: int = 5) -> str:
    if not value:
        return ""
    if len(value) <= visible * 2:
        return "•" * len(value)
    return value[:visible] + "…" + value[-visible:]


class EbaySettingsIn(BaseModel):
    client_id: str | None = None
    client_secret: str | None = None
    runame: str | None = None
    environment: Literal["sandbox", "production"] = "sandbox"
    marketplace_id: str = "EBAY_FR"
    currency: str = "EUR"


class RiskSettingsIn(BaseModel):
    ebay_fee_percent: float = Field(ge=0, le=50)
    ad_rate_percent: float = Field(ge=0, le=50)
    fixed_fee: float = Field(ge=0, le=50)
    return_reserve_percent: float = Field(ge=0, le=50)
    min_margin_percent: float = Field(ge=0, le=100)
    min_profit_eur: float = Field(ge=0)
    min_stock: int = Field(ge=0)
    max_shipping_days: int = Field(ge=0, le=90)
    max_supplier_price_jump_percent: float = Field(ge=0, le=500)


@router.get("/ebay")
def ebay_settings():
    s = get_settings()
    missing = []
    if not s.ebay_client_id:
        missing.append("Client ID")
    if not s.ebay_client_secret:
        missing.append("Client Secret")
    if not s.ebay_runame:
        missing.append("RuName")
    return {
        "configured": not missing,
        "missing": missing,
        "environment": s.ebay_env,
        "marketplace_id": s.ebay_marketplace_id,
        "currency": s.ebay_currency,
        "client_id_masked": _masked(s.ebay_client_id),
        "runame_masked": _masked(s.ebay_runame),
        "has_client_secret": bool(s.ebay_client_secret),
        "connected": EbayClient().token_status().get("connected", False),
    }


@router.post("/ebay")
def save_ebay_settings(payload: EbaySettingsIn):
    current = _read_env()
    encryption_key = current.get("APP_ENCRYPTION_KEY") or os.getenv("APP_ENCRYPTION_KEY") or Fernet.generate_key().decode()

    # Empty fields mean "keep the existing credential" so editing marketplace/currency never destroys keys.
    client_id = (payload.client_id or "").strip() or current.get("EBAY_CLIENT_ID", "")
    client_secret = (payload.client_secret or "").strip() or current.get("EBAY_CLIENT_SECRET", "")
    runame = (payload.runame or "").strip() or current.get("EBAY_RUNAME", "")

    _write_env({
        "APP_ENCRYPTION_KEY": encryption_key,
        "EBAY_CLIENT_ID": client_id,
        "EBAY_CLIENT_SECRET": client_secret,
        "EBAY_RUNAME": runame,
        "EBAY_ENV": payload.environment,
        "EBAY_MARKETPLACE_ID": payload.marketplace_id.strip() or "EBAY_FR",
        "EBAY_CURRENCY": payload.currency.strip().upper() or "EUR",
        "DEMO_MODE": "true",
        "EBAY_WRITE_ENABLED": "false",
        "EBAY_PUBLISH_ENABLED": "false",
    })
    configured = bool(client_id and client_secret and runame)
    return {
        "saved": True,
        "configured": configured,
        "message": "Configuration eBay sauvegardée dans l'espace privé. Sandbox et Dry-run restent activés.",
    }


@router.get("/risk")
def get_risk_settings():
    s = get_settings()
    return {
        "ebay_fee_percent": s.default_ebay_fee_percent,
        "ad_rate_percent": s.default_ad_rate_percent,
        "fixed_fee": s.default_fixed_fee,
        "return_reserve_percent": s.default_return_reserve_percent,
        "min_margin_percent": s.min_margin_percent,
        "min_profit_eur": s.min_profit_eur,
        "min_stock": s.min_stock,
        "max_shipping_days": s.max_shipping_days,
        "max_supplier_price_jump_percent": s.max_supplier_price_jump_percent,
    }


@router.post("/risk")
def save_risk_settings(payload: RiskSettingsIn):
    _write_env({
        "DEFAULT_EBAY_FEE_PERCENT": str(payload.ebay_fee_percent),
        "DEFAULT_AD_RATE_PERCENT": str(payload.ad_rate_percent),
        "DEFAULT_FIXED_FEE": str(payload.fixed_fee),
        "DEFAULT_RETURN_RESERVE_PERCENT": str(payload.return_reserve_percent),
        "MIN_MARGIN_PERCENT": str(payload.min_margin_percent),
        "MIN_PROFIT_EUR": str(payload.min_profit_eur),
        "MIN_STOCK": str(payload.min_stock),
        "MAX_SHIPPING_DAYS": str(payload.max_shipping_days),
        "MAX_SUPPLIER_PRICE_JUMP_PERCENT": str(payload.max_supplier_price_jump_percent),
    })
    return {"saved": True, "message": "Règles de marge et de risque mises à jour.",
            "applied": get_risk_settings()}
