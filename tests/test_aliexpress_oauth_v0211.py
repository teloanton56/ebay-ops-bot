from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app


ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_aliexpress_oauth_routes_are_retired_in_v023():
    with TestClient(app) as client:
        authorize = client.get("/api/connections/aliexpress/authorize")
        callback = client.get("/api/connections/aliexpress/callback")
        save = client.post("/api/connections/aliexpress", json={"app_key": "old", "app_secret": "old"})
        test = client.post("/api/connections/aliexpress/test")

    assert authorize.status_code == 410
    assert callback.status_code == 410
    assert save.status_code == 410
    assert test.status_code == 410
    assert "désactivé" in authorize.json()["detail"].lower()


def test_aliexpress_is_not_loaded_by_active_supplier_or_market_flows():
    flow = read("app/routers/supplier_flow.py").lower()
    hunter = read("app/services/margin_hunter.py").lower()
    spy = read("app/services/shop_spy_sourcing.py").lower()
    main = read("app/main.py").lower()
    worker = read("app/static/service-worker.js").lower()

    assert "aliexpress" not in flow
    assert "aliexpress" not in hunter
    assert "aliexpress" not in spy
    assert "aliexpress_dropship_search" not in main
    assert "aliexpress" not in worker


def test_cleanup_keeps_aliexpress_explicitly_retired_from_visible_ui():
    cleanup = read("app/static/provider_cleanup.js").lower()
    connections = read("app/routers/connections.py").lower()
    assert "aliexpress" in cleanup
    assert '"aliexpress"' in connections
    assert "retired" in connections.lower()
