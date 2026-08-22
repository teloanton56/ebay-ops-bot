import asyncio

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from app.services.aliexpress_dropship_search import aliexpress_dropship_supplier_offers
from app.services.cj import CJClient, CJError
from app.services.cj_landed import resolve_cj_landed_offer, save_cj_product_link
from app.services.db import list_suppliers, save_supplier, upsert_product
from app.services.marketplace_supplier_sources import amazon_supplier_offers
from app.services.profit import suggest_price
from app.services.supplier_relevance import rank_supplier_results

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
    cj_pid: str = Field(default="", max_length=120)


def _normalized_group(source: str, offers: list[dict], keyword: str) -> tuple[dict | None, int]:
    relevant, rejected = rank_supplier_results(keyword, offers, title_keys=("name", "title"), limit=20)
    if not relevant:
        return None, rejected
    return {
        "source": source,
        "total": len(relevant),
        "filtered_out": rejected,
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
                "match_strength": row.get("match_strength"),
            }
            for row in relevant
        ],
    }, rejected


def _no_relevant_message(source: str, keyword: str, raw_count: int) -> dict:
    suffix = f" ({raw_count} résultat(s) hors sujet ignoré(s))" if raw_count else ""
    return {
        "source": source,
        "message": f"Aucun produit pertinent trouvé pour « {keyword} »{suffix}",
    }


