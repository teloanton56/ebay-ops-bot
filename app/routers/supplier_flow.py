import asyncio

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from app.services.aliexpress_dropship_search import aliexpress_dropship_supplier_offers
from app.services.cj import CJClient, CJError
from app.services.db import list_suppliers, save_supplier, upsert_product
from app.services.marketplace_supplier_sources import amazon_supplier_offers

router = APIRouter(prefix="/api/supplier-flow", tags=["Supplier Flow"])


class OfferIn(BaseModel):
    provider: str = Field(min_length=2, max_length=40)
    supplier_sku: str = Field(min_length=1, max_length=100)
    name: str = Field(min_length=1, max_length=300)
    price: float = Field(ge=0)
    shipping_cost: float | None = Field(default=None, ge=0)
    currency: str = Field(default="EUR", min_length=3, max_length=3)
    stock: int | None = Field(default=None, ge=0)
    shipping_days: int | None = Field(default=None, ge=0)
    image_url: str = Field(default="", max_length=1200)
    source_url: str = Field(default="", max_length=1200)


def _normalized_group(source: str, offers: list[dict]) -> dict:
    return {
        "source": source,
        "total": len(offers),
        "products": [
            {
                "provider": source,
                "supplier_sku": row.get("supplier_sku") or "",
                "name": row.get("name") or "Produit",
                "price": row.get("product_cost"),
                "shipping_cost": row.get("shipping_cost"),
                "currency": row.get("currency") or "EUR",
                "stock": row.get("stock"),
                "shipping_days": row.get("shipping_days"),
                "warehouse": row.get("warehouse") or "",
                "image_url": row.get("image_url") or "",
                "source_url": row.get("source_url") or "",
                "quality_evidence": row.get("evidence") or [],
            }
            for row in offers
        ],
    }


async def _cj_group(keyword: str) -> tuple[dict | None, list[dict]]:
    try:
        client = CJClient()
        if not client.status().get("connected"):
            return None, [{"source": "CJ", "message": "CJ n'est pas connecté"}]
        result = await client.search_products(keyword=keyword, size=12, min_stock=3)
        rows = []
        for product in result.get("products") or []:
            rows.append({
                "provider": "CJ",
                "supplier_sku": product.get("sku") or product.get("cj_pid") or "",
                "cj_pid": product.get("cj_pid"),
                "name": product.get("name") or keyword,
                "price": product.get("price_usd"),
                "shipping_cost": None,
                "currency": "USD",
                "stock": product.get("stock"),
                "shipping_days": None,
                "warehouse": product.get("warehouse_country") or "CJ",
                "image_url": product.get("image_url") or "",
                "source_url": "",
                "quality_evidence": [
                    f"Stock observé : {product.get('stock', 0)}",
                    f"Présence CJ : {product.get('listed_num', 0)} listings",
                ],
            })
        return {"source": "CJ", "products": rows, "total": len(rows)}, []
    except (CJError, RuntimeError, Exception) as exc:
        return None, [{"source": "CJ", "message": str(exc)}]


@router.get("/compare")
async def compare(q: str = Query(min_length=2, max_length=120)):
    keyword = q.strip()
    cj_task = _cj_group(keyword)
    amazon_task = amazon_supplier_offers(keyword)
    ali_task = aliexpress_dropship_supplier_offers(keyword)
    cj_result, amazon_result, ali_result = await asyncio.gather(cj_task, amazon_task, ali_task)

    groups = []
    errors = []
    cj_group, cj_errors = cj_result
    if cj_group and cj_group.get("products"):
        groups.append(cj_group)
    errors.extend(cj_errors)

    amazon_offers, amazon_errors = amazon_result
    if amazon_offers:
        groups.append(_normalized_group("Amazon", amazon_offers))
    errors.extend(amazon_errors)

    ali_offers, ali_errors = ali_result
    if ali_offers:
        groups.append(_normalized_group("AliExpress", ali_offers))
    errors.extend(ali_errors)

    return {
        "keyword": keyword,
        "groups": groups,
        "errors": errors,
        "queried": ["CJ", "Amazon", "AliExpress"],
        "note": "Comparaison CJ, Amazon et AliExpress. Une source non connectée ou sans résultat est signalée séparément.",
    }


def _supplier_for(provider: str) -> int:
    code = provider.lower()
    aliases = {
        "aliexpress": ("AliExpress", "CN"),
        "amazon": ("Amazon France", "FR"),
        "cj": ("CJ Dropshipping", "CN"),
    }
    if code not in aliases:
        raise HTTPException(400, "Fournisseur non pris en charge")
    for row in list_suppliers():
        if str(row.get("provider_code") or "").lower() == code:
            return int(row["id"])
    name, country = aliases[code]
    return int(save_supplier({
        "name": name,
        "contact_name": "",
        "email": "",
        "website": "",
        "country": country,
        "notes": "Fournisseur API du bot",
        "provider_code": code,
        "supplier_type": "API",
        "catalog_url": "",
        "catalog_status": "Connecté",
        "reliability_score": None,
        "last_checked_at": None,
        "active": True,
    }))


@router.post("/add")
def add_offer(payload: OfferIn):
    provider = payload.provider.strip().lower()
    supplier_id = _supplier_for(provider)
    prefix = {"aliexpress": "ALI", "amazon": "AMZ", "cj": "CJ"}[provider]
    sku = f"{prefix}-{payload.supplier_sku}"[:50]
    product_id = upsert_product({
        "supplier_sku": sku,
        "title": payload.name,
        "description": (
            f"Produit importé depuis {payload.provider}. "
            f"Source fournisseur : {payload.source_url}" if payload.source_url else f"Produit importé depuis {payload.provider}."
        ),
        "supplier_cost": payload.price,
        "shipping_cost": payload.shipping_cost or 0,
        "stock": payload.stock or 0,
        "shipping_days": payload.shipping_days if payload.shipping_days is not None else 0,
        "target_price": None,
        "marketplace_id": "EBAY_FR",
        "currency": payload.currency.upper(),
        "images": [payload.image_url] if payload.image_url else [],
        "aspects": {},
        "supplier_id": supplier_id,
        "product_status": "À tester",
    })
    return {
        "created": True,
        "product_id": product_id,
        "message": "Produit ajouté au dashboard Produits. Stock, livraison et marge restent à valider avant publication eBay.",
    }
