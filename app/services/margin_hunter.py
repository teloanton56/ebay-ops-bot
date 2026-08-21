from __future__ import annotations

import asyncio
import re
from typing import Any

from app.config import get_settings
from app.services.aliexpress_dropship_search import aliexpress_dropship_supplier_offers
from app.services.cj import CJClient, CJError
from app.services.connections import connection_status
from app.services.marketplace_supplier_sources import aliexpress_connection_status
from app.services.product_research import build_product_research_summary
from app.services.profit import calculate_profit
from app.services.radar import analyze_amazon_market, analyze_ebay_market
from app.services.supplier_relevance import rank_supplier_results


TARGET_LANDED_RATIO = 30.0
CJ_POOL_SIZE = 50
CJ_DEEP_LIMIT = 6
ALI_POOL_LIMIT = 20
MAX_RESULTS = 10


def _clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(float(value), high))


def _delivery_days(value: Any) -> int | None:
    values = [int(item) for item in re.findall(r"\d+", str(value or ""))]
    return max(values) if values else None


def _competition_points(listings: int) -> float:
    if listings <= 100:
        return 15.0
    if listings <= 500:
        return 12.0
    if listings <= 2000:
        return 8.0
    if listings <= 5000:
        return 4.0
    return 2.0


def _cost_ratio_points(cost_ratio: float) -> float:
    if cost_ratio <= 20:
        return 20.0
    if cost_ratio <= 30:
        return 20.0 - (cost_ratio - 20.0) * 0.5
    if cost_ratio <= 40:
        return 15.0 - (cost_ratio - 30.0) * 0.7
    if cost_ratio <= 50:
        return 8.0 - (cost_ratio - 40.0) * 0.6
    return 0.0


def _margin_points(margin_percent: float | None) -> float:
    if margin_percent is None:
        return 0.0
    return _clamp(float(margin_percent) / 40.0 * 35.0, 0.0, 35.0)


def _delivery_points(days: int | None, maximum: int) -> float:
    if days is None or days <= 0:
        return 0.0
    if days <= 3:
        return 5.0
    if days <= 5:
        return 4.0
    if days <= maximum:
        return 3.0
    if days <= maximum + 3:
        return 1.0
    return 0.0


def _demand_points(research: dict[str, Any]) -> float:
    raw = (research.get("demand_proxy") or {}).get("score")
    if raw is None:
        return 0.0
    return _clamp(float(raw) / 100.0 * 10.0, 0.0, 10.0)


def _market_context(ebay: dict[str, Any], amazon: dict[str, Any] | None) -> dict[str, Any]:
    markets = [ebay] + ([amazon] if amazon else [])
    research = build_product_research_summary(markets)
    reference_price = ebay.get("median_price")
    listings = int(ebay.get("total_results") or 0)
    return {
        "markets": markets,
        "research": research,
        "reference_price": round(float(reference_price), 2) if reference_price is not None else None,
        "currency": str(ebay.get("currency") or "EUR"),
        "active_listings": listings,
        "competition": (research.get("competition") or {}).get("label") or "Non mesurée",
        "competition_points": _competition_points(listings),
        "demand_points": _demand_points(research),
    }


def _choose_freight(options: list[dict[str, Any]], max_days: int) -> dict[str, Any] | None:
    usable = []
    for row in options:
        try:
            price = float(row.get("price_usd") or 0)
        except (TypeError, ValueError):
            continue
        if price < 0:
            continue
        days = _delivery_days(row.get("delivery_days"))
        usable.append((row, price, days))
    if not usable:
        return None
    fast = [item for item in usable if item[2] is not None and item[2] <= max_days]
    pool = fast or usable
    selected, _, _ = min(pool, key=lambda item: (item[1], item[2] if item[2] is not None else 999))
    return selected


def _source_country(variant: dict[str, Any]) -> str:
    inventories = [row for row in variant.get("inventories") or [] if int(row.get("stock") or 0) > 0]
    preferred = ("FR", "DE", "ES", "IT", "PL", "NL", "BE", "CZ", "CN")
    for country in preferred:
        if any(str(row.get("country_code") or "").upper() == country for row in inventories):
            return country
    return str(next((row.get("country_code") for row in inventories if row.get("country_code")), "CN")).upper()


