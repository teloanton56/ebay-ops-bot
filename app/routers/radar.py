from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field

from app.services.cj import CJClient, CJError
from app.services.db import (
    delete_radar_watch,
    list_radar_scans,
    list_radar_watchlist,
    save_radar_watch,
)
from app.services.margin_hunter import hunt_margin_opportunities
from app.services.product_research import build_product_research_summary
from app.services.radar import analyze_ebay_market, source_statuses
from app.services.supplier_relevance import rank_supplier_results


router = APIRouter(prefix="/api/radar", tags=["Radar eBay US"])


class WatchIn(BaseModel):
    keyword: str = Field(min_length=2, max_length=120)
    notes: str = Field(default="", max_length=500)


class ScanIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    keyword: str = Field(min_length=2, max_length=120)


class MarginHunterIn(BaseModel):
    keyword: str = Field(min_length=2, max_length=120)
    limit: int = Field(default=10, ge=1, le=10)


@router.get("/sources")
def radar_sources():
    return [row for row in source_statuses() if row.get("id") in {"ebay", "cj"}]


@router.get("/watchlist")
def radar_watchlist():
    return list_radar_watchlist()


@router.post("/watchlist")
def add_radar_watch(payload: WatchIn):
    watch_id = save_radar_watch(payload.keyword, payload.notes)
    return {"id": watch_id, "saved": True}


@router.delete("/watchlist/{watch_id}")
def remove_radar_watch(watch_id: int):
    if not delete_radar_watch(watch_id):
        raise HTTPException(404, "Produit surveillé introuvable")
    return {"deleted": True}


@router.get("/history")
def radar_history():
    return [
        row for row in list_radar_scans()
        if row.get("marketplace") == "EBAY_US"
        and str((row.get("payload") or {}).get("currency") or "").upper() == "USD"
    ]


@router.post("/margin-hunter")
async def margin_hunter(payload: MarginHunterIn):
    try:
        return await hunt_margin_opportunities(payload.keyword, limit=payload.limit)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.post("/scan")
async def run_radar_scan(payload: ScanIn):
    keyword = payload.keyword.strip()
    try:
        market = await analyze_ebay_market(keyword, "EBAY_US")
    except Exception as exc:
        raise HTTPException(400, f"Analyse eBay US impossible : {exc}") from exc
    research_summary = build_product_research_summary([market])
    return {
        "keyword": keyword,
        "marketplace": "EBAY_US",
        "markets": [market],
        "errors": [],
        "research_summary": research_summary,
        "measured_only": True,
        "note": (
            "Le Radar v0.25.3 mesure uniquement eBay US. Le score repose sur des annonces actives observées ; "
            "eBay ne fournit pas le volume exact de recherches concurrentes via Browse API."
        ),
    }


@router.get("/supplier-match")
async def supplier_match(q: str = Query(min_length=2, max_length=120)):
    keyword = q.strip()
    client = CJClient()
    if not client.status().get("connected"):
        raise HTTPException(400, "Connectez CJ avant de rechercher un fournisseur")
    try:
        result = await client.search_products(keyword=keyword, size=40, min_stock=1)
        relevant, rejected = rank_supplier_results(
            keyword,
            result.get("products") or [],
            title_keys=("name",),
            limit=12,
        )
    except (CJError, RuntimeError) as exc:
        raise HTTPException(400, str(exc)) from exc

    products = []
    for product in relevant:
        products.append({
            **product,
            "provider": "CJ",
            "warehouse": "US prioritaire · CN fallback",
            "currency": "USD",
            "quality_verified": False,
            "quality_evidence": [
                f"Pertinence : {float(product.get('match_strength') or 0) * 100:.0f}%",
                "Coût livré US calculé à l'ajout ou dans Margin Hunter.",
            ],
        })
    return {
        "groups": [{"source": "CJ", "products": products, "total": len(products)}] if products else [],
        "errors": ([{"source": "CJ", "message": f"{rejected} résultat(s) hors sujet masqué(s)"}] if rejected else []),
        "measured_only": True,
        "note": "Comparaison fournisseur limitée à CJ Dropshipping.",
    }
