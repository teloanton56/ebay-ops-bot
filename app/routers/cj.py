import re

from cryptography.fernet import Fernet
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.config import get_settings
from app.routers.settings import _read_env, _write_env
from app.services.cj import CJClient, CJError
from app.services.db import (delete_cj_candidate, get_cj_candidate, list_cj_candidates,
                             ensure_provider_supplier, save_cj_candidate, save_cj_candidate_analysis,
                             upsert_product)
from app.services.profit import suggest_price

router = APIRouter(prefix="/api/cj", tags=["CJ Dropshipping"])


class CJKeyIn(BaseModel):
    api_key: str = Field(min_length=10, max_length=300)


class CJCandidateIn(BaseModel):
    cj_pid: str
    sku: str = ""
    name: str
    image_url: str = ""
    price_usd: float = 0
    category_name: str = ""
    stock: int = 0
    warehouse_country: str = ""
    delivery_cycle: str = ""


class CJAnalyzeIn(BaseModel):
    vid: str
    destination_country: str = Field(default="FR", min_length=2, max_length=2)
    postcode: str = Field(default="", max_length=12)


def _ensure_encryption_key() -> None:
    if get_settings().app_encryption_key:
        return
    current = _read_env()
    _write_env({"APP_ENCRYPTION_KEY": current.get("APP_ENCRYPTION_KEY") or Fernet.generate_key().decode()})


@router.get("/settings")
def cj_settings():
    return CJClient().status()


@router.post("/settings")
async def save_cj_settings(payload: CJKeyIn):
    _ensure_encryption_key()
    client = CJClient()
    client.save_api_key(payload.api_key)
    try:
        result = await client.test_connection()
    except CJError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {**result, "message": "CJ est connecté en lecture seule."}


@router.post("/test")
async def test_cj():
    try:
        return await CJClient().test_connection()
    except CJError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.get("/warehouses")
async def cj_warehouses():
    try:
        return await CJClient().warehouses()
    except CJError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.get("/categories")
async def cj_categories():
    try:
        return await CJClient().categories()
    except CJError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.get("/products")
async def cj_products(q: str = "", page: int = 1, size: int = 20, category_id: str = "",
                      country_code: str = "", min_price: float | None = None, max_price: float | None = None,
                      min_stock: int = 1, order_by: int = 0):
    try:
        return await CJClient().search_products(keyword=q, page=min(max(page, 1), 1000), size=min(max(size, 1), 50),
                                                category_id=category_id, country_code=country_code,
                                                min_price=min_price, max_price=max_price,
                                                min_stock=max(min_stock, 0), order_by=order_by)
    except CJError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.get("/products/{pid}/details")
async def cj_product_details(pid: str):
    try:
        return await CJClient().product_detail(pid)
    except CJError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.get("/candidates")
def candidates():
    return list_cj_candidates()


@router.post("/candidates")
def select_candidate(payload: CJCandidateIn):
    candidate_id = save_cj_candidate(payload.model_dump())
    return {"selected": True, "candidate_id": candidate_id,
            "message": "Produit ajouté à la sélection CJ. Aucun listing créé."}


