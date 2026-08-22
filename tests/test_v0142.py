import inspect
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app
from app.services.connections import AmazonRadarClient


ROOT = Path(__file__).resolve().parents[1]


def test_legacy_amazon_client_remains_read_only_if_reused_later():
    source = inspect.getsource(AmazonRadarClient)
    assert "client.get(" in source
    assert "client.post(self.token_url" in source  # OAuth token exchange only.
    for forbidden in ("client.put(", "client.patch(", "client.delete(", "/orders", "/feeds", "/listings"):
        assert forbidden not in source


def test_amazon_is_not_part_of_active_radar_anymore():
    router = (ROOT / "app/routers/radar.py").read_text(encoding="utf-8")
    assert "analyze_amazon_market" not in router
    assert "amazon_supplier_offers" not in router
    assert 'analyze_ebay_market(keyword, "EBAY_US")' in router


def test_radar_sources_expose_only_ebay_and_cj():
    response = TestClient(app).get("/api/radar/sources")
    assert response.status_code == 200
    assert {row["id"] for row in response.json()} <= {"ebay", "cj"}


def test_amazon_cards_are_retired_from_runtime_interface():
    cleanup = (ROOT / "app/static/provider_cleanup.js").read_text(encoding="utf-8").lower()
    workflow = (ROOT / "app/static/workflow_cleanup.js").read_text(encoding="utf-8")
    assert "amazon" in cleanup
    assert "eBay US" in workflow
    assert "CJ Dropshipping" in workflow
