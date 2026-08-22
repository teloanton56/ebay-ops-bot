from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any

from app.config import get_settings
from app.services.cj import CJClient, CJError
from app.services.db import kv_get, kv_set


PREFERRED_WAREHOUSE_COUNTRIES = ("FR", "DE", "ES", "IT", "PL", "NL", "BE", "CZ", "CN")
_CJ_LINK_PREFIX = "product:cj-link:"


def delivery_days(value: Any) -> int | None:
    values = [int(item) for item in re.findall(r"\d+", str(value or ""))]
    return max(values) if values else None


def _choose_variant(variants: list[dict[str, Any]], preferred_variant_id: str = "") -> dict[str, Any]:
    usable = [row for row in variants if float(row.get("price_usd") or 0) > 0]
    if not usable:
        raise CJError("CJ ne retourne aucune variante exploitable pour ce produit")

    preferred_variant_id = str(preferred_variant_id or "").strip()
    if preferred_variant_id:
        preferred = next((row for row in usable if str(row.get("vid") or "") == preferred_variant_id), None)
        if preferred and int(preferred.get("stock") or 0) > 0:
            return preferred

    stocked = [row for row in usable if int(row.get("stock") or 0) > 0]
    pool = stocked or usable
    return min(pool, key=lambda row: (float(row.get("price_usd") or 0), -int(row.get("stock") or 0), str(row.get("name") or "")))


def source_country(variant: dict[str, Any]) -> str:
    inventories = [row for row in variant.get("inventories") or [] if int(row.get("stock") or 0) > 0]
    for country in PREFERRED_WAREHOUSE_COUNTRIES:
        if any(str(row.get("country_code") or "").upper() == country for row in inventories):
            return country
    return str(next((row.get("country_code") for row in inventories if row.get("country_code")), "CN")).upper()


def choose_freight(options: list[dict[str, Any]], max_days: int) -> dict[str, Any] | None:
    usable: list[tuple[dict[str, Any], float, int | None]] = []
    for row in options:
        try:
            price = float(row.get("price_usd") or 0)
        except (TypeError, ValueError):
            continue
        if price < 0:
            continue
        days = delivery_days(row.get("delivery_days"))
        usable.append((row, price, days))
    if not usable:
        return None

    fast = [item for item in usable if item[2] is not None and item[2] <= max_days]
    pool = fast or usable
    selected, _, _ = min(pool, key=lambda item: (item[1], item[2] if item[2] is not None else 999))
    return selected


async def resolve_cj_landed_offer(
    client: CJClient,
    pid: str,
    *,
    fallback_price_usd: float = 0.0,
    preferred_variant_id: str = "",
    destination_country: str = "FR",
    max_shipping_days: int | None = None,
    exchange_rate: float | None = None,
) -> dict[str, Any]:
    """Resolve one CJ product into the exact supplier snapshot used everywhere.

    Search, Margin Hunter, catalogue addition and pre-publication refresh must all
    share this function so a product cannot be scored with one warehouse/freight
    option then added or published with another.
    """
    pid = str(pid or "").strip()
    if not pid:
        raise CJError("Identifiant produit CJ manquant")

    settings = get_settings()
    maximum = settings.max_shipping_days if max_shipping_days is None else max(int(max_shipping_days), 1)
    detail = await client.product_detail(pid)
    variant = _choose_variant(detail.get("variants") or [], preferred_variant_id)
    country = source_country(variant)
    freight_options = await client.freight_options(
        str(variant.get("vid") or ""),
        start_country=country,
        destination_country=destination_country,
    )
    freight = choose_freight(freight_options, maximum)
    if not freight:
        raise CJError("CJ ne propose aucun transport exploitable vers la France pour cette variante")

    days = delivery_days(freight.get("delivery_days"))
    if days is None or days <= 0:
        raise CJError("CJ ne fournit pas de délai exploitable pour le transport sélectionné")

    if exchange_rate is None:
        exchange = await client.usd_to_eur()
        exchange_rate = float(exchange["rate"])
        exchange_date = str(exchange.get("date") or "")
    else:
        exchange_rate = float(exchange_rate)
        exchange_date = ""
    if exchange_rate <= 0:
        raise CJError("Taux USD/EUR CJ invalide")

    product_usd = float(variant.get("price_usd") or fallback_price_usd or 0)
    if product_usd <= 0:
        raise CJError("Prix fournisseur CJ invalide")
    shipping_usd = float(freight.get("price_usd") or 0)
    supplier_cost = round(product_usd * exchange_rate, 2)
    shipping_cost = round(shipping_usd * exchange_rate, 2)

    return {
        "pid": str(detail.get("pid") or pid),
        "product_name": detail.get("name") or "Produit CJ",
        "variant_id": str(variant.get("vid") or ""),
        "variant_sku": str(variant.get("sku") or ""),
        "variant_name": variant.get("name") or "Variante CJ",
        "image_url": variant.get("image_url") or detail.get("image_url") or "",
        "stock": int(variant.get("stock") or 0),
        "warehouse": country,
        "supplier_cost": supplier_cost,
        "shipping_cost": shipping_cost,
        "landed_cost": round(supplier_cost + shipping_cost, 2),
        "shipping_days": days,
        "freight_name": freight.get("name") or "CJ",
        "exchange_rate": exchange_rate,
        "exchange_date": exchange_date,
        "risk_flags": detail.get("risk_flags") or [],
    }


def _link_key(supplier_sku: str) -> str:
    return _CJ_LINK_PREFIX + str(supplier_sku or "").strip()


def save_cj_product_link(supplier_sku: str, landed: dict[str, Any]) -> None:
    payload = {
        "pid": str(landed.get("pid") or ""),
        "variant_id": str(landed.get("variant_id") or ""),
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
