from fastapi import APIRouter, HTTPException
from app.services.ebay import EbayClient, EbayError

router = APIRouter(prefix="/api/taxonomy", tags=["Taxonomy"])


def _fail(exc: EbayError):
    raise HTTPException(status_code=exc.status_code or 400, detail={"message": str(exc), "payload": exc.payload})


@router.get("/suggest")
async def suggest(q: str, marketplace_id: str | None = None):
    try:
        return await EbayClient().get_category_suggestions(q, marketplace_id)
    except EbayError as exc:
        _fail(exc)


@router.get("/aspects/{category_id}")
async def aspects(category_id: str, marketplace_id: str | None = None):
    try:
        return await EbayClient().get_item_aspects(category_id, marketplace_id)
    except EbayError as exc:
        _fail(exc)
