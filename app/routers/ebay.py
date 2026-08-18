from fastapi import APIRouter, HTTPException

from app.config import get_settings
from app.services.db import get_listing_for_product, get_product, save_listing
from app.services.ebay import EbayClient, EbayError
from app.services.risk import assess_product

router = APIRouter(prefix="/api/ebay", tags=["eBay"])


def fail(exc: EbayError):
    raise HTTPException(status_code=exc.status_code or 400, detail={"message": str(exc), "payload": exc.payload})


@router.get("/config")
def config():
    s = get_settings()
    return {
        "environment": s.ebay_env,
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
            "inventory_payload": client.build_inventory_item_payload(product),
            "offer_payload": client.build_offer_payload(product, float(product["target_price"])),
        }
    except EbayError as exc:
        fail(exc)


@router.post("/listings/{product_id}/create")
async def create_listing(product_id: int):
    product = get_product(product_id)
    if not product:
        raise HTTPException(404, "Product not found")
    risk = assess_product(product)
    if not risk["pass"]:
        raise HTTPException(409, detail={"message": "Risk engine blocked listing", "risk": risk})
    try:
        result = await EbayClient().create_offer_for_product(product, float(product["target_price"]))
        offer_id = None
        if not result.get("dry_run"):
            offer_id = (result.get("offer") or {}).get("offerId")
        save_listing(product_id, offer_id, None, "OFFER_CREATED" if offer_id else "DRY_RUN",
                     float(product["target_price"]), int(product["stock"]))
        return {"risk": risk, **result}
    except EbayError as exc:
        save_listing(product_id, None, None, "ERROR", product.get("target_price"), product.get("stock"), str(exc))
        fail(exc)


@router.post("/listings/{product_id}/publish")
async def publish_listing(product_id: int):
    product = get_product(product_id)
    if not product:
        raise HTTPException(404, "Product not found")
    listing = get_listing_for_product(product_id)
    if not listing or not listing.get("offer_id"):
        raise HTTPException(400, "No created offer_id for this product. Create the offer first with writes enabled.")
    try:
        result = await EbayClient().publish_offer(listing["offer_id"])
        listing_id = result.get("listingId") if not result.get("dry_run") else None
        save_listing(product_id, listing["offer_id"], listing_id, "PUBLISHED" if listing_id else "PUBLISH_DRY_RUN",
                     product.get("target_price"), product.get("stock"))
        return result
    except EbayError as exc:
        fail(exc)


@router.post("/listings/{product_id}/sync")
async def sync_listing(product_id: int):
    product = get_product(product_id)
    if not product:
        raise HTTPException(404, "Product not found")
    listing = get_listing_for_product(product_id)
    if not listing or not listing.get("offer_id"):
        raise HTTPException(400, "Product has no eBay offer_id")
    risk = assess_product(product)
    qty = int(product.get("stock") or 0) if risk["pass"] else 0
    price = float(product.get("target_price") or 0)
    try:
        result = await EbayClient().update_live_offer_price_quantity(
            product["supplier_sku"], listing["offer_id"], price, qty, product.get("currency") or get_settings().ebay_currency
        )
        return {"risk": risk, "effective_quantity": qty, "result": result}
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
