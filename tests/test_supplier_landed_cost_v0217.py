from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_supplier_flow_keeps_cj_product_id_and_calculates_real_freight():
    source = read("app/routers/supplier_flow.py")
    assert "cj_pid" in source
    assert "client.product_detail(payload.cj_pid)" in source
    assert "client.freight_options" in source
    assert "client.usd_to_eur" in source
    assert '"shipping_cost": shipping_eur' in source
    assert '"target_price": pricing["suggested_price"]' in source


def test_unknown_marketplace_logistics_are_not_marked_as_free_shipping():
    source = read("app/routers/supplier_flow.py")
    assert "logistics_complete = payload.shipping_cost is not None" in source
    assert '"shipping_days": payload.shipping_days if logistics_complete else 99' in source
    assert '"target_price": pricing["suggested_price"] if pricing else None' in source


def test_missing_target_price_does_not_create_fake_minus_100_margin():
    source = read("app/services/profit.py")
    assert '"margin_percent": None' in source
    assert '"estimated_profit": None' in source
    assert "margin = profit / price * 100" in source


def test_risk_engine_treats_missing_price_and_delivery_as_missing_data():
    source = read("app/services/risk.py")
    assert 'blocks.append("Prix de vente cible manquant")' in source
    assert 'blocks.append("Délai de livraison non confirmé")' in source
    assert "if not has_target_price" in source


def test_manual_price_calculation_refuses_unknown_delivery_and_sets_target():
    source = read("app/routers/products.py")
    assert "shipping_days <= 0 or shipping_days >= 99" in source
    assert "Impossible de calculer un prix fiable tant que la livraison n'est pas confirmée." in source
    assert 'set_product_fields(product_id, suggested_price=result["suggested_price"], target_price=result["suggested_price"])' in source


def test_supplier_ui_explains_shipping_state():
    source = read("app/static/supplier_flow_v2.js")
    assert "Calculer livraison & ajouter" in source
    assert "Transport calculé à l’ajout" in source
    assert "Livraison à confirmer" in source
    assert "livraison à confirmer" in source


def test_current_version_and_cache_include_landed_cost_ui():
    main = read("app/main.py")
    sw = read("app/static/service-worker.js")
    assert 'VERSION = "0.21.8"' in main
    assert "opsbot-v0.21.8-shell" in sw
    assert "supplier_flow_v2.js?v=0.21.8" in sw
