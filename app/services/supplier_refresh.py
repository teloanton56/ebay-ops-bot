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


async def refresh_product_from_supplier(product: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    """Refresh the supplier facts that can change before an eBay write.

    CJ is the only current first-class supplier for which the bot can re-check
    variant, stock, freight and delivery end-to-end. Marketplace sources remain
    research/sourcing inputs until equivalent fulfillment verification exists.
    """
    if not product or not product.get("id"):
        raise SupplierRefreshError("Produit introuvable pour revalidation fournisseur")

    supplier = supplier_for_product(product)
    code = str((supplier or {}).get("provider_code") or "").strip().lower()
    if not code:
        raise SupplierRefreshError("Fournisseur non vérifiable automatiquement avant publication")
    if code in {"amazon", "aliexpress"}:
        raise SupplierRefreshError(
            f"{(supplier or {}).get('name') or code.title()} ne fournit pas encore au bot une revalidation complète "
            "stock + transport France + délai. Utilisez cette source pour le sourcing, pas pour une publication directe."
        )
    if code != "cj":
        raise SupplierRefreshError(f"Revalidation live non implémentée pour le fournisseur {code}")

    link = load_cj_product_link(str(product.get("supplier_sku") or ""))
    pid = str(link.get("pid") or "").strip()
    if not pid:
        raise SupplierRefreshError(
            "Ce produit CJ a été ajouté avant l'enregistrement du lien produit CJ. "
            "Relancez-le depuis Fournisseurs ou Margin Hunter puis ajoutez-le à nouveau avant publication."
        )

    client = CJClient()
    if not client.status().get("connected"):
        raise SupplierRefreshError("CJ n'est pas connecté : publication bloquée tant que le fournisseur n'est pas revalidé")

    try:
        landed = await resolve_cj_landed_offer(
            client,
            pid,
            fallback_price_usd=0,
            preferred_variant_id=str(link.get("variant_id") or ""),
        )
    except CJError as exc:
        raise SupplierRefreshError(f"Revalidation CJ impossible : {exc}") from exc

    refreshed_data = {
        **product,
        "supplier_cost": landed["supplier_cost"],
        "shipping_cost": landed["shipping_cost"],
        "stock": landed["stock"],
        "shipping_days": landed["shipping_days"],
        "currency": "EUR",
    }
    product_id = upsert_product(refreshed_data)
    save_cj_product_link(str(product.get("supplier_sku") or ""), landed)
    refreshed = get_product(product_id)
    if not refreshed:
        raise SupplierRefreshError("Produit introuvable après revalidation CJ")

    return refreshed, {
        "provider": "cj",
        "provider_name": (supplier or {}).get("name") or "CJ Dropshipping",
        "verified": True,
        "supplier_cost": landed["supplier_cost"],
        "shipping_cost": landed["shipping_cost"],
        "landed_cost": landed["landed_cost"],
        "stock": landed["stock"],
        "shipping_days": landed["shipping_days"],
        "warehouse": landed["warehouse"],
        "variant_id": landed["variant_id"],
        "freight_name": landed["freight_name"],
    }
