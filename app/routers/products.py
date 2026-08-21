import csv
import io
import json
from typing import Any

from fastapi import APIRouter, File, HTTPException, UploadFile
from pydantic import BaseModel, Field

from app.config import get_settings
from app.services.db import (delete_product, get_product, list_cj_candidates, list_products,
                             ensure_provider_supplier, list_suppliers, list_trend_discoveries, save_listing,
                             set_product_fields, upsert_product)
from app.services.profit import suggest_price
from app.services.risk import assess_product
from app.services.scoring import calculate_product_score

router = APIRouter(prefix="/api/products", tags=["Products"])


def _with_live_scores(product: dict, suppliers: dict[int, dict] | None = None) -> dict:
    supplier_map = suppliers or {row["id"]: row for row in list_suppliers()}
    supplier = supplier_map.get(product.get("supplier_id"))
    return {**product, "risk": assess_product(product),
            "product_score": calculate_product_score(product, supplier)}


def _import_csv_text(text: str, supplier_id: int | None = None):
    # Accept both comma-separated CSVs and the semicolon format commonly produced by French Excel.
    sample = text[:4096]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t")
    except csv.Error:
        dialect = csv.excel
    reader = csv.DictReader(io.StringIO(text), dialect=dialect)
    required = {"supplier_sku", "title", "supplier_cost"}
    if not reader.fieldnames or not required.issubset(set(reader.fieldnames)):
        raise HTTPException(400, f"CSV must include: {sorted(required)}")
    s = get_settings()
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
                "marketplace_id": (row.get("marketplace_id") or "").strip() or s.ebay_marketplace_id,
                "currency": (row.get("currency") or "").strip() or s.ebay_currency,
                "images": images,
                "aspects": aspects,
                "supplier_id": supplier_id,
            }
            ids.append(upsert_product(data))
        except Exception as exc:
            errors.append({"line": idx, "error": str(exc)})
    return {"imported": len(ids), "product_ids": ids, "errors": errors}


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
    currency: str = Field(default="EUR", min_length=3, max_length=3)
    stock: int | None = Field(default=None, ge=0)
    shipping_days: int | None = Field(default=None, ge=0)
    image_url: str = Field(default="", max_length=1000)


@router.get("")
def products():
    suppliers = {row["id"]: row for row in list_suppliers()}
    return [_with_live_scores(p, suppliers) for p in list_products()]


@router.post("")
def create_product(payload: ProductIn):
    data = payload.model_dump()
    s = get_settings()
    data["marketplace_id"] = data.get("marketplace_id") or s.ebay_marketplace_id
    data["currency"] = data.get("currency") or s.ebay_currency
    product_id = upsert_product(data)
    product = get_product(product_id)
    scored = _with_live_scores(product)
    return {"product": product, "risk": scored["risk"], "product_score": scored["product_score"]}


@router.post("/from-supplier-offer")
def create_from_supplier_offer(payload: SupplierOfferIn):
    provider = payload.provider.strip().lower()
    providers = {
        "dropxl": ("DropXL / vidaXL", "NL"), "printful": ("Printful", "US"),
        "printify": ("Printify", "US"), "gelato": ("Gelato", "NO"),
        "wholesale2b": ("Wholesale2B", "US"), "hypersku": ("HyperSKU", "CN"),
        "banggood": ("Banggood Dropshipping", "CN"),
    }
    if provider not in providers:
        raise HTTPException(400, "Fournisseur non pris en charge")
    supplier_name, country = providers[provider]
    supplier_id = ensure_provider_supplier(provider, supplier_name, country)
    sku = f"{provider.upper()}-{payload.supplier_sku}"[:50]
    product_id = upsert_product({
        "supplier_sku": sku, "title": payload.name,
        "description": f"Offre {supplier_name}. Transport, conformité et droits des contenus à confirmer.",
        "supplier_cost": payload.price, "shipping_cost": payload.shipping_cost,
        "stock": payload.stock or 0, "shipping_days": payload.shipping_days if payload.shipping_days is not None else 99,
        "target_price": None, "marketplace_id": "EBAY_FR", "currency": payload.currency.upper(),
        "images": [payload.image_url] if payload.image_url else [], "aspects": {},
        "supplier_id": supplier_id, "product_status": "À tester",
    })
    return {"created": True, "product_id": product_id, "dry_run": True,
            "message": "Offre ajoutée aux Produits. Transport et conformité restent à valider."}