async def _deep_cj_candidate(
    client: CJClient,
    product: dict[str, Any],
    *,
    exchange_rate: float,
    reference_price: float,
    market: dict[str, Any],
    semaphore: asyncio.Semaphore,
) -> tuple[dict[str, Any] | None, str | None]:
    settings = get_settings()
    async with semaphore:
        try:
            pid = str(product.get("cj_pid") or "").strip()
            if not pid:
                return None, "CJ : identifiant produit manquant"
            detail = await client.product_detail(pid)
            variants = [row for row in detail.get("variants") or [] if float(row.get("price_usd") or 0) > 0]
            if not variants:
                return None, f"CJ {pid} : aucune variante exploitable"
            stocked = [row for row in variants if int(row.get("stock") or 0) > 0]
            variant = min(stocked or variants, key=lambda row: (float(row.get("price_usd") or 0), -int(row.get("stock") or 0)))
            country = _source_country(variant)
            freight = await client.freight_options(variant["vid"], start_country=country, destination_country="FR")
            chosen = _choose_freight(freight, settings.max_shipping_days)
            if not chosen:
                return None, f"CJ {pid} : aucun transport France exploitable"

            supplier_cost = round(float(variant.get("price_usd") or product.get("price_usd") or 0) * exchange_rate, 2)
            shipping_cost = round(float(chosen.get("price_usd") or 0) * exchange_rate, 2)
            landed_cost = round(supplier_cost + shipping_cost, 2)
            if reference_price <= 0:
                return None, "Prix eBay de référence indisponible"
            cost_ratio = round(landed_cost / reference_price * 100.0, 1)
            profit = calculate_profit({"supplier_cost": supplier_cost, "shipping_cost": shipping_cost}, reference_price)
            margin_percent = profit.get("margin_percent")
            estimated_profit = profit.get("estimated_profit")
            days = _delivery_days(chosen.get("delivery_days"))
            relevance = float(product.get("match_strength") or 0)

            score = (
                _margin_points(margin_percent)
                + _cost_ratio_points(cost_ratio)
                + market["competition_points"]
                + relevance * 15.0
                + market["demand_points"]
                + _delivery_points(days, settings.max_shipping_days)
            )
            score = round(_clamp(score), 1)
            goal_hit = (
                cost_ratio <= TARGET_LANDED_RATIO
                and margin_percent is not None
                and float(margin_percent) >= settings.min_margin_percent
                and estimated_profit is not None
                and float(estimated_profit) >= settings.min_profit_eur
                and days is not None
                and days <= settings.max_shipping_days
            )
            if goal_hit and score >= 70:
                verdict = "PRIORITÉ"
            elif margin_percent is not None and float(margin_percent) >= settings.min_margin_percent and cost_ratio <= 40:
                verdict = "À TESTER"
            elif days is not None and days > settings.max_shipping_days:
                verdict = "LIVRAISON LENTE"
            else:
                verdict = "À CREUSER"

            return {
                "provider": "CJ",
                "verified": True,
                "confidence": "Élevée" if market["demand_points"] > 0 else "Moyenne",
                "score": score,
                "verdict": verdict,
                "goal_hit": goal_hit,
                "supplier_sku": str(product.get("sku") or pid),
                "cj_pid": pid,
                "name": product.get("name") or "Produit CJ",
                "image_url": variant.get("image_url") or product.get("image_url") or "",
                "source_url": "",
                "stock": int(variant.get("stock") or product.get("stock") or 0),
                "warehouse": country,
                "supplier_cost": supplier_cost,
                "shipping_cost": shipping_cost,
                "landed_cost": landed_cost,
                "currency": "EUR",
                "shipping_days": days,
                "reference_price": reference_price,
                "cost_ratio_percent": cost_ratio,
                "margin_percent": margin_percent,
                "estimated_profit": estimated_profit,
                "roi_percent": profit.get("roi_percent"),
                "match_strength": round(relevance, 2),
                "shipping_budget_to_30": round(max(reference_price * TARGET_LANDED_RATIO / 100.0 - supplier_cost, 0), 2),
                "quality_evidence": [
                    f"Coût livré France calculé : {landed_cost:.2f} EUR",
                    f"Transport {chosen.get('name') or 'CJ'} depuis {country}",
                    f"Prix eBay médian observé : {reference_price:.2f} EUR",
                ],
                "add_payload": {
                    "provider": "cj",
                    "supplier_sku": str(product.get("sku") or pid),
                    "cj_pid": pid,
                    "name": product.get("name") or "Produit CJ",
                    "price": float(product.get("price_usd") or 0),
                    "shipping_cost": None,
                    "currency": "USD",
                    "stock": int(product.get("stock") or 0),
                    "shipping_days": None,
                    "image_url": product.get("image_url") or "",
                    "source_url": "",
                },
            }, None
        except (CJError, RuntimeError, ValueError, TypeError) as exc:
            return None, f"CJ {product.get('cj_pid') or product.get('sku') or ''} : {exc}"


