import re
from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.config import get_settings
from app.services.cj import CJClient, CJError
from app.services.cj_landed import load_cj_product_link
from app.services.db import (
    delete_product,
    get_product,
    list_cj_candidates,
    list_products,
    list_suppliers,
    save_listing,
    set_product_fields,
    upsert_product,
)
from app.services.profit import calculate_profit, suggest_price
from app.services.risk import assess_product
from app.services.scoring import calculate_product_score
from app.services.supplier_refresh import is_verified_cj_product

router = APIRouter(prefix="/api/products", tags=["Products"])


def _active_cj_product(product: dict, suppliers: dict[int, dict] | None = None) -> bool:
    supplier_map = suppliers or {row["id"]: row for row in list_suppliers()}
    supplier = supplier_map.get(product.get("supplier_id"))
    return is_verified_cj_product(product, supplier)


def _fee_model() -> dict:
    s = get_settings()
    return {
        "ebay_fee_percent": s.default_ebay_fee_percent,
        "promoted_listings_percent": s.default_ad_rate_percent,
        "return_reserve_percent": s.default_return_reserve_percent,
        "order_fee_low": s.ebay_low_order_fee,
        "order_fee_standard": s.ebay_standard_order_fee,
        "currency": "USD",
    }


def _with_live_scores(product: dict, suppliers: dict[int, dict] | None = None) -> dict:
    supplier_map = suppliers or {row["id"]: row for row in list_suppliers()}
    supplier = supplier_map.get(product.get("supplier_id"))
    return {
        **product,
        "risk": assess_product(product, supplier),
        "product_score": calculate_product_score(product, supplier),
        "profit": calculate_profit(product),
        "fee_model": _fee_model(),
    }


def _normalized_title(value: str) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", str(value or "").lower()))


def _duplicate_product_for_title(title: str, product_id: int) -> dict | None:
    normalized = _normalized_title(title)
    if not normalized:
        return None
    return next(
        (
            row for row in list_products()
            if int(row.get("id") or 0) != product_id
            and _active_cj_product(row)
            and _normalized_title(row.get("title") or "") == normalized
        ),
        None,
    )


def _candidate_for_pid(pid: str) -> dict | None:
    clean = str(pid or "").strip()
    if not clean:
        return None
    return next((row for row in list_cj_candidates() if str(row.get("cj_pid") or "") == clean), None)


async def _verified_product_identity(product: dict) -> dict:
    """Recover the immutable CJ identity instead of reusing an already-SEO'd title."""
    link = load_cj_product_link(str(product.get("supplier_sku") or ""))
    pid = str(link.get("pid") or "").strip()
    variant_id = str(link.get("variant_id") or "").strip()
    candidate = _candidate_for_pid(pid)
    analysis = (candidate or {}).get("analysis") or {}

    source_title = str((candidate or {}).get("name") or analysis.get("product_name") or "").strip()
    variant_name = str(analysis.get("variant_name") or "").strip()
    category_name = str((candidate or {}).get("category_name") or analysis.get("category_name") or "").strip()
    identity_source = "CJ candidate" if source_title else "catalog"

    # Old v0.25 records did not persist variant/product identity in the analysis.
    # When possible, repair it from CJ live data. This is especially important if
    # two catalogue rows have already been overwritten by the same SEO title.
    current_is_duplicate = _duplicate_product_for_title(str(product.get("title") or ""), int(product["id"])) is not None
    client = CJClient()
    should_refresh = bool(
        pid
        and client.status().get("connected")
        and (not source_title or not variant_name or not category_name or current_is_duplicate)
    )
    if should_refresh:
        try:
            detail = await client.product_detail(pid)
            source_title = str(detail.get("name") or source_title).strip()
            category_name = str(detail.get("category_name") or category_name).strip()
            if variant_id:
                variant = next(
                    (row for row in detail.get("variants") or [] if str(row.get("vid") or "") == variant_id),
                    None,
                )
                if variant:
                    variant_name = str(variant.get("name") or variant_name).strip()
            identity_source = "CJ live"
        except CJError:
            # Candidate identity is still safer than the mutable optimized title.
            pass

    if not source_title:
        source_title = str(product.get("title") or "").strip()

    return {
        "source_title": source_title,
        "variant_name": variant_name,
        "category_name": category_name,
        "identity_source": identity_source,
        "cj_pid": pid,
    }


