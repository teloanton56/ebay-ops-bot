from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any

from app.config import get_settings
from app.services.cj import CJClient, CJError
from app.services.db import kv_get, kv_set
from app.services.profit import calculate_profit


ALLOWED_WAREHOUSE_COUNTRIES = ("US", "CN")
_CJ_LINK_PREFIX = "product:cj-link:"
_MAX_VARIANTS_PER_ROUTE = 8


def delivery_days(value: Any) -> int | None:
    values = [int(item) for item in re.findall(r"\d+", str(value or ""))]
    return max(values) if values else None


def _inventory_stock(variant: dict[str, Any], country: str) -> int:
    country = country.upper()
    return sum(
        int(row.get("stock") or 0)
        for row in variant.get("inventories") or []
        if str(row.get("country_code") or "").upper() == country
    )


def _storage_ids(variant: dict[str, Any], country: str) -> list[str]:
    country = country.upper()
    values: list[str] = []
    for row in variant.get("inventories") or []:
        if str(row.get("country_code") or "").upper() != country:
            continue
        for value in row.get("storage_ids") or []:
            clean = str(value or "").strip()
            if clean and clean not in values:
                values.append(clean)
    return values


def _merge_authoritative_inventory(detail: dict[str, Any], inventory: dict[str, Any]) -> None:
    by_vid = inventory.get("variant_inventories") or {}
    for variant in detail.get("variants") or []:
        vid = str(variant.get("vid") or "").strip()
        rows = by_vid.get(vid)
        if rows:
            variant["inventories"] = rows
            variant["stock"] = sum(int(row.get("stock") or 0) for row in rows)
    detail["product_inventories"] = inventory.get("product_inventories") or []


def _variant_candidates_for_country(
    variants: list[dict[str, Any]],
    country: str,
    preferred_variant_id: str = "",
) -> list[dict[str, Any]]:
    country = country.upper()
    preferred_variant_id = str(preferred_variant_id or "").strip()
    if preferred_variant_id:
        preferred = next(
            (row for row in variants if str(row.get("vid") or "") == preferred_variant_id),
            None,
        )
        if not preferred:
            raise CJError("La variante CJ enregistrée n'existe plus")
        if float(preferred.get("price_usd") or 0) <= 0:
            raise CJError("La variante CJ enregistrée n'a plus de prix exploitable")
        if _inventory_stock(preferred, country) <= 0:
            raise CJError(f"La variante CJ enregistrée n'a plus de stock {country}")
        return [preferred]

    usable = [
        row for row in variants
        if float(row.get("price_usd") or 0) > 0 and _inventory_stock(row, country) > 0
    ]
    usable.sort(
        key=lambda row: (
            float(row.get("price_usd") or 0),
            -_inventory_stock(row, country),
            str(row.get("name") or ""),
        )
    )
    return usable[:_MAX_VARIANTS_PER_ROUTE]


def choose_freight(options: list[dict[str, Any]], max_days: int) -> dict[str, Any] | None:
    usable: list[tuple[dict[str, Any], float, int | None]] = []
    for row in options:
        try:
            price = float(row.get("price_usd") if row.get("price_usd") is not None else 0)
        except (TypeError, ValueError):
            continue
        if price < 0:
            continue
        days = delivery_days(row.get("delivery_days"))
        usable.append((row, price, days))
    if not usable:
        return None

    on_time = [item for item in usable if item[2] is not None and item[2] <= max_days]
    pool = on_time or usable
    selected, _, _ = min(
        pool,
        key=lambda item: (item[1], item[2] if item[2] is not None else 999),
    )
    return selected


async def _refresh_variant_inventory_if_needed(
    client: CJClient,
    detail: dict[str, Any],
    warehouse: str,
) -> None:
    if any(_inventory_stock(row, warehouse) > 0 for row in detail.get("variants") or []):
        return
    product_has_stock = any(
        str(row.get("country_code") or "").upper() == warehouse and int(row.get("stock") or 0) > 0
        for row in detail.get("product_inventories") or []
    )
    if not product_has_stock or not hasattr(client, "variant_inventory"):
        return

    for variant in (detail.get("variants") or [])[:_MAX_VARIANTS_PER_ROUTE]:
        vid = str(variant.get("vid") or "").strip()
        if not vid:
            continue
        try:
            rows = await client.variant_inventory(vid)
        except CJError:
            continue
        if rows:
            variant["inventories"] = rows
            variant["stock"] = sum(int(row.get("stock") or 0) for row in rows)
        if _inventory_stock(variant, warehouse) > 0:
            # Keep looking only until we have enough viable candidates to try.
            if sum(1 for row in detail.get("variants") or [] if _inventory_stock(row, warehouse) > 0) >= 3:
                break


