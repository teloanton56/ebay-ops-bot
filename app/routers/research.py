from fastapi import APIRouter, HTTPException, Query

from app.config import get_settings
from app.services.db import get_product, list_research, save_research, set_product_fields
from app.services.ebay import EbayClient, EbayError
from app.services.research import summarize_market
from app.services.supplier_refresh import is_verified_cj_product

router = APIRouter(prefix="/api/research", tags=["Research eBay US"])


def _fail(exc: EbayError):
    raise HTTPException(status_code=exc.status_code or 400, detail={"message": str(exc), "payload": exc.payload})


def _require_real_market():
    settings = get_settings()
    if settings.ebay_effective_env != "production" or not settings.ebay_client_id or not settings.ebay_client_secret:
        raise HTTPException(400, "Connectez des clés eBay Production pour obtenir les données réelles eBay US.")
    return settings


def _usd_items(rows: list[dict]) -> list[dict]:
    return [
        row for row in rows
        if str((row.get("price") or {}).get("currency") or "USD").upper() == "USD"
    ]


@router.get("/search")
async def search(q: str = Query(min_length=2, max_length=120), marketplace_id: str | None = None,
                 limit: int = Query(default=20, ge=1, le=200), category_id: str | None = None):
    _require_real_market()
    if marketplace_id and marketplace_id != "EBAY_US":
        raise HTTPException(400, "La recherche est limitée à eBay US")
    try:
        data = await EbayClient().search_items(q, limit, "EBAY_US", category_id)
        items = _usd_items(data.get("itemSummaries") or [])
        result = {
            "demo": False,
            "marketplace": "EBAY_US",
            "currency": "USD",
            "total": data.get("total"),
            "itemSummaries": items,
            "summary": summarize_market(items, total_results=int(data.get("total") or len(items))),
        }
        save_research(q, "EBAY_US", result)
        return result
    except EbayError as exc:
        _fail(exc)


@router.get("/score/{product_id}")
async def score_product(product_id: int, limit: int = Query(default=30, ge=1, le=200)):
    product = get_product(product_id)
    if not product:
        raise HTTPException(404, "Produit introuvable")
    if not is_verified_cj_product(product):
        raise HTTPException(410, "Ce produit n'appartient pas au flux CJ vérifié pour eBay US / USD.")
    _require_real_market()
    try:
        data = await EbayClient().search_items(product["title"], limit, "EBAY_US", product.get("category_id"))
        items = _usd_items(data.get("itemSummaries") or [])
        summary = summarize_market(items, product, total_results=int(data.get("total") or len(items)))
        set_product_fields(
            product_id,
            opportunity_score=summary.get("opportunity_score"),
            suggested_price=summary.get("suggested_price"),
        )
        return {"demo": False, "marketplace": "EBAY_US", "currency": "USD", "summary": summary, "items": items}
    except EbayError as exc:
        _fail(exc)


@router.get("/history")
def history(limit: int = 20):
    return [
        row for row in list_research(min(max(limit, 1), 100))
        if row.get("marketplace_id") == "EBAY_US"
        and str((row.get("payload") or {}).get("currency") or "").upper() == "USD"
    ]
