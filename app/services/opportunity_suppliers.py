from __future__ import annotations

import json
from typing import Any

from app.services.cj import CJClient
from app.services.cj_landed import resolve_cj_landed_offer, route_requirements
from app.services.db import utc_now
from app.services.profit import suggest_price
from app.services.opportunity_store import (
    CJ_DEEP_LIMIT,
    _add_event,
    _limited,
    _match_strength,
    _offer_key,
    _safe_float,
    _safe_int,
    _update_workflow,
    get_workflow,
)


async def _cj_offers(
    keyword: str,
    market_price: float | None,
) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    client = CJClient()
    if not client.status().get("connected"):
        return [], [{"source": "CJ", "message": "CJ n'est pas connecté"}]
    try:
        result = await client.search_products(keyword=keyword, size=12, min_stock=0)
    except Exception as exc:
        return [], [{"source": "CJ", "message": str(exc)}]

    products = (result.get("products") or [])[:CJ_DEEP_LIMIT]

    async def enrich(product: dict[str, Any]) -> dict[str, Any]:
        landed = await resolve_cj_landed_offer(
            client,
            str(product.get("cj_pid") or ""),
            fallback_price_usd=float(product.get("price_usd") or 0),
            destination_country="US",
            reference_price=market_price,
        )
        warehouse = str(landed.get("warehouse") or "").upper()
        return {
            "provider": "CJ Dropshipping",
            "provider_code": "cj",
            "supplier_sku": str(product.get("sku") or landed.get("variant_sku") or landed.get("pid") or ""),
            "cj_pid": str(product.get("cj_pid") or landed.get("pid") or ""),
            "variant_id": str(landed.get("variant_id") or ""),
            "name": landed.get("variant_name") or landed.get("product_name") or product.get("name") or keyword,
            "product_cost": _safe_float(landed.get("supplier_cost")),
            "shipping_cost": _safe_float(landed.get("shipping_cost")),
            "currency": "USD",
            "stock": _safe_int(landed.get("stock")),
            "shipping_days": _safe_int(landed.get("shipping_days")),
            "shipping_method": landed.get("freight_name") or "",
            "warehouse": warehouse,
            "destination_country": "US",
            "image_url": landed.get("image_url") or product.get("image_url") or "",
            "compliance_flags": list(landed.get("risk_flags") or []),
            "evidence": [
                "Variante et stock vérifiés avec CJ",
                f"Transport {warehouse or 'CJ'} vers les États-Unis calculé en USD",
                "Entrepôt US prioritaire ; Chine retenue uniquement avec les seuils renforcés",
            ],
            "shipping_known": landed.get("shipping_cost") is not None,
            "match_strength": round(
                _match_strength(keyword, landed.get("product_name") or product.get("name") or ""),
                2,
            ),
        }

    raw = await _limited([enrich(product) for product in products], concurrency=2)
    offers: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    for product, item in zip(products, raw):
        if isinstance(item, Exception):
            errors.append(
                {
                    "source": "CJ",
                    "message": str(item),
                    "product": str(product.get("name") or ""),
                }
            )
        else:
            offers.append(item)
    return offers, errors


def _score_offer(offer: dict[str, Any], market_price: float | None) -> dict[str, Any]:
    blocks: list[str] = []
    warnings: list[str] = []
    points = 0.0

    provider_code = str(offer.get("provider_code") or "").casefold()
    if provider_code != "cj":
        blocks.append("Seules les offres CJ Dropshipping sont autorisées")
    if not str(offer.get("cj_pid") or "").strip():
        blocks.append("Identifiant produit CJ manquant")
    if not str(offer.get("variant_id") or "").strip():
        blocks.append("Variante CJ non vérifiée")

    currency = str(offer.get("currency") or "").upper()
    if currency != "USD":
        blocks.append("La devise fournisseur doit être USD")

    destination_country = str(offer.get("destination_country") or "").upper()
    if destination_country != "US":
        blocks.append("La destination de livraison doit être US")

    warehouse = str(offer.get("warehouse") or "").upper()
    if warehouse not in {"US", "CN"}:
        blocks.append("Entrepôt CJ non autorisé")
        requirements = route_requirements("US")
    else:
        requirements = route_requirements(warehouse)
        points += 12 if warehouse == "US" else 6
        if warehouse == "CN":
            warnings.append("Route Chine : seuils renforcés appliqués")

    product_cost = _safe_float(offer.get("product_cost"))
    shipping_cost = _safe_float(offer.get("shipping_cost"))
    shipping_known = bool(offer.get("shipping_known") and shipping_cost is not None)
    landed_cost = (
        round(product_cost + shipping_cost, 2)
        if product_cost is not None and shipping_known
        else None
    )
    target = None
    profit = None
    if landed_cost is None:
        blocks.append("Coût livré US inconnu")
    else:
        suggestion = suggest_price(
            {
                "supplier_cost": product_cost,
                "shipping_cost": shipping_cost,
                "target_price": market_price or 0,
            },
            market_price,
            min_margin_percent=float(requirements["min_margin_percent"]),
            min_profit=float(requirements["min_profit"]),
        )
        target = suggestion["suggested_price"]
        profit = suggestion["profit"]
        margin = float(profit.get("margin_percent") or -100)
        estimated_profit = float(profit.get("estimated_profit") or -100)
        roi = float(profit.get("roi_percent") or 0)
        points += min(max(margin, 0) / 35 * 25, 25)
        points += min(max(estimated_profit, 0) / 12 * 15, 15)
        points += min(max(roi, 0) / 100 * 10, 10)
        if margin < float(requirements["min_margin_percent"]):
            blocks.append(
                f"Marge {margin:.1f}% sous le minimum {float(requirements['min_margin_percent']):.1f}%"
            )
        if estimated_profit < float(requirements["min_profit"]):
            blocks.append(
                f"Profit {estimated_profit:.2f} USD sous le minimum {float(requirements['min_profit']):.2f} USD"
            )

    shipping_days = _safe_int(offer.get("shipping_days"))
    max_days = int(requirements["max_shipping_days"])
    if shipping_days is None or shipping_days <= 0:
        blocks.append("Délai CJ non confirmé")
    elif shipping_days > max_days:
        blocks.append(f"Délai {shipping_days} jours au-dessus du maximum {max_days}")
    else:
        points += max(2, 12 - max(shipping_days - 2, 0))

    stock = _safe_int(offer.get("stock"))
    min_stock = int(requirements["min_stock"])
    if stock is None or stock < min_stock:
        blocks.append(
            f"Stock {stock if stock is not None else 'inconnu'} sous le minimum {min_stock}"
        )
    else:
        points += min(10, 5 + (stock - min_stock) / max(min_stock, 1) * 5)

    high_flags = [
        flag
        for flag in offer.get("compliance_flags") or []
        if str(flag.get("level") or "").casefold() == "high"
    ]
    medium_flags = [
        flag
        for flag in offer.get("compliance_flags") or []
        if str(flag.get("level") or "").casefold() == "medium"
    ]
    if high_flags:
        blocks.extend(str(flag.get("label") or flag.get("code")) for flag in high_flags)
    else:
        points += 7
    warnings.extend(str(flag.get("label") or flag.get("code")) for flag in medium_flags)

    points += min(len(offer.get("evidence") or []) * 2, 6)
    points += min(max(float(offer.get("match_strength") or 0), 0) * 5, 5)
    if offer.get("image_url"):
        points += 5
    else:
        warnings.append("Image CJ absente")

    score = round(max(0, min(points - len(blocks) * 12, 100)))
    return {
        **offer,
        "offer_key": _offer_key("cj", str(offer.get("supplier_sku") or ""), str(offer.get("variant_id") or "")),
        "landed_cost": landed_cost,
        "suggested_price": target,
        "profit": profit,
        "requirements": requirements,
        "decision_score": score,
        "blocks": list(dict.fromkeys(blocks)),
        "warnings": list(dict.fromkeys(warnings)),
        "eligible": not blocks,
    }


