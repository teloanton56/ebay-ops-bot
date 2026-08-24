from fastapi.testclient import TestClient

from app.main import app
from app.services import db
from app.services.cj_landed import save_cj_product_link


CORRUPTED_TITLE = "fan Lasko 16 3-Speed Oscillating Adjustable Height Pedestal S16200 White Camping"


def _create_candidate(pid: str, sku: str, name: str, category: str, variant_name: str) -> tuple[int, int]:
    supplier_id = db.ensure_provider_supplier("cj", "CJ Dropshipping", "US")
    candidate_id = db.save_cj_candidate({
        "cj_pid": pid,
        "sku": sku,
        "name": name,
        "image_url": "",
        "price_usd": 5.0,
        "category_name": category,
        "stock": 100,
        "warehouse_country": "US",
        "delivery_cycle": "3-5",
    })
    db.save_cj_candidate_analysis(candidate_id, {
        "product_name": name,
        "variant_name": variant_name,
        "category_name": category,
        "variant_id": f"VID-{pid}",
        "variant_sku": sku,
        "source_country": "US",
        "verified_stock": 100,
        "landed_cost_usd": 8.0,
        "shipping": {"delivery_days": "5 days"},
    }, [])
    product_id = db.upsert_product({
        "supplier_sku": sku,
        "title": CORRUPTED_TITLE,
        "description": "",
        "supplier_cost": 5.0,
        "shipping_cost": 3.0,
        "stock": 100,
        "shipping_days": 5,
        "target_price": 29.99,
        "marketplace_id": "EBAY_US",
        "currency": "USD",
        "images": [],
        "aspects": {},
        "supplier_id": supplier_id,
        "product_status": "À tester",
    })
    save_cj_product_link(sku, {
        "pid": pid,
        "variant_id": f"VID-{pid}",
        "warehouse": "US",
        "destination_country": "US",
        "currency": "USD",
        "risk_flags": [],
    })
    return candidate_id, product_id


def test_two_corrupted_fan_titles_are_repaired_from_their_own_cj_products():
    _, desk_id = _create_candidate(
        "PID-DESK",
        "CJ-DESK-FAN",
        "Portable USB Desk Fan Rechargeable Quiet Mini",
        "Desktop Fans",
        "White USB",
    )
    _, neck_id = _create_candidate(
        "PID-NECK",
        "CJ-NECK-FAN",
        "Bladeless Neck Fan Wearable Personal Cooling",
        "Personal Fans",
        "Green 4000mAh",
    )

    payload = {
        "market_keywords": [
            "fan",
            "Lasko 16 3-Speed Oscillating Adjustable Height Pedestal S16200 White Camping",
        ]
    }
    with TestClient(app) as client:
        desk = client.post(f"/api/products/{desk_id}/optimize-ebay", json=payload)
        neck = client.post(f"/api/products/{neck_id}/optimize-ebay", json=payload)

    assert desk.status_code == 200, desk.text
    assert neck.status_code == 200, neck.text
    desk_data = desk.json()
    neck_data = neck.json()

    assert desk_data["repaired_from_cj"] is True
    assert neck_data["repaired_from_cj"] is True
    assert desk_data["optimized_title"] != neck_data["optimized_title"]
    assert "Desk" in desk_data["optimized_title"]
    assert "Neck" in neck_data["optimized_title"]
    for result in (desk_data, neck_data):
        assert "Lasko" not in result["optimized_title"]
        assert "S16200" not in result["optimized_title"]
        assert result["duplicate_guard"] is True


def test_duplicate_guard_refuses_two_catalog_rows_with_same_verified_identity():
    _, first_id = _create_candidate(
        "PID-SAME-1",
        "CJ-SAME-1",
        "Portable Cooling Fan",
        "Portable Fans",
        "White",
    )
    _, second_id = _create_candidate(
        "PID-SAME-2",
        "CJ-SAME-2",
        "Portable Cooling Fan",
        "Portable Fans",
        "White",
    )

    with TestClient(app) as client:
        first = client.post(f"/api/products/{first_id}/optimize-ebay", json={"market_keywords": ["fan"]})
        second = client.post(f"/api/products/{second_id}/optimize-ebay", json={"market_keywords": ["fan"]})

    assert first.status_code == 200
    assert second.status_code == 409
    assert "identique à un autre produit" in second.json()["detail"]
