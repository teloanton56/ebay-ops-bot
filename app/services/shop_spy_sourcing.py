from __future__ import annotations

import asyncio
from typing import Any

from app.services.aliexpress_dropship_search import aliexpress_dropship_supplier_offers
from app.services.cj import CJClient
from app.services.margin_hunter import _ali_candidates, _deep_cj_candidate
from app.services.sourcing_queries import build_supplier_search_queries
from app.services.supplier_relevance import rank_supplier_results


MAX_SUPPLIER_RESULTS = 8
CJ_POOL_LIMIT = 6
ALI_POOL_LIMIT = 12


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
            payload = await client.search_products(keyword=query, size=40, min_stock=3, order_by=0)
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


async def _search_ali_variants(queries: list[str]) -> tuple[list[dict[str, Any]], list[str]]:
    merged: dict[str, dict[str, Any]] = {}
    failures: list[str] = []
    for query in queries:
        offers, errors = await aliexpress_dropship_supplier_offers(query)
        for error in errors:
            message = str(error.get("message") or error)
            if "Aucun produit pertinent" not in message:
                failures.append(f"{query}: {message}")
        for offer in offers:
            enriched = dict(offer)
            enriched["matched_query"] = query
            key = _candidate_key(enriched, "supplier_sku", "source_url")
            _merge_best(merged, key, enriched)
        if len(merged) >= ALI_POOL_LIMIT:
            break

    rows = sorted(merged.values(), key=lambda row: -float(row.get("match_strength") or 0))
    return rows[:ALI_POOL_LIMIT], failures


def _query_summary(queries: list[str]) -> str:
    return " / ".join(f"« {query} »" for query in queries)


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

    queries = build_supplier_search_queries(title, max_queries=3)
    if not queries:
        raise ValueError("Impossible de construire une recherche fournisseur")

    market = {"competition_points": 0.0, "demand_points": 0.0}
    candidates: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []

    cj_client = CJClient()
    if cj_client.status().get("connected"):
        cj_products, cj_failures = await _search_cj_variants(cj_client, queries)
        if cj_products:
            try:
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
                    for product in cj_products[:4]
                ]
                results = await asyncio.gather(*jobs) if jobs else []
                for product, (candidate, error) in zip(cj_products[:4], results):
                    if candidate:
                        candidate["reference_source"] = "PRIX_BOUTIQUE_EBAY"
                        candidate["matched_query"] = product.get("matched_query")
                        evidence = list(candidate.get("quality_evidence") or [])
                        evidence.insert(0, f"Recherche fournisseur : {product.get('matched_query')}")
                        candidate["quality_evidence"] = evidence
                        candidates.append(candidate)
                    elif error:
                        errors.append({"source": "CJ", "message": error})
            except Exception as exc:
                errors.append({"source": "CJ", "message": str(exc)})
        elif cj_failures:
            errors.append({"source": "CJ", "message": cj_failures[0]})
        else:
            errors.append({
                "source": "CJ",
                "message": f"Aucun équivalent pertinent trouvé après recherches ciblées {_query_summary(queries)}",
            })
    else:
        errors.append({"source": "CJ", "message": "CJ n'est pas connecté"})

    ali_offers, ali_failures = await _search_ali_variants(queries)
    if ali_offers:
        for offer in ali_offers:
            built = _ali_candidates([offer], reference_price=reference_price, market=market)
            for candidate in built:
                candidate["reference_source"] = "PRIX_BOUTIQUE_EBAY"
                candidate["matched_query"] = offer.get("matched_query")
                evidence = list(candidate.get("quality_evidence") or [])
                evidence.insert(0, f"Recherche fournisseur : {offer.get('matched_query')}")
                candidate["quality_evidence"] = evidence
                candidates.append(candidate)
    elif ali_failures:
        errors.append({"source": "AliExpress", "message": ali_failures[0]})
    else:
        errors.append({
            "source": "AliExpress",
            "message": f"Aucun équivalent pertinent trouvé après recherches ciblées {_query_summary(queries)}",
        })

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
        "search_queries": queries,
        "candidates": candidates[:limit],
        "errors": errors,
        "note": (
            "Le titre eBay est réduit en recherches fournisseur ciblées avant comparaison. "
            "CJ utilise un coût livré France calculé avant estimation de marge. "
            "AliExpress reste préliminaire tant que son coût de livraison n'est pas confirmé."
        ),
    }
