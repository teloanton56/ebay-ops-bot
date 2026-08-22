from app.config import get_settings
from app.services.cj_landed import load_cj_product_link, route_requirements
from app.services.profit import calculate_profit


def _thresholds(product: dict) -> tuple[dict, str]:
    settings = get_settings()
    link = load_cj_product_link(str(product.get("supplier_sku") or ""))
    warehouse = str(link.get("warehouse") or "").upper()
    if warehouse in {"US", "CN"}:
        return route_requirements(warehouse), warehouse
    return {
        "min_margin_percent": settings.min_margin_percent,
        "min_profit": settings.min_profit_amount,
        "min_stock": settings.min_stock,
        "max_shipping_days": settings.max_shipping_days,
    }, ""


def calculate_product_score(product: dict, supplier: dict | None = None) -> dict:
    """Explainable US catalogue-readiness score; marketplace demand stays separate."""
    requirements, warehouse = _thresholds(product)
    profit = calculate_profit(product)
    points = 0.0
    factors: list[dict] = []

    def add(label: str, earned: float, maximum: float, detail: str) -> None:
        nonlocal points
        earned = max(0.0, min(float(earned), float(maximum)))
        points += earned
        factors.append({"label": label, "earned": round(earned, 1), "maximum": maximum, "detail": detail})

    target_price = float(product.get("target_price") or 0)
    min_margin = float(requirements["min_margin_percent"])
    min_profit = float(requirements["min_profit"])
    if target_price and profit["margin_percent"] is not None and profit["estimated_profit"] is not None:
        margin_ratio = profit["margin_percent"] / max(min_margin, 1)
        profit_ratio = profit["estimated_profit"] / max(min_profit, 0.01)
        earned = 15 * min(max(margin_ratio, 0), 1) + 10 * min(max(profit_ratio, 0), 1)
        add("Rentabilité", earned, 25, f"{profit['margin_percent']:.1f}% marge · ${profit['estimated_profit']:.2f}")
    else:
        add("Rentabilité", 0, 25, "Prix cible manquant")

    stock = int(product.get("stock") or 0)
    min_stock = int(requirements["min_stock"])
    add("Stock", 15 * min(stock / max(min_stock, 1), 1), 15, f"{stock} unité(s) · minimum {min_stock}")

    shipping_days = int(product.get("shipping_days") or 0)
    max_days = int(requirements["max_shipping_days"])
    if shipping_days <= 0 or shipping_days == 99:
        shipping_points, shipping_detail = 0, "Délai non confirmé"
    elif shipping_days <= max_days:
        shipping_points, shipping_detail = 15, f"{shipping_days} j · route conforme"
    else:
        shipping_points = 0
        shipping_detail = f"{shipping_days} j · maximum {max_days}"
    add("Livraison", shipping_points, 15, shipping_detail)

    images = product.get("images") or []
    aspects = product.get("aspects") or {}
    completeness = (
        (6 if images else 0)
        + (5 if product.get("category_id") else 0)
        + (5 if aspects else 0)
        + (4 if len(str(product.get("description") or "").strip()) >= 40 else 0)
    )
    missing = []
    if not images:
        missing.append("photo")
    if not product.get("category_id"):
        missing.append("catégorie US")
    if not aspects:
        missing.append("item specifics")
    if len(str(product.get("description") or "").strip()) < 40:
        missing.append("description")
    add("Fiche produit", completeness, 20, "Complète" if not missing else "À compléter : " + ", ".join(missing))

    supplier_points = 0.0
    supplier_detail = "CJ non rattaché"
    if supplier and str(supplier.get("provider_code") or "").lower() == "cj":
        supplier_points = 10.0
        supplier_detail = "CJ Dropshipping"
        if warehouse:
            supplier_detail += f" · {'US' if warehouse == 'US' else 'Chine → US'}"
    add("Fournisseur", supplier_points, 10, supplier_detail)

    financial_ok = bool(
        target_price
        and profit["estimated_profit"] is not None
        and profit["margin_percent"] is not None
        and profit["estimated_profit"] >= min_profit
        and profit["margin_percent"] >= min_margin
    )
    add("Sécurité financière", 15 if financial_ok else 5 if target_price else 0, 15,
        "Seuils route respectés" if financial_ok else "Règles route à vérifier")

    return {
        "score": round(points),
        "source": "CATALOGUE_LOCAL_US",
        "label": "Préparation eBay US",
        "factors": factors,
        "market_score": product.get("opportunity_score"),
        "market_label": "Demande eBay US réelle" if product.get("opportunity_score") is not None else "Demande US non encore mesurée",
        "route": "CJ US" if warehouse == "US" else "CJ China → US" if warehouse == "CN" else "Non confirmée",
        "meaning": "Rentabilité USD, stock CJ, route vers les États-Unis et complétude. Le score marché eBay US reste séparé.",
    }