def _ali_candidates(
    offers: list[dict[str, Any]],
    *,
    reference_price: float,
    market: dict[str, Any],
) -> list[dict[str, Any]]:
    out = []
    for offer in offers[:ALI_POOL_LIMIT]:
        try:
            cost = float(offer.get("product_cost"))
        except (TypeError, ValueError):
            continue
        if cost <= 0 or reference_price <= 0:
            continue
        cost_ratio = round(cost / reference_price * 100.0, 1)
        shipping_budget = round(reference_price * TARGET_LANDED_RATIO / 100.0 - cost, 2)
        relevance = float(offer.get("match_strength") or 0)
        rating = offer.get("rating")
        try:
            rating_points = _clamp(float(rating or 0) / 5.0 * 5.0, 0.0, 5.0)
        except (TypeError, ValueError):
            rating_points = 0.0

        preliminary_margin = calculate_profit({"supplier_cost": cost, "shipping_cost": 0}, reference_price)
        room_points = 10.0 if shipping_budget >= reference_price * 0.12 else 6.0 if shipping_budget > 0 else 0.0
        raw_score = (
            _cost_ratio_points(cost_ratio)
            + market["competition_points"]
            + relevance * 20.0
            + market["demand_points"]
            + rating_points
            + room_points
        )
        score = round(min(_clamp(raw_score), 72.0), 1)
        if shipping_budget > 0 and cost_ratio <= TARGET_LANDED_RATIO:
            verdict = "À CONFIRMER"
        elif cost_ratio <= 45:
            verdict = "À CREUSER"
        else:
            verdict = "COÛT ÉLEVÉ"

        out.append({
            "provider": "AliExpress",
            "verified": False,
            "confidence": "Faible",
            "score": score,
            "verdict": verdict,
            "goal_hit": False,
            "supplier_sku": str(offer.get("supplier_sku") or ""),
            "cj_pid": "",
            "name": offer.get("name") or "Produit AliExpress",
            "image_url": offer.get("image_url") or "",
            "source_url": offer.get("source_url") or "",
            "stock": offer.get("stock"),
            "warehouse": offer.get("warehouse") or "CN/EU selon annonce",
            "supplier_cost": round(cost, 2),
            "shipping_cost": None,
            "landed_cost": None,
            "currency": offer.get("currency") or "EUR",
            "shipping_days": offer.get("shipping_days"),
            "reference_price": reference_price,
            "cost_ratio_percent": cost_ratio,
            "margin_percent": None,
            "estimated_profit": None,
            "roi_percent": None,
            "margin_ceiling_percent": preliminary_margin.get("margin_percent"),
            "match_strength": round(relevance, 2),
            "shipping_budget_to_30": max(shipping_budget, 0),
            "quality_evidence": [
                f"Prix produit observé : {cost:.2f} EUR",
                f"Budget transport maximal pour rester sous 30% : {max(shipping_budget, 0):.2f} EUR",
                "Transport non fourni par l'API : marge finale non validée",
            ],
            "add_payload": {
                "provider": "aliexpress",
                "supplier_sku": str(offer.get("supplier_sku") or ""),
                "cj_pid": "",
                "name": offer.get("name") or "Produit AliExpress",
                "price": cost,
                "shipping_cost": offer.get("shipping_cost"),
                "currency": offer.get("currency") or "EUR",
                "stock": offer.get("stock"),
                "shipping_days": offer.get("shipping_days"),
                "image_url": offer.get("image_url") or "",
                "source_url": offer.get("source_url") or "",
            },
        })
    return out


