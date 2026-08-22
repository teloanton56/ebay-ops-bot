from __future__ import annotations

import asyncio
from typing import Any

from app.services.cj import CJClient
from app.services.margin_hunter import _deep_cj_candidate
from app.services.sourcing_queries import build_supplier_search_queries
from app.services.supplier_relevance import rank_supplier_results


MAX_SUPPLIER_RESULTS = 8
CJ_POOL_LIMIT = 8


def _candidate_key(row: dict[str, Any], *fields: str) -> str:
    for field in fields:
        value = str(row.get(field) or "").strip()
        if value:
            return value
    return str(row.get("name") or row.get("title") or "").strip().casefold()


def _merge_best(target: dict[str, dict[str, Any]], key: str, row: dict[str, Any]) -> None:
    if not key:
        return
    previous = target.get(key)
    if previous is None or float(row.get("match_strength") or 0) > float(previous.get("match_strength") or 0):
        target[key] = row


async def _search_cj_variants(client: CJClient, queries: list[str]) -> tuple[list[dict[str, Any]], list[str]]:
    merged: dict[str, dict[str, Any]] = {}
    failures: list[str] = []
    for query in queries:
        try:
            payload = await client.search_products(keyword=query, size=50, min_stock=1, order_by=0)
        except Exception as exc:
            failures.append(f"{query}: {exc}")
            continue

        relevant, _ = rank_supplier_results(
            query,
            payload.get("products") or [],
            title_keys=("name",),
            limit=CJ_POOL_LIMIT,
        )
        for product in relevant:
            enriched = dict(product)
            enriched["matched_query"] = query
            key = _candidate_key(enriched, "cj_pid", "sku")
            _merge_best(merged, key, enriched)
        if len(merged) >= CJ_POOL_LIMIT:
            break

    rows = sorted(merged.values(), key=lambda row: -float(row.get("match_strength") or 0))
    return rows[:CJ_POOL_LIMIT], failures


def _query_summary(queries: list[str]) -> str:
    return " / ".join(f"« {query} »" for query in queries)


async def compare_shop_listing(
    title: str,
    competitor_price: float,
    *,
    limit: int = MAX_SUPPLIER_RESULTS,
) -> dict[str, Any]:
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

    queries = build_supplier_search_queries(title, max_queries=3)
    if not queries:
        raise ValueError("Impossible de construire une recherche CJ")

    market = {"competition_points": 0.0, "demand_points": 0.0}
    candidates: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []

    cj_client = CJClient()
    if cj_client.status().get("connected"):
        cj_products, cj_failures = await _search_cj_variants(cj_client, queries)
        if cj_products:
            semaphore = asyncio.Semaphore(2)
            jobs = [
                _deep_cj_candidate(
                    cj_client,
                    product,
                    reference_price=reference_price,
                    market=market,
                    semaphore=semaphore,
                )
                for product in cj_products[:6]
            ]
            results = await asyncio.gather(*jobs) if jobs else []
            for product, (candidate, error) in zip(cj_products[:6], results):
                if candidate:
                    candidate["reference_source"] = "EBAY_US_COMPETITOR_PRICE"
                    candidate["matched_query"] = product.get("matched_query")
                    evidence = list(candidate.get("quality_evidence") or [])
                    evidence.insert(0, f"Recherche CJ : {product.get('matched_query')}")
                    candidate["quality_evidence"] = evidence
                    candidates.append(candidate)
                elif error:
                    errors.append({"source": "CJ", "message": error})
        elif cj_failures:
            errors.append({"source": "CJ", "message": cj_failures[0]})
        else:
            errors.append({
                "source": "CJ",
                "message": f"Aucun équivalent CJ pertinent trouvé après {_query_summary(queries)}",
            })
    else:
        errors.append({"source": "CJ", "message": "CJ n'est pas connecté"})

    candidates.sort(
        key=lambda row: (
            0 if row.get("goal_hit") else 1,
            0 if row.get("warehouse") == "US" else 1,
            -float(row.get("score") or 0),
        )
    )
    return {
        "title": title,
        "competitor_price": round(reference_price, 2),
        "currency": "USD",
        "marketplace": "EBAY_US",
        "search_queries": queries,
        "candidates": candidates[:limit],
        "errors": errors,
        "note": (
            "Spy eBay Shop compare uniquement les annonces eBay US à CJ. "
            "Le coût livré vers les États-Unis est vérifié avant toute estimation de marge."
        ),
    }
