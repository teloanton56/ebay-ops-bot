from __future__ import annotations

import json
import math
from collections import Counter
from datetime import datetime, timezone
from statistics import median
from typing import Any

from app.services.connections import AmazonRadarClient, connection_status
from app.services.ebay import EbayClient
from app.services.db import utc_now
from app.services.opportunity_store import (
    SELLER_LIMIT, _add_event, _limited, _safe_float, _safe_int, _update_workflow, get_workflow,
)

async def seller_intelligence(workflow_id: int) -> dict[str, Any]:
    workflow = get_workflow(workflow_id)
    keyword = workflow.get("keyword") or ""
    marketplace = workflow.get("marketplace") or "EBAY_FR"
    client = EbayClient()
    payload = await client.search_items(keyword, 100, marketplace)
    items = payload.get("itemSummaries") or []
    counts: Counter[str] = Counter()
    seller_meta: dict[str, dict[str, Any]] = {}
    for item in items:
        seller = item.get("seller") or {}
        username = str(seller.get("username") or "").strip()
        if not username:
            continue
        counts[username] += 1
        seller_meta[username] = {
            "feedback_score": _safe_int(seller.get("feedbackScore")),
            "feedback_percentage": _safe_float(seller.get("feedbackPercentage")),
            "seller_account_type": seller.get("sellerAccountType"),
        }

    top = counts.most_common(SELLER_LIMIT)

    async def inspect(username: str, niche_count: int) -> dict[str, Any]:
        params = {
            "q": keyword,
            "limit": 50,
            "filter": f"sellers:{{{username}}}",
            "sort": "newlyListed",
        }
        response = await client.public_request(
            "GET", "/buy/browse/v1/item_summary/search", params=params, marketplace_id=marketplace
        )
        rows = response.get("itemSummaries") or []
        prices = [
            float((row.get("price") or {}).get("value"))
            for row in rows
            if _safe_float((row.get("price") or {}).get("value")) is not None
        ]
        recent = 0
        dated = 0
        categories: Counter[str] = Counter()
        for row in rows:
            raw_date = str(row.get("itemOriginDate") or "")
            if raw_date:
                try:
                    origin = datetime.fromisoformat(raw_date.replace("Z", "+00:00"))
                    dated += 1
                    if (datetime.now(timezone.utc) - origin).total_seconds() <= 30 * 86400:
                        recent += 1
                except ValueError:
                    pass
            for category in row.get("categories") or []:
                if category.get("categoryName"):
                    categories[str(category["categoryName"])] += 1
        recent_share = round(recent / dated * 100, 1) if dated else None
        meta = seller_meta.get(username) or {}
        return {
            "username": username,
            "listings_in_initial_sample": niche_count,
            "niche_results": int(response.get("total") or len(rows)),
            "observed_listings": len(rows),
            "recent_listing_share": recent_share,
            "median_price": round(median(prices), 2) if prices else None,
            "feedback_score": meta.get("feedback_score"),
            "feedback_percentage": meta.get("feedback_percentage"),
            "seller_account_type": meta.get("seller_account_type"),
            "top_categories": [name for name, _ in categories.most_common(5)],
            "activity_label": (
                "Accélération récente" if recent_share is not None and recent_share >= 35
                else "Activité régulière" if recent_share is not None and recent_share >= 10
                else "Données récentes limitées"
            ),
            "note": "Analyse de l'activité publique dans cette niche, pas du chiffre d'affaires total du vendeur.",
        }

    raw = await _limited([inspect(username, count) for username, count in top], concurrency=3)
    sellers = []
    errors = []
    for (username, _), item in zip(top, raw):
        if isinstance(item, Exception):
            errors.append({"seller": username, "message": str(item)})
        else:
            sellers.append(item)
    emerging = [row for row in sellers if row.get("activity_label") == "Accélération récente"]
    snapshot = {
        "keyword": keyword,
        "observed_at": utc_now(),
        "total_results": int(payload.get("total") or len(items)),
        "seller_count_sample": len(counts),
        "top_seller_share": round(top[0][1] / max(sum(counts.values()), 1) * 100, 1) if top else 0,
        "sellers": sellers,
        "emerging_count": len(emerging),
        "errors": errors,
        "meaning": (
            "Le module observe les annonces publiques d'une niche et les ajouts récents. Il ne déduit ni chiffre "
            "d'affaires exact ni date de création du compte vendeur."
        ),
    }
    _update_workflow(
        workflow_id,
        seller_snapshot_json=json.dumps(snapshot, ensure_ascii=False),
    )
    _add_event(
        workflow_id,
        "SELLER_INTELLIGENCE",
        f"{len(sellers)} vendeur(s) analysé(s) dans la niche",
        payload={"emerging_count": len(emerging), "errors": errors},
    )
    return snapshot


