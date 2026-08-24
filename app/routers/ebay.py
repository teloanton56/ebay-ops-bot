from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.config import get_settings
from app.services.cj_landed import load_cj_product_link
from app.services.db import get_listing_for_product, get_product, save_listing
from app.services.ebay import EbayClient, EbayError
from app.services.ebay_us_listing import (
    build_us_offer_payload,
    create_us_offer_for_product,
    location_key_for_warehouse,
)
from app.services.risk import assess_product
from app.services.supplier_refresh import SupplierRefreshError, is_verified_cj_product, refresh_product_from_supplier

router = APIRouter(prefix="/api/ebay", tags=["eBay US"])


def fail(exc: EbayError):
    raise HTTPException(status_code=exc.status_code or 400, detail={"message": str(exc), "payload": exc.payload})


def _warehouse_for_product(product: dict) -> str:
    link = load_cj_product_link(str(product.get("supplier_sku") or ""))
    return str(link.get("warehouse") or "").upper()


def _publication_blocks(
    product: dict,
    risk: dict,
    *,
    actual_write: bool,
    warehouse: str = "",
    merchant_location_key: str = "",
) -> list[str]:
    blocks = list(risk.get("blocks") or [])
    if not is_verified_cj_product(product):
        blocks.append("Produit hors flux CJ vérifié")
    if (product.get("marketplace_id") or "") != "EBAY_US":
        blocks.append("Marketplace invalide : le bot publie uniquement sur eBay US")
    if (product.get("currency") or "") != "USD":
        blocks.append("Devise invalide : le bot publie uniquement en USD")
    if not product.get("category_id"):
        blocks.append("Catégorie eBay US obligatoire avant publication")
    if not product.get("images"):
        blocks.append("Au moins une image est obligatoire avant publication")
    if not product.get("aspects"):
        blocks.append("Item specifics/aspects obligatoires avant publication")
    if warehouse not in {"US", "CN"}:
        blocks.append("Route CJ US/CN non enregistrée")
    if actual_write and not merchant_location_key:
        blocks.append(
            f"Merchant location eBay manquante pour la route CJ {warehouse or 'inconnue'}"
        )
    if actual_write:
        blocks.extend((risk.get("compliance") or {}).get("publication_blocks") or [])
    return list(dict.fromkeys(blocks))


async def _revalidate_for_ebay(
    product_id: int,
    *,
    actual_write: bool,
) -> tuple[dict, dict, dict | None, str, str]:
    product = get_product(product_id)
    if not product:
        raise HTTPException(404, "Product not found")

    supplier_verification = None
    if actual_write:
        try:
            product, supplier_verification = await refresh_product_from_supplier(product)
        except SupplierRefreshError as exc:
            raise HTTPException(
                409,
                detail={
                    "message": "Supplier revalidation blocked eBay write",
                    "supplier_error": str(exc),
                },
            ) from exc

    warehouse = str((supplier_verification or {}).get("warehouse") or _warehouse_for_product(product)).upper()
    merchant_location_key = location_key_for_warehouse(warehouse)
    risk = assess_product(product)
    blocks = _publication_blocks(
        product,
        risk,
        actual_write=actual_write,
        warehouse=warehouse,
        merchant_location_key=merchant_location_key,
    )
    if blocks:
        raise HTTPException(
            409,
            detail={
                "message": "Publication readiness blocked eBay US write",
                "blocks": blocks,
                "risk": risk,
                "supplier_verification": supplier_verification,
                "warehouse": warehouse,
            },
        )
    return product, risk, supplier_verification, warehouse, merchant_location_key


@router.get("/config")
def config():
    s = get_settings()
    return {
        "environment": s.ebay_effective_env,
        "marketplace": "EBAY_US",
        "currency": "USD",
        "locale": "en-US",
        "write_enabled": s.ebay_write_enabled,
        "publish_enabled": s.ebay_publish_enabled,
        "route_locations": {
            "US": {"configured": bool(s.ebay_cj_us_location_key), "key": s.ebay_cj_us_location_key},
            "CN": {"configured": bool(s.ebay_cj_cn_location_key), "key": s.ebay_cj_cn_location_key},
        },
        "policies_configured": {
            "payment": bool(s.ebay_payment_policy_id),
            "return": bool(s.ebay_return_policy_id),
            "fulfillment": bool(s.ebay_fulfillment_policy_id),
        },
    }


@router.get("/policies")
async def policies():
    try:
        return await EbayClient().get_policies()
    except EbayError as exc:
        fail(exc)


@router.get("/orders")
async def orders(limit: int = 50):
    try:
        return await EbayClient().get_orders(limit)
    except EbayError as exc:
        fail(exc)


