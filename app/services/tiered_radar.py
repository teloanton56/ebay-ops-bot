"""Tiered automatic Radar: frequent light monitoring plus periodic deep discovery."""

from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timezone
from statistics import median
from typing import Any, Awaitable

from app.config import get_settings
from app.services.auto_radar import (
    _AUTO_LOCK,
    _browse_category,
    _browse_seed,
    _confirm_social,
    _finish_run,
    _limited,
    _load_category_tree,
    _marketing_products,
    _measure_candidate,
    _start_run,
    _upsert_opportunity,
    auto_radar_status,
    extract_candidate_phrases,
    list_auto_opportunities,
    score_auto_opportunity,
    select_discovery_categories,
    FALLBACK_DISCOVERY_SEEDS,
)
from app.services.connections import connection_statuses
from app.services.db import conn, previous_radar_scan, save_radar_scan
from app.services.ebay import EbayClient
from app.services.radar_quota import RadarQuotaError, quota_status, reserve_browse_calls
from app.services.radar_runtime import estimate_daily_browse_calls, load_radar_settings

DISCOVERY_CATEGORY_COUNT = 8


def _safe_float(value: Any) -> float | None:
    try:
        return float(value) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _parse_date(value: Any) -> datetime | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None


def _latest_run_for(triggers: tuple[str, ...]) -> dict[str, Any] | None:
    placeholders = ",".join("?" for _ in triggers)
    with conn() as database:
        try:
            row = database.execute(
                f"SELECT * FROM radar_auto_runs WHERE trigger IN ({placeholders}) ORDER BY id DESC LIMIT 1",
                triggers,
            ).fetchone()
        except Exception:
            return None
    if not row:
        return None
    result = dict(row)
    try:
        result["errors"] = json.loads(result.pop("errors_json") or "[]")
    except (TypeError, json.JSONDecodeError):
        result["errors"] = []
    return result


def tiered_radar_status() -> dict[str, Any]:
    runtime = load_radar_settings()
    base = auto_radar_status()
    return {
        **base,
        "method": "EBAY_TIERED_V2",
        "quick_interval_minutes": runtime["quick_minutes"],
        "full_interval_hours": runtime["full_hours"],
        "interval_hours": runtime["full_hours"],
        "candidate_pool": runtime["candidate_pool"],
        "deep_candidates": runtime["deep_candidates"],
        "social_confirmations": runtime["social_confirmations"],
        "quick_opportunities": runtime["quick_opportunities"],
        "quota_reserve_percent": runtime["quota_reserve_percent"],
        "browse_daily_budget": runtime["browse_daily_budget"],
        "estimated_daily": estimate_daily_browse_calls(runtime),
        "last_quick_run": _latest_run_for(("scheduler-quick", "manual-quick")),
        "last_full_run": _latest_run_for(("scheduler-full", "manual-full", "manual")),
        "note": (
            f"Suivi léger toutes les {runtime['quick_minutes']} min et découverte complète toutes les "
            f"{runtime['full_hours']} h. Jusqu'à {runtime['candidate_pool']} candidats sont classés, "
            f"puis les {runtime['deep_candidates']} meilleurs sont analysés en profondeur."
        ),
    }


def _full_browse_estimate(runtime: dict[str, int]) -> int:
    return DISCOVERY_CATEGORY_COUNT * 2 + runtime["deep_candidates"] * 2


def _candidate_from_opportunity(opportunity: dict[str, Any]) -> dict[str, Any]:
    payload = opportunity.get("payload") if isinstance(opportunity.get("payload"), dict) else {}
    stored = payload.get("candidate") if isinstance(payload.get("candidate"), dict) else {}
    sources = list(stored.get("sources") or opportunity.get("sources") or [])
    if "Suivi eBay 30 min" not in sources:
        sources.append("Suivi eBay 30 min")
    return {
        **stored,
        "keyword": opportunity.get("keyword") or stored.get("keyword") or "",
        "category_name": opportunity.get("category_name") or stored.get("category_name") or "eBay",
        "sample_title": opportunity.get("title") or stored.get("sample_title") or opportunity.get("keyword") or "",
        "sample_image": opportunity.get("image_url") or stored.get("sample_image") or "",
        "sources": sources,
    }


