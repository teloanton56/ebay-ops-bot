from __future__ import annotations

import asyncio
import re
from statistics import median
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

from app.config import get_settings
from app.services.aliexpress_dropship_search import aliexpress_dropship_supplier_offers
from app.services.cj import CJClient
from app.services.ebay import EbayClient, EbayError
from app.services.margin_hunter import _ali_candidates, _deep_cj_candidate
from app.services.supplier_relevance import rank_supplier_results


SELLER_RE = re.compile(r"^[A-Za-z0-9_.-]{2,80}$")
MAX_SHOP_ITEMS = 100
MAX_SUPPLIER_RESULTS = 8
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
        costs.append((price, str(block.get("currency") or "EUR")))
    if not costs:
        return None, "EUR"
    return min(costs, key=lambda entry: entry[0])


def _normalize_browse_listing(item: dict[str, Any], rank: int) -> dict[str, Any] | None:
    price_block = item.get("price") or {}
    if not isinstance(price_block, dict):
        return None
    price = _float(price_block.get("value"))
    if price is None:
        return None

    shipping, shipping_currency = _shipping_cost(item)
    currency = str(price_block.get("currency") or shipping_currency or "EUR")
    seller = item.get("seller") or {}
    if not isinstance(seller, dict):
        seller = {}
    image = item.get("image") or {}
    if not isinstance(image, dict):
        image = {}
    location = item.get("itemLocation") or {}
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
        "title": str(item.get("title") or "Produit eBay"),
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
            marketplace_id="EBAY_FR",
        )
    except EbayError as exc:
        detail = exc.payload if isinstance(exc.payload, dict) else {}
        errors = detail.get("errors") or []
        message = errors[0].get("message") if errors and isinstance(errors[0], dict) else None
        raise ValueError(message or f"Impossible de lire la boutique eBay « {seller} » avec Browse API") from exc


async def analyze_ebay_shop(value: str, *, limit: int = 50) -> dict[str, Any]:
    settings = get_settings()
    if settings.ebay_effective_env != "production" or not settings.ebay_client_id or not settings.ebay_client_secret:
        raise ValueError("Spy eBay Shop nécessite les clés eBay Production pour lire les annonces réelles.")

    seller = extract_seller_username(value)
    limit = min(max(int(limit), 1), MAX_SHOP_ITEMS)
    payload = await _browse_seller_items(seller, limit)

    listings = []
    for index, item in enumerate(payload.get("itemSummaries") or [], start=1):
        if not isinstance(item, dict):
            continue
        row = _normalize_browse_listing(item, index)
        if row:
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
        "active_listings_total": int(payload.get("total") or len(listings)),
        "sample_size": len(listings),
        "median_price": round(median(prices), 2) if prices else None,
        "min_price": round(min(prices), 2) if prices else None,
        "max_price": round(max(prices), 2) if prices else None,
        "sample_inventory_value": round(sum(buyer_totals), 2) if buyer_totals else 0.0,
        "currency": listings[0].get("currency") if listings else "EUR",
        "watchers_available": watchers_available,
        "ranking_basis": "EBAY_BROWSE_SELLER_ROOT_CATEGORY",
        "listings": listings,
        "note": (
            "Les annonces actives sont récupérées avec l'API eBay Browse actuelle, filtrée sur le vendeur et la catégorie racine. "
            "Le volume de ventes par annonce n'est pas exposé par ce flux. Les watchers ne sont affichés que si eBay les fournit à l'application. "
            "La valeur d'inventaire affichée correspond uniquement à l'échantillon d'annonces actives, pas au chiffre d'affaires."
        ),
    }


async def compare_shop_listing(title: str, competitor_price: float, *, limit: int = MAX_SUPPLIER_RESULTS) -> dict[str, Any]:
    title = str(title or "").strip()
    if len(title) < 2:
        raise ValueError("Titre eBay trop court")
    try:
        reference_price = float(competitor_price)
    except (TypeError, ValueError) as exc:
        raise ValueError("Prix concurrent invalide") from exc
    if reference_price <= 0:
        raise ValueError("Prix concurrent invalide")
    limit = min(max(int(limit), 1), MAX_SUPPLIER_RESULTS)

    market = {"competition_points": 0.0, "demand_points": 0.0}
    candidates: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []

    cj_client = CJClient()
    if cj_client.status().get("connected"):
        try:
            search = await cj_client.search_products(keyword=title, size=40, min_stock=3, order_by=0)
            relevant, _ = rank_supplier_results(title, search.get("products") or [], title_keys=("name",), limit=4)
            exchange = await cj_client.usd_to_eur()
            semaphore = asyncio.Semaphore(2)
            jobs = [
                _deep_cj_candidate(
                    cj_client,
                    product,
                    exchange_rate=float(exchange["rate"]),
                    reference_price=reference_price,
                    market=market,
                    semaphore=semaphore,
                )
                for product in relevant[:4]
            ]
            results = await asyncio.gather(*jobs) if jobs else []
            for candidate, error in results:
                if candidate:
                    candidate["reference_source"] = "PRIX_BOUTIQUE_EBAY"
                    candidates.append(candidate)
                elif error:
                    errors.append({"source": "CJ", "message": error})
        except Exception as exc:
            errors.append({"source": "CJ", "message": str(exc)})
    else:
        errors.append({"source": "CJ", "message": "CJ n'est pas connecté"})

    ali_offers, ali_errors = await aliexpress_dropship_supplier_offers(title)
    for row in ali_errors:
        errors.append({"source": "AliExpress", "message": str(row.get("message") or row)})
    for candidate in _ali_candidates(ali_offers, reference_price=reference_price, market=market):
        candidate["reference_source"] = "PRIX_BOUTIQUE_EBAY"
        candidates.append(candidate)

    candidates.sort(
        key=lambda row: (
            0 if row.get("verified") else 1,
            0 if row.get("goal_hit") else 1,
            -float(row.get("score") or 0),
        )
    )
    return {
        "title": title,
        "competitor_price": round(reference_price, 2),
        "currency": "EUR",
        "candidates": candidates[:limit],
        "errors": errors,
        "note": (
            "CJ utilise un coût livré France calculé avant estimation de marge. "
            "AliExpress reste préliminaire tant que son coût de livraison n'est pas confirmé. "
            "La référence de prix est l'annonce du concurrent analysée, pas une estimation de ventes."
        ),
    }
