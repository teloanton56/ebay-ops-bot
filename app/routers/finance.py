from fastapi import APIRouter, HTTPException, Query

from app.services.db import list_products
from app.services.ebay import EbayClient, EbayError
from app.services.finance import MILESTONES, ebay_series, empty_series, summarize


router = APIRouter(prefix="/api/finance", tags=["Finance"])


@router.get("/summary")
async def finance_summary(days: int = Query(30, ge=1, le=3650),
                          target: int = Query(5_000)):
    if target not in MILESTONES:
        raise HTTPException(400, "Palier de chiffre d'affaires invalide")
    client = EbayClient()
    if client.token_status().get("connected"):
        try:
            payload = await client.get_orders(200)
        except EbayError as exc:
            raise HTTPException(exc.status_code or 400, str(exc)) from exc
        rows, completeness = ebay_series(payload.get("orders") or [], list_products(), days)
        return summarize(rows, days=days, target=target,
                         source="EBAY", completeness=completeness)
    return summarize(empty_series(days), days=days, target=target, source="NO_SALES")