async def _freight_for_variant(
    client: CJClient,
    detail: dict[str, Any],
    variant: dict[str, Any],
    *,
    warehouse: str,
    destination_country: str,
    max_shipping_days: int,
) -> dict[str, Any] | None:
    storage_ids = _storage_ids(variant, warehouse)
    standard_error = ""
    try:
        options = await client.freight_options(
            str(variant.get("vid") or ""),
            start_country=warehouse,
            destination_country=destination_country,
            storage_ids=storage_ids,
        )
        freight = choose_freight(options, max_shipping_days)
        if freight:
            return freight
    except CJError as exc:
        standard_error = str(exc)

    if hasattr(client, "freight_options_tip"):
        try:
            options = await client.freight_options_tip(
                variant,
                detail,
                start_country=warehouse,
                destination_country=destination_country,
                storage_ids=storage_ids,
            )
            freight = choose_freight(options, max_shipping_days)
            if freight:
                return freight
        except CJError as exc:
            if not standard_error:
                standard_error = str(exc)

    if standard_error:
        raise CJError(standard_error)
    return None


async def _resolve_route_from_detail(
    client: CJClient,
    detail: dict[str, Any],
    *,
    warehouse: str,
    preferred_variant_id: str = "",
    destination_country: str = "US",
    max_shipping_days: int,
    fallback_price_usd: float = 0.0,
) -> dict[str, Any]:
    warehouse = warehouse.upper()
    if warehouse not in ALLOWED_WAREHOUSE_COUNTRIES:
        raise CJError("La stratégie v0.23 autorise uniquement les entrepôts CJ US et CN")

    await _refresh_variant_inventory_if_needed(client, detail, warehouse)
    candidates = _variant_candidates_for_country(
        detail.get("variants") or [],
        warehouse,
        preferred_variant_id,
    )
    if not candidates:
        product_stock = sum(
            int(row.get("stock") or 0)
            for row in detail.get("product_inventories") or []
            if str(row.get("country_code") or "").upper() == warehouse
        )
        suffix = f" (stock produit annoncé : {product_stock})" if product_stock else ""
        raise CJError(f"Aucune variante CJ en stock {warehouse}{suffix}")

    quoted_routes: list[dict[str, Any]] = []
    errors: list[str] = []
    for variant in candidates:
        try:
            freight = await _freight_for_variant(
                client,
                detail,
                variant,
                warehouse=warehouse,
                destination_country=destination_country,
                max_shipping_days=max_shipping_days,
            )
            if not freight:
                errors.append(f"{variant.get('sku') or variant.get('vid')}: aucun transport")
                continue
            days = delivery_days(freight.get("delivery_days"))
            if days is None or days <= 0:
                errors.append(f"{variant.get('sku') or variant.get('vid')}: délai absent")
                continue

            product_usd = float(variant.get("price_usd") or fallback_price_usd or 0)
            if product_usd <= 0:
                errors.append(f"{variant.get('sku') or variant.get('vid')}: prix invalide")
                continue
            shipping_usd = float(freight.get("price_usd") if freight.get("price_usd") is not None else 0)
            warehouse_stock = _inventory_stock(variant, warehouse)
            quoted_routes.append({
                "pid": str(detail.get("pid") or ""),
                "product_name": detail.get("name") or "Produit CJ",
                "variant_id": str(variant.get("vid") or ""),
                "variant_sku": str(variant.get("sku") or ""),
                "variant_name": variant.get("name") or "Variante CJ",
                "image_url": variant.get("image_url") or detail.get("image_url") or "",
                "stock": warehouse_stock,
                "warehouse": warehouse,
                "supplier_cost": round(product_usd, 2),
                "shipping_cost": round(shipping_usd, 2),
                "landed_cost": round(product_usd + shipping_usd, 2),
                "shipping_days": days,
                "freight_name": freight.get("name") or "CJ",
                "freight_source": freight.get("source") or "freightCalculate",
                "currency": "USD",
                "destination_country": destination_country,
                "storage_ids": _storage_ids(variant, warehouse),
                "risk_flags": detail.get("risk_flags") or [],
            })
        except CJError as exc:
            errors.append(f"{variant.get('sku') or variant.get('vid')}: {exc}")

    if not quoted_routes:
        detail_text = "; ".join(errors[:3])
        raise CJError(
            f"CJ ne propose aucun transport exploitable de {warehouse} vers {destination_country}"
            + (f" — {detail_text}" if detail_text else "")
        )

    quoted_routes.sort(
        key=lambda route: (
            int(route.get("shipping_days") or 999) > max_shipping_days,
            float(route.get("landed_cost") or 999999),
            int(route.get("shipping_days") or 999),
            -int(route.get("stock") or 0),
        )
    )
    return quoted_routes[0]


