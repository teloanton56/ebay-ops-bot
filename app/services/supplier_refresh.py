from __future__ import annotations

from typing import Any

from app.services.cj import CJClient, CJError
from app.services.cj_landed import load_cj_product_link, resolve_cj_landed_offer, save_cj_product_link
from app.services.db import get_product, get_supplier, upsert_product


class SupplierRefreshError(RuntimeError):
    pass


def supplier_for_product(product: dict[str, Any]) -> dict[str, Any] | None:
    supplier_id = product.get("supplier_id")
    if not supplier_id:
        return None
    return get_supplier(int(supplier_id))


def is_verified_cj_product(
    product: dict[str, Any],
    supplier: dict[str, Any] | None = None,
) -> bool:
    if (
        not product
        or str(product.get("marketplace_id") or "") != "EBAY_US"
        or str(product.get("currency") or "").upper() != "USD"
    ):
        return False
    supplier = supplier or supplier_for_product(product)
    if str((supplier or {}).get("provider_code") or "").casefold() != "cj":
        return False
    link = load_cj_product_link(str(product.get("supplier_sku") or ""))
    return bool(
        str(link.get("pid") or "").strip()
        and str(link.get("variant_id") or "").strip()
        and str(link.get("warehouse") or "").upper() in {"US", "CN"}
        and str(link.get("destination_country") or "").upper() == "US"
        and str(link.get("currency") or "").upper() == "USD"
    )


async def refresh_product_from_supplier(product: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    """Refresh the exact CJ route immediately before a real eBay write.

    The bot never switches a live product silently from US to China or vice versa,
    because that would change item location and delivery promises on eBay.
    """
    if not product or not product.get("id"):
        raise SupplierRefreshError("Produit introuvable pour revalidation fournisseur")

    supplier = supplier_for_product(product)
    code = str((supplier or {}).get("provider_code") or "").strip().lower()
    if code != "cj":
        raise SupplierRefreshError("Seul CJ Dropshipping est autorisé avant publication eBay")

    link = load_cj_product_link(str(product.get("supplier_sku") or ""))
    pid = str(link.get("pid") or "").strip()
    variant_id = str(link.get("variant_id") or "").strip()
    warehouse = str(link.get("warehouse") or "").upper()
    destination_country = str(link.get("destination_country") or "").upper()
    currency = str(link.get("currency") or "").upper()
    if (
        not pid
        or not variant_id
        or warehouse not in {"US", "CN"}
        or destination_country != "US"
        or currency != "USD"
    ):
        raise SupplierRefreshError(
            "Ce produit n'a pas de route CJ US/CN vers les États-Unis en USD. "
            "Relancez-le depuis CJ ou Margin Hunter avant publication."
        )

    client = CJClient()
    if not client.status().get("connected"):
        raise SupplierRefreshError("CJ n'est pas connecté : publication bloquée")

    target_price = float(product.get("target_price") or 0)
    if target_price <= 0:
        raise SupplierRefreshError("Prix eBay cible manquant avant revalidation CJ")

    try:
        landed = await resolve_cj_landed_offer(
            client,
            pid,
            fallback_price_usd=0,
            preferred_variant_id=variant_id,
            preferred_warehouse=warehouse,
            destination_country="US",
            reference_price=target_price,
        )
    except CJError as exc:
        raise SupplierRefreshError(f"Revalidation CJ impossible : {exc}") from exc

    if str(landed.get("warehouse") or "").upper() != warehouse:
        raise SupplierRefreshError(
            f"La route CJ {warehouse} n'est plus exploitable. Le bot refuse de basculer automatiquement "
            "vers un autre pays d'expédition ; ressourcez le produit avant publication."
        )
    if not landed.get("eligible"):
        req = landed.get("requirements") or {}
        raise SupplierRefreshError(
            f"Route CJ {warehouse} hors seuils : stock {landed.get('stock')} · délai {landed.get('shipping_days')}j. "
            f"Minimum attendu : stock {req.get('min_stock')} · marge {req.get('min_margin_percent')}% · "
            f"profit ${req.get('min_profit')} · délai ≤ {req.get('max_shipping_days')}j."
        )

    refreshed_data = {
        **product,
        "supplier_cost": landed["supplier_cost"],
        "shipping_cost": landed["shipping_cost"],
        "stock": landed["stock"],
        "shipping_days": landed["shipping_days"],
        "marketplace_id": "EBAY_US",
        "currency": "USD",
    }
    product_id = upsert_product(refreshed_data)
    save_cj_product_link(str(product.get("supplier_sku") or ""), landed)
    refreshed = get_product(product_id)
    if not refreshed:
        raise SupplierRefreshError("Produit introuvable après revalidation CJ")

    return refreshed, {
        "provider": "cj",
        "provider_name": "CJ Dropshipping",
        "verified": True,
        "supplier_cost": landed["supplier_cost"],
        "shipping_cost": landed["shipping_cost"],
        "landed_cost": landed["landed_cost"],
        "stock": landed["stock"],
        "shipping_days": landed["shipping_days"],
        "warehouse": warehouse,
        "route": "CJ US" if warehouse == "US" else "CJ China → US",
        "variant_id": landed["variant_id"],
        "freight_name": landed["freight_name"],
        "requirements": landed.get("requirements") or {},
        "profit": landed.get("profit"),
        "currency": "USD",
    }
