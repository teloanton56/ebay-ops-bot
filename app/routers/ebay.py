from fastapi import APIRouter, HTTPException

from app.config import get_settings
from app.services.db import get_listing_for_product, get_product, save_listing
from app.services.ebay import EbayClient, EbayError
from app.services.risk import assess_product
from app.services.supplier_refresh import SupplierRefreshError, refresh_product_from_supplier

router = APIRouter(prefix="/api/ebay", tags=["eBay"])


def fail(exc: EbayError):
    raise HTTPException(status_code=exc.status_code or 400, detail={"message": str(exc), "payload": exc.payload})


def _publication_blocks(product: dict, risk: dict, *, actual_write: bool) -> list[str]:
    blocks = list(risk.get("blocks") or [])
    if not product.get("category_id"):
        blocks.append("Catégorie eBay obligatoire avant publication")
    if not product.get("images"):
        blocks.append("Au moins une image est obligatoire avant publication")
    if not product.get("aspects"):
        blocks.append("Item specifics/aspects obligatoires avant publication")
    if actual_write:
        blocks.extend((risk.get("compliance") or {}).get("publication_blocks") or [])
    return list(dict.fromkeys(blocks))


async def _revalidate_for_ebay(product_id: int, *, actual_write: bool) -> tuple[dict, dict, dict | None]:
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

    risk = assess_product(product)
    blocks = _publication_blocks(product, risk, actual_write=actual_write)
    if blocks:
        raise HTTPException(
            409,
            detail={
                "message": "Publication readiness blocked eBay write",
                "blocks": blocks,
                "risk": risk,
                "supplier_verification": supplier_verification,
            },
        )
    return product, risk, supplier_verification


@router.get("/config")
def config():
    s = get_settings()
    return {
        "environment": s.ebay_effective_env,
        "marketplace": s.ebay_marketplace_id,
        "currency": s.ebay_currency,
        "write_enabled": s.ebay_write_enabled,
        "publish_enabled": s.ebay_publish_enabled,
        "merchant_location_key": s.ebay_merchant_location_key,
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


@router.post("/inventory-location")
async def inventory_location():
    try:
        return await EbayClient().create_inventory_location()
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
    try:
        client = EbayClient()
        return {
            "risk": risk,
            "publication_blocks": _publication_blocks(product, risk, actual_write=False),
            "inventory_payload": client.build_inventory_item_payload(product),
            "offer_payload": client.build_offer_payload(product, float(product["target_price"])),
        }
    except EbayError as exc:
        fail(exc)


@router.post("/listings/{product_id}/create")
async def create_listing(product_id: int):
    settings = get_settings()
    actual_write = bool(settings.ebay_write_enabled)
    product, risk, supplier_verification = await _revalidate_for_ebay(product_id, actual_write=actual_write)
    try:
        result = await EbayClient().create_offer_for_product(product, float(product["target_price"]))
        offer_id = None
        if not result.get("dry_run"):
            offer_id = (result.get("offer") or {}).get("offerId")
        save_listing(product_id, offer_id, None, "OFFER_CREATED" if offer_id else "DRY_RUN",
                     float(product["target_price"]), int(product["stock"]))
        return {"risk": risk, "supplier_verification": supplier_verification, **result}
    except EbayError as exc:
        save_listing(product_id, None, None, "ERROR", product.get("target_price"), product.get("stock"), str(exc))
        fail(exc)


@router.post("/listings/{product_id}/publish")
async def publish_listing(product_id: int):
    listing = get_listing_for_product(product_id)
    if not listing or not listing.get("offer_id"):
        raise HTTPException(400, "No created offer_id for this product. Create the offer first with writes enabled.")

    settings = get_settings()
    actual_write = bool(settings.ebay_write_enabled and settings.ebay_publish_enabled)
    product, risk, supplier_verification = await _revalidate_for_ebay(product_id, actual_write=actual_write)
    client = EbayClient()
    try:
        if actual_write:
            # The offer may have been created minutes or hours earlier. Push the fresh
            # supplier-validated price/quantity snapshot immediately before publish.
            await client.update_live_offer_price_quantity(
                product["supplier_sku"],
                listing["offer_id"],
                float(product["target_price"]),
                int(product["stock"]),
                product.get("currency") or settings.ebay_currency,
            )
        result = await client.publish_offer(listing["offer_id"])
        listing_id = result.get("listingId") if not result.get("dry_run") else None
        save_listing(product_id, listing["offer_id"], listing_id, "PUBLISHED" if listing_id else "PUBLISH_DRY_RUN",
                     product.get("target_price"), product.get("stock"))
        return {"risk": risk, "supplier_verification": supplier_verification, **result}
    except EbayError as exc:
        fail(exc)


@router.post("/listings/{product_id}/sync")
async def sync_listing(product_id: int):
    listing = get_listing_for_product(product_id)
    if not listing or not listing.get("offer_id"):
        raise HTTPException(400, "Product has no eBay offer_id")
    settings = get_settings()
    actual_write = bool(settings.ebay_write_enabled)
    product, risk, supplier_verification = await _revalidate_for_ebay(product_id, actual_write=actual_write)
    qty = int(product.get("stock") or 0) if risk["pass"] else 0
    price = float(product.get("target_price") or 0)
    try:
        result = await EbayClient().update_live_offer_price_quantity(
            product["supplier_sku"], listing["offer_id"], price, qty, product.get("currency") or settings.ebay_currency
        )
        return {
            "risk": risk,
            "supplier_verification": supplier_verification,
            "effective_quantity": qty,
            "result": result,
        }
    except EbayError as exc:
        fail(exc)


from pydantic import BaseModel, Field


class TrackingIn(BaseModel):
    tracking_number: str = Field(min_length=2)
    carrier: str = Field(min_length=2)
    line_item_ids: list[str] = []


@router.post("/orders/{order_id}/tracking")
async def add_tracking(order_id: str, payload: TrackingIn):
    try:
        return await EbayClient().create_shipping_fulfillment(order_id, payload.tracking_number, payload.carrier, payload.line_item_ids or None)
    except EbayError as exc:
        fail(exc)