async def _light_measure(client: EbayClient, opportunity: dict[str, Any], marketplace: str) -> dict[str, Any]:
    keyword = str(opportunity.get("keyword") or "").strip()
    payload = await client.public_request(
        "GET",
        "/buy/browse/v1/item_summary/search",
        params={"q": keyword, "limit": 50},
        marketplace_id=marketplace,
    )
    items = payload.get("itemSummaries") or []
    prices: list[float] = []
    sellers: list[str] = []
    recent = 0
    dated = 0
    fixed = 0
    for item in items:
        price = _safe_float((item.get("price") or {}).get("value"))
        if price is not None:
            prices.append(price)
        seller = str((item.get("seller") or {}).get("username") or "").strip()
        if seller:
            sellers.append(seller)
        if "FIXED_PRICE" in (item.get("buyingOptions") or []):
            fixed += 1
        origin = _parse_date(item.get("itemOriginDate"))
        if origin:
            dated += 1
            if (datetime.now(timezone.utc) - origin).total_seconds() <= 30 * 86400:
                recent += 1

    seller_counts = Counter(sellers)
    top_seller, top_count = seller_counts.most_common(1)[0] if seller_counts else ("", 0)
    previous_payload = opportunity.get("payload") if isinstance(opportunity.get("payload"), dict) else {}
    previous_measurement = previous_payload.get("measurement") if isinstance(previous_payload.get("measurement"), dict) else {}
    representative = next((item for item in items if item.get("itemId")), {})
    currency = next(
        (
            str((item.get("price") or {}).get("currency") or "")
            for item in items
            if (item.get("price") or {}).get("currency")
        ),
        opportunity.get("currency") or "EUR",
    )
    result = {
        "keyword": keyword,
        "source": "EBAY_AUTO_QUICK",
        "marketplace": marketplace,
        "marketplace_name": marketplace,
        "total_results": int(payload.get("total") or len(items)),
        "currency": currency,
        "median_price": round(median(prices), 2) if prices else opportunity.get("median_price"),
        "min_price": round(min(prices), 2) if prices else previous_measurement.get("min_price"),
        "max_price": round(max(prices), 2) if prices else previous_measurement.get("max_price"),
        "sellers_sample": len(seller_counts),
        "top_seller": top_seller,
        "top_seller_share": round(top_count / len(sellers) * 100, 1) if sellers else 0,
        "recent_listing_share": round(recent / dated * 100, 1) if dated else previous_measurement.get("recent_listing_share"),
        "fixed_price_share": round(fixed / len(items) * 100, 1) if items else previous_measurement.get("fixed_price_share"),
        "sold_quantity": opportunity.get("sold_quantity"),
        "sales_velocity": opportunity.get("sales_velocity"),
        "listing_age_days": previous_measurement.get("listing_age_days"),
        "item_url": opportunity.get("item_url") or representative.get("itemWebUrl") or "",
        "image_url": opportunity.get("image_url") or ((representative.get("image") or {}).get("imageUrl") or ""),
        "representative_title": opportunity.get("title") or representative.get("title") or keyword,
        "items_observed": len(items),
    }
    scan_id = save_radar_scan(result)
    previous = previous_radar_scan(keyword, "EBAY_AUTO_QUICK", marketplace, scan_id)
    result["history_available"] = bool(previous) or bool(previous_measurement)
    result["listing_change_percent"] = None
    if previous and int(previous.get("total_results") or 0) > 0:
        result["listing_change_percent"] = round(
            (result["total_results"] - int(previous["total_results"]))
            / int(previous["total_results"])
            * 100,
            1,
        )
    return result


