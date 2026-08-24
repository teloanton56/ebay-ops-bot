from collections import Counter
from statistics import median

from app.config import get_settings
from app.services.cj import CJClient
from app.services.db import previous_radar_scan, save_radar_scan
from app.services.ebay import EbayClient


MARKETPLACES = {"EBAY_US": "eBay United States"}


def source_statuses() -> list[dict]:
    settings = get_settings()
    ebay_keys = bool(settings.ebay_client_id and settings.ebay_client_secret)
    ebay_live = ebay_keys and settings.ebay_effective_env == "production"
    cj = CJClient().status()
    return [
        {
            "id": "ebay",
            "name": "eBay US",
            "kind": "Sales channel",
            "configured": ebay_keys,
            "ready": ebay_live,
            "status": "Ready" if ebay_live else "Production keys required",
            "note": "Active US listings and seller competition. This is the only supported market.",
        },
        {
            "id": "cj",
            "name": "CJ Dropshipping",
            "kind": "Supplier",
            "configured": cj["configured"],
            "ready": cj["connected"],
            "status": "Ready" if cj["connected"] else "Connect CJ",
            "note": "US warehouse first; China route only when stricter profitability rules pass.",
        },
    ]


async def analyze_ebay_market(keyword: str, marketplace: str = "EBAY_US") -> dict:
    if marketplace != "EBAY_US":
        raise ValueError("Le Radar analyse uniquement eBay US")
    payload = await EbayClient().search_items(keyword, limit=50, marketplace_id="EBAY_US")
    items = payload.get("itemSummaries") or []
    prices = []
    usd_items = []
    for item in items:
        price = item.get("price") or {}
        currency = str(price.get("currency") or "USD").upper()
        if currency != "USD":
            continue
        usd_items.append(item)
        try:
            if price.get("value") is not None:
                prices.append(float(price["value"]))
        except (TypeError, ValueError):
            pass
    sellers = [str((item.get("seller") or {}).get("username") or "").strip() for item in usd_items]
    sellers = [seller for seller in sellers if seller]
    seller_counts = Counter(sellers)
    top_seller, top_count = seller_counts.most_common(1)[0] if seller_counts else ("", 0)
    result = {
        "keyword": keyword,
        "source": "EBAY",
        "marketplace": "EBAY_US",
        "marketplace_name": "eBay United States",
        "total_results": int(payload.get("total") or len(items)),
        "currency": "USD",
        "median_price": round(median(prices), 2) if prices else None,
        "min_price": round(min(prices), 2) if prices else None,
        "max_price": round(max(prices), 2) if prices else None,
        "sellers_sample": len(seller_counts),
        "top_seller": top_seller,
        "top_seller_share": round(top_count / len(sellers) * 100, 1) if sellers else 0,
        "conversion_rate": None,
        "search_volume": None,
        "items": [
            {
                "title": item.get("title") or "Product",
                "price": item.get("price") or {},
                "seller": (item.get("seller") or {}).get("username") or "",
                "image_url": ((item.get("image") or {}).get("imageUrl") or ""),
                "item_url": item.get("itemWebUrl") or "",
            }
            for item in usd_items[:8]
        ],
    }
    scan_id = save_radar_scan(result)
    previous = previous_radar_scan(keyword, "EBAY", "EBAY_US", scan_id)
    result["history_available"] = bool(previous)
    result["listing_change_percent"] = None
    if previous and int(previous.get("total_results") or 0) > 0:
        result["listing_change_percent"] = round(
            (result["total_results"] - int(previous["total_results"]))
            / int(previous["total_results"]) * 100,
            1,
        )
    return result
