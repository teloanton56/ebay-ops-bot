import asyncio

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from app.services.cj import CJClient, CJError
from app.services.connections import (IntegrationError, YouTubeClient, connection_status,
                                      match_connected_suppliers)
from app.services.db import (delete_factory_lead, delete_radar_watch, list_factory_leads, list_radar_scans,
                             delete_rfq, list_radar_watchlist, list_rfqs, list_trend_discoveries,
                             save_factory_lead, save_radar_watch, save_rfq)
from app.services.radar import (MARKETPLACES, analyze_ebay_market, build_rfq_message,
                                source_statuses)


router = APIRouter(prefix="/api/radar", tags=["Radar 360"])


class WatchIn(BaseModel):
    keyword: str = Field(min_length=2, max_length=120)
    notes: str = Field(default="", max_length=500)


class ScanIn(BaseModel):
    keyword: str = Field(min_length=2, max_length=120)
    marketplaces: list[str] = Field(min_length=1, max_length=6)


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
    country: str = Field(default="FR", min_length=2, max_length=2)


@router.get("/sources")
def radar_sources():
    return source_statuses()


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
    return list_radar_scans()


@router.get("/discoveries")
def discoveries():
    return list_trend_discoveries()


@router.post("/discover")
async def discover_without_keyword(payload: DiscoveryIn):
    status = connection_status("youtube")
    if not status["connected"]:
        raise HTTPException(400, "Connectez et testez YouTube pour lancer la détection automatique sans mot-clé.")
    try:
        return await YouTubeClient().discover(payload.country.upper())
    except IntegrationError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.post("/scan")
async def run_radar_scan(payload: ScanIn):
    invalid = [market for market in payload.marketplaces if market not in MARKETPLACES]
    if invalid:
        raise HTTPException(400, "Marketplace non prise en charge : " + ", ".join(invalid))
    ebay = next(x for x in source_statuses() if x["id"] == "ebay")
    if not ebay["ready"]:
        raise HTTPException(400, "Les clés eBay Production sont nécessaires pour analyser la demande réelle. Aucun résultat Sandbox n'est utilisé.")
    results = await asyncio.gather(*(analyze_ebay_market(payload.keyword, market)
                                     for market in payload.marketplaces), return_exceptions=True)
    markets, errors = [], []
    for market, result in zip(payload.marketplaces, results):
        if isinstance(result, Exception):
            errors.append({"marketplace": market, "message": str(result)})
        else:
            markets.append(result)
    if not markets and errors:
        raise HTTPException(400, errors[0]["message"])
    return {"keyword": payload.keyword, "markets": markets, "errors": errors,
            "measured_only": True, "note": "Les conversions concurrentes et volumes de recherche non publics restent indisponibles."}


@router.get("/supplier-match")
async def supplier_match(q: str = Query(min_length=2, max_length=120)):
    if len(q.strip()) < 2:
        raise HTTPException(400, "Mot-clé trop court")
    groups, errors = await match_connected_suppliers(q.strip())
    try:
        cj_status = CJClient().status()
        if cj_status.get("configured"):
            result = await CJClient().search_products(keyword=q.strip(), size=12, min_stock=3)
            for product in result["products"]:
                product["provider"] = "CJ"
                product["quality_evidence"] = [x for x in ["CE déclaré" if product.get("has_ce") else None,
                                                            f"Stock observé : {product.get('stock', 0)}",
                                                            f"Présence CJ : {product.get('listed_num', 0)} listings"] if x]
                product["quality_verified"] = False
            groups.insert(0, {"source": "CJ", "products": result["products"], "total": result["total"],
                              "note": "Prix produit CJ avant transport; analyse France disponible après sélection."})
    except (CJError, RuntimeError) as exc:
        errors.append({"source": "CJ", "message": str(exc)})
    if not groups:
        message = errors[0]["message"] if errors else "Connectez CJ, DropXL ou un fournisseur POD avant de comparer les offres"
        raise HTTPException(400, message)
    return {"groups": groups, "errors": errors, "measured_only": True,
            "note": "La qualité doit toujours être confirmée par un échantillon et des documents de conformité."}


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
    message = build_rfq_message(factory["company"] if factory else "", payload.product_query,
                                payload.quantities, payload.specifications)
    rfq_id = save_rfq({**payload.model_dump(), "message": message})
    return {"id": rfq_id, "message": message, "status": "BROUILLON",
            "sent": False, "notice": "Aucun message n'a été envoyé."}


@router.delete("/rfqs/{rfq_id}")
def remove_rfq(rfq_id: int):
    if not delete_rfq(rfq_id):
        raise HTTPException(404, "Brouillon RFQ introuvable")
    return {"deleted": True}