class ProductIn(BaseModel):
    supplier_sku: str = Field(min_length=1, max_length=50)
    title: str = Field(min_length=1, max_length=200)
    description: str = ""
    supplier_cost: float = Field(ge=0)
    shipping_cost: float = Field(default=0, ge=0)
    stock: int = Field(default=0, ge=0)
    shipping_days: int = Field(default=0, ge=0)
    target_price: float | None = Field(default=None, gt=0)
    category_id: str | None = None
    condition: str = "NEW"
    marketplace_id: Literal["EBAY_US"] | None = None
    currency: Literal["USD"] | None = None
    images: list[str] = Field(default_factory=list)
    aspects: dict[str, list[str]] = Field(default_factory=dict)
    supplier_id: int | None = None
    product_status: str = "À tester"


class SeoOptimizeIn(BaseModel):
    market_keywords: list[str] = Field(default_factory=list, max_length=12)


@router.get("")
def products():
    suppliers = {row["id"]: row for row in list_suppliers()}
    return [_with_live_scores(p, suppliers) for p in list_products() if _active_cj_product(p, suppliers)]


@router.put("/{product_id}")
def update_product(product_id: int, payload: ProductIn):
    existing = get_product(product_id)
    if not existing:
        raise HTTPException(404, "Product not found")
    if not _active_cj_product(existing):
        raise HTTPException(410, "Produit hors flux CJ vérifié")
    data = payload.model_dump()
    data["supplier_sku"] = existing["supplier_sku"]
    data["supplier_id"] = existing["supplier_id"]
    data["marketplace_id"] = "EBAY_US"
    data["currency"] = "USD"
    pid = upsert_product(data)
    product = get_product(pid)
    scored = _with_live_scores(product)
    return {"product": product, "risk": scored["risk"], "product_score": scored["product_score"]}


@router.delete("/{product_id}")
def remove_product(product_id: int):
    if not delete_product(product_id):
        raise HTTPException(404, "Product not found")
    return {"deleted": True}


class StatusIn(BaseModel):
    status: str


@router.patch("/{product_id}/status")
def change_status(product_id: int, payload: StatusIn):
    if payload.status not in {"À tester", "Winner", "Rejeté"}:
        raise HTTPException(400, "Statut invalide")
    product = get_product(product_id)
    if not product:
        raise HTTPException(404, "Product not found")
    if not _active_cj_product(product):
        raise HTTPException(410, "Produit hors flux CJ vérifié")
    if not set_product_fields(product_id, product_status=payload.status):
        raise HTTPException(404, "Product not found")
    return get_product(product_id)


@router.post("/{product_id}/suggest-price")
def price_suggestion(product_id: int):
    product = get_product(product_id)
    if not product:
        raise HTTPException(404, "Product not found")
    if not _active_cj_product(product):
        raise HTTPException(409, "Ce produit n'appartient pas au flux CJ vérifié pour eBay US / USD.")
    shipping_days = int(product.get("shipping_days") or 0)
    if shipping_days <= 0 or shipping_days >= 99:
        raise HTTPException(400, "Impossible de calculer un prix fiable tant que la livraison US n'est pas confirmée.")
    risk = assess_product(product)
    requirements = (risk.get("route") or {}).get("requirements") or {}
    result = suggest_price(
        product,
        min_margin_percent=float(requirements.get("min_margin_percent") or get_settings().min_margin_percent),
        min_profit=float(requirements.get("min_profit") or get_settings().min_profit_amount),
    )
    set_product_fields(product_id, suggested_price=result["suggested_price"], target_price=result["suggested_price"])
    return result


@router.get("/{product_id}/margin")
def margin_simulator(product_id: int, sale_price: float | None = None):
    product = get_product(product_id)
    if not product:
        raise HTTPException(404, "Product not found")
    if not _active_cj_product(product):
        raise HTTPException(409, "Simulateur disponible uniquement pour le flux CJ vers eBay US / USD")
    return {
        "profit": calculate_profit(product, sale_price),
        "fee_model": _fee_model(),
        "marketplace": "EBAY_US",
        "currency": "USD",
        "includes": ["CJ product", "CJ shipping", "eBay final value fee", "Promoted Listings reserve", "returns reserve", "per-order fee"],
    }


