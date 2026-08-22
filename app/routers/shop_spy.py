from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.services.ebay_shop_spy import analyze_ebay_shop
from app.services.shop_spy_sourcing import compare_shop_listing


router = APIRouter(prefix="/api/shop-spy", tags=["Shop Spy"])


class ShopAnalyzeIn(BaseModel):
    seller: str = Field(min_length=2, max_length=300)
    limit: int = Field(default=50, ge=1, le=100)


class ShopCompareIn(BaseModel):
    title: str = Field(min_length=2, max_length=300)
    competitor_price: float = Field(gt=0)
    limit: int = Field(default=8, ge=1, le=8)


@router.post("/analyze")
async def analyze_shop(payload: ShopAnalyzeIn):
    try:
        return await analyze_ebay_shop(payload.seller, limit=payload.limit)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.post("/compare")
async def compare_listing(payload: ShopCompareIn):
    try:
        return await compare_shop_listing(
            payload.title,
            payload.competitor_price,
            limit=payload.limit,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
