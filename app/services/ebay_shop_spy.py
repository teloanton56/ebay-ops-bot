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


def _shipping_cost(item: dict[str, Any]) -> tuple[float | None, str]:
    rows = item.get("shippingOptions") or []
    costs: list[tuple[float, str]] = []
    for row in rows:
        price = row.get("shippingCost") or {}
        value = _float(price.get("value"))
        if value is None:
            continue
        costs.append((value, str(price.get("currency") or "EUR")))
    if not costs:
        return None, "EUR"
    return min(costs, key=lambda entry: entry[0])


def _normalize_listing(item: dict[str, Any], rank: int) -> dict[str, Any] | None:
    price_block = item.get("price") or {}
    price = _float(price_block.get("value"))
    if price is None:
        return None
    shipping, shipping_currency = _shipping_cost(item)
    currency = str(price_block.get("currency") or shipping_currency or "EUR")
    seller = item.get("seller") or {}
    image = item.get("image") or {}
    location = item.get("itemLocation") or {}
    watch_count = item.get("watchCount")
    try:
        watch_count = int(watch_count) if watch_count is not None else None
    except (TypeError, ValueError):
        watch_count = None
    total_price = round(price + (shipping or 0.0), 2)
    return {
        "rank": rank,
        "item_id": str(item.get("itemId") or ""),
        "legacy_item_id": str(item.get("legacyItemId") or ""),
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
        "seller_feedback_score": seller.get("feedbackScore"),
        "seller_feedback_percent": seller.get("feedbackPercentage"),
        "seller_account_type": seller.get("sellerAccountType"),
        "location_country": str(location.get("country") or ""),
        "location_city": str(location.get("city") or ""),
        "item_creation_date": item.get("itemCreationDate"),
    }


async def analyze_ebay_shop(value: str, *, limit: int = 50) -> dict[str, Any]:
    settings = get_settings()
    if settings.ebay_effective_env != "production" or not settings.ebay_client_id or not settings.ebay_client_secret:
        raise ValueError("Spy eBay Shop nécessite les clés eBay Production pour lire les annonces réelles.")

    seller = extract_seller_username(value)
    limit = min(max(int(limit), 1), MAX_SHOP_ITEMS)
    client = EbayClient()
    params = {
        "filter": f"sellers:{{{seller}}},deliveryCountry:FR",
        "limit": limit,
        "fieldgroups": "EXTENDED",
    }
    try:
        payload = await client.public_request(
            "GET",
            "/buy/browse/v1/item_summary/search",
            params=params,
            marketplace_id="EBAY_FR",
        )
    except EbayError as exc:
        detail = exc.payload if isinstance(exc.payload, dict) else {}
        errors = detail.get("errors") or []
        message = errors[0].get("message") if errors and isinstance(errors[0], dict) else None
        raise ValueError(message or f"Impossible de lire la boutique eBay « {seller} »") from exc

    raw_items = payload.get("itemSummaries") or []
    listings = []
    for index, item in enumerate(raw_items, start=1):
        if not isinstance(item, dict):
            continue
        row = _normalize_listing(item, index)
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
        "ranking_basis": "WATCHERS_WHEN_AVAILABLE_AND_EBAY_ORDER" if watchers_available else "EBAY_BEST_MATCH_ORDER",
        "listings": listings,
        "note": (
            "Les annonces sont celles renvoyées par l'API Browse eBay pour ce vendeur. "
            "Le volume de ventes par annonce n'est pas exposé par ce flux. Le nombre de watchers n'est affiché que si eBay l'autorise pour l'application. "
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
            for candidate, error in await asyncio.gather(*jobs) if jobs else []:
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