async def run_quick_radar(marketplace: str | None = None, trigger: str = "manual-quick") -> dict[str, Any]:
    settings = get_settings()
    runtime = load_radar_settings()
    market = marketplace or settings.ebay_marketplace_id or "EBAY_FR"
    if settings.ebay_effective_env != "production" or not settings.ebay_client_id or not settings.ebay_client_secret:
        raise RuntimeError("Des clés eBay Production sont nécessaires pour le suivi rapide")
    if _AUTO_LOCK.locked():
        raise RuntimeError("Une analyse automatique du Radar est déjà en cours")

    opportunities = list_auto_opportunities(runtime["quick_opportunities"])
    if not opportunities:
        return {
            "status": "NO_OP",
            "marketplace": market,
            "opportunities_refreshed": 0,
            "alerts_created": 0,
            "message": "Aucune opportunité enregistrée à actualiser. Lancez d'abord un grand scan.",
        }

    quota = await reserve_browse_calls(len(opportunities), trigger)
    async with _AUTO_LOCK:
        run_id = _start_run(trigger, market)
        errors: list[dict[str, Any]] = []
        stored: list[dict[str, Any]] = []
        alerts_created = 0
        try:
            client = EbayClient()
            await client.get_application_token()
            raw = await _limited(
                [_light_measure(client, opportunity, market) for opportunity in opportunities],
                concurrency=5,
            )
            for opportunity, measurement in zip(opportunities, raw):
                if isinstance(measurement, Exception):
                    errors.append(
                        {
                            "source": "Suivi rapide",
                            "keyword": opportunity.get("keyword"),
                            "message": str(measurement),
                        }
                    )
                    continue
                candidate = _candidate_from_opportunity(opportunity)
                social_payload = opportunity.get("social") if isinstance(opportunity.get("social"), dict) else {}
                score = score_auto_opportunity(candidate, measurement, social_payload)
                updated, alerted = _upsert_opportunity(candidate, measurement, score, social_payload, market)
                stored.append(updated)
                alerts_created += int(alerted)

            stored.sort(key=lambda row: float(row.get("score") or 0), reverse=True)
            _finish_run(
                run_id,
                status="COMPLETED",
                categories=0,
                candidates=len(stored),
                opportunities=len(stored),
                alerts=alerts_created,
                errors=errors,
            )
            return {
                "run_id": run_id,
                "status": "COMPLETED",
                "mode": "QUICK",
                "marketplace": market,
                "opportunities_refreshed": len(stored),
                "opportunities": stored,
                "alerts_created": alerts_created,
                "errors": errors,
                "quota": quota,
                "method": "EBAY_TIERED_V2",
            }
        except Exception as exc:
            errors.append({"source": "Suivi rapide", "message": str(exc)})
            _finish_run(
                run_id,
                status="FAILED",
                categories=0,
                candidates=0,
                opportunities=len(stored),
                alerts=alerts_created,
                errors=errors,
            )
            raise


