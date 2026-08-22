from statistics import median

from app.config import get_settings
from app.services.cj_landed import load_cj_product_link, route_requirements
from app.services.profit import calculate_profit, suggest_price


def _competition_points(listing_count: int) -> float:
    if listing_count <= 0:
        return 0.0
    if listing_count <= 100:
        return 25.0
    if listing_count <= 500:
        return 20.0
    if listing_count <= 2000:
        return 12.0
    if listing_count <= 5000:
        return 6.0
    return 2.0


def _requirements(product: dict) -> tuple[dict, str]:
    settings = get_settings()
    link = load_cj_product_link(str(product.get("supplier_sku") or ""))
    warehouse = str(link.get("warehouse") or "").upper()
    if warehouse in {"US", "CN"}:
        return route_requirements(warehouse), warehouse
    return {
        "min_margin_percent": settings.min_margin_percent,
        "min_profit": settings.min_profit_amount,
        "min_stock": settings.min_stock,
        "max_shipping_days": settings.max_shipping_days,
    }, ""


def summarize_market(
    items: list[dict],
    supplier_product: dict | None = None,
    *,
    total_results: int | None = None,
) -> dict:
    prices = []
    sellers = set()
    for item in items:
        price = ((item.get("price") or {}).get("value"))
        try:
            prices.append(float(price))
        except (TypeError, ValueError):
            pass
        seller = (item.get("seller") or {}).get("username")
        if seller:
            sellers.add(seller)

    listing_count = int(total_results if total_results is not None else len(items))
    summary = {
        "listing_count": listing_count,
        "sample_size": len(items),
        "unique_sellers": len(sellers),
        "min_price": round(min(prices), 2) if prices else None,
        "median_price": round(median(prices), 2) if prices else None,
        "max_price": round(max(prices), 2) if prices else None,
        "currency": "USD",
        "marketplace": "EBAY_US",
    }
    if not supplier_product or not summary["median_price"]:
        return summary

    requirements, warehouse = _requirements(supplier_product)
    market_price = round(float(summary["median_price"]) * 0.99, 2)
    market_profit = calculate_profit(supplier_product, market_price)
    safe_pricing = suggest_price(
        supplier_product,
        float(summary["median_price"]),
        min_margin_percent=float(requirements["min_margin_percent"]),
        min_profit=float(requirements["min_profit"]),
    )
    suggested = float(safe_pricing["suggested_price"])

    margin = float(market_profit.get("margin_percent") or 0)
    profit = float(market_profit.get("estimated_profit") or 0)
    margin_points = 30.0 * min(max(margin, 0.0) / max(float(requirements["min_margin_percent"]), 1.0), 1.0)
    profit_points = 15.0 * min(max(profit, 0.0) / max(float(requirements["min_profit"]), 0.01), 1.0)
    competition_points = _competition_points(listing_count)

    shipping_days = int(supplier_product.get("shipping_days") or 99)
    max_days = int(requirements["max_shipping_days"])
    if shipping_days <= max_days:
        shipping_points = 15.0
    elif shipping_days <= max_days + 2:
        shipping_points = 4.0
    else:
        shipping_points = 0.0

    stock = int(supplier_product.get("stock") or 0)
    min_stock = int(requirements["min_stock"])
    if stock >= min_stock * 2:
        stock_points = 15.0
    elif stock >= min_stock:
        stock_points = 10.0
    else:
        stock_points = 0.0

    score = margin_points + profit_points + competition_points + shipping_points + stock_points
    price_gap_percent = (suggested - float(summary["median_price"])) / float(summary["median_price"]) * 100.0
    if price_gap_percent > 5:
        score -= min(25.0, 5.0 + (price_gap_percent - 5.0) * 0.6)

    route_label = "CJ US" if warehouse == "US" else "CJ China → US" if warehouse == "CN" else "Route CJ non confirmée"
    summary.update({
        "market_price_99": market_price,
        "suggested_price": round(suggested, 2),
        "minimum_viable_price": safe_pricing["minimum_viable_price"],
        "profit_at_market_price": market_profit,
        "profit_at_suggested_price": safe_pricing["profit"],
        "price_gap_percent": round(price_gap_percent, 1),
        "competition_points": round(competition_points, 1),
        "opportunity_score": round(max(min(score, 100), 0), 1),
        "route": route_label,
        "route_requirements": requirements,
        "note": (
            f"Score eBay US basé sur prix, concurrence et économie de la route {route_label}. "
            "Davantage d'annonces concurrentes ne rapporte jamais davantage de points."
        ),
    })
    return summary
