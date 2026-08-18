from app.services.risk import assess_product

def test_risk_blocks_low_stock():
    p = {
        "target_price": 30.0, "supplier_cost": 10.0, "shipping_cost": 2.0,
        "stock": 0, "shipping_days": 3, "previous_supplier_cost": None,
        "category_id": "123", "images": ["https://example.com/a.jpg"], "aspects": {"Brand": ["X"]},
    }
    r = assess_product(p)
    assert r["pass"] is False
    assert any(x.startswith("Stock") for x in r["blocks"])