async def run_full_radar(marketplace: str | None = None, trigger: str = "manual-full") -> dict[str, Any]:
    settings = get_settings()
    runtime = load_radar_settings()
    market = marketplace or settings.ebay_marketplace_id or "EBAY_FR"
    if settings.ebay_effective_env != "production" or not settings.ebay_client_id or not settings.ebay_client_secret:
        raise RuntimeError("Des clés eBay Production sont nécessaires pour la découverte automatique")
    if _AUTO_LOCK.locked():
        raise RuntimeError("Une analyse automatique du Radar est déjà en cours")

    quota = await reserve_browse_calls(_full_browse_estimate(runtime), trigger, force_actual=True)
    async with _AUTO_LOCK:
        run_id = _start_run(trigger, market)
        errors: list[dict[str, Any]] = []
        categories: list[dict[str, str]] = []
        candidates: list[dict[str, Any]] = []
        deep_candidates: list[dict[str, Any]] = []
        stored: list[dict[str, Any]] = []
        alerts_created = 0
        try:
            client = EbayClient()
            await client.get_application_token()
            try:
                tree = await _load_category_tree(client, market)
                categories = select_discovery_categories(tree, limit=DISCOVERY_CATEGORY_COUNT)
            except Exception as exc:
                errors.append({"source": "Taxonomy", "message": str(exc)})

            browse_calls: list[Awaitable[Any]] = []
            marketing_calls: list[Awaitable[Any]] = []
            if categories:
                for category in categories:
                    browse_calls.extend(
                        [
                            _browse_category(client, category, market),
                            _browse_category(client, category, market, "newlyListed"),
                        ]
                    )
                    marketing_calls.append(_marketing_products(client, category, market))
            else:
                fallback = list(FALLBACK_DISCOVERY_SEEDS)[:DISCOVERY_CATEGORY_COUNT]
                categories = [{"id": "", "name": group, "group": group} for group, _ in fallback]
                for group, query in fallback:
                    browse_calls.extend(
                        [
                            _browse_seed(client, group, query, market),
                            _browse_seed(client, group, query, market, "newlyListed"),
                        ]
                    )

            browse_raw = await _limited(browse_calls, concurrency=5)
            browse_rows = []
            for item in browse_raw:
                if isinstance(item, Exception):
                    errors.append({"source": "Browse", "message": str(item)})
                else:
                    browse_rows.append(item)

            marketing_rows = []
            if marketing_calls:
                marketing_raw = await _limited(marketing_calls, concurrency=3)
                marketing_denied = False
                for item in marketing_raw:
                    if isinstance(item, Exception):
                        if not marketing_denied:
                            errors.append(
                                {
                                    "source": "Marketing API",
                                    "message": "Accès Best Selling indisponible; le Radar continue avec Browse API.",
                                }
                            )
                            marketing_denied = True
                    else:
                        marketing_rows.append(item)

            candidates = extract_candidate_phrases(
                browse_rows,
                marketing_rows,
                limit=runtime["candidate_pool"],
            )
            deep_candidates = candidates[: runtime["deep_candidates"]]
            measurements_raw = await _limited(
                [_measure_candidate(client, candidate, market) for candidate in deep_candidates],
                concurrency=4,
            )
            measured_pairs = []
            for candidate, measurement in zip(deep_candidates, measurements_raw):
                if isinstance(measurement, Exception):
                    errors.append(
                        {
                            "source": "Mesure eBay",
                            "keyword": candidate["keyword"],
                            "message": str(measurement),
                        }
                    )
                else:
                    measured_pairs.append((candidate, measurement))

            connected_social = [
                row["id"]
                for row in connection_statuses()
                if row.get("connected") and row.get("id") in {"youtube", "tiktok", "etsy"}
            ]
            preliminary = [
                (candidate, measurement, score_auto_opportunity(candidate, measurement, None))
                for candidate, measurement in measured_pairs
            ]
            preliminary.sort(key=lambda row: row[2]["score"], reverse=True)
            social_targets = (
                preliminary[: runtime["social_confirmations"]]
                if connected_social and runtime["social_confirmations"]
                else []
            )
            social_raw = (
                await _limited(
                    [_confirm_social(candidate, connected_social, "FR") for candidate, _, _ in social_targets],
                    concurrency=2,
                )
                if social_targets
                else []
            )
            social_by_keyword = {
                candidate["keyword"]: (
                    payload
                    if not isinstance(payload, Exception)
                    else {"results": [], "errors": [{"message": str(payload)}]}
                )
                for (candidate, _, _), payload in zip(social_targets, social_raw)
            }

            for candidate, measurement in measured_pairs:
                social_payload = social_by_keyword.get(candidate["keyword"], {"results": [], "errors": []})
                scored = score_auto_opportunity(candidate, measurement, social_payload)
                opportunity, alerted = _upsert_opportunity(candidate, measurement, scored, social_payload, market)
                stored.append(opportunity)
                alerts_created += int(alerted)

            stored.sort(key=lambda row: float(row.get("score") or 0), reverse=True)
            _finish_run(
                run_id,
                status="COMPLETED",
                categories=len(categories),
                candidates=len(measured_pairs),
                opportunities=len(stored),
                alerts=alerts_created,
                errors=errors,
            )
            return {
                "run_id": run_id,
                "status": "COMPLETED",
                "mode": "FULL",
                "marketplace": market,
                "categories_scanned": len(categories),
                "candidates_collected": len(candidates),
                "candidates_measured": len(measured_pairs),
                "opportunities": stored,
                "alerts_created": alerts_created,
                "social_sources": connected_social,
                "social_confirmations": len(social_targets),
                "errors": errors,
                "quota": quota,
                "method": "EBAY_TIERED_V2",
            }
        except Exception as exc:
            errors.append({"source": "Grand scan", "message": str(exc)})
            _finish_run(
                run_id,
                status="FAILED",
                categories=len(categories),
                candidates=len(deep_candidates),
                opportunities=len(stored),
                alerts=alerts_created,
                errors=errors,
            )
            raise


async def get_quota_status(force: bool = False) -> dict[str, Any]:
    return await quota_status(force=force)


__all__ = [
    "RadarQuotaError",
    "get_quota_status",
    "run_full_radar",
    "run_quick_radar",
    "tiered_radar_status",
]