@router.post("/{product_id}/optimize-ebay")
async def optimize_ebay(product_id: int, payload: SeoOptimizeIn):
    from app.services.listing_generator import generate_description, optimize_title

    product = get_product(product_id)
    if not product:
        raise HTTPException(404, "Product not found")
    if not _active_cj_product(product):
        raise HTTPException(409, "SEO disponible uniquement pour le flux CJ vers eBay US / USD")

    identity = await _verified_product_identity(product)
    keywords = [str(value).strip() for value in payload.market_keywords if str(value).strip()]
    optimized = optimize_title(
        identity["source_title"],
        market_keywords=keywords,
        variant_name=identity["variant_name"],
        category_name=identity["category_name"],
        aspects=product.get("aspects") or {},
    )

    duplicate = _duplicate_product_for_title(optimized, product_id)
    if duplicate:
        # Retry without any market hint. If two genuinely different products still
        # collapse to the same title, do not silently publish a duplicate identity.
        optimized = optimize_title(
            identity["source_title"],
            market_keywords=[],
            variant_name=identity["variant_name"],
            category_name=identity["category_name"],
            aspects=product.get("aspects") or {},
        )
        duplicate = _duplicate_product_for_title(optimized, product_id)
    if duplicate:
        raise HTTPException(
            409,
            "Le titre généré serait identique à un autre produit du catalogue. "
            "Vérifiez la variante CJ ou ajoutez une caractéristique distinctive avant de continuer.",
        )

    data = dict(product)
    previous_title = str(product.get("title") or "")
    data["title"] = optimized
    data["description"] = generate_description({**product, "title": optimized})
    for key in ("id", "created_at", "updated_at", "previous_supplier_cost"):
        data.pop(key, None)
    pid = upsert_product(data)
    out = _with_live_scores(get_product(pid))
    return {
        "product": out,
        "optimized_title": optimized,
        "previous_title": previous_title,
        "source_title": identity["source_title"],
        "variant_name": identity["variant_name"],
        "identity_source": identity["identity_source"],
        "repaired_from_cj": _normalized_title(previous_title) != _normalized_title(identity["source_title"]),
        "market_keywords": keywords,
        "keyword_source": "eBay US relevant query only",
        "duplicate_guard": True,
        "note": "L'identité CJ reste prioritaire ; aucun titre concurrent complet n'est copié.",
    }


@router.post("/{product_id}/prepare-ebay")
def prepare_ebay(product_id: int):
    product = get_product(product_id)
    if not product:
        raise HTTPException(404, "Product not found")
    if not _active_cj_product(product):
        raise HTTPException(409, "Seuls les produits CJ vérifiés pour eBay US / USD peuvent être préparés.")
    risk = assess_product(product)
    if not risk["pass"]:
        raise HTTPException(400, "Le Risk Engine bloque cette préparation : " + " ; ".join(risk["blocks"]))
    listing_id = save_listing(product_id, None, None, "PREPARED_DRY_RUN", product["target_price"], product["stock"])
    return {
        "prepared": True,
        "dry_run": True,
        "listing_id": listing_id,
        "marketplace": "EBAY_US",
        "currency": "USD",
        "message": "Brouillon eBay US préparé localement. Aucune donnée envoyée à eBay.",
    }


@router.get("/opportunities/inbox")
def opportunity_inbox():
    return {
        "themes": [],
        "cj_candidates": list_cj_candidates()[:12],
        "supplier_count": 1,
        "measured_only": True,
        "note": "Utilisez Radar eBay US puis CJ Dropshipping.",
    }


@router.get("/{product_id}")
def product(product_id: int):
    p = get_product(product_id)
    if not p:
        raise HTTPException(404, "Product not found")
    if not _active_cj_product(p):
        raise HTTPException(410, "Produit hors flux CJ vérifié pour eBay US / USD")
    return _with_live_scores(p)


@router.post("/{product_id}/generate-listing")
async def generate_listing(product_id: int):
    return await optimize_ebay(product_id, SeoOptimizeIn())
