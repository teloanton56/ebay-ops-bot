from __future__ import annotations

import asyncio
import json
from typing import Any

from app.config import get_settings
from app.services.cj import CJClient
from app.services.connections import DropXLClient, connection_status
from app.services.db import list_products, list_suppliers, utc_now
from app.services.marketplace_supplier_sources import aliexpress_supplier_offers, amazon_supplier_offers
from app.services.profit import suggest_price
from app.services.opportunity_store import (
    CJ_DEEP_LIMIT, _add_event, _days_from_text, _limited, _match_strength,
    _offer_key, _safe_float, _safe_int, _update_workflow, get_workflow,
)

def _manual_offers(keyword: str) -> list[dict[str, Any]]:
    suppliers = {row["id"]: row for row in list_suppliers()}
    offers = []
    for product in list_products():
        strength = _match_strength(keyword, product.get("title") or "")
        if strength < 0.5:
            continue
        supplier = suppliers.get(product.get("supplier_id")) or {}
        images = product.get("images") or []
        offers.append({
            "provider": supplier.get("name") or "Catalogue local",
            "provider_code": supplier.get("provider_code") or "manual",
            "supplier_sku": product.get("supplier_sku") or str(product.get("id")),
            "variant_id": "",
            "name": product.get("title") or keyword,
            "product_cost": _safe_float(product.get("supplier_cost")),
            "shipping_cost": _safe_float(product.get("shipping_cost")),
            "currency": product.get("currency") or "EUR",
            "stock": _safe_int(product.get("stock")),
            "shipping_days": _safe_int(product.get("shipping_days")),
            "warehouse": supplier.get("country") or "",
            "image_url": images[0] if images else "",
            "reliability_score": _safe_float(supplier.get("reliability_score")),
            "compliance_flags": [],
            "evidence": [
                "Coût et stock issus du catalogue local",
                "Transport et conformité à revalider avant publication",
            ],
            "shipping_known": product.get("shipping_cost") is not None,
            "source_product_id": product.get("id"),
            "match_strength": round(strength, 2),
        })
    return offers[:20]


async def _dropxl_offers(keyword: str) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    if not connection_status("dropxl").get("connected"):
        return [], []
    try:
        payload = await DropXLClient().search(keyword)
    except Exception as exc:
        return [], [{"source": "DropXL", "message": str(exc)}]
    offers = []
    for product in payload.get("products") or []:
        offers.append({
            "provider": "DropXL / vidaXL",
            "provider_code": "dropxl",
            "supplier_sku": str(product.get("supplier_sku") or ""),
            "variant_id": "",
            "name": product.get("name") or keyword,
            "product_cost": _safe_float(product.get("price")),
            "shipping_cost": None,
            "currency": product.get("currency") or "EUR",
            "stock": _safe_int(product.get("stock")),
            "shipping_days": None,
            "warehouse": "EU",
            "image_url": product.get("image_url") or "",
            "reliability_score": None,
            "compliance_flags": [],
            "evidence": list(product.get("quality_evidence") or []) + [
                "Frais et délai vers la France à confirmer auprès de DropXL"
            ],
            "shipping_known": False,
            "match_strength": round(_match_strength(keyword, product.get("name") or ""), 2),
        })
    return offers, []


