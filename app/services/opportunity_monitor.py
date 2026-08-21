from __future__ import annotations

import json
from collections import Counter
from statistics import median
from typing import Any

from app.config import get_settings
from app.services.backups import create_backup, list_backups, resolve_backup
from app.services.cj import CJClient
from app.services.connections import DropXLClient, connection_status
from app.services.db import add_alert, conn, get_product, utc_now
from app.services.ebay import EbayClient
from app.services.opportunity_store import (
    MONITOR_LIMIT, STAGES, STAGE_LABELS, _CENTER_LOCK, _add_event, _ensure_tables,
    _limited, _safe_float, _safe_int, _update_workflow, ensure_radar_tables,
    get_workflow, list_workflows,
)
from app.services.opportunity_suppliers import _score_offer

def _workflow_stage(workflow: dict[str, Any]) -> str:
    if workflow.get("stage") == "REJECTED":
        return "REJECTED"
    listing = workflow.get("listing") or {}
    risk = workflow.get("risk") or {}
    offer = workflow.get("selected_offer") or {}
    if listing:
        if listing.get("category_id") and not listing.get("required_aspects_missing"):
            return "MONITORING" if workflow.get("monitoring_enabled") else "READY_TO_LAUNCH"
        return "DRAFT_READY"
    if risk.get("pass"):
        return "RISK_VALIDATED"
    if offer.get("eligible") and offer.get("profit"):
        return "MARGIN_VALIDATED"
    if offer:
        return "SOURCED"
    return "DETECTED"


def set_monitoring(workflow_id: int, enabled: bool) -> dict[str, Any]:
    workflow = get_workflow(workflow_id)
    stage = "MONITORING" if enabled and workflow.get("listing") else _workflow_stage({**workflow, "monitoring_enabled": False})
    updated = _update_workflow(
        workflow_id,
        monitoring_enabled=1 if enabled else 0,
        stage=stage,
    )
    _add_event(
        workflow_id,
        "MONITORING_TOGGLE",
        "Surveillance activée" if enabled else "Surveillance désactivée",
    )
    return updated


def set_workflow_stage(workflow_id: int, stage: str) -> dict[str, Any]:
    if stage not in STAGES:
        raise ValueError("Statut de pipeline invalide")
    updated = _update_workflow(workflow_id, stage=stage)
    _add_event(workflow_id, "STAGE_CHANGED", f"Statut changé vers {STAGE_LABELS.get(stage, stage)}")
    return updated


def _euro_offer_from_selected(selected: dict[str, Any], *, product_cost: float | None = None,
                              stock: int | None = None, shipping_days: int | None = None) -> dict[str, Any]:
    updated = dict(selected)
    if product_cost is not None:
        updated["product_cost"] = product_cost
    if stock is not None:
        updated["stock"] = stock
    if shipping_days is not None:
        updated["shipping_days"] = shipping_days
    market_price = _safe_float(selected.get("suggested_price"))
    return _score_offer(updated, market_price)