@router.get("/listings/{product_id}/preview")
def listing_preview(product_id: int):
    product = get_product(product_id)
    if not product:
        raise HTTPException(404, "Product not found")
    risk = assess_product(product)
    if not product.get("target_price"):
        raise HTTPException(400, "target_price is required")
    warehouse = _warehouse_for_product(product)
    location_key = location_key_for_warehouse(warehouse) or f"DRYRUN-CJ-{warehouse or 'UNKNOWN'}"
    blocks = _publication_blocks(
        product,
        risk,
        actual_write=False,
        warehouse=warehouse,
        merchant_location_key=location_key,
    )
    try:
        client = EbayClient()
        return {
            "risk": risk,
            "warehouse": warehouse,
            "publication_blocks": blocks,
            "inventory_payload": client.build_inventory_item_payload(product),
            "offer_payload": build_us_offer_payload(product, float(product["target_price"]), location_key),
        }
    except EbayError as exc:
        fail(exc)


@router.post("/listings/{product_id}/create")
async def create_listing(product_id: int):
    settings = get_settings()
    actual_write = bool(settings.ebay_write_enabled)
    product, risk, supplier_verification, warehouse, location_key = await _revalidate_for_ebay(
        product_id,
        actual_write=actual_write,
    )
    if not location_key:
        location_key = f"DRYRUN-CJ-{warehouse}"
    try:
        result = await create_us_offer_for_product(
            EbayClient(),
            product,
            float(product["target_price"]),
            location_key,
        )
        offer_id = None
        if not result.get("dry_run"):
            offer_id = (result.get("offer") or {}).get("offerId")
        save_listing(
            product_id,
            offer_id,
            None,
            "OFFER_CREATED" if offer_id else "DRY_RUN",
            float(product["target_price"]),
            int(product["stock"]),
        )
        return {
            "risk": risk,
            "supplier_verification": supplier_verification,
            "warehouse": warehouse,
            **result,
        }
    except EbayError as exc:
        save_listing(
            product_id,
            None,
            None,
            "ERROR",
            product.get("target_price"),
            product.get("stock"),
            str(exc),
        )
        fail(exc)


@router.post("/listings/{product_id}/publish")
async def publish_listing(product_id: int):
    listing = get_listing_for_product(product_id)
    if not listing or not listing.get("offer_id"):
        raise HTTPException(400, "No created offer_id for this product. Create the offer first with writes enabled.")

    settings = get_settings()
    actual_write = bool(settings.ebay_write_enabled and settings.ebay_publish_enabled)
    product, risk, supplier_verification, warehouse, _ = await _revalidate_for_ebay(
        product_id,
        actual_write=actual_write,
    )
    client = EbayClient()
    try:
        if actual_write:
            await client.update_live_offer_price_quantity(
                product["supplier_sku"],
                listing["offer_id"],
                float(product["target_price"]),
                int(product["stock"]),
                "USD",
            )
        result = await client.publish_offer(listing["offer_id"])
        listing_id = result.get("listingId") if not result.get("dry_run") else None
        save_listing(
            product_id,
            listing["offer_id"],
            listing_id,
            "PUBLISHED" if listing_id else "PUBLISH_DRY_RUN",
            product.get("target_price"),
            product.get("stock"),
        )
        return {
            "risk": risk,
            "supplier_verification": supplier_verification,
            "warehouse": warehouse,
            **result,
        }
    except EbayError as exc:
        fail(exc)


@router.post("/listings/{product_id}/sync")
async def sync_listing(product_id: int):
    listing = get_listing_for_product(product_id)
    if not listing or not listing.get("offer_id"):
        raise HTTPException(400, "Product has no eBay offer_id")
    settings = get_settings()
    actual_write = bool(settings.ebay_write_enabled)
    product, risk, supplier_verification, warehouse, _ = await _revalidate_for_ebay(
        product_id,
        actual_write=actual_write,
    )
    qty = int(product.get("stock") or 0) if risk["pass"] else 0
    price = float(product.get("target_price") or 0)
    try:
        result = await EbayClient().update_live_offer_price_quantity(
            product["supplier_sku"],
            listing["offer_id"],
            price,
            qty,
            "USD",
        )
        return {
            "risk": risk,
            "supplier_verification": supplier_verification,
            "warehouse": warehouse,
            "effective_quantity": qty,
            "result": result,
        }
    except EbayError as exc:
        fail(exc)


class TrackingIn(BaseModel):
    tracking_number: str = Field(min_length=2)
    carrier: str = Field(min_length=2)
    line_item_ids: list[str] = []


@router.post("/orders/{order_id}/tracking")
async def add_tracking(order_id: str, payload: TrackingIn):
    try:
        return await EbayClient().create_shipping_fulfillment(
            order_id,
            payload.tracking_number,
            payload.carrier,
            payload.line_item_ids or None,
        )
    except EbayError as exc:
        fail(exc)
