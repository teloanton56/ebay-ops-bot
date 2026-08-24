from app.config import get_settings
from app.services.cj_landed import load_cj_product_link, route_requirements
from app.services.compliance import assess_compliance
from app.services.db import get_supplier
from app.services.profit import calculate_profit


def _thresholds_for_product(product: dict) -> tuple[dict, str]:
    settings = get_settings()
    link = load_cj_product_link(str(product.get("supplier_sku") or ""))
    warehouse = str(link.get("warehouse") or "").upper()
    destination_country = str(link.get("destination_country") or "").upper()
    currency = str(link.get("currency") or "").upper()
    if warehouse in {"US", "CN"} and destination_country == "US" and currency == "USD":
        return route_requirements(warehouse), warehouse
    return {
        "min_margin_percent": settings.min_margin_percent,
        "min_profit": settings.min_profit_amount,
        "min_stock": settings.min_stock,
        "max_shipping_days": settings.max_shipping_days,
    }, ""


def assess_product(product: dict, supplier: dict | None = None) -> dict:
    s = get_settings()
    p = calculate_profit(product)
    requirements, warehouse = _thresholds_for_product(product)
    blocks = []
    warnings = []

    supplier_cost = float(product.get("supplier_cost") or 0)
    if supplier_cost <= 0:
        blocks.append("Coût fournisseur manquant ou nul")

    has_target_price = bool(product.get("target_price"))
    if not has_target_price:
        blocks.append("Prix de vente cible manquant")
    else:
        min_margin = float(requirements["min_margin_percent"])
        min_profit = float(requirements["min_profit"])
        if p["margin_percent"] is not None and p["margin_percent"] < min_margin:
            blocks.append(f"Marge {p['margin_percent']:.1f}% < minimum {min_margin:.1f}%")
        if p["estimated_profit"] is not None and p["estimated_profit"] < min_profit:
            blocks.append(f"Profit estimé ${p['estimated_profit']:.2f} < minimum ${min_profit:.2f}")

    stock = int(product.get("stock") or 0)
    min_stock = int(requirements["min_stock"])
    if stock < min_stock:
        blocks.append(f"Stock {stock} < minimum {min_stock}")

    shipping_days = int(product.get("shipping_days") or 0)
    max_days = int(requirements["max_shipping_days"])
    if shipping_days <= 0 or shipping_days == 99:
        blocks.append("Délai de livraison non confirmé")
    elif shipping_days > max_days:
        blocks.append(f"Délai {shipping_days}j > maximum {max_days}j")

    if (product.get("marketplace_id") or s.ebay_marketplace_id) != "EBAY_US":
        blocks.append("Produit hors profil eBay US")
    if (product.get("currency") or s.ebay_currency) != "USD":
        blocks.append("Produit hors devise USD")

    prev = product.get("previous_supplier_cost")
    cur = supplier_cost
    if prev and float(prev) > 0:
        jump = (cur - float(prev)) / float(prev) * 100
        if jump > s.max_supplier_price_jump_percent:
            blocks.append(f"Coût fournisseur +{jump:.1f}%")
        elif jump > 10:
            warnings.append(f"Coût fournisseur +{jump:.1f}%")

    if warehouse == "CN":
        warnings.append("Route CJ Chine → US : seuils renforcés appliqués")
    elif warehouse == "US":
        warnings.append("Route CJ US prioritaire")
    else:
        blocks.append("Route CJ US/CN non vérifiée")

    if not product.get("images"):
        warnings.append("Aucune image")
    if not product.get("category_id"):
        warnings.append("Catégorie eBay US non définie")
    if not product.get("aspects"):
        warnings.append("Item specifics/aspects non définis")

    if supplier is None and product.get("supplier_id"):
        try:
            supplier = get_supplier(int(product["supplier_id"]))
        except (TypeError, ValueError):
            supplier = None
    compliance = assess_compliance(product, supplier)
    blocks.extend(compliance["publication_blocks"])
    warnings.extend(compliance["warnings"])

    blocks = list(dict.fromkeys(blocks))
    warnings = list(dict.fromkeys(warnings))
    return {
        "pass": not blocks,
        "blocks": blocks,
        "warnings": warnings,
        "profit": p,
        "compliance": compliance,
        "route": {
            "warehouse": warehouse or None,
            "label": "CJ US" if warehouse == "US" else "CJ China → US" if warehouse == "CN" else "Non confirmée",
            "requirements": requirements,
        },
    }