async def _refresh_selected_offer(workflow: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    selected = dict(workflow.get("selected_offer") or {})
    if not selected:
        return selected, []
    provider = str(selected.get("provider_code") or "").casefold()
    warnings: list[str] = []
    if provider == "cj" and CJClient().status().get("connected"):
        try:
            detail = await CJClient().product_detail(str(selected.get("cj_pid") or ""))
            variant = next(
                (row for row in detail.get("variants") or [] if str(row.get("vid") or "") == str(selected.get("variant_id") or "")),
                None,
            )
            if variant:
                rate = await CJClient().usd_to_eur()
                price = round(float(variant.get("price_usd") or 0) * float(rate["rate"]), 2)
                selected = _euro_offer_from_selected(
                    selected,
                    product_cost=price,
                    stock=_safe_int(variant.get("stock")),
                )
        except Exception as exc:
            warnings.append(f"CJ : {exc}")
    elif provider == "dropxl" and connection_status("dropxl").get("connected"):
        try:
            result = await DropXLClient().search(workflow.get("keyword") or "")
            match = next(
                (row for row in result.get("products") or [] if str(row.get("supplier_sku")) == str(selected.get("supplier_sku"))),
                None,
            )
            if match:
                selected = _euro_offer_from_selected(
                    selected,
                    product_cost=_safe_float(match.get("price")),
                    stock=_safe_int(match.get("stock")),
                )
        except Exception as exc:
            warnings.append(f"DropXL : {exc}")
    elif selected.get("source_product_id"):
        product = get_product(int(selected["source_product_id"]))
        if product:
            selected = _euro_offer_from_selected(
                selected,
                product_cost=_safe_float(product.get("supplier_cost")),
                stock=_safe_int(product.get("stock")),
                shipping_days=_safe_int(product.get("shipping_days")),
            )
    return selected, warnings


async def monitor_workflow(workflow_id: int) -> dict[str, Any]:
    workflow = get_workflow(workflow_id)
    client = EbayClient()
    keyword = workflow.get("keyword") or ""
    marketplace = workflow.get("marketplace") or "EBAY_FR"
    payload = await client.search_items(keyword, 50, marketplace)
    items = payload.get("itemSummaries") or []
    prices = [
        float((row.get("price") or {}).get("value"))
        for row in items
        if _safe_float((row.get("price") or {}).get("value")) is not None
    ]
    current_market = {
        "total_results": int(payload.get("total") or len(items)),
        "median_price": round(median(prices), 2) if prices else None,
    }
    opportunity = workflow.get("opportunity") or {}
    baseline_total = int(opportunity.get("total_results") or 0)
    baseline_price = _safe_float(opportunity.get("median_price"))
    selected_before = workflow.get("selected_offer") or {}
    selected_after, refresh_warnings = await _refresh_selected_offer(workflow)
    alerts: list[dict[str, str]] = []
    settings = get_settings()

    old_cost = _safe_float(selected_before.get("product_cost"))
    new_cost = _safe_float(selected_after.get("product_cost"))
    if old_cost and new_cost and new_cost > old_cost * (1 + settings.max_supplier_price_jump_percent / 100):
        alerts.append({"kind": "SUPPLIER_PRICE", "level": "HIGH",
                       "message": f"Coût fournisseur en hausse : {old_cost:.2f} € → {new_cost:.2f} €"})
    stock = _safe_int(selected_after.get("stock"))
    if stock is not None and stock < settings.min_stock:
        alerts.append({"kind": "SUPPLIER_STOCK", "level": "HIGH",
                       "message": f"Stock fournisseur faible : {stock}"})
    days = _safe_int(selected_after.get("shipping_days"))
    if days is not None and days > settings.max_shipping_days:
        alerts.append({"kind": "SUPPLIER_DELAY", "level": "HIGH",
                       "message": f"Délai fournisseur passé à {days} jours"})
    if baseline_total and current_market["total_results"] > baseline_total * 1.30:
        alerts.append({"kind": "COMPETITION", "level": "MEDIUM",
                       "message": f"Concurrence eBay +{(current_market['total_results'] / baseline_total - 1) * 100:.0f}%"})
    if baseline_price and current_market["median_price"] is not None and current_market["median_price"] < baseline_price * 0.85:
        alerts.append({"kind": "MARKET_PRICE", "level": "HIGH",
                       "message": f"Prix médian eBay en baisse : {baseline_price:.2f} € → {current_market['median_price']:.2f} €"})
    profit = selected_after.get("profit") if isinstance(selected_after.get("profit"), dict) else {}
    margin = _safe_float(profit.get("margin_percent"))
    if margin is not None and margin < settings.min_margin_percent:
        alerts.append({"kind": "MARGIN", "level": "HIGH",
                       "message": f"Marge estimée tombée à {margin:.1f}%"})

    for alert in alerts:
        add_alert(None, alert["level"], f"OPPORTUNITY_{alert['kind']}", f"{keyword} — {alert['message']}")
        _add_event(workflow_id, alert["kind"], alert["message"], level=alert["level"])
    for warning in refresh_warnings:
        _add_event(workflow_id, "MONITOR_WARNING", warning, level="WARNING")

    _update_workflow(
        workflow_id,
        selected_offer_json=json.dumps(selected_after, ensure_ascii=False),
        last_monitored_at=utc_now(),
    )
    _add_event(
        workflow_id,
        "MONITOR_RUN",
        f"Surveillance terminée : {len(alerts)} alerte(s)",
        payload={"market": current_market, "warnings": refresh_warnings},
    )
    return {
        "workflow_id": workflow_id,
        "keyword": keyword,
        "market": current_market,
        "selected_offer": selected_after,
        "alerts": alerts,
        "warnings": refresh_warnings,
        "checked_at": utc_now(),
    }


async def monitor_enabled_workflows(limit: int = MONITOR_LIMIT) -> dict[str, Any]:
    if _CENTER_LOCK.locked():
        return {"status": "BUSY", "processed": 0, "results": []}
    _ensure_tables()
    with conn() as database:
        rows = database.execute(
            "SELECT id FROM opportunity_workflows WHERE monitoring_enabled=1 ORDER BY updated_at DESC LIMIT ?",
            (min(max(int(limit), 1), 100),),
        ).fetchall()
    workflow_ids = [int(row["id"]) for row in rows]
    if not workflow_ids:
        return {"status": "NO_OP", "processed": 0, "results": []}
    async with _CENTER_LOCK:
        raw = await _limited([monitor_workflow(workflow_id) for workflow_id in workflow_ids], concurrency=2)
    results, errors = [], []
    for workflow_id, item in zip(workflow_ids, raw):
        if isinstance(item, Exception):
            errors.append({"workflow_id": workflow_id, "message": str(item)})
        else:
            results.append(item)
    return {"status": "COMPLETED", "processed": len(results), "results": results, "errors": errors}


def verify_latest_backup(create: bool = False) -> dict[str, Any]:
    if create:
        create_backup()
    backups = list_backups()
    if not backups:
        return {"ok": False, "message": "Aucune sauvegarde disponible", "backup": None}
    latest = backups[0]
    path = resolve_backup(latest["name"])
    if not path:
        return {"ok": False, "message": "Sauvegarde introuvable", "backup": latest}
    import sqlite3

    try:
        with sqlite3.connect(f"file:{path}?mode=ro", uri=True) as database:
            integrity = database.execute("PRAGMA integrity_check").fetchone()[0]
            tables = {
                row[0] for row in database.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }
        required = {"products", "app_kv", "radar_scans"}
        missing = sorted(required - tables)
        ok = integrity == "ok" and not missing
        return {
            "ok": ok,
            "message": "Sauvegarde lisible et intègre" if ok else "Sauvegarde incomplète",
            "integrity": integrity,
            "missing_tables": missing,
            "backup": latest,
        }
    except Exception as exc:
        return {"ok": False, "message": str(exc), "backup": latest}


def workflow_readiness(workflow: dict[str, Any]) -> dict[str, Any]:
    supplier_snapshot = workflow.get("supplier_snapshot") or {}
    selected = workflow.get("selected_offer") or {}
    risk = workflow.get("risk") or {}
    listing = workflow.get("listing") or {}
    checks = [
        {
            "id": "supplier_comparison",
            "label": "Au moins 3 offres comparées",
            "done": len(supplier_snapshot.get("offers") or []) >= 3,
            "critical": True,
        },
        {
            "id": "supplier_selected",
            "label": "Fournisseur sélectionné",
            "done": bool(selected),
            "critical": True,
        },
        {
            "id": "landed_cost",
            "label": "Coût livré confirmé",
            "done": selected.get("landed_cost") is not None,
            "critical": True,
        },
        {
            "id": "margin",
            "label": "Marge et profit minimums validés",
            "done": bool(selected.get("eligible") and selected.get("profit")),
            "critical": True,
        },
        {
            "id": "risk",
            "label": "Risk Engine validé",
            "done": bool(risk.get("pass")),
            "critical": True,
        },
        {
            "id": "listing",
            "label": "Brouillon eBay préparé",
            "done": bool(listing),
            "critical": True,
        },
        {
            "id": "category",
            "label": "Catégorie eBay identifiée",
            "done": bool(listing.get("category_id")),
            "critical": True,
        },
        {
            "id": "aspects",
            "label": "Caractéristiques obligatoires complétées",
            "done": bool(listing) and not listing.get("required_aspects_missing"),
            "critical": True,
        },
        {
            "id": "monitoring",
            "label": "Surveillance activée",
            "done": bool(workflow.get("monitoring_enabled")),
            "critical": False,
        },
    ]
    score = round(sum(1 for item in checks if item["done"]) / len(checks) * 100)
    critical_ready = all(item["done"] for item in checks if item["critical"])
    return {
        "score": score,
        "ready": critical_ready,
        "checks": checks,
        "missing": [item["label"] for item in checks if not item["done"]],
    }


def launch_readiness() -> dict[str, Any]:
    settings = get_settings()
    workflows = list_workflows(200)
    ensure_radar_tables()
    with conn() as database:
        opportunity_count = int(database.execute(
            "SELECT COUNT(*) FROM radar_opportunities WHERE dismissed=0"
        ).fetchone()[0])
        latest_full = database.execute(
            """
            SELECT * FROM radar_auto_runs
            WHERE trigger IN ('scheduler-full','manual-full','manual')
            ORDER BY id DESC LIMIT 1
            """
        ).fetchone()
    backup = verify_latest_backup(False)
    ebay_connected = EbayClient().token_status().get("connected", False)
    amazon_connected = connection_status("amazon").get("connected", False)
    workflow_reports = []
    for workflow in workflows:
        readiness = workflow_readiness(workflow)
        workflow_reports.append({
            "id": workflow["id"],
            "keyword": workflow["keyword"],
            "stage": workflow["stage"],
            "stage_label": workflow.get("stage_label"),
            **readiness,
        })
    checks = [
        {"id": "ebay_keys", "label": "Clés eBay Production", "done": bool(
            settings.ebay_effective_env == "production" and settings.ebay_client_id and settings.ebay_client_secret
        ), "critical": True},
        {"id": "ebay_oauth", "label": "Compte eBay autorisé", "done": bool(ebay_connected), "critical": True},
        {"id": "radar_runs", "label": "Plusieurs opportunités Radar", "done": opportunity_count >= 3, "critical": True},
        {"id": "full_scan", "label": "Grand scan réussi", "done": bool(latest_full and latest_full["status"] == "COMPLETED"), "critical": True},
        {"id": "workflow", "label": "Au moins un dossier prêt", "done": any(row["ready"] for row in workflow_reports), "critical": True},
        {"id": "backup", "label": "Sauvegarde intègre", "done": bool(backup.get("ok")), "critical": True},
        {"id": "dry_run", "label": "Écritures eBay verrouillées pendant les tests", "done": not settings.ebay_write_enabled and not settings.ebay_publish_enabled, "critical": True},
        {"id": "amazon", "label": "Amazon SP-API connecté", "done": bool(amazon_connected), "critical": False},
    ]
    critical_ready = all(item["done"] for item in checks if item["critical"])
    score = round(sum(1 for item in checks if item["done"]) / len(checks) * 100)
    return {
        "ready": critical_ready,
        "score": score,
        "checks": checks,
        "workflow_reports": workflow_reports,
        "opportunity_count": opportunity_count,
        "workflow_count": len(workflows),
        "backup": backup,
        "amazon_optional": not amazon_connected,
        "notice": "La publication réelle reste bloquée tant que les interrupteurs d'écriture eBay sont désactivés.",
    }


def command_center_status() -> dict[str, Any]:
    workflows = list_workflows(200)
    stage_counts = Counter(row.get("stage") for row in workflows)
    return {
        "workflow_count": len(workflows),
        "monitoring_count": sum(1 for row in workflows if row.get("monitoring_enabled")),
        "ready_count": sum(1 for row in workflows if workflow_readiness(row).get("ready")),
        "stage_counts": dict(stage_counts),
        "amazon_connected": connection_status("amazon").get("connected", False),
        "cj_connected": CJClient().status().get("connected", False),
        "dropxl_connected": connection_status("dropxl").get("connected", False),
        "dry_run": True,
        "stages": [{"id": stage, "label": STAGE_LABELS[stage]} for stage in STAGES],
    }
