from fastapi import APIRouter
from app.services.db import list_products, get_listing_for_product, list_analysis_runs, list_alerts, mark_alerts_read
from app.services.analyzer import analyze_catalog
from app.services.ebay import EbayClient, EbayError
from app.services.risk import assess_product
from app.config import get_settings

router = APIRouter(prefix="/api/automation", tags=["Automation"])


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
    s = get_settings()
    real_market = bool(s.ebay_env == "production" and s.ebay_client_id and s.ebay_client_secret
                       and EbayClient().token_status().get("connected"))
    return {"enabled": s.auto_analysis_enabled, "interval_minutes": s.auto_analysis_minutes,
            "mode": "EBAY" if real_market else "CATALOGUE",
            "market_data": real_market,
            "write_enabled": s.ebay_write_enabled, "publish_enabled": s.ebay_publish_enabled}


@router.post("/sync-all")
async def sync_all():
    client = EbayClient()
    s = get_settings()
    results = []
    for p in list_products():
        listing = get_listing_for_product(p["id"])
        if not listing or not listing.get("offer_id"):
            continue
        risk = assess_product(p)
        qty = int(p.get("stock") or 0) if risk["pass"] else 0
        try:
            result = await client.update_live_offer_price_quantity(
                p["supplier_sku"], listing["offer_id"], float(p.get("target_price") or 0), qty,
                p.get("currency") or s.ebay_currency,
            )
            results.append({"product_id": p["id"], "ok": True, "risk": risk, "result": result})
        except EbayError as exc:
            results.append({"product_id": p["id"], "ok": False, "error": str(exc)})
    return {"processed": len(results), "results": results}