async def _cj_offers(keyword: str) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    client = CJClient()
    if not client.status().get("connected"):
        return [], []
    errors: list[dict[str, str]] = []
    try:
        result = await client.search_products(keyword=keyword, size=10, min_stock=1)
    except Exception as exc:
        return [], [{"source": "CJ", "message": str(exc)}]
    try:
        exchange = await client.usd_to_eur()
        usd_eur = float(exchange["rate"])
        exchange_note = f"Conversion USD/EUR BCE du {exchange.get('date') or 'jour'}"
    except Exception as exc:
        usd_eur = 0.0
        exchange_note = "Taux USD/EUR indisponible"
        errors.append({"source": "CJ taux de change", "message": str(exc)})

    products = (result.get("products") or [])[:CJ_DEEP_LIMIT]

    async def enrich(product: dict[str, Any]) -> dict[str, Any]:
        detail = await client.product_detail(str(product.get("cj_pid") or ""))
        variants = [row for row in detail.get("variants") or [] if int(row.get("stock") or 0) > 0]
        variant = variants[0] if variants else (detail.get("variants") or [{}])[0]
        variant_id = str(variant.get("vid") or "")
        freight: list[dict[str, Any]] = []
        start_country = next(
            (
                str(row.get("country_code") or "CN")
                for row in variant.get("inventories") or []
                if int(row.get("stock") or 0) > 0
            ),
            "CN",
        )
        if variant_id:
            try:
                freight = await client.freight_options(
                    variant_id,
                    start_country=start_country,
                    destination_country="FR",
                    postcode=get_settings().ebay_location_postal_code or "",
                )
            except Exception as exc:
                errors.append({"source": "CJ transport", "message": str(exc)})
        best_freight = freight[0] if freight else {}
        product_usd = _safe_float(variant.get("price_usd")) or _safe_float(product.get("price_usd"))
        shipping_usd = _safe_float(best_freight.get("price_usd"))
        product_eur = round(product_usd * usd_eur, 2) if product_usd is not None and usd_eur else None
        shipping_eur = round(shipping_usd * usd_eur, 2) if shipping_usd is not None and usd_eur else None
        return {
            "provider": "CJ Dropshipping",
            "provider_code": "cj",
            "supplier_sku": str(product.get("sku") or detail.get("sku") or product.get("cj_pid") or ""),
            "cj_pid": str(product.get("cj_pid") or detail.get("pid") or ""),
            "variant_id": variant_id,
            "name": variant.get("name") or detail.get("name") or product.get("name") or keyword,
            "product_cost": product_eur,
            "shipping_cost": shipping_eur,
            "currency": "EUR" if usd_eur else "USD",
            "raw_product_cost_usd": product_usd,
            "raw_shipping_cost_usd": shipping_usd,
            "stock": _safe_int(variant.get("stock")) or _safe_int(product.get("stock")),
            "shipping_days": _days_from_text(best_freight.get("delivery_days")),
            "shipping_method": best_freight.get("name") or "",
            "warehouse": start_country,
            "image_url": variant.get("image_url") or detail.get("image_url") or product.get("image_url") or "",
            "reliability_score": None,
            "compliance_flags": list(detail.get("risk_flags") or []),
            "evidence": [
                "Prix, variante et stock observés chez CJ",
                exchange_note,
                "Transport calculé vers la France" if best_freight else "Transport CJ non disponible",
                "Échantillon et documents de conformité à valider",
            ],
            "shipping_known": shipping_eur is not None,
            "match_strength": round(_match_strength(keyword, detail.get("name") or product.get("name") or ""), 2),
        }

    raw = await _limited([enrich(product) for product in products], concurrency=2)
    offers = []
    for product, item in zip(products, raw):
        if isinstance(item, Exception):
            errors.append({"source": "CJ", "message": str(item), "product": product.get("name")})
        else:
            offers.append(item)
    return offers, errors


def _score_offer(offer: dict[str, Any], market_price: float | None) -> dict[str, Any]:
    product_cost = _safe_float(offer.get("product_cost"))
    shipping_cost = _safe_float(offer.get("shipping_cost"))
    shipping_known = bool(offer.get("shipping_known") and shipping_cost is not None)
    landed_cost = round(product_cost + shipping_cost, 2) if product_cost is not None and shipping_known else None
    target = None
    profit = None
    if landed_cost is not None:
        product = {
            "supplier_cost": product_cost,
            "shipping_cost": shipping_cost,
            "target_price": market_price or 0,
        }
        suggestion = suggest_price(product, market_price)
        target = suggestion["suggested_price"]
        profit = suggestion["profit"]

    blocks: list[str] = []
    warnings: list[str] = []
    points = 0.0
    if profit:
        margin = float(profit.get("margin_percent") or -100)
        estimated_profit = float(profit.get("estimated_profit") or -100)
        roi = float(profit.get("roi_percent") or 0)
        points += min(max(margin, 0) / 25 * 22, 22)
        points += min(max(estimated_profit, 0) / 10 * 10, 10)
        points += min(max(roi, 0) / 100 * 8, 8)
        settings = get_settings()
        if margin < settings.min_margin_percent:
            blocks.append(f"Marge {margin:.1f}% sous le minimum")
        if estimated_profit < settings.min_profit_eur:
            blocks.append(f"Profit {estimated_profit:.2f} € sous le minimum")
    else:
        blocks.append("Coût livré inconnu")

    shipping_days = _safe_int(offer.get("shipping_days"))
    if shipping_days is None:
        warnings.append("Délai non fourni")
    elif shipping_days <= 3:
        points += 15
    elif shipping_days <= 7:
        points += 12
    elif shipping_days <= 12:
        points += 7
    else:
        points += 1
        blocks.append(f"Délai {shipping_days} jours trop long")

    stock = _safe_int(offer.get("stock"))
    if stock is None:
        warnings.append("Stock non fourni")
    elif stock <= 0:
        blocks.append("Rupture de stock")
    elif stock < 3:
        points += 3
        warnings.append("Stock très faible")
    elif stock < 20:
        points += 9
    else:
        points += 15

    reliability = _safe_float(offer.get("reliability_score"))
    if reliability is not None:
        points += min(max(reliability, 0) / 100 * 10, 10)
    else:
        points += 4 if offer.get("provider_code") in {"cj", "dropxl"} else 2

    high_flags = [
        flag for flag in offer.get("compliance_flags") or []
        if str(flag.get("level") or "").casefold() == "high"
    ]
    medium_flags = [
        flag for flag in offer.get("compliance_flags") or []
        if str(flag.get("level") or "").casefold() == "medium"
    ]
    if high_flags:
        blocks.extend(str(flag.get("label") or flag.get("code")) for flag in high_flags)
    elif medium_flags:
        points += 4
        warnings.extend(str(flag.get("label") or flag.get("code")) for flag in medium_flags)
    else:
        points += 10

    evidence_count = len(offer.get("evidence") or [])
    points += min(evidence_count * 2, 10)
    if not offer.get("image_url"):
        warnings.append("Image fournisseur absente")

    score = round(max(0, min(points - len(blocks) * 12, 100)))
    return {
        **offer,
        "offer_key": _offer_key(
            str(offer.get("provider_code") or offer.get("provider") or "supplier"),
            str(offer.get("supplier_sku") or ""),
            str(offer.get("variant_id") or ""),
        ),
        "landed_cost": landed_cost,
        "suggested_price": target,
        "profit": profit,
        "decision_score": score,
        "blocks": list(dict.fromkeys(blocks)),
        "warnings": list(dict.fromkeys(warnings)),
        "eligible": not blocks,
    }


