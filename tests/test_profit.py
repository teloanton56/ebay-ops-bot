from app.services.profit import calculate_profit

def test_profit_calculation():
    product = {"target_price": 39.90, "supplier_cost": 18.0, "shipping_cost": 4.0}
    r = calculate_profit(product)
    assert r["sale_price"] == 39.90
    assert r["estimated_profit"] > 0
    assert r["margin_percent"] > 0
