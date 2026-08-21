from __future__ import annotations

import asyncio
import re
from statistics import median
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

import httpx

from app.config import get_settings
from app.services.aliexpress_dropship_search import aliexpress_dropship_supplier_offers
from app.services.cj import CJClient
from app.services.margin_hunter import _ali_candidates, _deep_cj_candidate
from app.services.supplier_relevance import rank_supplier_results


SELLER_RE = re.compile(r"^[A-Za-z0-9_.-]{2,80}$")
MAX_SHOP_ITEMS = 100
MAX_SUPPLIER_RESULTS = 8
FINDING_ENDPOINT = "https://svcs.ebay.com/services/search/FindingService/v1"


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


def _first(value: Any, default: Any = None) -> Any:
    if isinstance(value, list):
        return value[0] if value else default
    return default if value is None else value


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


def _finding_money(value: Any) -> tuple[float | None, str]:
    block = _first(value, {})
    if not isinstance(block, dict):
        return None, "EUR"
    return _float(block.get("__value__")), str(block.get("@currencyId") or "EUR")


def _normalize_finding_listing(item: dict[str, Any], rank: int) -> dict[str, Any] | None:
    selling = _first(item.get("sellingStatus"), {})
    shipping_info = _first(item.get("shippingInfo"), {})
    seller_info = _first(item.get("sellerInfo"), {})
    condition = _first(item.get("condition"), {})
    listing_info = _first(item.get("listingInfo"), {})

    if not isinstance(selling, dict):
        selling = {}
    if not isinstance(shipping_info, dict):
        shipping_info = {}
    if not isinstance(seller_info, dict):
        seller_info = {}
    if not isinstance(condition, dict):
        condition = {}
    if not isinstance(listing_info, dict):
        listing_info = {}

    price, currency = _finding_money(selling.get("currentPrice"))
    if price is None:
        return None
    shipping, shipping_currency = _finding_money(shipping_info.get("shippingServiceCost"))
    currency = currency or shipping_currency or "EUR"
    item_id = str(_first(item.get("itemId"), ""))
    total_price = round(price + (shipping or 0.0), 2)

    return {
        "rank": rank,
        "item_id": item_id,
        "legacy_item_id": item_id,
        "title": str(_first(item.get("title"), "Produit eBay")),
        "price": round(price, 2),
        "shipping_cost": round(shipping, 2) if shipping is not None else None,
        "buyer_total": total_price,
        "currency": currency,
        "condition": str(_first(condition.get("conditionDisplayName"), "")),
        "image_url": str(_first(item.get("galleryURL"), "")),
        "item_url": str(_first(item.get("viewItemURL"), "")),
        "watch_count": None,
        "seller_username": str(_first(seller_info.get("sellerUserName"), "")),
        "seller_feedback_score": _int(_first(seller_info.get("feedbackScore"))),
        "seller_feedback_percent": _float(_first(seller_info.get("positiveFeedbackPercent"))),
        "seller_account_type": "",
        "location_country": str(_first(item.get("country"), "")),
        "location_city": str(_first(item.get("location"), "")),
        "item_creation_date": _first(listing_info.get("startTime")),
    }


def _finding_error_message(response: dict[str, Any]) -> str | None:
    error_group = _first(response.get("errorMessage"), {})
    if not isinstance(error_group, dict):
        return None
    error = _first(error_group.get("error"), {})
    if not isinstance(error, dict):
        return None
    message = _first(error.get("message"))
    return str(message) if message else None


async def _find_seller_items(seller: str, limit: int, app_id: str) -> dict[str, Any]:
    params = {
        "OPERATION-NAME": "findItemsAdvanced",
        "SERVICE-VERSION": "1.13.0",
        "SECURITY-APPNAME": app_id,
        "RESPONSE-DATA-FORMAT": "JSON",
        "REST-PAYLOAD": "true",
        "GLOBAL-ID": "EBAY-FR",
        "outputSelector": "SellerInfo",
        "itemFilter(0).name": "Seller",
        "itemFilter(0).value(0)": seller,
        "itemFilter(1).name": "LocatedIn",
        "itemFilter(1).value(0)": "WorldWide",
        "paginationInput.entriesPerPage": str(limit),
        "paginationInput.pageNumber": "1",
        "sortOrder": "BestMatch",
    }
    async with httpx.AsyncClient(timeout=45) as client:
        response = await client.get(FINDING_ENDPOINT, params=params)
    if response.is_error:
        raise ValueError(f"eBay Finding a répondu HTTP {response.status_code}")
    try:
        payload = response.json()
    except ValueError as exc:
        raise ValueError("Réponse eBay Finding invalide") from exc

    root = _first(payload.get("findItemsAdvancedResponse"), {})
    if not isinstance(root, dict):
        raise ValueError("Réponse eBay Finding incomplète")
    ack = str(_first(root.get("ack"), "")).upper()
    if ack not in {"SUCCESS", "WARNING"}:
        raise ValueError(_finding_error_message(root) or f"Impossible de lire la boutique eBay « {seller} »")
    return root


async def analyze_ebay_shop(value: str, *, limit: int = 50) -> dict[str, Any]:
    settings = get_settings()
    if settings.ebay_effective_env != "production" or not settings.ebay_client_id:
        raise ValueError("Spy eBay Shop nécessite les clés eBay Production pour lire les annonces réelles.")

    seller = extract_seller_username(value)
    limit = min(max(int(limit), 1), MAX_SHOP_ITEMS)
    root = await _find_seller_items(seller, limit, settings.ebay_client_id)

    search_result = _first(root.get("searchResult"), {})
    if not isinstance(search_result, dict):
        search_result = {}
    raw_items = search_result.get("item") or []
    listings = []
    for index, item in enumerate(raw_items, start=1):
        if not isinstance(item, dict):
            continue
        row = _normalize_finding_listing(item, index)
        if row:
            listings.append(row)

    pagination = _first(root.get("paginationOutput"), {})
    if not isinstance(pagination, dict):
        pagination = {}
    total_entries = _int(_first(pagination.get("totalEntries")))

    first_seller = next((row for row in listings if row.get("seller_username")), None)
    resolved_seller = str((first_seller or {}).get("seller_username") or seller)
    prices = [float(row["price"]) for row in listings if row.get("price") is not None]
    buyer_totals = [float(row["buyer_total"]) for row in listings if row.get("buyer_total") is not None]

    return {
        "seller": {
            "requested": seller,
            "username": resolved_seller,
            "feedback_score": (first_seller or {}).get("seller_feedback_score"),
            "feedback_percent": (first_seller or {}).get("seller_feedback_percent"),
            "account_type": (first_seller or {}).get("seller_account_type"),
        },
        "active_listings_total": total_entries if total_entries is not None else len(listings),
        "sample_size": len(listings),
        "median_price": round(median(prices), 2) if prices else None,
        "min_price": round(min(prices), 2) if prices else None,
        "max_price": round(max(prices), 2) if prices else None,
        "sample_inventory_value": round(sum(buyer_totals), 2) if buyer_totals else 0.0,
        "currency": listings[0].get("currency") if listings else "EUR",
        "watchers_available": False,
        "ranking_basis": "EBAY_FINDING_BEST_MATCH",
        "listings": listings,
        "note": (
            "Les annonces actives sont récupérées avec eBay Finding findItemsAdvanced et le filtre Seller, sans faux mot-clé. "
            "Le volume de ventes par annonce et le nombre de watchers ne sont pas exposés par ce flux. "
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
