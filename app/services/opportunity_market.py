from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timezone
from statistics import median
from typing import Any

from app.services.ebay import EbayClient
from app.services.db import utc_now
from app.services.opportunity_store import (
    SELLER_LIMIT, _add_event, _limited, _safe_float, _safe_int, _update_workflow, get_workflow,
)

async def seller_intelligence(workflow_id: int) -> dict[str, Any]:
    workflow = get_workflow(workflow_id)
    keyword = workflow.get("keyword") or ""
    marketplace = workflow.get("marketplace") or "EBAY_US"
    if marketplace != "EBAY_US":
        raise ValueError("L'intelligence vendeur est limitée à eBay US")
    client = EbayClient()
    payload = await client.search_items(keyword, 100, marketplace)
    items = [
        row for row in payload.get("itemSummaries") or []
        if str((row.get("price") or {}).get("currency") or "USD").upper() == "USD"
    ]
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
        rows = [
            row for row in response.get("itemSummaries") or []
            if str((row.get("price") or {}).get("currency") or "USD").upper() == "USD"
        ]
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
