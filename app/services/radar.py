from collections import Counter
from statistics import median

from app.config import get_settings
from app.services.cj import CJClient
from app.services.connections import AmazonRadarClient, connection_status
from app.services.db import previous_radar_scan, save_radar_scan
from app.services.ebay import EbayClient


MARKETPLACES = {
    "EBAY_FR": "eBay France", "EBAY_DE": "eBay Allemagne", "EBAY_IT": "eBay Italie",
    "EBAY_ES": "eBay Espagne", "EBAY_GB": "eBay Royaume-Uni", "EBAY_US": "eBay États-Unis",
}
AMAZON_MARKETPLACES = {key: value["name"] for key, value in AmazonRadarClient.marketplaces.items()}


def source_statuses() -> list[dict]:
    settings = get_settings()
    ebay_keys = bool(settings.ebay_client_id and settings.ebay_client_secret)
    ebay_live = ebay_keys and settings.ebay_env == "production"
    cj = CJClient().status()
    return [
        {"id": "ebay", "name": "eBay multi-pays", "kind": "Marketplace", "configured": ebay_keys,
         "ready": ebay_live, "status": "Prêt" if ebay_live else "Clés Production requises",
         "note": "Annonces actives et vendeurs observés. Conversion disponible uniquement pour votre boutique."},
        {**connection_status("amazon"),
         "note": "Catalogue, catégories, rangs de vente et prix si le rôle Pricing est accordé. Aucune écriture Amazon."},
        {"id": "cj", "name": "CJ Dropshipping", "kind": "Fournisseur", "configured": cj["configured"],
         "ready": cj["connected"], "status": "Prêt" if cj["connected"] else "À connecter",
         "note": "Produits, variantes, stock, propriétés et devis transport."},
        connection_status("tiktok"),
        connection_status("youtube"),
        connection_status("etsy"),
        connection_status("dropxl"),
        connection_status("printful"),
        connection_status("printify"),
        connection_status("gelato"),
    ]


async def analyze_ebay_market(keyword: str, marketplace: str) -> dict:
    payload = await EbayClient().search_items(keyword, limit=50, marketplace_id=marketplace)
    items = payload.get("itemSummaries") or []
    prices, currencies = [], []
    for item in items:
        price = item.get("price") or {}
        try:
            if price.get("value") is not None:
                prices.append(float(price["value"]))
        except (TypeError, ValueError):
            continue
        if price.get("currency"):
            currencies.append(str(price["currency"]))
    currency = Counter(currencies).most_common(1)[0][0] if currencies else "EUR"
    sellers = [str((item.get("seller") or {}).get("username") or "").strip() for item in items]
    sellers = [seller for seller in sellers if seller]
    seller_counts = Counter(sellers)
    top_seller, top_count = seller_counts.most_common(1)[0] if seller_counts else ("", 0)
    result = {
        "keyword": keyword, "source": "EBAY", "marketplace": marketplace,
        "marketplace_name": MARKETPLACES.get(marketplace, marketplace),
        "total_results": int(payload.get("total") or len(items)),
        "currency": currency,
        "median_price": round(median(prices), 2) if prices else None,
        "min_price": round(min(prices), 2) if prices else None,
        "max_price": round(max(prices), 2) if prices else None,
        "sellers_sample": len(seller_counts), "top_seller": top_seller,
        "top_seller_share": round(top_count / len(sellers) * 100, 1) if sellers else 0,
        "conversion_rate": None, "search_volume": None,
        "items": [{"title": item.get("title") or "Produit", "price": item.get("price") or {},
                   "seller": (item.get("seller") or {}).get("username") or "",
                   "image_url": ((item.get("image") or {}).get("imageUrl") or ""),
                   "item_url": item.get("itemWebUrl") or ""} for item in items[:8]],
    }
    scan_id = save_radar_scan(result)
    previous = previous_radar_scan(keyword, "EBAY", marketplace, scan_id)
    result["history_available"] = bool(previous)
    result["listing_change_percent"] = None
    if previous and int(previous.get("total_results") or 0) > 0:
        result["listing_change_percent"] = round((result["total_results"] - int(previous["total_results"])) /
                                                  int(previous["total_results"]) * 100, 1)
    return result


async def analyze_amazon_market(keyword: str, marketplace: str) -> dict:
    payload = await AmazonRadarClient().search_catalog(keyword, marketplace, page_size=20)
    products = payload.get("products") or []
    prices = [float(row["price"]) for row in products if row.get("price") is not None]
    offers = sum(int(row.get("offer_count") or 0) for row in products)
    ranks = [int(row["sales_rank"]) for row in products if row.get("sales_rank") is not None]
    result = {
        "keyword": keyword,
        "source": "AMAZON",
        "marketplace": marketplace,
        "marketplace_name": AMAZON_MARKETPLACES.get(marketplace, marketplace),
        "total_results": int(payload.get("total") or len(products)),
        "currency": payload.get("currency") or "EUR",
        "median_price": round(median(prices), 2) if prices else None,
        "min_price": round(min(prices), 2) if prices else None,
        "max_price": round(max(prices), 2) if prices else None,
        "sellers_sample": 0,
        "top_seller": "",
        "top_seller_share": 0,
        "offers_sample": offers,
        "ranked_products": len(ranks),
        "best_sales_rank": min(ranks) if ranks else None,
        "pricing_available": bool(payload.get("pricing_available")),
        "conversion_rate": None,
        "search_volume": None,
        "items": products[:8],
    }
    scan_id = save_radar_scan(result)
    previous = previous_radar_scan(keyword, "AMAZON", marketplace, scan_id)
    result["history_available"] = bool(previous)
    result["listing_change_percent"] = None
    if previous and int(previous.get("total_results") or 0) > 0:
        result["listing_change_percent"] = round(
            (result["total_results"] - int(previous["total_results"])) /
            int(previous["total_results"]) * 100, 1
        )
    return result


def build_rfq_message(company: str, product_query: str, quantities: str, specifications: str = "") -> str:
    company_line = f" {company}" if company else ""
    specs = specifications.strip() or "Please provide the full product specifications and available compliance documents."
    return (f"Hello{company_line},\n\n"
            f"We are evaluating a long-term supply partnership for: {product_query}.\n\n"
            f"Please quote the unit price for these quantities: {quantities}.\n"
            "Please also include:\n"
            "- MOQ and sample price\n- DDP shipping cost to France\n- production and delivery lead time\n"
            "- available certifications and test reports\n- packaging and private-label options\n"
            "- warranty, defect policy and payment terms\n\n"
            f"Product requirements: {specs}\n\n"
            "No order is confirmed by this request. We will review the quotation and sample first.\n\n"
            "Best regards")
