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


@router.get("/summary")
def summary():
    s = get_settings()
    products = list_products()
    risks = [assess_product(p) for p in products]
    listings = list_listings()
    statuses = Counter((x.get("status") or "DRAFT") for x in listings)
    oauth = EbayClient().token_status()

    credentials_configured = bool(s.ebay_client_id and s.ebay_client_secret and s.ebay_runame)
    connected = bool(oauth.get("connected"))
    setup_steps = [
        {"key": "app", "label": "Bot installé", "done": True},
        {"key": "catalog", "label": "Catalogue fournisseur", "done": len(products) > 0},
        {"key": "keys", "label": "Clés eBay Developer", "done": credentials_configured},
        {"key": "oauth", "label": "Compte eBay connecté", "done": connected},
        {"key": "sandbox", "label": "Tests Sandbox", "done": connected and s.ebay_env == "sandbox"},
    ]

    return {
        "version": "0.14.3",
        "products": len(products),
        "risk_pass": sum(1 for r in risks if r.get("pass")),
        "risk_block": sum(1 for r in risks if not r.get("pass")),
        "listings": len(listings),
        "listing_statuses": dict(statuses),
        "connected": connected,
        "credentials_configured": credentials_configured,
        "environment": s.ebay_env,
        "marketplace": s.ebay_marketplace_id,
        "currency": s.ebay_currency,
        "demo_mode": s.demo_mode,
        "write_enabled": s.ebay_write_enabled,
        "publish_enabled": s.ebay_publish_enabled,
        "setup_steps": setup_steps,
    }


@router.get("/listings")
def listings():
    return list_listings()


@router.get("/system")
def system_status():
    s = get_settings()
    db_path = Path(s.database_path).resolve()
    return {
        "version": "0.14.3",
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "database": str(db_path),
        "database_exists": db_path.exists(),
        "database_parent_writable": db_path.parent.exists(),
        "mode": "cloud" if s.cloud_mode else "local",
        "environment": s.ebay_env,
        "demo_mode": s.demo_mode,
        "write_enabled": s.ebay_write_enabled,
        "publish_enabled": s.ebay_publish_enabled,
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
