from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from app.services.cj import CJClient, CJError
from app.services.cj_landed import resolve_cj_landed_offer, route_requirements, save_cj_product_link
from app.services.db import list_suppliers, save_supplier, upsert_product
from app.services.profit import suggest_price
from app.services.radar import analyze_ebay_market
from app.services.supplier_relevance import rank_supplier_results

router = APIRouter(prefix="/api/supplier-flow", tags=["Supplier Flow"])

CJ_SEARCH_PAGE_SIZE = 100
CJ_VISIBLE_RESULTS = 60


class OfferIn(BaseModel):
    provider: str = Field(default="cj", min_length=2, max_length=40)
    supplier_sku: str = Field(min_length=1, max_length=100)
    name: str = Field(min_length=1, max_length=300)
    price: float = Field(ge=0)
    shipping_cost: float | None = Field(default=None, ge=0)
    currency: str = Field(default="USD", min_length=3, max_length=3)
    stock: int | None = Field(default=None, ge=0)
    shipping_days: int | None = Field(default=None, ge=0)
    image_url: str = Field(default="", max_length=1200)
    source_url: str = Field(default="", max_length=1200)
    cj_pid: str = Field(default="", max_length=120)


def _no_relevant_message(keyword: str, raw_count: int) -> dict:
    suffix = f" ({raw_count} résultat(s) hors sujet ignoré(s))" if raw_count else ""
    return {"source": "CJ", "message": f"Aucun produit CJ pertinent trouvé pour « {keyword} »{suffix}"}


async def _cj_group(keyword: str) -> tuple[dict | None, list[dict]]:
    try:
        client = CJClient()
        if not client.status().get("connected"):
            return None, [{"source": "CJ", "message": "CJ n'est pas connecté"}]
        # listV2 accepts up to 100 products per page. Do not pre-filter on global
        # inventory here: the exact US/CN variant inventory is verified only when
        # the operator asks to calculate the route.
        result = await client.search_products(
            keyword=keyword,
            size=CJ_SEARCH_PAGE_SIZE,
            min_stock=0,
            order_by=0,
        )
        raw_products = result.get("products") or []
        relevant, rejected = rank_supplier_results(
            keyword,
            raw_products,
            title_keys=("name",),
            limit=CJ_VISIBLE_RESULTS,
        )
        if not relevant:
            return None, [_no_relevant_message(keyword, len(raw_products))]
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
                "warehouse": "US prioritaire · CN fallback rentable",
                "image_url": product.get("image_url") or "",
                "source_url": "",
                "match_strength": product.get("match_strength"),
                "quality_evidence": [
                    f"Pertinence recherche : {float(product.get('match_strength') or 0) * 100:.0f}%",
                    f"Stock catalogue CJ observé : {product.get('stock', 0)}",
                    "Le stock exact par variante US/CN est vérifié avec l'API inventaire CJ à l'ajout.",
                    "Le transport US est calculé sur plusieurs variantes si nécessaire.",
                ],
            })
        return {
            "source": "CJ",
            "products": rows,
            "total": len(rows),
            "source_total": int(result.get("total") or len(raw_products)),
            "sampled": len(raw_products),
            "filtered_out": rejected,
        }, []
    except Exception as exc:
        return None, [{"source": "CJ", "message": str(exc)}]


@router.get("/compare")
async def compare(q: str = Query(min_length=2, max_length=120)):
    keyword = q.strip()
    group, errors = await _cj_group(keyword)
    return {
        "keyword": keyword,
        "groups": [group] if group and group.get("products") else [],
        "errors": errors,
        "queried": ["CJ"],
        "market": "EBAY_US",
        "currency": "USD",
        "note": (
            "Recherche CJ élargie à 100 résultats catalogue par requête. "
            "Le stock US/Chine et le transport vers les États-Unis sont revalidés au clic."
        ),
    }


