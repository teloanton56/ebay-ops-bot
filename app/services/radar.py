from collections import Counter
from statistics import median

from app.config import get_settings
from app.services.cj import CJClient
from app.services.connections import AmazonRadarClient
from app.services.db import previous_radar_scan, save_radar_scan
from app.services.ebay import EbayClient


MARKETPLACES = {"EBAY_US": "eBay United States"}
AMAZON_MARKETPLACES = {key: value["name"] for key, value in AmazonRadarClient.marketplaces.items()}


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
            "note": "Active US listings and seller competition. This is the only market used by v0.23.",
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
        raise ValueError("v0.23 analyse uniquement eBay US")
    payload = await EbayClient().search_items(keyword, limit=50, marketplace_id="EBAY_US")
    items = payload.get("itemSummaries") or []
    prices, currencies = [], []
    for item in items:
        price = item.get("price") or {}
        try:
            if price.get("value") is not None:
                prices.append(float(price["value"]))
        except (TypeError, ValueError):
            pass
        if price.get("currency"):
            currencies.append(str(price["currency"]))
    currency = Counter(currencies).most_common(1)[0][0] if currencies else "USD"
    sellers = [str((item.get("seller") or {}).get("username") or "").strip() for item in items]
    sellers = [seller for seller in sellers if seller]
    seller_counts = Counter(sellers)
    top_seller, top_count = seller_counts.most_common(1)[0] if seller_counts else ("", 0)
    result = {
        "keyword": keyword,
        "source": "EBAY",
        "marketplace": "EBAY_US",
        "marketplace_name": "eBay United States",
        "total_results": int(payload.get("total") or len(items)),
        "currency": currency,
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
            for item in items[:8]
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


# Kept only for dormant legacy modules/tests. It is not exposed by v0.23 UI or Radar.
async def analyze_amazon_market(keyword: str, marketplace: str) -> dict:
    payload = await AmazonRadarClient().search_catalog(keyword, marketplace, page_size=20)
    products = payload.get("products") or []
    prices = [float(row["price"]) for row in products if row.get("price") is not None]
    return {
        "keyword": keyword,
        "source": "AMAZON",
        "marketplace": marketplace,
        "marketplace_name": AMAZON_MARKETPLACES.get(marketplace, marketplace),
        "total_results": int(payload.get("total") or len(products)),
        "currency": payload.get("currency") or "USD",
        "median_price": round(median(prices), 2) if prices else None,
        "min_price": round(min(prices), 2) if prices else None,
        "max_price": round(max(prices), 2) if prices else None,
        "conversion_rate": None,
        "search_volume": None,
        "items": products[:8],
    }


def build_rfq_message(company: str, product_query: str, quantities: str, specifications: str = "") -> str:
    company_line = f" {company}" if company else ""
    specs = specifications.strip() or "Please provide full product specifications and compliance documents."
    return (
        f"Hello{company_line},\n\n"
        f"We are evaluating a long-term supply partnership for: {product_query}.\n\n"
        f"Please quote the unit price for these quantities: {quantities}.\n"
        "Please include MOQ, sample price, DDP shipping to the United States, lead time, "
        "certifications, packaging/private-label options, warranty and defect policy.\n\n"
        f"Product requirements: {specs}\n\n"
        "No order is confirmed by this request.\n\nBest regards"
    )
