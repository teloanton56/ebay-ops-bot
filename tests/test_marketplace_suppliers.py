from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app


ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_amazon_and_aliexpress_are_not_active_supplier_searches():
    supplier_flow = read("app/routers/supplier_flow.py").lower()
    suppliers = read("app/routers/suppliers.py").lower()
    hunter = read("app/services/margin_hunter.py").lower()
    shop_spy = read("app/services/shop_spy_sourcing.py").lower()

    assert "amazon_supplier_offers" not in supplier_flow
    assert "aliexpress" not in supplier_flow
    assert "amazon_supplier_offers" not in hunter
    assert "aliexpress" not in hunter
    assert "aliexpress" not in shop_spy
    assert 'pattern="^cj$"' in suppliers


def test_retired_marketplace_supplier_endpoints_return_gone():
    with TestClient(app) as client:
        for provider in ("amazon", "aliexpress"):
            response = client.post(
                "/api/supplier-flow/add",
                json={
                    "provider": provider,
                    "supplier_sku": "OLD-1",
                    "name": "Legacy marketplace product",
                    "price": 5.0,
                    "currency": "USD",
                },
            )
            assert response.status_code == 410


def test_source_search_schema_allows_only_cj():
    with TestClient(app) as client:
        amazon = client.get("/api/suppliers/source-search", params={"provider": "amazon", "q": "fan"})
        ali = client.get("/api/suppliers/source-search", params={"provider": "aliexpress", "q": "fan"})
    assert amazon.status_code == 422
    assert ali.status_code == 422


def test_dormant_marketplace_code_is_not_loaded_by_application_shell():
    main = read("app/main.py").lower()
    worker = read("app/static/service-worker.js").lower()
    workflow = read("app/static/workflow_cleanup.js").lower()

    assert "aliexpress_dropship_search" not in main
    assert "marketplace_supplier_sources" not in main
    assert "amazon" not in worker
    assert "aliexpress" not in worker
    assert "cj dropshipping" in workflow
    assert "ebay us" in workflow
