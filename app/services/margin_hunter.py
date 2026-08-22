from __future__ import annotations

import asyncio
from typing import Any

from app.config import get_settings
from app.services.cj import CJClient, CJError
from app.services.cj_landed import resolve_cj_landed_offer, route_requirements
from app.services.product_research import build_product_research_summary
from app.services.profit import calculate_profit
from app.services.radar import analyze_ebay_market
from app.services.supplier_relevance import rank_supplier_results


TARGET_LANDED_RATIO = 30.0
CJ_POOL_SIZE = 50
CJ_DEEP_LIMIT = 8
MAX_RESULTS = 10


def _clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(float(value), high))


def _competition_points(listings: int) -> float:
    if listings <= 0:
        return 0.0
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
        return 8.0
    if days <= 5:
        return 6.0
    if days <= maximum:
        return 4.0
    return 0.0


def _demand_points(research: dict[str, Any]) -> float:
    raw = (research.get("demand_proxy") or {}).get("score")
    if raw is None:
        return 0.0
    return _clamp(float(raw) / 100.0 * 10.0, 0.0, 10.0)


def _market_context(ebay: dict[str, Any]) -> dict[str, Any]:
    research = build_product_research_summary([ebay])
    reference_price = ebay.get("median_price")
    listings = int(ebay.get("total_results") or 0)
    return {
        "research": research,
        "reference_price": round(float(reference_price), 2) if reference_price is not None else None,
        "currency": str(ebay.get("currency") or "USD"),
        "active_listings": listings,
        "competition": (research.get("competition") or {}).get("label") or "Non mesurée",
        "competition_points": _competition_points(listings),
        "demand_points": _demand_points(research),
    }


