from app.config import get_settings
from app.services.profit import calculate_profit


def assess_product(product: dict) -> dict:
    s = get_settings()
    p = calculate_profit(product)
    blocks = []
    warnings = []

    has_target_price = bool(product.get("target_price"))
    if not has_target_price:
        blocks.append("Prix de vente cible manquant")
    else:
        if p["margin_percent"] is not None and p["margin_percent"] < s.min_margin_percent:
            blocks.append(f"Marge {p['margin_percent']:.1f}% < minimum {s.min_margin_percent:.1f}%")
        if p["estimated_profit"] is not None and p["estimated_profit"] < s.min_profit_eur:
            blocks.append(f"Profit estimé {p['estimated_profit']:.2f}€ < minimum {s.min_profit_eur:.2f}€")

    stock = int(product.get("stock") or 0)
    if stock < s.min_stock:
        blocks.append(f"Stock {stock} < minimum {s.min_stock}")

    shipping_days = int(product.get("shipping_days") or 0)
    if shipping_days <= 0 or shipping_days >= 99:
        blocks.append("Délai de livraison non confirmé")
    elif shipping_days > s.max_shipping_days:
        blocks.append(f"Délai {shipping_days}j > maximum {s.max_shipping_days}j")

    prev = product.get("previous_supplier_cost")
    cur = float(product.get("supplier_cost") or 0)
    if prev and float(prev) > 0:
        jump = (cur - float(prev)) / float(prev) * 100
        if jump > s.max_supplier_price_jump_percent:
            blocks.append(f"Coût fournisseur +{jump:.1f}%")
        elif jump > 10:
            warnings.append(f"Coût fournisseur +{jump:.1f}%")

    if not product.get("images"):
        warnings.append("Aucune image")
    if not product.get("category_id"):
        warnings.append("Catégorie eBay non définie")
    if not product.get("aspects"):
        warnings.append("Item specifics/aspects non définis")

    return {"pass": not blocks, "blocks": blocks, "warnings": warnings, "profit": p}