def _median_int(values: list[int]) -> int | None:
    return int(median(values)) if values else None


async def amazon_intelligence(workflow_id: int) -> dict[str, Any]:
    workflow = get_workflow(workflow_id)
    if not connection_status("amazon").get("connected"):
        raise ValueError("Amazon SP-API n'est pas encore connecté")
    keyword = workflow.get("keyword") or ""
    previous = workflow.get("amazon_snapshot") or {}
    payload = await AmazonRadarClient().search_catalog(keyword, "AMAZON_FR", page_size=20, include_pricing=True)
    products = payload.get("products") or []
    ranks = [int(row["sales_rank"]) for row in products if _safe_int(row.get("sales_rank")) is not None]
    prices = [float(row["price"]) for row in products if _safe_float(row.get("price")) is not None]
    offers = [int(row["offer_count"]) for row in products if _safe_int(row.get("offer_count")) is not None]
    best_rank = min(ranks) if ranks else None
    previous_rank = _safe_int(previous.get("best_sales_rank"))
    rank_change = previous_rank - best_rank if previous_rank is not None and best_rank is not None else None
    if best_rank is None:
        amazon_score = 0
    elif best_rank <= 1_000:
        amazon_score = 35
    elif best_rank <= 5_000:
        amazon_score = 30
    elif best_rank <= 20_000:
        amazon_score = 23
    elif best_rank <= 50_000:
        amazon_score = 15
    elif best_rank <= 100_000:
        amazon_score = 8
    else:
        amazon_score = 3
    if rank_change and rank_change > 0:
        amazon_score = min(40, amazon_score + min(5, math.log10(rank_change + 1) * 1.5))
    ebay_score = _safe_float(workflow.get("opportunity", {}).get("score")) or 0
    competition_score = _safe_float(workflow.get("opportunity", {}).get("competition_score")) or 0
    if amazon_score >= 25 and ebay_score >= 65:
        signal = "CONFIRMED_MULTI_MARKET"
        label = "Confirmé Amazon + eBay"
    elif amazon_score >= 25 and competition_score >= 15:
        signal = "AMAZON_TO_EBAY"
        label = "Transfert Amazon → eBay"
    elif ebay_score >= 65:
        signal = "EBAY_EMERGING"
        label = "Tendance eBay émergente"
    else:
        signal = "INSUFFICIENT"
        label = "Signal à confirmer"
    snapshot = {
        "keyword": keyword,
        "observed_at": utc_now(),
        "connected": True,
        "total_results": int(payload.get("total") or len(products)),
        "products_observed": len(products),
        "ranked_products": len(ranks),
        "best_sales_rank": best_rank,
        "median_sales_rank": _median_int(ranks),
        "rank_change": rank_change,
        "median_price": round(median(prices), 2) if prices else None,
        "offer_count_total": sum(offers) if offers else None,
        "pricing_available": bool(payload.get("pricing_available")),
        "brand_count": len({str(row.get("brand") or "").strip() for row in products if str(row.get("brand") or "").strip()}),
        "amazon_score": round(amazon_score, 1),
        "signal": signal,
        "signal_label": label,
        "products": products[:10],
        "meaning": "Le classement des ventes est un indicateur relatif; il n'est pas converti en ventes exactes.",
    }
    _update_workflow(
        workflow_id,
        amazon_snapshot_json=json.dumps(snapshot, ensure_ascii=False),
    )
    _add_event(
        workflow_id,
        "AMAZON_INTELLIGENCE",
        f"Amazon : {label}",
        payload={"best_sales_rank": best_rank, "amazon_score": snapshot["amazon_score"]},
    )
    return snapshot
