from __future__ import annotations

import json
from typing import Any

from app.services.db import ensure_provider_supplier, save_listing, upsert_product, utc_now
from app.services.cj_landed import route_requirements, save_cj_product_link
from app.services.ebay import EbayClient
from app.services.listing_generator import generate_description, optimize_title
from app.services.profit import suggest_price
from app.services.opportunity_store import (
    RESTRICTED_TERMS, _add_event, _safe_float, _safe_int, _update_workflow, get_workflow,
)


def _validate_cj_offer(offer: dict[str, Any]) -> None:
    if (
        str(offer.get("provider_code") or "").casefold() != "cj"
        or str(offer.get("currency") or "").upper() != "USD"
        or str(offer.get("destination_country") or "").upper() != "US"
        or str(offer.get("warehouse") or "").upper() not in {"US", "CN"}
        or not str(offer.get("cj_pid") or "").strip()
        or not str(offer.get("variant_id") or "").strip()
    ):
        raise ValueError("Seules les variantes CJ vérifiées en USD et livrées aux États-Unis sont autorisées")


def build_risk_report(workflow_id: int) -> dict[str, Any]:
    workflow = get_workflow(workflow_id)
    offer = workflow.get("selected_offer") or {}
    if not offer:
        raise ValueError("Sélectionnez d'abord une offre fournisseur")
    _validate_cj_offer(offer)
    requirements = offer.get("requirements") or route_requirements(str(offer.get("warehouse") or "US"))
    blocks = list(offer.get("blocks") or [])
    warnings = list(offer.get("warnings") or [])
    checks: list[dict[str, Any]] = []

    def check(label: str, passed: bool, detail: str, critical: bool = False) -> None:
        checks.append({"label": label, "passed": passed, "detail": detail, "critical": critical})
        if not passed:
            (blocks if critical else warnings).append(detail)

    stock = _safe_int(offer.get("stock"))
    min_stock = int(requirements["min_stock"])
    check("Stock", stock is not None and stock >= min_stock,
          f"Stock requis : {min_stock}; observé : {stock if stock is not None else 'inconnu'}",
          critical=stock is not None and stock <= 0)
    days = _safe_int(offer.get("shipping_days"))
    max_days = int(requirements["max_shipping_days"])
    check("Délai", days is not None and 0 < days <= max_days,
          f"Maximum : {max_days} jours; observé : {days if days is not None else 'inconnu'}",
          critical=days is not None and days > max_days)
    profit = offer.get("profit") if isinstance(offer.get("profit"), dict) else {}
    margin = _safe_float(profit.get("margin_percent"))
    estimated_profit = _safe_float(profit.get("estimated_profit"))
    min_margin = float(requirements["min_margin_percent"])
    check("Marge", margin is not None and margin >= min_margin,
          f"Minimum : {min_margin:.1f}%; estimée : {margin if margin is not None else 'inconnue'}",
          critical=True)
    min_profit = float(requirements["min_profit"])
    check("Profit", estimated_profit is not None and estimated_profit >= min_profit,
          f"Minimum : {min_profit:.2f} USD; estimé : {estimated_profit if estimated_profit is not None else 'inconnu'} USD",
          critical=True)
    check("Coût livré", offer.get("landed_cost") is not None,
          "Prix produit et transport doivent être tous les deux confirmés", critical=True)
    check("Image", bool(offer.get("image_url")), "Une image exploitable doit être disponible")

    normalized = str(workflow.get("keyword") or "").casefold()
    detected_categories = [
        category for category, terms in RESTRICTED_TERMS.items()
        if any(term in normalized for term in terms)
    ]
    if "weapon" in detected_categories:
        blocks.append("Catégorie arme ou autodéfense détectée : produit exclu")
    for category in detected_categories:
        if category != "weapon":
            warnings.append(f"Catégorie sensible détectée ({category}) : conformité renforcée requise")

    for flag in offer.get("compliance_flags") or []:
        label = str(flag.get("label") or flag.get("code") or "Risque conformité")
        if str(flag.get("level") or "").casefold() == "high":
            blocks.append(label)
        else:
            warnings.append(label)

    blocks = list(dict.fromkeys(str(item) for item in blocks if item))
    warnings = list(dict.fromkeys(str(item) for item in warnings if item and item not in blocks))
    passed = not blocks
    report = {
        "pass": passed,
        "blocks": blocks,
        "warnings": warnings,
        "checks": checks,
        "assessed_at": utc_now(),
        "dry_run": True,
        "meaning": "Le contrôle bloque les coûts inconnus, marges insuffisantes, ruptures et risques élevés.",
    }
    stage = "RISK_VALIDATED" if passed else "SOURCED"
    _update_workflow(
        workflow_id,
        risk_json=json.dumps(report, ensure_ascii=False),
        stage=stage,
    )
    _add_event(
        workflow_id,
        "RISK_ASSESSMENT",
        "Risk Engine validé" if passed else f"Risk Engine bloqué ({len(blocks)} point(s))",
        level="INFO" if passed else "WARNING",
        payload={"blocks": blocks, "warnings": warnings},
    )
    return report


