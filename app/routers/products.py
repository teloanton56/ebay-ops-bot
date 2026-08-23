import csv
import io
import json
from typing import Any

from fastapi import APIRouter, File, HTTPException, UploadFile
from pydantic import BaseModel, Field

from app.config import get_settings
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

router = APIRouter(prefix="/api/products", tags=["Products"])


def _active_us_product(product: dict) -> bool:
    return (
        (product.get("marketplace_id") or "") == "EBAY_US"
        and (product.get("currency") or "") == "USD"
    )


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


def _import_csv_text(text: str, supplier_id: int | None = None):
    sample = text[:4096]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t")
    except csv.Error:
        dialect = csv.excel
    reader = csv.DictReader(io.StringIO(text), dialect=dialect)
    required = {"supplier_sku", "title", "supplier_cost"}
    if not reader.fieldnames or not required.issubset(set(reader.fieldnames)):
        raise HTTPException(400, f"CSV must include: {sorted(required)}")

    ids: list[int] = []
    errors: list[dict[str, Any]] = []
    for idx, row in enumerate(reader, start=2):
        try:
            def fnum(name, default=0.0):
                value = (row.get(name) or "").strip()
                return float(value.replace(",", ".")) if value else default

            def fint(name, default=0):
                value = (row.get(name) or "").strip()
                return int(float(value)) if value else default

            images = [x.strip() for x in (row.get("images") or "").split("|") if x.strip()]
            aspects = json.loads(row.get("aspects_json") or "{}")
            data = {
                "supplier_sku": row["supplier_sku"].strip(),
                "title": row["title"].strip(),
                "description": row.get("description") or "",
                "supplier_cost": fnum("supplier_cost"),
                "shipping_cost": fnum("shipping_cost"),
                "stock": fint("stock"),
                "shipping_days": fint("shipping_days"),
                "target_price": fnum("target_price", None) if (row.get("target_price") or "").strip() else None,
                "category_id": (row.get("category_id") or "").strip() or None,
                "condition": (row.get("condition") or "NEW").strip(),
                "marketplace_id": "EBAY_US",
                "currency": "USD",
                "images": images,
                "aspects": aspects,
                "supplier_id": supplier_id,
                "product_status": (row.get("product_status") or "À tester").strip(),
            }
            ids.append(upsert_product(data))
        except Exception as exc:
            errors.append({"line": idx, "error": str(exc)})
    return {"imported": len(ids), "product_ids": ids, "errors": errors, "marketplace": "EBAY_US", "currency": "USD"}


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
    marketplace_id: str | None = None
    currency: str | None = None
    images: list[str] = Field(default_factory=list)
    aspects: dict[str, list[str]] = Field(default_factory=dict)
    supplier_id: int | None = None
    product_status: str = "À tester"


class SupplierOfferIn(BaseModel):
    provider: str = Field(min_length=2, max_length=40)
    supplier_sku: str = Field(min_length=1, max_length=80)
    name: str = Field(min_length=1, max_length=250)
    price: float = Field(ge=0)
    shipping_cost: float = Field(default=0, ge=0)
    currency: str = Field(default="USD", min_length=3, max_length=3)
    stock: int | None = Field(default=None, ge=0)
    shipping_days: int | None = Field(default=None, ge=0)
    image_url: str = Field(default="", max_length=1000)


class SeoOptimizeIn(BaseModel):
    market_keywords: list[str] = Field(default_factory=list, max_length=12)


@router.get("")
def products():
    suppliers = {row["id"]: row for row in list_suppliers()}
    return [_with_live_scores(p, suppliers) for p in list_products() if _active_us_product(p)]


@router.post("")
def create_product(payload: ProductIn):
    data = payload.model_dump()
    data["marketplace_id"] = "EBAY_US"
    data["currency"] = "USD"
    product_id = upsert_product(data)
    product = get_product(product_id)
    scored = _with_live_scores(product)
    return {"product": product, "risk": scored["risk"], "product_score": scored["product_score"]}


