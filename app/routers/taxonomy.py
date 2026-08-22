from fastapi import APIRouter, HTTPException

from app.services.ebay import EbayClient, EbayError

router = APIRouter(prefix="/api/taxonomy", tags=["Taxonomy eBay US"])


def _fail(exc: EbayError):
    raise HTTPException(status_code=exc.status_code or 400, detail={"message": str(exc), "payload": exc.payload})


@router.get("/suggest")
async def suggest(q: str, marketplace_id: str | None = None):
    if marketplace_id and marketplace_id != "EBAY_US":
        raise HTTPException(400, "v0.23 utilise uniquement la taxonomie eBay US")
    try:
        return await EbayClient().get_category_suggestions(q, "EBAY_US")
    except EbayError as exc:
        _fail(exc)


@router.get("/aspects/{category_id}")
async def aspects(category_id: str, marketplace_id: str | None = None):
    if marketplace_id and marketplace_id != "EBAY_US":
        raise HTTPException(400, "v0.23 utilise uniquement la taxonomie eBay US")
    try:
        return await EbayClient().get_item_aspects(category_id, "EBAY_US")
    except EbayError as exc:
        _fail(exc)