@router.put("/{product_id}")
def update_product(product_id: int, payload: ProductIn):
    if not get_product(product_id):
        raise HTTPException(404, "Product not found")
    data = payload.model_dump()
    data["supplier_sku"] = get_product(product_id)["supplier_sku"]
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
    shipping_days = int(product.get("shipping_days") or 0)
    if shipping_days <= 0 or shipping_days >= 99:
        raise HTTPException(400, "Impossible de calculer un prix fiable tant que la livraison n'est pas confirmée.")
    result = suggest_price(product)
    set_product_fields(product_id, suggested_price=result["suggested_price"], target_price=result["suggested_price"])
    return result


@router.post("/{product_id}/prepare-ebay")
def prepare_ebay(product_id: int):
    product = get_product(product_id)
    if not product:
        raise HTTPException(404, "Product not found")
    risk = assess_product(product)
    if not risk["pass"]:
        raise HTTPException(400, "Le Risk Engine bloque cette préparation : " + " ; ".join(risk["blocks"]))
    listing_id = save_listing(product_id, None, None, "PREPARED_DRY_RUN", product["target_price"], product["stock"])
    return {"prepared": True, "dry_run": True, "listing_id": listing_id, "message": "Brouillon local préparé. Aucune donnée envoyée à eBay."}


@router.get("/opportunities/inbox")
def opportunity_inbox():
    discoveries = [row for row in list_trend_discoveries(12)
                   if row.get("source") == "YOUTUBE_SHORTS_COMMERCE"][:3]
    themes = []
    for discovery in discoveries:
        for theme in discovery["themes"]:
            key = str(theme.get("keyword") or "").lower()
            if key and not any(str(row.get("keyword") or "").lower() == key for row in themes):
                themes.append({**theme, "country": discovery["country"],
                               "source": discovery["source"], "scanned_at": discovery["scanned_at"]})
    candidates = list_cj_candidates()
    return {
        "themes": themes[:12],
        "cj_candidates": candidates[:12],
        "supplier_count": len(list_suppliers()),
        "measured_only": True,
        "note": "Une niche reste une piste tant qu'un fournisseur, un coût livré et une demande eBay réelle ne sont pas confirmés.",
    }


@router.get("/{product_id}")
def product(product_id: int):
    p = get_product(product_id)
    if not p:
        raise HTTPException(404, "Product not found")
    return _with_live_scores(p)


@router.post("/import-csv")
async def import_csv(file: UploadFile = File(...)):
    raw = await file.read()
    return _import_csv_text(raw.decode("utf-8-sig"))


@router.post("/import-csv/{supplier_id}")
async def import_csv_for_supplier(supplier_id: int, file: UploadFile = File(...)):
    from app.services.db import get_supplier
    if not get_supplier(supplier_id):
        raise HTTPException(404, "Fournisseur introuvable")
    raw = await file.read()
    return _import_csv_text(raw.decode("utf-8-sig"), supplier_id)


@router.post("/load-demo")
def load_demo():
    from pathlib import Path
    demo = Path("sample_supplier.csv")
    if not demo.exists():
        raise HTTPException(404, "sample_supplier.csv not found")
    return _import_csv_text(demo.read_text(encoding="utf-8-sig"))


@router.post("/{product_id}/generate-listing")
def generate_listing(product_id: int):
    from app.services.listing_generator import generate_description, optimize_title
    p = get_product(product_id)
    if not p:
        raise HTTPException(404, "Product not found")
    data = dict(p)
    data["title"] = optimize_title(p["title"])
    data["description"] = generate_description(p)
    data.pop("id", None)
    data.pop("created_at", None)
    data.pop("updated_at", None)
    data.pop("previous_supplier_cost", None)
    pid = upsert_product(data)
    out = get_product(pid)
    scored = _with_live_scores(out)
    return {"product": out, "risk": scored["risk"], "product_score": scored["product_score"]}