async def _deep_cj_candidate(
    client: CJClient,
    product: dict[str, Any],
    *,
    reference_price: float,
    market: dict[str, Any],
    semaphore: asyncio.Semaphore,
) -> tuple[dict[str, Any] | None, str | None]:
    async with semaphore:
        try:
            pid = str(product.get("cj_pid") or "").strip()
            if not pid:
                return None, "CJ : identifiant produit manquant"

            landed = await resolve_cj_landed_offer(
                client,
                pid,
                fallback_price_usd=float(product.get("price_usd") or 0),
                destination_country="US",
                reference_price=reference_price,
            )
            supplier_cost = float(landed["supplier_cost"])
            shipping_cost = float(landed["shipping_cost"])
            landed_cost = float(landed["landed_cost"])
            warehouse = str(landed.get("warehouse") or "")
            requirements = route_requirements(warehouse)
            profit = landed.get("profit") or calculate_profit(
                {"supplier_cost": supplier_cost, "shipping_cost": shipping_cost},
                reference_price,
            )
            margin_percent = profit.get("margin_percent")
            estimated_profit = profit.get("estimated_profit")
            days = int(landed["shipping_days"])
            relevance = float(product.get("match_strength") or 0)
            cost_ratio = round(landed_cost / reference_price * 100.0, 1)
            route_bonus = 10.0 if warehouse == "US" else 0.0

            score = (
                _margin_points(margin_percent)
                + _cost_ratio_points(cost_ratio)
                + market["competition_points"]
                + relevance * 12.0
                + market["demand_points"]
                + _delivery_points(days, int(requirements["max_shipping_days"]))
                + route_bonus
            )
            if not landed.get("eligible"):
                score = min(score, 54.0)
            score = round(_clamp(score), 1)

            goal_hit = bool(
                landed.get("eligible")
                and cost_ratio <= TARGET_LANDED_RATIO
                and margin_percent is not None
                and estimated_profit is not None
            )
            if goal_hit and warehouse == "US" and score >= 70:
                verdict = "PRIORITÉ US"
            elif goal_hit and warehouse == "CN":
                verdict = "CHINE RENTABLE"
            elif landed.get("eligible"):
                verdict = "À TESTER"
            else:
                verdict = "REJETER"

            route_label = "CJ US" if warehouse == "US" else "CJ China → US"
            return {
                "provider": "CJ",
                "verified": True,
                "confidence": "Élevée" if warehouse == "US" else "Moyenne",
                "score": score,
                "verdict": verdict,
                "goal_hit": goal_hit,
                "route_eligible": bool(landed.get("eligible")),
                "supplier_sku": str(product.get("sku") or pid),
                "cj_pid": pid,
                "name": product.get("name") or "Produit CJ",
                "image_url": landed.get("image_url") or product.get("image_url") or "",
                "source_url": "",
                "stock": int(landed.get("stock") or 0),
                "warehouse": warehouse,
                "route": route_label,
                "supplier_cost": supplier_cost,
                "shipping_cost": shipping_cost,
                "landed_cost": landed_cost,
                "currency": "USD",
                "shipping_days": days,
                "reference_price": reference_price,
                "cost_ratio_percent": cost_ratio,
                "margin_percent": margin_percent,
                "estimated_profit": estimated_profit,
                "roi_percent": profit.get("roi_percent"),
                "match_strength": round(relevance, 2),
                "requirements": requirements,
                "quality_evidence": [
                    f"Route retenue : {route_label}",
                    f"Coût livré US calculé : ${landed_cost:.2f}",
                    f"Transport {landed.get('freight_name') or 'CJ'} · {days} jours",
                    f"Prix médian eBay US observé : ${reference_price:.2f}",
                    f"Seuil route : marge ≥ {requirements['min_margin_percent']}% · profit ≥ ${requirements['min_profit']}",
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


async def hunt_margin_opportunities(keyword: str, *, limit: int = MAX_RESULTS) -> dict[str, Any]:
    keyword = str(keyword or "").strip()
    if len(keyword) < 2:
        raise ValueError("Mot-clé trop court")
    limit = min(max(int(limit), 1), MAX_RESULTS)
    settings = get_settings()

    if settings.ebay_effective_env != "production" or not settings.ebay_client_id or not settings.ebay_client_secret:
        raise ValueError("Margin Hunter nécessite les clés eBay Production pour mesurer le marché US réel.")

    ebay = await analyze_ebay_market(keyword, "EBAY_US")
    market = _market_context(ebay)
    reference_price = market["reference_price"]
    if reference_price is None or reference_price <= 0:
        raise ValueError("eBay US ne retourne aucun prix médian exploitable pour cette recherche.")
    if market["currency"].upper() != "USD":
        raise ValueError("Margin Hunter v0.23 attend des prix eBay US en USD.")

    candidates: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    cj_client = CJClient()
    if not cj_client.status().get("connected"):
        errors.append({"source": "CJ", "message": "CJ n'est pas connecté"})
    else:
        try:
            raw = await cj_client.search_products(keyword=keyword, size=CJ_POOL_SIZE, min_stock=1, order_by=0)
            relevant, rejected = rank_supplier_results(
                keyword,
                raw.get("products") or [],
                title_keys=("name",),
                limit=CJ_DEEP_LIMIT,
            )
            semaphore = asyncio.Semaphore(3)
            deep = await asyncio.gather(*[
                _deep_cj_candidate(
                    cj_client,
                    product,
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

    candidates.sort(
        key=lambda row: (
            0 if row.get("goal_hit") else 1,
            0 if row.get("warehouse") == "US" else 1,
            -float(row.get("score") or 0),
            float(row.get("cost_ratio_percent") or 999),
        )
    )
    selected = candidates[:limit]
    return {
        "keyword": keyword,
        "market": {
            "marketplace": "EBAY_US",
            "reference_price": reference_price,
            "currency": "USD",
            "active_listings": market["active_listings"],
            "competition": market["competition"],
            "product_research_score": market["research"].get("score"),
            "demand_proxy": market["research"].get("demand_proxy"),
        },
        "fees": {
            "ebay_percent": settings.default_ebay_fee_percent,
            "ads_percent": settings.default_ad_rate_percent,
            "returns_reserve_percent": settings.default_return_reserve_percent,
            "order_fee_over_10": settings.ebay_standard_order_fee,
        },
        "route_policy": {
            "US": route_requirements("US"),
            "CN": route_requirements("CN"),
            "rule": "US prioritaire. Chine uniquement si ses seuils renforcés de marge, profit, stock et délai sont respectés.",
        },
        "candidates": selected,
        "total_candidates": len(candidates),
        "verified_candidates": len(selected),
        "goal_hits": sum(1 for row in selected if row.get("goal_hit")),
        "errors": errors,
        "note": "Margin Hunter v0.23 compare uniquement eBay US à CJ Dropshipping, en USD et avec coût livré vers les États-Unis.",
    }
