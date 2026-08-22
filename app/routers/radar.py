from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from app.services.cj import CJClient, CJError
from app.services.db import (
    delete_factory_lead,
    delete_radar_watch,
    delete_rfq,
    list_factory_leads,
    list_radar_scans,
    list_radar_watchlist,
    list_rfqs,
    save_factory_lead,
    save_radar_watch,
    save_rfq,
)
from app.services.margin_hunter import hunt_margin_opportunities
from app.services.product_research import build_product_research_summary
from app.services.radar import analyze_ebay_market, build_rfq_message, source_statuses
from app.services.supplier_relevance import rank_supplier_results


router = APIRouter(prefix="/api/radar", tags=["Radar eBay US"])


class WatchIn(BaseModel):
    keyword: str = Field(min_length=2, max_length=120)
    notes: str = Field(default="", max_length=500)


class ScanIn(BaseModel):
    keyword: str = Field(min_length=2, max_length=120)
    # Kept for backward-compatible clients; v0.23 always uses EBAY_US only.
    marketplaces: list[str] = Field(default_factory=list, max_length=6)
    amazon_marketplaces: list[str] = Field(default_factory=list, max_length=6)


class FactoryIn(BaseModel):
    company: str = Field(min_length=2, max_length=150)
    source: str = Field(default="", max_length=80)
    website: str = Field(default="", max_length=300)
    email: str = Field(default="", max_length=180)
    country: str = Field(default="", max_length=80)
    status: str = Field(default="À contacter", max_length=50)
    notes: str = Field(default="", max_length=1000)


class RFQIn(BaseModel):
    factory_id: int | None = None
    product_query: str = Field(min_length=2, max_length=200)
    quantities: str = Field(default="10, 50, 100, 500", min_length=1, max_length=120)
    specifications: str = Field(default="", max_length=1500)


class DiscoveryIn(BaseModel):
    country: str = Field(default="US", min_length=2, max_length=2)


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
    return [row for row in list_radar_scans() if row.get("marketplace") == "EBAY_US"]


@router.get("/discoveries")
def discoveries():
    return []


@router.post("/discover")
async def discover_without_keyword(_: DiscoveryIn):
    raise HTTPException(
        410,
        "La détection YouTube/TikTok a été retirée en v0.23. Utilisez une niche eBay US ou Margin Hunter.",
    )


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
            "Radar v0.23 mesure uniquement eBay US. Le score repose sur des annonces actives observées ; "
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


# Legacy factory/RFQ endpoints remain read/write compatible for existing data but
# are no longer exposed in the v0.23 interface. They can support the later Shopify phase.
@router.get("/factories")
def factories():
    return list_factory_leads()


@router.post("/factories")
def add_factory(payload: FactoryIn):
    return {"id": save_factory_lead(payload.model_dump()), "saved": True,
            "message": "Contact enregistré localement. Aucun message envoyé."}


@router.delete("/factories/{factory_id}")
def remove_factory(factory_id: int):
    if not delete_factory_lead(factory_id):
        raise HTTPException(404, "Usine introuvable")
    return {"deleted": True}


@router.get("/rfqs")
def rfqs():
    return list_rfqs()


@router.post("/rfqs")
def create_rfq(payload: RFQIn):
    factory = next((x for x in list_factory_leads() if x["id"] == payload.factory_id), None)
    if payload.factory_id and not factory:
        raise HTTPException(404, "Usine introuvable")
    message = build_rfq_message(
        factory["company"] if factory else "",
        payload.product_query,
        payload.quantities,
        payload.specifications,
    )
    rfq_id = save_rfq({**payload.model_dump(), "message": message})
    return {"id": rfq_id, "message": message, "status": "BROUILLON", "sent": False}


@router.delete("/rfqs/{rfq_id}")
def remove_rfq(rfq_id: int):
    if not delete_rfq(rfq_id):
        raise HTTPException(404, "Brouillon RFQ introuvable")
    return {"deleted": True}
