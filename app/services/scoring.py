from app.config import get_settings
from app.services.profit import calculate_profit


def calculate_product_score(product: dict, supplier: dict | None = None) -> dict:
    """Return an explainable catalogue-readiness score.

    This score deliberately excludes unobserved marketplace demand. A separate
    opportunity_score is kept for real eBay marketplace analysis.
    """
    settings = get_settings()
    profit = calculate_profit(product)
    points = 0.0
    factors: list[dict] = []

    def add(label: str, earned: float, maximum: float, detail: str) -> None:
        nonlocal points
        earned = max(0.0, min(float(earned), float(maximum)))
        points += earned
        factors.append({"label": label, "earned": round(earned, 1), "maximum": maximum, "detail": detail})

    target_price = float(product.get("target_price") or 0)
    if target_price:
        margin_ratio = profit["margin_percent"] / max(settings.min_margin_percent, 1)
        profit_ratio = profit["estimated_profit"] / max(settings.min_profit_eur, 0.01)
        earned = 15 * min(max(margin_ratio, 0), 1) + 10 * min(max(profit_ratio, 0), 1)
        add("Rentabilité", earned, 25, f"{profit['margin_percent']:.1f}% de marge · {profit['estimated_profit']:.2f} €")
    else:
        add("Rentabilité", 0, 25, "Prix cible manquant")

    stock = int(product.get("stock") or 0)
    add("Stock", 15 * min(stock / max(settings.min_stock, 1), 1), 15,
        f"{stock} unité(s) · minimum {settings.min_stock}")

    shipping_days = int(product.get("shipping_days") or 0)
    if shipping_days <= 0:
        shipping_points, shipping_detail = 0, "Délai non confirmé"
    elif shipping_days <= settings.max_shipping_days:
        shipping_points, shipping_detail = 15, f"{shipping_days} j · dans la règle"
    else:
        shipping_points = 15 * max(0, 1 - (shipping_days - settings.max_shipping_days) / max(settings.max_shipping_days * 2, 1))
        shipping_detail = f"{shipping_days} j · maximum {settings.max_shipping_days}"
    add("Livraison", shipping_points, 15, shipping_detail)

    images = product.get("images") or []
    aspects = product.get("aspects") or {}
    completeness = (6 if images else 0) + (5 if product.get("category_id") else 0) + (5 if aspects else 0) + (4 if len(str(product.get("description") or "").strip()) >= 40 else 0)
    missing = []
    if not images:
        missing.append("photo")
    if not product.get("category_id"):
        missing.append("catégorie")
    if not aspects:
        missing.append("caractéristiques")
    if len(str(product.get("description") or "").strip()) < 40:
        missing.append("description")
    add("Fiche produit", completeness, 20, "Complète" if not missing else "À compléter : " + ", ".join(missing))

    supplier_points = 0.0
    supplier_detail = "Fournisseur non rattaché"
    if supplier:
        reliability = supplier.get("reliability_score")
        supplier_points = 5 if reliability is None else 4 + 6 * float(reliability) / 100
        supplier_detail = supplier.get("name") or "Fournisseur rattaché"
        if reliability is not None:
            supplier_detail += f" · fiabilité {float(reliability):.0f}/100"
    add("Fournisseur", supplier_points, 10, supplier_detail)

    risk_points = 15 if target_price and profit["estimated_profit"] >= settings.min_profit_eur and profit["margin_percent"] >= settings.min_margin_percent else 5 if target_price else 0
    add("Sécurité financière", risk_points, 15, "Seuils respectés" if risk_points == 15 else "Règles à vérifier")

    return {
        "score": round(points),
        "source": "CATALOGUE_LOCAL",
        "label": "Préparation locale",
        "factors": factors,
        "market_score": product.get("opportunity_score"),
        "market_label": "Demande eBay réelle" if product.get("opportunity_score") is not None else "Demande non encore mesurée",
        "meaning": "Qualité, rentabilité, stock, livraison et complétude. Ce score ne prétend pas mesurer les ventes du marché.",
    }