async def _cj_group(keyword: str) -> tuple[dict | None, list[dict]]:
    try:
        client = CJClient()
        if not client.status().get("connected"):
            return None, [{"source": "CJ", "message": "CJ n'est pas connecté"}]

        result = await client.search_products(keyword=keyword, size=50, min_stock=3, order_by=0)
        raw_products = result.get("products") or []
        relevant, rejected = rank_supplier_results(keyword, raw_products, title_keys=("name",), limit=20)
        if not relevant:
            return None, [_no_relevant_message("CJ", keyword, len(raw_products))]

        rows = []
        for product in relevant:
            rows.append({
                "provider": "CJ",
                "supplier_sku": product.get("sku") or product.get("cj_pid") or "",
                "cj_pid": product.get("cj_pid") or "",
                "name": product.get("name") or keyword,
                "price": product.get("price_usd"),
                "shipping_cost": None,
                "currency": "USD",
                "stock": product.get("stock"),
                "shipping_days": None,
                "warehouse": product.get("warehouse_country") or "CJ",
                "image_url": product.get("image_url") or "",
                "source_url": "",
                "match_strength": product.get("match_strength"),
                "quality_evidence": [
                    f"Pertinence recherche : {float(product.get('match_strength') or 0) * 100:.0f}%",
                    f"Stock observé : {product.get('stock', 0)}",
                    f"Présence CJ : {product.get('listed_num', 0)} listings",
                    "Transport France calculé au moment de l'ajout avec le même moteur que Margin Hunter",
                ],
            })
        return {
            "source": "CJ",
            "products": rows,
            "total": len(rows),
            "filtered_out": rejected,
        }, []
    except Exception as exc:
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
        amazon_group, _ = _normalized_group("Amazon", amazon_offers, keyword)
        if amazon_group:
            groups.append(amazon_group)
        else:
            errors.append(_no_relevant_message("Amazon", keyword, len(amazon_offers)))
    errors.extend(amazon_errors)

    ali_offers, ali_errors = ali_result
    if ali_offers:
        ali_group, _ = _normalized_group("AliExpress", ali_offers, keyword)
        if ali_group:
            groups.append(ali_group)
        else:
            errors.append(_no_relevant_message("AliExpress", keyword, len(ali_offers)))
    errors.extend(ali_errors)

    return {
        "keyword": keyword,
        "groups": groups,
        "errors": errors,
        "queried": ["CJ", "Amazon", "AliExpress"],
        "note": (
            "Comparaison CJ, Amazon et AliExpress. Les résultats hors sujet sont filtrés "
            "et seuls les produits réellement liés à la recherche sont affichés."
        ),
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


async def _add_cj_offer(payload: OfferIn, supplier_id: int, sku: str) -> dict:
    if not payload.cj_pid:
        raise HTTPException(400, "Identifiant produit CJ manquant. Relancez la recherche fournisseur avant l'ajout.")

    client = CJClient()
    try:
        landed = await resolve_cj_landed_offer(
            client,
            payload.cj_pid,
            fallback_price_usd=payload.price,
        )
        pricing = suggest_price({
            "supplier_cost": landed["supplier_cost"],
            "shipping_cost": landed["shipping_cost"],
        })
        image = landed.get("image_url") or payload.image_url
        product_id = upsert_product({
            "supplier_sku": sku,
            "title": payload.name,
            "description": (
                f"Produit importé depuis CJ Dropshipping. Variante {landed.get('variant_sku') or landed.get('variant_id')}. "
                f"Transport France : {landed.get('freight_name') or 'CJ'} · départ {landed.get('warehouse')}. "
                "Données fournisseur revalidées avant toute écriture eBay."
            ),
            "supplier_cost": landed["supplier_cost"],
            "shipping_cost": landed["shipping_cost"],
            "stock": landed["stock"],
            "shipping_days": landed["shipping_days"],
            "target_price": pricing["suggested_price"],
            "marketplace_id": "EBAY_FR",
            "currency": "EUR",
            "images": [image] if image else [],
            "aspects": {},
            "supplier_id": supplier_id,
            "product_status": "À tester",
            "suggested_price": pricing["suggested_price"],
        })
        save_cj_product_link(sku, landed)
        return {
            "created": True,
            "product_id": product_id,
            "pricing_ready": True,
            "supplier_cost": landed["supplier_cost"],
            "shipping_cost": landed["shipping_cost"],
            "shipping_days": landed["shipping_days"],
            "target_price": pricing["suggested_price"],
            "warehouse": landed["warehouse"],
            "variant_id": landed["variant_id"],
            "message": (
                f"Produit CJ ajouté avec coût livré France {landed['landed_cost']:.2f} EUR "
                f"et prix conseillé {pricing['suggested_price']:.2f} EUR."
            ),
        }
    except CJError as exc:
        raise HTTPException(400, f"Calcul CJ impossible : {exc}") from exc


@router.post("/add")
async def add_offer(payload: OfferIn):
    provider = payload.provider.strip().lower()
    supplier_id = _supplier_for(provider)
    prefix = {"aliexpress": "ALI", "amazon": "AMZ", "cj": "CJ"}[provider]
    sku = f"{prefix}-{payload.supplier_sku}"[:50]

    if provider == "cj":
        return await _add_cj_offer(payload, supplier_id, sku)

    logistics_complete = payload.shipping_cost is not None and payload.shipping_days is not None and payload.shipping_days > 0
    pricing = None
    if logistics_complete:
        pricing = suggest_price({"supplier_cost": payload.price, "shipping_cost": payload.shipping_cost})

    product_id = upsert_product({
        "supplier_sku": sku,
        "title": payload.name,
        "description": (
            f"Produit importé depuis {payload.provider}. "
            + (f"Source fournisseur : {payload.source_url}. " if payload.source_url else "")
            + ("Transport API confirmé." if logistics_complete else "Transport non fourni par l'API : coût et délai à confirmer avant publication.")
        ),
        "supplier_cost": payload.price,
        "shipping_cost": payload.shipping_cost if payload.shipping_cost is not None else 0,
        "stock": payload.stock or 0,
        "shipping_days": payload.shipping_days if logistics_complete else 99,
        "target_price": pricing["suggested_price"] if pricing else None,
        "marketplace_id": "EBAY_FR",
        "currency": payload.currency.upper(),
        "images": [payload.image_url] if payload.image_url else [],
        "aspects": {},
        "supplier_id": supplier_id,
        "product_status": "À tester",
        "suggested_price": pricing["suggested_price"] if pricing else None,
    })
    return {
        "created": True,
        "product_id": product_id,
        "pricing_ready": bool(pricing),
        "message": (
            f"Produit ajouté avec prix conseillé {pricing['suggested_price']:.2f} {payload.currency.upper()}."
            if pricing
            else "Produit ajouté. Le transport n'est pas fourni par cette API : livraison et prix conseillé restent à confirmer."
        ),
    }
