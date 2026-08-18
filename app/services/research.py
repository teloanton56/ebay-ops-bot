from statistics import median
from app.services.profit import calculate_profit


def summarize_market(items: list[dict], supplier_product: dict | None = None) -> dict:
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
    summary = {
        "listing_count": len(items),
        "unique_sellers": len(sellers),
        "min_price": round(min(prices), 2) if prices else None,
        "median_price": round(median(prices), 2) if prices else None,
        "max_price": round(max(prices), 2) if prices else None,
    }
    if supplier_product and summary["median_price"]:
        suggested = round(summary["median_price"] * 0.99, 2)
        profit = calculate_profit(supplier_product, suggested)
        score = 0
        score += min(len(items), 20) * 1.5
        score += max(min(profit["margin_percent"], 40), -20) * 1.5
        if int(supplier_product.get("shipping_days") or 99) <= 5:
            score += 15
        if int(supplier_product.get("stock") or 0) >= 10:
            score += 10
        summary.update({
            "suggested_price": suggested,
            "profit_at_suggested_price": profit,
            "opportunity_score": round(max(min(score, 100), 0), 1),
            "note": "Score basé sur annonces actives/prix/marge. Ce n'est pas un historique de ventes.",
        })
    return summary