@router.post("/candidates/{candidate_id}/analyze")
async def analyze_candidate(candidate_id: int, payload: CJAnalyzeIn):
    candidate = get_cj_candidate(candidate_id)
    if not candidate:
        raise HTTPException(404, "Sélection CJ introuvable")
    client = CJClient()
    try:
        detail = await client.product_detail(candidate["cj_pid"])
        variant = next((x for x in detail["variants"] if x["vid"] == payload.vid), None)
        if not variant:
            raise CJError("Cette variante CJ n'est plus disponible")
        stocked = [x for x in variant.get("inventories", []) if x.get("stock", 0) > 0]
        destination = payload.destination_country.upper()
        source = next((x["country_code"] for x in stocked if x.get("country_code") == destination), None)
        source = source or next((x["country_code"] for x in stocked if x.get("country_code") == "CN"), None)
        source = source or (stocked[0].get("country_code") if stocked else "CN")
        freight = await client.freight_options(variant["vid"], start_country=source,
                                               destination_country=destination, postcode=payload.postcode)
        if not freight:
            raise CJError("CJ ne propose aucun transport pour cette variante vers la France")
        exchange = await client.usd_to_eur()
        chosen = freight[0]
        supplier_eur = round(variant["price_usd"] * exchange["rate"], 2)
        shipping_eur = round(chosen["price_usd"] * exchange["rate"], 2)
        pricing = suggest_price({"supplier_cost": supplier_eur, "shipping_cost": shipping_eur})
        analysis = {
            "variant": variant,
            "source_country": source,
            "destination_country": destination,
            "postcode": payload.postcode,
            "shipping": chosen,
            "shipping_alternatives": freight[:5],
            "shipping_methods_found": len(freight),
            "exchange": exchange,
            "supplier_cost_eur": supplier_eur,
            "shipping_cost_eur": shipping_eur,
            "landed_cost_eur": round(supplier_eur + shipping_eur, 2),
            "suggested_price_eur": pricing["suggested_price"],
            "minimum_viable_price_eur": pricing["minimum_viable_price"],
            "estimated_profit_eur": pricing["profit"]["estimated_profit"],
            "margin_percent": pricing["profit"]["margin_percent"],
            "roi_percent": pricing["profit"]["roi_percent"],
            "fees_included": True,
            "market_price_checked": False,
            "dry_run": True,
        }
        save_cj_candidate_analysis(candidate_id, analysis, detail["risk_flags"])
        return {"candidate": get_cj_candidate(candidate_id), "detail": detail,
                "message": "Analyse calculée en Dry-run. Aucune commande ni annonce créée."}
    except CJError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.delete("/candidates/{candidate_id}")
def unselect_candidate(candidate_id: int):
    if not delete_cj_candidate(candidate_id):
        raise HTTPException(404, "Sélection introuvable")
    return {"deleted": True}


@router.post("/candidates/{candidate_id}/add-product")
def candidate_to_product(candidate_id: int):
    candidate = get_cj_candidate(candidate_id)
    if not candidate:
        raise HTTPException(404, "Sélection CJ introuvable")
    analysis = candidate.get("analysis") or {}
    if analysis.get("landed_cost_eur") is None:
        raise HTTPException(400, "Analysez d'abord le transport et la marge de ce produit CJ.")
    supplier_id = ensure_provider_supplier("cj", "CJ Dropshipping", "CN")
    delivery_text = str((analysis.get("shipping") or {}).get("delivery_days") or "")
    delivery_values = [int(value) for value in re.findall(r"\d+", delivery_text)]
    variant = analysis.get("variant") or {}
    sku = str(variant.get("sku") or candidate.get("sku") or f"CJ-{candidate['cj_pid']}")[:50]
    product_id = upsert_product({
        "supplier_sku": sku,
        "title": candidate["name"],
        "description": f"Produit CJ {candidate.get('category_name', '')}. Données fournisseur à vérifier avant publication.",
        "supplier_cost": float(analysis.get("supplier_cost_eur") or candidate.get("price_usd") or 0),
        "shipping_cost": float(analysis.get("shipping_cost_eur") or 0),
        "stock": int(variant.get("stock") or candidate.get("stock") or 0),
        "shipping_days": max(delivery_values, default=0),
        "target_price": analysis.get("suggested_price_eur"),
        "marketplace_id": "EBAY_FR",
        "currency": "EUR",
        "images": [candidate["image_url"]] if candidate.get("image_url") else [],
        "aspects": {},
        "supplier_id": supplier_id,
        "product_status": "À tester",
        "suggested_price": analysis.get("suggested_price_eur"),
    })
    return {"created": True, "product_id": product_id, "dry_run": True,
            "message": "Produit ajouté au catalogue local. Aucune annonce eBay créée."}
