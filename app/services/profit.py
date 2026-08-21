from app.config import get_settings
import math


def calculate_profit(product: dict, sale_price: float | None = None) -> dict:
    s = get_settings()
    explicit_price = sale_price is not None
    raw_price = sale_price if explicit_price else product.get("target_price")
    has_price = raw_price is not None and float(raw_price or 0) > 0
    price = float(raw_price or 0)
    supplier = float(product.get("supplier_cost") or 0)
    shipping = float(product.get("shipping_cost") or 0)
    landed_cost = supplier + shipping

    if not has_price:
        variable_rate = (s.default_ebay_fee_percent + s.default_ad_rate_percent + s.default_return_reserve_percent) / 100
        break_even = landed_cost + s.default_fixed_fee
        if variable_rate < 1:
            break_even = break_even / (1 - variable_rate)
        return {
            "sale_price": None,
            "supplier_cost": round(supplier, 2),
            "shipping_cost": round(shipping, 2),
            "landed_cost": round(landed_cost, 2),
            "estimated_ebay_fee": None,
            "estimated_ad_fee": None,
            "returns_reserve": None,
            "fixed_fee": None,
            "total_estimated_cost": None,
            "estimated_profit": None,
            "margin_percent": None,
            "roi_percent": None,
            "break_even_price": round(break_even, 2),
        }

    ebay_fee = price * s.default_ebay_fee_percent / 100
    ad_fee = price * s.default_ad_rate_percent / 100
    returns_reserve = price * s.default_return_reserve_percent / 100
    fixed = s.default_fixed_fee
    total_cost = landed_cost + ebay_fee + ad_fee + returns_reserve + fixed
    profit = price - total_cost
    margin = profit / price * 100
    roi = (profit / landed_cost * 100) if landed_cost else 0
    break_even = landed_cost + fixed
    variable_rate = (s.default_ebay_fee_percent + s.default_ad_rate_percent + s.default_return_reserve_percent) / 100
    if variable_rate < 1:
        break_even = break_even / (1 - variable_rate)
    return {
        "sale_price": round(price, 2),
        "supplier_cost": round(supplier, 2),
        "shipping_cost": round(shipping, 2),
        "landed_cost": round(landed_cost, 2),
        "estimated_ebay_fee": round(ebay_fee, 2),
        "estimated_ad_fee": round(ad_fee, 2),
        "returns_reserve": round(returns_reserve, 2),
        "fixed_fee": round(fixed, 2),
        "total_estimated_cost": round(total_cost, 2),
        "estimated_profit": round(profit, 2),
        "margin_percent": round(margin, 2),
        "roi_percent": round(roi, 2),
        "break_even_price": round(break_even, 2),
    }


def suggest_price(product: dict, market_median: float | None = None) -> dict:
    """Smallest psychological price satisfying both configured margin and profit thresholds."""
    s = get_settings()
    landed = float(product.get("supplier_cost") or 0) + float(product.get("shipping_cost") or 0)
    variable = (s.default_ebay_fee_percent + s.default_ad_rate_percent + s.default_return_reserve_percent) / 100
    by_profit = (landed + s.default_fixed_fee + s.min_profit_eur) / max(1 - variable, 0.01)
    by_margin = (landed + s.default_fixed_fee) / max(1 - variable - s.min_margin_percent / 100, 0.01)
    floor = max(by_profit, by_margin)
    market_target = float(market_median) * 0.99 if market_median else floor
    raw = max(floor, market_target)
    price = math.ceil((raw + 0.01) * 10) / 10 - 0.01
    return {"suggested_price": round(price, 2), "minimum_viable_price": round(floor, 2),
            "market_median": market_median, "profit": calculate_profit(product, price)}