async def hunt_margin_opportunities(keyword: str, *, limit: int = MAX_RESULTS) -> dict[str, Any]:
    keyword = str(keyword or "").strip()
    if len(keyword) < 2:
        raise ValueError("Mot-clé trop court")
    limit = min(max(int(limit), 1), MAX_RESULTS)
    settings = get_settings()

    if settings.ebay_effective_env != "production" or not settings.ebay_client_id or not settings.ebay_client_secret:
        raise ValueError("Margin Hunter nécessite les clés eBay Production pour mesurer les prix et la concurrence réels.")

    amazon_connected = bool(connection_status("amazon").get("connected"))
    market_tasks: list[Any] = [analyze_ebay_market(keyword, "EBAY_FR")]
    if amazon_connected:
        market_tasks.append(analyze_amazon_market(keyword, "AMAZON_FR"))
    market_results = await asyncio.gather(*market_tasks, return_exceptions=True)
    ebay = market_results[0]
    if isinstance(ebay, Exception):
        raise ValueError(f"Analyse eBay impossible : {ebay}")
    amazon = None
    errors: list[dict[str, str]] = []
    if amazon_connected and len(market_results) > 1:
        if isinstance(market_results[1], Exception):
            errors.append({"source": "Amazon", "message": str(market_results[1])})
        else:
            amazon = market_results[1]

    market = _market_context(ebay, amazon)
    reference_price = market["reference_price"]
    if reference_price is None or reference_price <= 0:
        raise ValueError("eBay ne retourne aucun prix médian exploitable pour cette recherche.")
    if market["currency"].upper() != "EUR":
        raise ValueError("Margin Hunter V1 nécessite un prix eBay France en EUR.")

    candidates: list[dict[str, Any]] = []

    cj_client = CJClient()
    if cj_client.status().get("connected"):
        try:
            raw = await cj_client.search_products(keyword=keyword, size=CJ_POOL_SIZE, min_stock=3, order_by=0)
            relevant, rejected = rank_supplier_results(keyword, raw.get("products") or [], title_keys=("name",), limit=CJ_DEEP_LIMIT)
            exchange = await cj_client.usd_to_eur()
            semaphore = asyncio.Semaphore(3)
            deep = await asyncio.gather(*[
                _deep_cj_candidate(
                    cj_client,
                    product,
                    exchange_rate=float(exchange["rate"]),
                    reference_price=reference_price,
                    market=market,
                    semaphore=semaphore,
                )
                for product in relevant
            ])
            for candidate, error in deep:
                if candidate:
                    candidates.append(candidate)
                if error:
                    errors.append({"source": "CJ", "message": error})
            if rejected:
                errors.append({"source": "CJ", "message": f"{rejected} résultat(s) hors sujet masqué(s)"})
        except Exception as exc:
            errors.append({"source": "CJ", "message": str(exc)})
    else:
        errors.append({"source": "CJ", "message": "CJ n'est pas connecté"})

    if aliexpress_connection_status().get("connected"):
        offers, ali_errors = await aliexpress_dropship_supplier_offers(keyword)
        errors.extend(ali_errors)
        candidates.extend(_ali_candidates(offers, reference_price=reference_price, market=market))
    else:
        errors.append({"source": "AliExpress", "message": "AliExpress n'est pas connecté"})

    candidates.sort(key=lambda row: (-float(row.get("score") or 0), 0 if row.get("verified") else 1, float(row.get("cost_ratio_percent") or 999)))
    selected = candidates[:limit]
    return {
        "keyword": keyword,
        "target_landed_ratio_percent": TARGET_LANDED_RATIO,
        "market": {
            "reference_price": reference_price,
            "currency": market["currency"],
            "active_listings": market["active_listings"],
            "competition": market["competition"],
            "product_research_score": market["research"].get("score"),
            "demand_proxy": market["research"].get("demand_proxy"),
            "amazon_signal_used": amazon is not None,
        },
        "fees": {
            "ebay_percent": settings.default_ebay_fee_percent,
            "ads_percent": settings.default_ad_rate_percent,
            "returns_reserve_percent": settings.default_return_reserve_percent,
            "fixed_fee": settings.default_fixed_fee,
        },
        "candidates": selected,
        "total_candidates": len(candidates),
        "verified_candidates": sum(1 for row in selected if row.get("verified")),
        "goal_hits": sum(1 for row in selected if row.get("goal_hit")),
        "errors": errors,
        "note": (
            "CJ est scoré avec coût livré France réel. AliExpress reste préliminaire tant que le transport n'est pas confirmé. "
            "Le prix eBay utilisé est la médiane des annonces actives observées, pas un prix de vente garanti."
        ),
    }
