from __future__ import annotations

from app.config import get_settings
from app.services.ebay import EbayClient, EbayError


def location_key_for_warehouse(warehouse: str) -> str:
    settings = get_settings()
    warehouse = str(warehouse or "").upper()
    if warehouse == "US":
        return settings.ebay_cj_us_location_key.strip()
    if warehouse == "CN":
        return settings.ebay_cj_cn_location_key.strip()
    return ""


def build_us_offer_payload(product: dict, price: float, merchant_location_key: str) -> dict:
    settings = get_settings()
    missing = [
        name for name, value in {
            "EBAY_PAYMENT_POLICY_ID": settings.ebay_payment_policy_id,
            "EBAY_RETURN_POLICY_ID": settings.ebay_return_policy_id,
            "EBAY_FULFILLMENT_POLICY_ID": settings.ebay_fulfillment_policy_id,
            "CJ_ROUTE_MERCHANT_LOCATION_KEY": merchant_location_key,
        }.items() if not value
    ]
    if missing:
        raise EbayError("Missing eBay US listing configuration: " + ", ".join(missing))
    if not product.get("category_id"):
        raise EbayError("Product category_id is required before an offer can be created")
    if (product.get("marketplace_id") or settings.ebay_marketplace_id) != "EBAY_US":
        raise EbayError("v0.23 can only create offers on EBAY_US")
    if (product.get("currency") or settings.ebay_currency) != "USD":
        raise EbayError("v0.23 can only create offers in USD")

    return {
        "sku": product["supplier_sku"],
        "marketplaceId": "EBAY_US",
        "format": "FIXED_PRICE",
        "availableQuantity": max(int(product.get("stock") or 0), 0),
        "categoryId": str(product["category_id"]),
        "merchantLocationKey": merchant_location_key,
        "listingDescription": product.get("description") or product["title"],
        "listingDuration": "GTC",
        "listingPolicies": {
            "paymentPolicyId": settings.ebay_payment_policy_id,
            "returnPolicyId": settings.ebay_return_policy_id,
            "fulfillmentPolicyId": settings.ebay_fulfillment_policy_id,
        },
        "pricingSummary": {"price": {"value": f"{price:.2f}", "currency": "USD"}},
    }


async def create_us_offer_for_product(
    client: EbayClient,
    product: dict,
    price: float,
    merchant_location_key: str,
) -> dict:
    inventory_payload = client.build_inventory_item_payload(product)
    offer_payload = build_us_offer_payload(product, price, merchant_location_key)
    if not client.s.ebay_write_enabled:
        return {
            "dry_run": True,
            "inventory_payload": inventory_payload,
            "offer_payload": offer_payload,
        }
    sku = product["supplier_sku"]
    await client.request("PUT", f"/sell/inventory/v1/inventory_item/{sku}", json_body=inventory_payload)
    offer = await client.request("POST", "/sell/inventory/v1/offer", json_body=offer_payload)
    return {
        "dry_run": False,
        "offer": offer,
        "inventory_payload": inventory_payload,
        "offer_payload": offer_payload,
    }