def _category_suggestion(payload: dict[str, Any]) -> tuple[str | None, str | None]:
    suggestions = payload.get("categorySuggestions") or []
    if not suggestions:
        return None, None
    category = suggestions[0].get("category") or {}
    return str(category.get("categoryId") or "") or None, str(category.get("categoryName") or "") or None


def _required_aspects(payload: dict[str, Any]) -> list[str]:
    missing = []
    for aspect in payload.get("aspects") or []:
        constraint = aspect.get("aspectConstraint") or {}
        if constraint.get("aspectRequired"):
            localized = aspect.get("localizedAspectName") or aspect.get("aspectName")
            if localized:
                missing.append(str(localized))
    return list(dict.fromkeys(missing))


async def prepare_listing_draft(workflow_id: int) -> dict[str, Any]:
    workflow = get_workflow(workflow_id)
    offer = workflow.get("selected_offer") or {}
    risk = workflow.get("risk") or {}
    if not offer:
        raise ValueError("Sélectionnez une offre fournisseur")
    _validate_cj_offer(offer)
    if not risk.get("pass"):
        risk = build_risk_report(workflow_id)
    if not risk.get("pass"):
        raise ValueError("Le Risk Engine bloque la préparation du brouillon")

    opportunity = workflow.get("opportunity") or {}
    keyword = workflow.get("keyword") or opportunity.get("title") or "Produit"
    market_price = _safe_float(opportunity.get("median_price"))
    product_cost = _safe_float(offer.get("product_cost")) or 0.0
    shipping_cost = _safe_float(offer.get("shipping_cost")) or 0.0
    requirements = offer.get("requirements") or route_requirements(str(offer.get("warehouse") or "US"))
    price_result = suggest_price(
        {"supplier_cost": product_cost, "shipping_cost": shipping_cost, "target_price": market_price or 0},
        market_price,
        min_margin_percent=float(requirements["min_margin_percent"]),
        min_profit=float(requirements["min_profit"]),
    )

    client = EbayClient()
    category_id = None
    category_name = None
    required_missing: list[str] = []
    taxonomy_errors: list[str] = []
    try:
        suggestion = await client.get_category_suggestions(keyword, "EBAY_US")
        category_id, category_name = _category_suggestion(suggestion)
        if category_id:
            aspects = await client.get_item_aspects(category_id, "EBAY_US")
            required_missing = _required_aspects(aspects)
    except Exception as exc:
        taxonomy_errors.append(str(exc))

    sku_seed = str(offer.get("supplier_sku") or offer.get("offer_key") or workflow_id)
    supplier_sku = f"CJ-{workflow_id}-{sku_seed}"[:50]
    raw_title = opportunity.get("title") or offer.get("name") or keyword
    title = optimize_title(str(raw_title))
    images = [offer.get("image_url")] if offer.get("image_url") else []
    supplier_id = ensure_provider_supplier("cj", "CJ Dropshipping", "US")
    product_data = {
        "supplier_sku": supplier_sku,
        "title": title,
        "description": "",
        "supplier_cost": product_cost,
        "shipping_cost": shipping_cost,
        "stock": max(_safe_int(offer.get("stock")) or 0, 0),
        "shipping_days": max(_safe_int(offer.get("shipping_days")) or 0, 0),
        "target_price": price_result["suggested_price"],
        "category_id": category_id,
        "condition": "NEW",
        "marketplace_id": "EBAY_US",
        "currency": "USD",
        "images": images,
        "aspects": {},
        "supplier_id": supplier_id,
        "product_status": "À tester",
        "opportunity_score": opportunity.get("score"),
        "suggested_price": price_result["suggested_price"],
    }
    product_data["description"] = generate_description(product_data)
    product_id = upsert_product(product_data)
    save_cj_product_link(supplier_sku, {
        "pid": str(offer.get("cj_pid") or ""),
        "variant_id": str(offer.get("variant_id") or ""),
        "warehouse": str(offer.get("warehouse") or "").upper(),
        "destination_country": "US",
        "currency": "USD",
        "risk_flags": offer.get("compliance_flags") or [],
    })
    listing_id = save_listing(
        product_id,
        None,
        None,
        "PREPARED_DRY_RUN",
        price_result["suggested_price"],
        product_data["stock"],
    )
    listing = {
        "product_id": product_id,
        "listing_record_id": listing_id,
        "title": title,
        "description": product_data["description"],
        "target_price": price_result["suggested_price"],
        "profit": price_result["profit"],
        "category_id": category_id,
        "category_name": category_name,
        "required_aspects_missing": required_missing,
        "taxonomy_errors": taxonomy_errors,
        "images": images,
        "dry_run": True,
        "prepared_at": utc_now(),
        "notice": "Brouillon local uniquement. Rien n'a été envoyé à eBay.",
    }
    stage = "DRAFT_READY"
    if not required_missing and category_id:
        stage = "READY_TO_LAUNCH"
    _update_workflow(
        workflow_id,
        listing_json=json.dumps(listing, ensure_ascii=False),
        stage=stage,
    )
    _add_event(
        workflow_id,
        "LISTING_DRAFT",
        "Brouillon eBay local préparé",
        payload={"product_id": product_id, "category_id": category_id, "missing_aspects": required_missing},
    )
    return listing
