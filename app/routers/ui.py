import platform
import sys
from collections import Counter
from pathlib import Path

from fastapi import APIRouter, Response

from app.config import get_settings
from app.services.db import list_products, list_listings
from app.services.ebay import EbayClient
from app.services.diagnostics import build_safe_diagnostic
from app.services.risk import assess_product

router = APIRouter(prefix="/api/ui", tags=["UI"])
VERSION = "0.24.0"


def _active_products() -> list[dict]:
    return [
        row for row in list_products()
        if row.get("marketplace_id") == "EBAY_US" and row.get("currency") == "USD"
    ]


@router.get("/summary")
def summary():
    settings = get_settings()
    products = _active_products()
    risks = [assess_product(product) for product in products]
    listings = list_listings()
    statuses = Counter((row.get("status") or "DRAFT") for row in listings)
    oauth = EbayClient().token_status()

    credentials_configured = bool(settings.ebay_client_id and settings.ebay_client_secret and settings.ebay_runame)
    connected = bool(oauth.get("connected"))
    setup_steps = [
        {"key": "profile", "label": "Mode eBay US / CJ actif", "done": True},
        {"key": "catalog", "label": "Au moins un produit CJ validé", "done": len(products) > 0},
        {"key": "keys", "label": "Clés eBay Production", "done": credentials_configured},
        {"key": "oauth", "label": "Compte eBay connecté", "done": connected},
    ]

    return {
        "version": VERSION,
        "products": len(products),
        "risk_pass": sum(1 for risk in risks if risk.get("pass")),
        "risk_block": sum(1 for risk in risks if not risk.get("pass")),
        "listings": len(listings),
        "listing_statuses": dict(statuses),
        "connected": connected,
        "credentials_configured": credentials_configured,
        "environment": settings.ebay_effective_env,
        "marketplace": "EBAY_US",
        "currency": "USD",
        "destination_country": "US",
        "demo_mode": settings.demo_mode,
        "write_enabled": settings.ebay_write_enabled,
        "publish_enabled": settings.ebay_publish_enabled,
        "operating_mode": "EBAY_US_CJ_ONLY",
        "setup_steps": setup_steps,
    }


@router.get("/listings")
def listings():
    return list_listings()


@router.get("/system")
def system_status():
    settings = get_settings()
    db_path = Path(settings.database_path).resolve()
    return {
        "version": VERSION,
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "database": str(db_path),
        "database_exists": db_path.exists(),
        "database_parent_writable": db_path.parent.exists(),
        "mode": "cloud" if settings.cloud_mode else "local",
        "environment": settings.ebay_effective_env,
        "marketplace": "EBAY_US",
        "currency": "USD",
        "destination_country": "US",
        "operating_mode": "EBAY_US_CJ_ONLY",
        "demo_mode": settings.demo_mode,
        "write_enabled": settings.ebay_write_enabled,
        "publish_enabled": settings.ebay_publish_enabled,
    }


@router.get("/diagnostic-export")
def diagnostic_export():
    filename, content = build_safe_diagnostic()
    return Response(
        content=content.encode("utf-8"),
        media_type="text/plain; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )
