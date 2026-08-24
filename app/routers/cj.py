from typing import Literal

from cryptography.fernet import Fernet
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.config import get_settings
from app.routers.settings import _read_env, _write_env
from app.services.cj import CJClient, CJError
from app.services.cj_landed import (
    resolve_cj_landed_offer,
    route_requirements,
    save_cj_product_link,
)
from app.services.db import (
    delete_cj_candidate,
    ensure_provider_supplier,
    get_cj_candidate,
    list_cj_candidates,
    save_cj_candidate,
    save_cj_candidate_analysis,
    upsert_product,
)
from app.services.profit import suggest_price
from app.services.supplier_relevance import rank_supplier_results

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
    vid: str = ""
    destination_country: Literal["US"] = "US"
    postcode: str = Field(default="", max_length=12)


def _ensure_encryption_key() -> None:
    if get_settings().app_encryption_key:
        return
    current = _read_env()
    _write_env({"APP_ENCRYPTION_KEY": current.get("APP_ENCRYPTION_KEY") or Fernet.generate_key().decode()})


@router.get("/settings")
def cj_settings():
    return {**CJClient().status(), "operating_mode": "US_FIRST_CN_FALLBACK", "currency": "USD"}


@router.post("/settings")
async def save_cj_settings(payload: CJKeyIn):
    _ensure_encryption_key()
    client = CJClient()
    client.save_api_key(payload.api_key)
    try:
        result = await client.test_connection()
    except CJError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {**result, "message": "CJ connecté. Mode actif : entrepôt US prioritaire, Chine en fallback rentable."}


@router.post("/test")
async def test_cj():
    try:
        return await CJClient().test_connection()
    except CJError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.get("/warehouses")
async def cj_warehouses():
    try:
        rows = await CJClient().warehouses()
        return [row for row in rows if str(row.get("country_code") or "").upper() in {"US", "CN"}]
    except CJError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.get("/categories")
async def cj_categories():
    try:
        return await CJClient().categories()
    except CJError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.get("/products")
async def cj_products(
    q: str = "",
    page: int = 1,
    size: int = 20,
    category_id: str = "",
    country_code: str = "",
    min_price: float | None = None,
    max_price: float | None = None,
    min_stock: int = 1,
    order_by: int = 0,
):
    # Search globally so products with either US or CN stock can be discovered;
    # exact route stock is verified by cj_landed before margin decisions.
    if country_code and country_code.upper() not in {"US", "CN"}:
        raise HTTPException(400, "Le mode actif autorise uniquement les entrepôts CJ US et CN")
    try:
        requested_size = min(max(size, 1), 50)
        clean_query = q.strip()
        search_size = min(max(requested_size * 3, 50), 100) if clean_query else requested_size
        result = await CJClient().search_products(
            keyword=clean_query,
            page=min(max(page, 1), 1000),
            size=search_size,
            category_id=category_id,
            country_code=country_code.upper() if country_code else "",
            min_price=min_price,
            max_price=max_price,
            min_stock=max(min_stock, 0),
            order_by=order_by,
        )
        if not clean_query:
            return {**result, "currency": "USD", "destination_country": "US"}
        raw_products = result.get("products") or []
        relevant, rejected = rank_supplier_results(
            clean_query,
            raw_products,
            title_keys=("name",),
            limit=requested_size,
        )
        result.update({
            "raw_total": result.get("total"),
            "products": relevant,
            "total": len(relevant),
            "total_pages": 1,
            "filtered_out": rejected,
            "relevance_filtered": True,
            "currency": "USD",
            "destination_country": "US",
            "note": f"{rejected} résultat(s) hors sujet ignoré(s)." if rejected else "Résultats CJ triés par pertinence.",
        })
        return result
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
    return {"selected": True, "candidate_id": candidate_id, "message": "Produit CJ sélectionné. Route US/CN à calculer avant ajout."}