def _supplier_for_cj() -> int:
    for row in list_suppliers():
        if str(row.get("provider_code") or "").lower() == "cj":
            return int(row["id"])
    return int(save_supplier({
        "name": "CJ Dropshipping",
        "contact_name": "",
        "email": "",
        "website": "https://cjdropshipping.com/",
        "country": "US",
        "notes": "Fournisseur unique v0.23 : US prioritaire, Chine en fallback rentable.",
        "provider_code": "cj",
        "supplier_type": "API",
        "catalog_url": "",
        "catalog_status": "Connecté",
        "reliability_score": None,
        "last_checked_at": None,
        "active": True,
    }))


async def _market_reference(title: str) -> float | None:
    try:
        market = await analyze_ebay_market(title, "EBAY_US")
        if str(market.get("currency") or "USD").upper() != "USD":
            return None
        value = market.get("median_price")
        return round(float(value), 2) if value is not None and float(value) > 0 else None
    except Exception:
        return None


async def _add_cj_offer(payload: OfferIn, supplier_id: int, sku: str) -> dict:
    if not payload.cj_pid:
        raise HTTPException(400, "Identifiant produit CJ manquant. Relancez la recherche avant l'ajout.")

    client = CJClient()
    try:
        reference_price = await _market_reference(payload.name)
        landed = await resolve_cj_landed_offer(
            client,
            payload.cj_pid,
            fallback_price_usd=payload.price,
            destination_country="US",
            reference_price=reference_price,
        )
        warehouse = str(landed.get("warehouse") or "").upper()
        requirements = route_requirements(warehouse or "US")
        if not landed.get("eligible"):
            raise CJError(
                f"La route CJ {warehouse or 'inconnue'} ne respecte pas les seuils stock/délai/marge du lancement eBay US"
            )
        if warehouse == "CN" and reference_price is None:
            raise CJError(
                "Route Chine refusée : le bot n'a pas de prix eBay US fiable pour prouver que la marge compense le délai"
            )

        pricing = suggest_price(
            {"supplier_cost": landed["supplier_cost"], "shipping_cost": landed["shipping_cost"]},
            reference_price,
            min_margin_percent=float(requirements["min_margin_percent"]),
            min_profit=float(requirements["min_profit"]),
        )
        image = landed.get("image_url") or payload.image_url
        route_label = "CJ US" if warehouse == "US" else "CJ China → US"
        product_id = upsert_product({
            "supplier_sku": sku,
            "title": payload.name,
            "description": (
                f"CJ Dropshipping · route {route_label}. Variante {landed.get('variant_sku') or landed.get('variant_id')}. "
                f"Transport US : {landed.get('freight_name') or 'CJ'}. Stock, coût et délai revalidés avant écriture eBay."
            ),
            "supplier_cost": landed["supplier_cost"],
            "shipping_cost": landed["shipping_cost"],
            "stock": landed["stock"],
            "shipping_days": landed["shipping_days"],
            "target_price": pricing["suggested_price"],
            "marketplace_id": "EBAY_US",
            "currency": "USD",
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
            "landed_cost": landed["landed_cost"],
            "shipping_days": landed["shipping_days"],
            "target_price": pricing["suggested_price"],
            "market_reference_price": reference_price,
            "warehouse": warehouse,
            "route": route_label,
            "variant_id": landed["variant_id"],
            "requirements": requirements,
            "message": (
                f"Produit ajouté via {route_label} · coût livré ${landed['landed_cost']:.2f} · "
                f"prix conseillé ${pricing['suggested_price']:.2f}."
            ),
        }
    except CJError as exc:
        raise HTTPException(400, f"Calcul CJ impossible : {exc}") from exc


@router.post("/add")
async def add_offer(payload: OfferIn):
    if payload.provider.strip().lower() != "cj":
        raise HTTPException(410, "v0.23 utilise uniquement CJ Dropshipping comme fournisseur actif")
    supplier_id = _supplier_for_cj()
    sku = f"CJ-{payload.supplier_sku}"[:50]
    return await _add_cj_offer(payload, supplier_id, sku)
