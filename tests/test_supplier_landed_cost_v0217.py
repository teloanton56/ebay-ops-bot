from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_supplier_flow_keeps_cj_product_id_and_uses_shared_us_landed_engine():
    flow = read("app/routers/supplier_flow.py")
    landed = read("app/services/cj_landed.py")
    assert "cj_pid" in flow
    assert "resolve_cj_landed_offer" in flow
    assert "save_cj_product_link" in flow
    assert "client.product_detail(pid)" in landed
    assert "client.freight_options" in landed
    assert "usd_to_eur" not in landed
    assert 'destination_country="US"' in flow
    assert '"shipping_cost": landed["shipping_cost"]' in flow


def test_margin_hunter_supplier_add_and_refresh_share_same_cj_resolver():
    flow = read("app/routers/supplier_flow.py")
    hunter = read("app/services/margin_hunter.py")
    refresh = read("app/services/supplier_refresh.py")
    assert "resolve_cj_landed_offer" in flow
    assert "resolve_cj_landed_offer" in hunter
    assert "resolve_cj_landed_offer" in refresh


def test_supplier_flow_has_no_generic_marketplace_logistics_path_anymore():
    source = read("app/routers/supplier_flow.py").lower()
    assert 'payload.provider.strip().lower() != "cj"' in source
    assert "utilise uniquement cj dropshipping" in source
    assert "aliexpress" not in source
    assert "amazon" not in source


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


def test_manual_price_calculation_refuses_unknown_us_delivery_and_sets_target():
    source = read("app/routers/products.py")
    assert "shipping_days <= 0 or shipping_days >= 99" in source
    assert "livraison US n'est pas confirmée" in source
    assert 'set_product_fields(product_id, suggested_price=result["suggested_price"], target_price=result["suggested_price"])' in source


def test_guided_supplier_ui_explains_us_and_china_route_state():
    dashboard = read("app/templates/dashboard.html")
    source = read("app/static/simple_ui.js")
    assert "Entrepôt US prioritaire" in dashboard
    assert "Chine uniquement" in dashboard
    assert "Calculer le coût livré US" in source
    assert "Destination" in source and "US" in source


def test_current_version_and_cache_include_guided_landed_cost_ui():
    main = read("app/main.py")
    sw = read("app/static/service-worker.js")
    version = main.split('VERSION = "', 1)[1].split('"', 1)[0]
    assert f"opsbot-v{version}-shell" in sw
    assert f"simple_ui.js?v={version}" in sw
    assert "supplier_flow_v2.js" not in sw
