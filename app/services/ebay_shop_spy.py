from __future__ import annotations

import re
from statistics import median
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

from app.config import get_settings
from app.services.ebay import EbayClient, EbayError


SELLER_RE = re.compile(r"^[A-Za-z0-9_.-]{2,80}$")
MAX_SHOP_ITEMS = 100
BROWSE_ROOT_CATEGORY = "0"


def extract_seller_username(value: str) -> str:
    raw = str(value or "").strip()
    if not raw:
        raise ValueError("Pseudo ou URL de boutique eBay manquant")

    if "://" not in raw:
        candidate = raw.lstrip("@").strip().strip("/")
    else:
        parsed = urlparse(raw)
        host = parsed.netloc.lower()
        if "ebay." not in host:
            raise ValueError("Utilisez une URL eBay ou le pseudo du vendeur")
        query = parse_qs(parsed.query)
        candidate = str((query.get("_ssn") or [""])[0]).strip()
        if not candidate:
            parts = [unquote(part).strip() for part in parsed.path.split("/") if part.strip()]
            lower = [part.lower() for part in parts]
            candidate = ""
            for marker in ("str", "usr"):
                if marker in lower:
                    index = lower.index(marker)
                    if index + 1 < len(parts):
                        candidate = parts[index + 1]
                        break
            if not candidate and parts:
                candidate = parts[-1]

    candidate = candidate.lstrip("@").strip()
    if not SELLER_RE.fullmatch(candidate):
        raise ValueError("Pseudo vendeur eBay invalide")
    return candidate


def _float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _shipping_cost(item: dict[str, Any]) -> tuple[float | None, str]:
    costs: list[tuple[float, str]] = []
    for row in item.get("shippingOptions") or []:
        if not isinstance(row, dict):
            continue
        block = row.get("shippingCost") or {}
        if not isinstance(block, dict):
            continue
        price = _float(block.get("value"))
        if price is None:
            continue
        costs.append((price, str(block.get("currency") or "USD")))
    if not costs:
        return None, "USD"
    return min(costs, key=lambda entry: entry[0])


def _normalize_browse_listing(item: dict[str, Any], rank: int) -> dict[str, Any] | None:
    price_block = item.get("price") or {}
    if not isinstance(price_block, dict):
        return None
    price = _float(price_block.get("value"))
    if price is None:
        return None

    shipping, shipping_currency = _shipping_cost(item)
    currency = str(price_block.get("currency") or shipping_currency or "USD")
    seller = item.get("seller") or {}
    image = item.get("image") or {}
    location = item.get("itemLocation") or {}
    if not isinstance(seller, dict):
        seller = {}
    if not isinstance(image, dict):
        image = {}
    if not isinstance(location, dict):
        location = {}

    watch_count = _int(item.get("watchCount"))
    total_price = round(price + (shipping or 0.0), 2)
    item_id = str(item.get("itemId") or "")
    legacy_id = str(item.get("legacyItemId") or "")
    if not legacy_id and item_id.startswith("v1|"):
        parts = item_id.split("|")
        if len(parts) > 1:
            legacy_id = parts[1]

    return {
        "rank": rank,
        "item_id": item_id,
        "legacy_item_id": legacy_id,
        "title": str(item.get("title") or "eBay product"),
        "price": round(price, 2),
        "shipping_cost": round(shipping, 2) if shipping is not None else None,
        "buyer_total": total_price,
        "currency": currency,
        "condition": str(item.get("condition") or ""),
        "image_url": str(image.get("imageUrl") or ""),
        "item_url": str(item.get("itemWebUrl") or ""),
        "watch_count": watch_count,
        "seller_username": str(seller.get("username") or ""),
        "seller_feedback_score": _int(seller.get("feedbackScore")),
        "seller_feedback_percent": _float(seller.get("feedbackPercentage")),
        "seller_account_type": str(seller.get("sellerAccountType") or ""),
        "location_country": str(location.get("country") or ""),
        "location_city": str(location.get("city") or ""),
        "item_creation_date": item.get("itemCreationDate"),
    }


async def _browse_seller_items(seller: str, limit: int) -> dict[str, Any]:
    client = EbayClient()
    params = {
        "category_ids": BROWSE_ROOT_CATEGORY,
        "filter": f"sellers:{{{seller}}},buyingOptions:{{AUCTION|FIXED_PRICE|BEST_OFFER}}",
        "limit": min(max(int(limit), 1), MAX_SHOP_ITEMS),
        "offset": 0,
        "fieldgroups": "EXTENDED",
    }
    try:
        return await client.public_request(
            "GET",
            "/buy/browse/v1/item_summary/search",
            params=params,
            marketplace_id="EBAY_US",
        )
    except EbayError as exc:
        detail = exc.payload if isinstance(exc.payload, dict) else {}
        errors = detail.get("errors") or []
        message = errors[0].get("message") if errors and isinstance(errors[0], dict) else None
        raise ValueError(message or f"Impossible de lire la boutique eBay US « {seller} »") from exc


async def analyze_ebay_shop(value: str, *, limit: int = 50) -> dict[str, Any]:
    settings = get_settings()
    if settings.ebay_effective_env != "production" or not settings.ebay_client_id or not settings.ebay_client_secret:
        raise ValueError("Spy eBay Shop nécessite les clés eBay Production pour lire eBay US.")

    seller = extract_seller_username(value)
    payload = await _browse_seller_items(seller, min(max(int(limit), 1), MAX_SHOP_ITEMS))
    listings = []
    for index, item in enumerate(payload.get("itemSummaries") or [], start=1):
        if isinstance(item, dict):
            row = _normalize_browse_listing(item, index)
            if row and str(row.get("currency") or "USD").upper() == "USD":
                listings.append(row)

    first_seller = next((row for row in listings if row.get("seller_username")), None)
    resolved_seller = str((first_seller or {}).get("seller_username") or seller)
    prices = [float(row["price"]) for row in listings if row.get("price") is not None]
    buyer_totals = [float(row["buyer_total"]) for row in listings if row.get("buyer_total") is not None]
    watchers_available = any(row.get("watch_count") is not None for row in listings)

    return {
        "seller": {
            "requested": seller,
            "username": resolved_seller,
            "feedback_score": (first_seller or {}).get("seller_feedback_score"),
            "feedback_percent": (first_seller or {}).get("seller_feedback_percent"),
            "account_type": (first_seller or {}).get("seller_account_type"),
        },
        "marketplace": "EBAY_US",
        "active_listings_total": int(payload.get("total") or len(listings)),
        "sample_size": len(listings),
        "median_price": round(median(prices), 2) if prices else None,
        "min_price": round(min(prices), 2) if prices else None,
        "max_price": round(max(prices), 2) if prices else None,
        "sample_inventory_value": round(sum(buyer_totals), 2) if buyer_totals else 0.0,
        "currency": "USD",
        "watchers_available": watchers_available,
        "ranking_basis": "EBAY_US_BROWSE_SELLER_ROOT_CATEGORY",
        "listings": listings,
        "note": (
            "Analyse limitée à eBay US. Les annonces actives sont lues via Browse API. "
            "Le nombre de ventes par annonce n'est pas exposé par ce flux ; aucune vente n'est inventée."
        ),
    }
