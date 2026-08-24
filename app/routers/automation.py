from fastapi import APIRouter

from app.config import get_settings
from app.services.analyzer import analyze_catalog
from app.services.db import (
    get_listing_for_product,
    list_alerts,
    list_analysis_runs,
    list_products,
    mark_alerts_read,
)
from app.services.ebay import EbayClient, EbayError
from app.services.risk import assess_product
from app.services.supplier_refresh import SupplierRefreshError, is_verified_cj_product, refresh_product_from_supplier

router = APIRouter(prefix="/api/automation", tags=["Automation eBay US"])


@router.post("/analyze-now")
async def analyze_now():
    return await analyze_catalog()


@router.get("/history")
def analysis_history(limit: int = 20):
    return list_analysis_runs(min(max(limit, 1), 100))


@router.get("/alerts")
def alerts(limit: int = 50):
    return list_alerts(min(max(limit, 1), 200))


@router.post("/alerts/read")
def read_alerts():
    return {"updated": mark_alerts_read()}


@router.get("/status")
def automation_status():
    settings = get_settings()
    real_market = bool(
        settings.ebay_effective_env == "production"
        and settings.ebay_client_id
        and settings.ebay_client_secret
        and EbayClient().token_status().get("connected")
    )
    return {
        "enabled": settings.auto_analysis_enabled,
        "interval_minutes": settings.auto_analysis_minutes,
        "mode": "EBAY_US" if real_market else "CATALOGUE_US",
        "market_data": real_market,
        "marketplace": "EBAY_US",
        "currency": "USD",
        "supplier": "CJ",
        "write_enabled": settings.ebay_write_enabled,
        "publish_enabled": settings.ebay_publish_enabled,
    }


@router.post("/sync-all")
async def sync_all():
    client = EbayClient()
    settings = get_settings()
    results = []
    for product in list_products():
        if not is_verified_cj_product(product):
            continue
        listing = get_listing_for_product(product["id"])
        if not listing or not listing.get("offer_id"):
            continue
        try:
            refreshed, supplier_verification = await refresh_product_from_supplier(product)
            risk = assess_product(refreshed)
            qty = int(refreshed.get("stock") or 0) if risk["pass"] else 0
            result = await client.update_live_offer_price_quantity(
                refreshed["supplier_sku"],
                listing["offer_id"],
                float(refreshed.get("target_price") or 0),
                qty,
                "USD",
            )
            results.append({
                "product_id": refreshed["id"],
                "ok": True,
                "risk": risk,
                "supplier_verification": supplier_verification,
                "effective_quantity": qty,
                "result": result,
            })
        except SupplierRefreshError as exc:
            # Never push stale positive stock when CJ cannot be revalidated.
            try:
                await client.update_live_offer_price_quantity(
                    product["supplier_sku"],
                    listing["offer_id"],
                    float(product.get("target_price") or 0),
                    0,
                    "USD",
                )
            except Exception:
                pass
            results.append({"product_id": product["id"], "ok": False, "safe_quantity": 0, "error": str(exc)})
        except EbayError as exc:
            results.append({"product_id": product["id"], "ok": False, "error": str(exc)})
    return {"processed": len(results), "marketplace": "EBAY_US", "currency": "USD", "results": results}