async def resolve_cj_landed_routes(
    client: CJClient,
    pid: str,
    *,
    fallback_price_usd: float = 0.0,
    preferred_variant_id: str = "",
    destination_country: str = "US",
) -> dict[str, dict[str, Any]]:
    """Return independently verified US and China fulfillment routes when available."""
    pid = str(pid or "").strip()
    if not pid:
        raise CJError("Identifiant produit CJ manquant")

    settings = get_settings()
    detail = await client.product_detail(pid)
    detail["pid"] = str(detail.get("pid") or pid)
    try:
        inventory = await client.product_inventory(pid)
        _merge_authoritative_inventory(detail, inventory)
    except CJError as exc:
        detail["inventory_warning"] = str(exc)

    routes: dict[str, dict[str, Any]] = {}
    route_errors: dict[str, str] = {}
    policies = {
        "US": settings.cj_us_max_shipping_days,
        "CN": settings.cj_cn_max_shipping_days,
    }
    for warehouse in ALLOWED_WAREHOUSE_COUNTRIES:
        try:
            routes[warehouse] = await _resolve_route_from_detail(
                client,
                detail,
                warehouse=warehouse,
                preferred_variant_id=preferred_variant_id,
                destination_country=destination_country,
                max_shipping_days=policies[warehouse],
                fallback_price_usd=fallback_price_usd,
            )
        except CJError as exc:
            route_errors[warehouse] = str(exc)
    if not routes:
        detail_text = " | ".join(f"{country}: {message}" for country, message in route_errors.items())
        raise CJError(
            "Aucun stock CJ US ou Chine avec transport exploitable vers les États-Unis"
            + (f". Détail : {detail_text}" if detail_text else "")
        )
    return routes


def route_requirements(warehouse: str) -> dict[str, float | int]:
    s = get_settings()
    if warehouse.upper() == "CN":
        return {
            "min_margin_percent": s.cj_cn_min_margin_percent,
            "min_profit": s.cj_cn_min_profit_usd,
            "min_stock": s.cj_cn_min_stock,
            "max_shipping_days": s.cj_cn_max_shipping_days,
        }
    return {
        "min_margin_percent": s.cj_us_min_margin_percent,
        "min_profit": s.cj_us_min_profit_usd,
        "min_stock": s.cj_us_min_stock,
        "max_shipping_days": s.cj_us_max_shipping_days,
    }


def evaluate_route(route: dict[str, Any], reference_price: float | None = None) -> dict[str, Any]:
    requirements = route_requirements(str(route.get("warehouse") or "US"))
    profit = calculate_profit(route, reference_price) if reference_price else None
    stock = int(route.get("stock") or 0)
    days = int(route.get("shipping_days") or 0)
    eligible = stock >= int(requirements["min_stock"]) and 0 < days <= int(requirements["max_shipping_days"])
    if profit is not None:
        eligible = eligible and (
            float(profit.get("margin_percent") or -999) >= float(requirements["min_margin_percent"])
            and float(profit.get("estimated_profit") or -999) >= float(requirements["min_profit"])
        )
    return {
        **route,
        "requirements": requirements,
        "profit": profit,
        "eligible": bool(eligible),
    }


def select_cj_route(
    routes: dict[str, dict[str, Any]],
    *,
    reference_price: float | None = None,
) -> dict[str, Any]:
    """US first; China only when its stricter economics and delivery rules pass."""
    evaluated = {
        warehouse: evaluate_route(route, reference_price)
        for warehouse, route in routes.items()
    }
    us = evaluated.get("US")
    cn = evaluated.get("CN")
    if us and us["eligible"]:
        return us
    if cn and cn["eligible"]:
        return cn
    if reference_price is None:
        if us:
            return us
        if cn:
            return cn
    if us:
        return us
    if cn:
        return cn
    raise CJError("Aucune route CJ exploitable vers les États-Unis")


async def resolve_cj_landed_offer(
    client: CJClient,
    pid: str,
    *,
    fallback_price_usd: float = 0.0,
    preferred_variant_id: str = "",
    preferred_warehouse: str = "",
    destination_country: str = "US",
    reference_price: float | None = None,
    **_: Any,
) -> dict[str, Any]:
    """Single source of truth for CJ US-market landed cost across the entire bot."""
    routes = await resolve_cj_landed_routes(
        client,
        pid,
        fallback_price_usd=fallback_price_usd,
        preferred_variant_id=preferred_variant_id,
        destination_country=destination_country,
    )
    if preferred_warehouse:
        preferred = routes.get(preferred_warehouse.upper())
        if preferred:
            return evaluate_route(preferred, reference_price)
    return select_cj_route(routes, reference_price=reference_price)


def _link_key(supplier_sku: str) -> str:
    return _CJ_LINK_PREFIX + str(supplier_sku or "").strip()


def save_cj_product_link(supplier_sku: str, landed: dict[str, Any]) -> None:
    payload = {
        "pid": str(landed.get("pid") or ""),
        "variant_id": str(landed.get("variant_id") or ""),
        "warehouse": str(landed.get("warehouse") or ""),
        "risk_flags": landed.get("risk_flags") or [],
        "verified_at": datetime.now(timezone.utc).isoformat(),
    }
    kv_set(_link_key(supplier_sku), json.dumps(payload, ensure_ascii=False))


def load_cj_product_link(supplier_sku: str) -> dict[str, Any]:
    raw = kv_get(_link_key(supplier_sku))
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}