@router.post("/from-supplier-offer")
def create_from_supplier_offer(_: SupplierOfferIn):
    raise HTTPException(
        410,
        "v0.25 utilise uniquement le flux CJ vérifié. Ajoutez le produit depuis Radar US / CJ.",
    )


@router.put("/{product_id}")
def update_product(product_id: int, payload: ProductIn):
    existing = get_product(product_id)
    if not existing:
        raise HTTPException(404, "Product not found")
    data = payload.model_dump()
    data["supplier_sku"] = existing["supplier_sku"]
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
    if not set_product_fields(product_id, product_status=payload.status):
        raise HTTPException(404, "Product not found")
    return get_product(product_id)


@router.post("/{product_id}/suggest-price")
def price_suggestion(product_id: int):
    product = get_product(product_id)
    if not product:
        raise HTTPException(404, "Product not found")
    if not _active_us_product(product):
        raise HTTPException(409, "Ce produit appartient à l'ancien catalogue. Re-sourcer en eBay US / USD.")
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
    if not _active_us_product(product):
        raise HTTPException(409, "Simulateur disponible uniquement pour eBay US / USD")
    return {
        "profit": calculate_profit(product, sale_price),
        "fee_model": _fee_model(),
        "marketplace": "EBAY_US",
        "currency": "USD",
        "includes": ["CJ product", "CJ shipping", "eBay final value fee", "Promoted Listings reserve", "returns reserve", "per-order fee"],
    }


@router.post("/{product_id}/optimize-ebay")
def optimize_ebay(product_id: int, payload: SeoOptimizeIn):
    from app.services.listing_generator import generate_description, optimize_title

    product = get_product(product_id)
    if not product:
        raise HTTPException(404, "Product not found")
    if not _active_us_product(product):
        raise HTTPException(409, "SEO disponible uniquement pour eBay US / USD")
    keywords = [str(value).strip() for value in payload.market_keywords if str(value).strip()]
    optimized = optimize_title(product["title"], market_keywords=keywords)
    data = dict(product)
    data["title"] = optimized
    data["description"] = generate_description({**product, "title": optimized})
    for key in ("id", "created_at", "updated_at", "previous_supplier_cost"):
        data.pop(key, None)
    pid = upsert_product(data)
    out = _with_live_scores(get_product(pid))
    return {
        "product": out,
        "optimized_title": optimized,
        "market_keywords": keywords,
        "keyword_source": "eBay US observed/relevant terms",
        "note": "Le bot n'invente pas de volume de recherche exact.",
    }


@router.post("/{product_id}/prepare-ebay")
def prepare_ebay(product_id: int):
    product = get_product(product_id)
    if not product:
        raise HTTPException(404, "Product not found")
    if not _active_us_product(product):
        raise HTTPException(409, "Seuls les produits eBay US / USD peuvent être préparés dans v0.25.")
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
    if not _active_us_product(p):
        raise HTTPException(410, "Produit legacy hors mode eBay US / USD")
    return _with_live_scores(p)


@router.post("/import-csv")
async def import_csv(file: UploadFile = File(...)):
    raw = await file.read()
    return _import_csv_text(raw.decode("utf-8-sig"))


@router.post("/import-csv/{supplier_id}")
async def import_csv_for_supplier(supplier_id: int, file: UploadFile = File(...)):
    from app.services.db import get_supplier
    supplier = get_supplier(supplier_id)
    if not supplier:
        raise HTTPException(404, "Fournisseur introuvable")
    if str(supplier.get("provider_code") or "").lower() != "cj":
        raise HTTPException(410, "v0.25 n'utilise que CJ comme fournisseur actif")
    raw = await file.read()
    return _import_csv_text(raw.decode("utf-8-sig"), supplier_id)


@router.post("/load-demo")
def load_demo():
    raise HTTPException(410, "Le catalogue démo a été retiré du mode eBay US / CJ only")


@router.post("/{product_id}/generate-listing")
def generate_listing(product_id: int):
    return optimize_ebay(product_id, SeoOptimizeIn())
