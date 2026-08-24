from datetime import datetime, timedelta, timezone

from app.config import get_settings
from app.services.profit import order_fee_for_price
from app.services.supplier_refresh import is_verified_cj_product


MILESTONES = (5_000, 10_000, 50_000, 100_000)


def _day(date: datetime) -> dict:
    return {"date": date.date().isoformat(), "revenue": 0.0, "orders": 0,
            "supplier_cost": 0.0, "shipping_cost": 0.0, "ebay_fees": 0.0,
            "ad_fees": 0.0, "returns_reserve": 0.0, "fixed_fees": 0.0,
            "net_result": 0.0}


def _round_day(row: dict) -> dict:
    return {key: round(value, 2) if isinstance(value, float) else value for key, value in row.items()}


def empty_series(days: int, now: datetime | None = None) -> list[dict]:
    now = now or datetime.now(timezone.utc)
    return [_day(now - timedelta(days=days - index - 1)) for index in range(days)]


def ebay_series(orders: list[dict], products: list[dict], days: int,
                now: datetime | None = None) -> tuple[list[dict], dict]:
    now = now or datetime.now(timezone.utc)
    start = (now - timedelta(days=days - 1)).date()
    rows = {_day(now - timedelta(days=days - index - 1))["date"]:
            _day(now - timedelta(days=days - index - 1)) for index in range(days)}
    active_products = [
        product for product in products
        if is_verified_cj_product(product)
    ]
    product_by_sku = {str(item.get("supplier_sku") or ""): item for item in active_products}
    known_lines = total_lines = 0
    settings = get_settings()

    for order in orders:
        raw_date = order.get("creationDate") or order.get("lastModifiedDate")
        try:
            created = datetime.fromisoformat(str(raw_date).replace("Z", "+00:00"))
        except (TypeError, ValueError):
            continue
        if created.date() < start or created.date() > now.date():
            continue
        row = rows.get(created.date().isoformat())
        if not row:
            continue

        total_block = (order.get("pricingSummary") or {}).get("total") or {}
        if str(total_block.get("currency") or "USD").upper() != "USD":
            continue
        revenue = float(total_block.get("value") or 0)
        row["revenue"] += revenue
        row["orders"] += 1

        unknown_revenue = 0.0
        for line in order.get("lineItems") or []:
            total_lines += 1
            quantity = max(int(line.get("quantity") or 1), 1)
            sku = str(line.get("sku") or line.get("legacyItemId") or "")
            product = product_by_sku.get(sku)
            line_revenue = float((line.get("lineItemCost") or {}).get("value") or 0) * quantity
            if product:
                known_lines += 1
                row["supplier_cost"] += float(product.get("supplier_cost") or 0) * quantity
                row["shipping_cost"] += float(product.get("shipping_cost") or 0) * quantity
            else:
                # Conservative temporary estimate only when an old/unknown SKU cannot
                # be matched. Completeness makes this uncertainty visible.
                unknown_revenue += line_revenue
        if unknown_revenue:
            row["supplier_cost"] += unknown_revenue * 0.35
            row["shipping_cost"] += unknown_revenue * 0.10

        row["ebay_fees"] += revenue * settings.default_ebay_fee_percent / 100
        row["ad_fees"] += revenue * settings.default_ad_rate_percent / 100
        row["returns_reserve"] += revenue * settings.default_return_reserve_percent / 100
        row["fixed_fees"] += order_fee_for_price(revenue)

    for row in rows.values():
        costs = sum(row[key] for key in (
            "supplier_cost", "shipping_cost", "ebay_fees", "ad_fees", "returns_reserve", "fixed_fees"
        ))
        row["net_result"] = row["revenue"] - costs
    completeness = round(known_lines / total_lines * 100, 1) if total_lines else 100.0
    return [_round_day(row) for row in rows.values()], {
        "known_lines": known_lines,
        "total_lines": total_lines,
        "cost_completeness_percent": completeness,
    }


def summarize(series: list[dict], *, days: int, target: int,
              source: str, completeness: dict | None = None) -> dict:
    keys = ("revenue", "orders", "supplier_cost", "shipping_cost", "ebay_fees",
            "ad_fees", "returns_reserve", "fixed_fees", "net_result")
    totals = {key: round(sum(float(row.get(key) or 0) for row in series), 2) for key in keys}
    totals["orders"] = int(round(totals["orders"]))
    revenue = totals["revenue"]
    daily_average = revenue / max(days, 1)
    remaining = max(target - revenue, 0)
    milestones = [{
        "amount": amount,
        "reached": revenue >= amount,
        "progress_percent": round(min(revenue / amount * 100, 100), 1),
        "remaining": round(max(amount - revenue, 0), 2),
    } for amount in MILESTONES]
    costs = {
        "supplier": totals["supplier_cost"],
        "shipping": totals["shipping_cost"],
        "ebay": totals["ebay_fees"],
        "ads": totals["ad_fees"],
        "returns": totals["returns_reserve"],
        "fixed": totals["fixed_fees"],
    }
    return {
        "source": source,
        "currency": "USD",
        "marketplace": "EBAY_US",
        "period_days": days,
        "series": series,
        "totals": {
            **totals,
            "average_order_value": round(revenue / totals["orders"], 2) if totals["orders"] else 0,
            "net_margin_percent": round(totals["net_result"] / revenue * 100, 1) if revenue else 0,
            "daily_revenue_average": round(daily_average, 2),
        },
        "costs": costs,
        "milestones": milestones,
        "goal": {
            "amount": target,
            "progress_percent": round(min(revenue / target * 100, 100), 1),
            "remaining": round(remaining, 2),
        },
        "completeness": completeness or {"cost_completeness_percent": 100.0},
        "disclaimer": "Estimation de pilotage en USD, hors fiscalité, remboursements réels et comptabilité officielle.",
    }