async def compare_suppliers(workflow_id: int) -> dict[str, Any]:
    workflow = get_workflow(workflow_id)
    keyword = workflow["keyword"]
    market_price = _safe_float(workflow.get("opportunity", {}).get("median_price"))
    manual = _manual_offers(keyword)
    (dropxl, dropxl_errors), (cj, cj_errors), (amazon, amazon_errors), (aliexpress, aliexpress_errors) = await asyncio.gather(
        _dropxl_offers(keyword),
        _cj_offers(keyword),
        amazon_supplier_offers(keyword),
        aliexpress_supplier_offers(keyword),
    )
    scored = [
        _score_offer(offer, market_price)
        for offer in [*manual, *dropxl, *cj, *amazon, *aliexpress]
    ]
    scored.sort(key=lambda row: (bool(row.get("eligible")), float(row.get("decision_score") or 0)), reverse=True)
    recommendation = next((row for row in scored if row.get("eligible")), scored[0] if scored else None)
    snapshot = {
        "keyword": keyword,
        "observed_at": utc_now(),
        "market_price": market_price,
        "offers": scored,
        "recommendation_key": recommendation.get("offer_key") if recommendation else None,
        "errors": [*dropxl_errors, *cj_errors, *amazon_errors, *aliexpress_errors],
        "sources": {
            "manual": len(manual),
            "dropxl": len(dropxl),
            "cj": len(cj),
            "amazon": len(amazon),
            "aliexpress": len(aliexpress),
        },
        "meaning": (
            "Le classement compare uniquement les coûts et preuves observés. Une offre dont le transport est inconnu "
            "reste bloquée jusqu'à validation."
        ),
    }
    _update_workflow(
        workflow_id,
        supplier_snapshot_json=json.dumps(snapshot, ensure_ascii=False),
    )
    _add_event(
        workflow_id,
        "SUPPLIER_COMPARISON",
        f"{len(scored)} offre(s) fournisseur comparée(s)",
        payload={"sources": snapshot["sources"], "errors": snapshot["errors"]},
    )
    return get_workflow(workflow_id)["supplier_snapshot"]


def select_supplier_offer(workflow_id: int, offer_key: str) -> dict[str, Any]:
    workflow = get_workflow(workflow_id)
    offers = workflow.get("supplier_snapshot", {}).get("offers") or []
    offer = next((row for row in offers if row.get("offer_key") == offer_key), None)
    if not offer:
        raise ValueError("Offre fournisseur introuvable dans la dernière comparaison")
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
        f"Offre {offer.get('provider')} sélectionnée",
        payload={"offer_key": offer_key, "score": offer.get("decision_score")},
    )
    return updated
