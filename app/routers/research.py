from fastapi import APIRouter, HTTPException, Query
from app.config import get_settings
from app.services.db import get_product, list_research, save_research, set_product_fields
from app.services.ebay import EbayClient, EbayError
from app.services.research import summarize_market

router = APIRouter(prefix="/api/research", tags=["Research"])


def _fail(exc: EbayError):
    raise HTTPException(status_code=exc.status_code or 400, detail={"message": str(exc), "payload": exc.payload})


def _require_real_market():
    settings = get_settings()
    if settings.ebay_env != "production" or not settings.ebay_client_id or not settings.ebay_client_secret:
        raise HTTPException(400, "Connectez des clés eBay Production pour obtenir des données de marché réelles. Aucune donnée simulée n'est générée.")
    return settings


@router.get("/search")
async def search(q: str = Query(min_length=2, max_length=120), marketplace_id: str | None = None,
                 limit: int = Query(default=20, ge=1, le=200), category_id: str | None = None):
    s = _require_real_market()
    market = marketplace_id or s.ebay_marketplace_id
    try:
        data = await EbayClient().search_items(q, limit, market, category_id)
        items = data.get("itemSummaries") or []
        result = {"demo": False, "total": data.get("total"), "itemSummaries": items, "summary": summarize_market(items)}
        save_research(q, market, result)
        return result
    except EbayError as exc:
        _fail(exc)


@router.get("/score/{product_id}")
async def score_product(product_id: int, limit: int = Query(default=30, ge=1, le=200)):
    product = get_product(product_id)
    if not product:
        raise HTTPException(404, "Produit introuvable")
    q = product["title"]
    _require_real_market()
    try:
        data = await EbayClient().search_items(q, limit, product.get("marketplace_id"), product.get("category_id"))
        items = data.get("itemSummaries") or []
        summary = summarize_market(items, product)
        set_product_fields(product_id, opportunity_score=summary.get("opportunity_score"), suggested_price=summary.get("suggested_price"))
        return {"demo": False, "summary": summary, "items": items}
    except EbayError as exc:
        _fail(exc)


@router.get("/history")
def history(limit: int = 20):
    return list_research(min(max(limit, 1), 100))