async def compare_suppliers(workflow_id: int) -> dict[str, Any]:
    workflow = get_workflow(workflow_id)
    if workflow.get("marketplace") != "EBAY_US" or workflow.get("currency") != "USD":
        raise ValueError("Le dossier doit appartenir à eBay US et utiliser USD")
    keyword = workflow["keyword"]
    market_price = _safe_float(workflow.get("opportunity", {}).get("median_price"))
    cj_offers, cj_errors = await _cj_offers(keyword, market_price)
    scored = [_score_offer(offer, market_price) for offer in cj_offers]
    scored.sort(
        key=lambda row: (bool(row.get("eligible")), float(row.get("decision_score") or 0)),
        reverse=True,
    )
    recommendation = next(
        (row for row in scored if row.get("eligible")),
        scored[0] if scored else None,
    )
    snapshot = {
        "keyword": keyword,
        "observed_at": utc_now(),
        "marketplace": "EBAY_US",
        "market_price": market_price,
        "currency": "USD",
        "destination_country": "US",
        "offers": scored,
        "recommendation_key": recommendation.get("offer_key") if recommendation else None,
        "errors": cj_errors,
        "sources": {"cj": len(cj_offers)},
        "operating_mode": "EBAY_US_CJ_ONLY",
        "meaning": (
            "Le classement utilise uniquement les variantes CJ, leur stock par entrepôt et le "
            "transport mesuré vers les États-Unis. La route US est prioritaire ; la Chine doit "
            "respecter des seuils de marge, profit, stock et délai renforcés."
        ),
    }
    _update_workflow(
        workflow_id,
        supplier_snapshot_json=json.dumps(snapshot, ensure_ascii=False),
    )
    _add_event(
        workflow_id,
        "SUPPLIER_COMPARISON",
        f"{len(scored)} offre(s) CJ comparée(s)",
        payload={"sources": snapshot["sources"], "errors": snapshot["errors"]},
    )
    return get_workflow(workflow_id)["supplier_snapshot"]


def select_supplier_offer(workflow_id: int, offer_key: str) -> dict[str, Any]:
    workflow = get_workflow(workflow_id)
    offers = workflow.get("supplier_snapshot", {}).get("offers") or []
    offer = next((row for row in offers if row.get("offer_key") == offer_key), None)
    if not offer:
        raise ValueError("Offre CJ introuvable dans la dernière comparaison")
    if (
        str(offer.get("provider_code") or "").casefold() != "cj"
        or str(offer.get("currency") or "").upper() != "USD"
        or str(offer.get("destination_country") or "").upper() != "US"
        or not str(offer.get("cj_pid") or "").strip()
        or not str(offer.get("variant_id") or "").strip()
    ):
        raise ValueError("Seules les offres CJ en USD livrées aux États-Unis sont autorisées")
    stage = "MARGIN_VALIDATED" if offer.get("eligible") and offer.get("profit") else "SOURCED"
    updated = _update_workflow(
        workflow_id,
        selected_offer_key=offer_key,
        selected_offer_json=json.dumps(offer, ensure_ascii=False),
        stage=stage,
    )
    _add_event(
        workflow_id,
        "SUPPLIER_SELECTED",
        "Offre CJ sélectionnée",
        payload={"offer_key": offer_key, "score": offer.get("decision_score")},
    )
    return updated
