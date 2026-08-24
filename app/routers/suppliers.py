from fastapi import APIRouter, HTTPException, Query

from app.services.cj import CJClient
from app.services.supplier_relevance import rank_supplier_results


router = APIRouter(prefix="/api/suppliers", tags=["CJ Dropshipping"])


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
        "metrics": {
            "connected_catalogs": 1 if cj["connected"] else 0,
            "registered_suppliers": 1,
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
        payload = await client.search_products(keyword=keyword, size=100, min_stock=0, order_by=0)
        relevant, rejected = rank_supplier_results(
            keyword,
            payload.get("products") or [],
            title_keys=("name",),
            limit=60,
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
        "source_total": int(payload.get("total") or len(payload.get("products") or [])),
        "sampled": len(payload.get("products") or []),
        "errors": [],
        "filtered_out": rejected,
        "measured_only": True,
        "marketplace": "EBAY_US",
        "currency": "USD",
        "destination_country": "US",
    }
