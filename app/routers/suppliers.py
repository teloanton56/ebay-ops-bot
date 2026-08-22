from urllib.parse import quote_plus

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from app.services.cj import CJClient
from app.services.db import (
    delete_supplier,
    get_supplier,
    list_factory_leads,
    list_rfqs,
    list_suppliers,
    save_supplier,
)
from app.services.supplier_directory import SUPPLIER_DIRECTORY, search_supplier_directory
from app.services.supplier_relevance import rank_supplier_results

router = APIRouter(prefix="/api/suppliers", tags=["Suppliers"])


class SupplierIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    contact_name: str = ""
    email: str = ""
    website: str = ""
    country: str = Field(default="US", min_length=2, max_length=2)
    notes: str = ""
    provider_code: str = Field(default="", max_length=50)
    supplier_type: str = Field(default="MANUEL", max_length=30)
    catalog_url: str = Field(default="", max_length=500)
    catalog_status: str = Field(default="À importer", max_length=80)
    reliability_score: float | None = Field(default=None, ge=0, le=100)
    last_checked_at: str | None = None
    active: bool = True


class FactoryDiscoveryIn(BaseModel):
    query: str = Field(default="", max_length=120)


@router.get("")
def suppliers():
    # Existing manual rows are preserved in the database for backwards compatibility,
    # but the v0.23 operating interface uses CJ only.
    return list_suppliers()


@router.get("/directory")
def supplier_directory(
    q: str = Query(default="", max_length=80),
    category: str = Query(default="", max_length=40),
    catalog: str = Query(default="", max_length=20),
):
    rows = search_supplier_directory(q, category, catalog)
    categories = sorted({category for row in SUPPLIER_DIRECTORY for category in row["categories"]})
    return {
        "results": rows,
        "total": len(rows),
        "categories": categories,
        "legacy": True,
        "note": "Legacy directory kept for a future Shopify/sourcing phase; not used by v0.23 eBay US operations.",
    }


@router.get("/hub")
def supplier_hub():
    cj = CJClient().status()
    provider = {
        "id": "cj",
        "name": "CJ Dropshipping",
        "kind": "Unique active supplier",
        "connected": cj["connected"],
        "configured": cj["configured"],
        "status": "Connecté" if cj["connected"] else "À reconnecter" if cj.get("recovery_required") else "À connecter",
        "catalog": True,
        "supplier": True,
        "available_in_products": cj["connected"],
        "url": "https://cjdropshipping.com/",
        "note": "eBay US only · CJ US warehouse first · China only under stricter profitability rules.",
        "capabilities": {
            "search": True,
            "price": True,
            "stock": True,
            "shipping": True,
            "variants": True,
            "margin_analysis": True,
            "us_warehouse_first": True,
            "china_fallback": True,
        },
    }
    return {
        "providers": [provider],
        "manual": [],
        "factories": [],
        "rfqs": [],
        "metrics": {
            "connected_catalogs": 1 if cj["connected"] else 0,
            "registered_suppliers": 1,
            "factory_contacts": 0,
            "rfq_drafts": 0,
        },
        "operating_mode": "EBAY_US_CJ_ONLY",
        "dry_run": True,
    }


@router.get("/source-search")
async def source_search(
    provider: str = Query(pattern="^cj$"),
    q: str = Query(min_length=2, max_length=120),
):
    keyword = q.strip()
    client = CJClient()
    if not client.status().get("connected"):
        raise HTTPException(400, "CJ n'est pas connecté")
    try:
        payload = await client.search_products(keyword=keyword, size=50, min_stock=1, order_by=0)
        relevant, rejected = rank_supplier_results(
            keyword,
            payload.get("products") or [],
            title_keys=("name",),
            limit=20,
        )
    except Exception as exc:
        raise HTTPException(400, str(exc)) from exc
    offers = [
        {
            "provider": "CJ",
            "supplier_sku": row.get("sku") or row.get("cj_pid") or "",
            "cj_pid": row.get("cj_pid") or "",
            "name": row.get("name") or "CJ product",
            "product_cost": row.get("price_usd"),
            "shipping_cost": None,
            "currency": "USD",
            "stock": row.get("stock"),
            "shipping_days": None,
            "warehouse": "US first · CN fallback",
            "image_url": row.get("image_url") or "",
            "source_url": "",
            "match_strength": row.get("match_strength"),
        }
        for row in relevant
    ]
    return {
        "provider": provider,
        "keyword": keyword,
        "offers": offers,
        "errors": [],
        "filtered_out": rejected,
        "measured_only": True,
    }


# Legacy CRUD is retained so historical rows do not become inaccessible, but the
# new interface does not expose manual suppliers during the eBay validation phase.
@router.post("/factory-discovery")
def factory_discovery(payload: FactoryDiscoveryIn):
    query = payload.query.strip()
    if len(query) < 2:
        raise HTTPException(400, "Indiquez un produit à rechercher.")
    encoded = quote_plus(query)
    return {
        "query": query,
        "origin": "manual",
        "directories": [
            {"name": "Alibaba.com", "url": f"https://www.alibaba.com/trade/search?SearchText={encoded}", "strength": "Future Shopify sourcing"},
        ],
        "known_contacts": [],
        "legacy": True,
    }


@router.post("")
def create(payload: SupplierIn):
    try:
        supplier_id = save_supplier(payload.model_dump())
    except Exception as exc:
        raise HTTPException(400, "Un fournisseur porte déjà ce nom.") from exc
    return get_supplier(supplier_id)


@router.put("/{supplier_id}")
def update(supplier_id: int, payload: SupplierIn):
    if not get_supplier(supplier_id):
        raise HTTPException(404, "Fournisseur introuvable")
    try:
        save_supplier(payload.model_dump(), supplier_id)
    except Exception as exc:
        raise HTTPException(400, "Un fournisseur porte déjà ce nom.") from exc
    return get_supplier(supplier_id)


@router.delete("/{supplier_id}")
def remove(supplier_id: int):
    if not delete_supplier(supplier_id):
        raise HTTPException(404, "Fournisseur introuvable")
    return {"deleted": True}
