import asyncio

from app.config import get_settings
from app.services.db import (
    add_alert,
    finish_analysis_run,
    get_product,
    list_products,
    save_analysis_result,
    set_product_fields,
    start_analysis_run,
)
from app.services.ebay import EbayClient
from app.services.research import summarize_market
from app.services.risk import assess_product

_lock = asyncio.Lock()


def _automatic_status(score: float, risk: dict) -> str:
    if not risk["pass"] or score < 40:
        return "Rejeté"
    if score >= 70:
        return "Winner"
    return "À tester"


async def analyze_catalog() -> dict:
    if _lock.locked():
        return {"already_running": True, "message": "Une analyse est déjà en cours."}
    async with _lock:
        products = [
            row for row in list_products()
            if row.get("marketplace_id") == "EBAY_US" and row.get("currency") == "USD"
        ]
        settings = get_settings()
        client = EbayClient()
        live = bool(
            settings.ebay_effective_env == "production"
            and settings.ebay_client_id
            and settings.ebay_client_secret
            and client.token_status().get("connected")
        )
        run_id = start_analysis_run("EBAY_US" if live else "CATALOGUE_US", len(products))
        analyzed = winners = rejected = errors = 0

        for product in products:
            try:
                score = price = None
                if live:
                    data = await client.search_items(
                        product["title"],
                        30,
                        "EBAY_US",
                        product.get("category_id"),
                    )
                    items = data.get("itemSummaries") or []
                    summary = summarize_market(
                        items,
                        product,
                        total_results=int(data.get("total") or len(items)),
                    )
                    score = float(summary.get("opportunity_score") or 0)
                    price = summary.get("suggested_price")
                    updates = {"opportunity_score": score}
                    if price:
                        # Recommendation only: never overwrite the operator's target price.
                        updates["suggested_price"] = price
                    set_product_fields(product["id"], **updates)

                refreshed = get_product(product["id"])
                risk = assess_product(refreshed)
                if live:
                    new_status = _automatic_status(score or 0, risk)
                else:
                    new_status = "Rejeté" if not risk["pass"] else (product.get("product_status") or "À tester")
                set_product_fields(product["id"], product_status=new_status)

                profit = risk["profit"]
                save_analysis_result(
                    run_id,
                    product["id"],
                    score=score,
                    suggested_price=price,
                    margin_percent=profit["margin_percent"],
                    estimated_profit=profit["estimated_profit"],
                    previous_status=product.get("product_status"),
                    new_status=new_status,
                )
                if new_status == "Winner":
                    winners += 1
                    if live:
                        add_alert(product["id"], "success", "WINNER", f"Winner eBay US détecté : score {score:.0f}/100.")
                elif new_status == "Rejeté":
                    rejected += 1
                    add_alert(
                        product["id"],
                        "danger",
                        "RISK",
                        "Produit rejeté automatiquement : " + (" ; ".join(risk["blocks"]) or f"score {score:.0f}/100"),
                    )
                analyzed += 1
            except Exception as exc:
                errors += 1
                save_analysis_result(
                    run_id,
                    product["id"],
                    previous_status=product.get("product_status"),
                    error=str(exc),
                )
                add_alert(product["id"], "danger", "ANALYSIS_ERROR", f"Analyse eBay US impossible : {exc}")

        finish_analysis_run(run_id, analyzed, winners, rejected, errors)
        return {
            "run_id": run_id,
            "mode": "EBAY_US" if live else "CATALOGUE_US",
            "products_total": len(products),
            "products_analyzed": analyzed,
            "winners": winners,
            "rejected": rejected,
            "errors": errors,
            "market_data": live,
            "dry_run": True,
        }