@router.post("/candidates/{candidate_id}/analyze")
async def analyze_candidate(candidate_id: int, payload: CJAnalyzeIn):
    candidate = get_cj_candidate(candidate_id)
    if not candidate:
        raise HTTPException(404, "Sélection CJ introuvable")
    client = CJClient()
    try:
        landed = await resolve_cj_landed_offer(
            client,
            candidate["cj_pid"],
            fallback_price_usd=float(candidate.get("price_usd") or 0),
            preferred_variant_id=payload.vid,
            destination_country="US",
        )
        requirements = route_requirements(str(landed.get("warehouse") or "US"))
        pricing = suggest_price(
            {"supplier_cost": landed["supplier_cost"], "shipping_cost": landed["shipping_cost"]},
            min_margin_percent=float(requirements["min_margin_percent"]),
            min_profit=float(requirements["min_profit"]),
        )
        analysis = {
            "product_name": landed.get("product_name") or candidate.get("name") or "Produit CJ",
            "variant_name": landed.get("variant_name") or "",
            "category_name": candidate.get("category_name") or "",
            "image_url": landed.get("image_url") or candidate.get("image_url") or "",
            "variant_id": landed["variant_id"],
            "variant_sku": landed["variant_sku"],
            "verified_stock": int(landed.get("stock") or 0),
            "source_country": landed["warehouse"],
            "destination_country": "US",
            "shipping": {
                "name": landed["freight_name"],
                "price_usd": landed["shipping_cost"],
                "delivery_days": f"{landed['shipping_days']} days",
            },
            "supplier_cost_usd": landed["supplier_cost"],
            "shipping_cost_usd": landed["shipping_cost"],
            "landed_cost_usd": landed["landed_cost"],
            "suggested_price_usd": pricing["suggested_price"],
            "minimum_viable_price_usd": pricing["minimum_viable_price"],
            "estimated_profit_usd": pricing["profit"]["estimated_profit"],
            "margin_percent": pricing["profit"]["margin_percent"],
            "roi_percent": pricing["profit"]["roi_percent"],
            "requirements": requirements,
            "route": "CJ US" if landed["warehouse"] == "US" else "CJ China → US",
            "currency": "USD",
            "dry_run": True,
        }
        save_cj_candidate_analysis(candidate_id, analysis, landed.get("risk_flags") or [])
        return {"candidate": get_cj_candidate(candidate_id), "analysis": analysis,
                "message": "Coût livré US calculé en USD. Aucune commande ni annonce créée."}
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
    if (
        analysis.get("landed_cost_usd") is None
        or str(analysis.get("destination_country") or "").upper() != "US"
        or str(analysis.get("currency") or "").upper() != "USD"
        or str(analysis.get("source_country") or "").upper() not in {"US", "CN"}
        or not str(analysis.get("variant_id") or "").strip()
    ):
        raise HTTPException(400, "Analysez d'abord le coût livré vers les États-Unis.")

    supplier_id = ensure_provider_supplier("cj", "CJ Dropshipping", "US")
    sku = str(analysis.get("variant_sku") or candidate.get("sku") or f"CJ-{candidate['cj_pid']}")[:50]
    warehouse = str(analysis.get("source_country") or "").upper()
    source_title = str(analysis.get("product_name") or candidate.get("name") or "Produit CJ").strip()
    source_image = str(analysis.get("image_url") or candidate.get("image_url") or "").strip()
    product_id = upsert_product({
        "supplier_sku": sku,
        "title": source_title,
        "description": f"CJ Dropshipping · {'US warehouse' if warehouse == 'US' else 'China → US'}. Données revalidées avant publication.",
        "supplier_cost": float(analysis.get("supplier_cost_usd") or 0),
        "shipping_cost": float(analysis.get("shipping_cost_usd") or 0),
        "stock": int(analysis.get("verified_stock") or candidate.get("stock") or 0),
        "shipping_days": int(str((analysis.get("shipping") or {}).get("delivery_days") or "0").split()[0] or 0),
        "target_price": analysis.get("suggested_price_usd"),
        "marketplace_id": "EBAY_US",
        "currency": "USD",
        "images": [source_image] if source_image else [],
        "aspects": {},
        "supplier_id": supplier_id,
        "product_status": "À tester",
        "suggested_price": analysis.get("suggested_price_usd"),
    })
    save_cj_product_link(sku, {
        "pid": candidate["cj_pid"],
        "variant_id": analysis.get("variant_id") or "",
        "warehouse": warehouse,
        "destination_country": "US",
        "currency": "USD",
        "risk_flags": candidate.get("risk_flags") or [],
    })
    return {"created": True, "product_id": product_id, "dry_run": True,
            "message": "Produit CJ ajouté au catalogue eBay US en USD."}
