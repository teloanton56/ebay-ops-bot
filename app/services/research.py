from statistics import median

from app.config import get_settings
from app.services.profit import calculate_profit, suggest_price


def _competition_points(listing_count: int) -> float:
    """Competition points never increase when active-listing competition rises."""
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
    }
    if not supplier_product or not summary["median_price"]:
        return summary

    settings = get_settings()
    market_price = round(float(summary["median_price"]) * 0.99, 2)
    market_profit = calculate_profit(supplier_product, market_price)
    safe_pricing = suggest_price(supplier_product, float(summary["median_price"]))
    suggested = float(safe_pricing["suggested_price"])

    margin = float(market_profit.get("margin_percent") or 0)
    profit = float(market_profit.get("estimated_profit") or 0)
    margin_points = 30.0 * min(max(margin, 0.0) / 40.0, 1.0)
    profit_points = 15.0 * min(max(profit, 0.0) / max(settings.min_profit_eur, 0.01), 1.0)
    competition_points = _competition_points(listing_count)

    shipping_days = int(supplier_product.get("shipping_days") or 99)
    if shipping_days <= settings.max_shipping_days:
        shipping_points = 15.0
    elif shipping_days <= settings.max_shipping_days + 3:
        shipping_points = 5.0
    else:
        shipping_points = 0.0

    stock = int(supplier_product.get("stock") or 0)
    if stock >= 10:
        stock_points = 15.0
    elif stock >= settings.min_stock:
        stock_points = 8.0
    else:
        stock_points = 0.0

    score = margin_points + profit_points + competition_points + shipping_points + stock_points
    price_gap_percent = (suggested - float(summary["median_price"])) / float(summary["median_price"]) * 100.0
    if price_gap_percent > 5:
        # A profitable floor far above the observed market should not become a Winner
        # merely because the bot can mathematically invent a higher selling price.
        score -= min(20.0, 5.0 + (price_gap_percent - 5.0) * 0.5)

    summary.update({
        "market_price_99": market_price,
        "suggested_price": round(suggested, 2),
        "minimum_viable_price": safe_pricing["minimum_viable_price"],
        "profit_at_market_price": market_profit,
        "profit_at_suggested_price": safe_pricing["profit"],
        "price_gap_percent": round(price_gap_percent, 1),
        "competition_points": round(competition_points, 1),
        "opportunity_score": round(max(min(score, 100), 0), 1),
        "note": (
            "Score basé sur prix eBay observés, rentabilité au prix du marché, concurrence, stock et délai. "
            "Davantage d'annonces concurrentes ne rapporte jamais davantage de points. Ce n'est pas un historique de ventes."
        ),
    })
    return summary
