import asyncio
import inspect
from pathlib import Path

import pytest

from app.services.cj import CJClient, CJError


ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_cj_freight_default_destination_is_us_and_non_us_is_blocked(monkeypatch):
    signature = inspect.signature(CJClient.freight_options)
    assert signature.parameters["destination_country"].default == "US"

    client = CJClient()
    with pytest.raises(CJError, match="États-Unis"):
        client._require_us_destination("FR")
    with pytest.raises(CJError, match="États-Unis"):
        client._require_us_destination("CA")

    captured = {}

    async def fake_request(method, path, *, params=None, json_body=None):
        captured.update({"method": method, "path": path, "body": json_body})
        return {"data": []}

    monkeypatch.setattr(client, "request", fake_request)
    asyncio.run(client.freight_options("VID-US-1", start_country="CN"))
    assert captured["path"] == "/logistic/freightCalculate"
    assert captured["body"]["endCountryCode"] == "US"
    assert captured["body"]["startCountryCode"] == "CN"


def test_active_cj_pricing_has_no_eur_conversion_path():
    cj = read("app/services/cj.py")
    landed = read("app/services/cj_landed.py")
    assert "usd_to_eur" not in cj
    assert 'destination_country: str = "FR"' not in cj
    assert 'destination_country: str = "US"' in cj
    assert 'destination_country: str = "US"' in landed
    assert '"currency": "USD"' in landed


def test_dashboard_is_physically_us_only_not_runtime_hidden():
    dashboard = read("app/templates/dashboard.html")
    forbidden = (
        "EBAY_FR", "AMAZON_FR", "AMAZON_US", "TikTok", "YouTube",
        "Fabricants", "demandes de prix", "RFQ", ">France<",
    )
    assert all(value not in dashboard for value in forbidden)
    assert "Radar eBay US" in dashboard
    assert "CJ Dropshipping" in dashboard
    assert "Destination verrouillée : United States" in dashboard
    assert "Aucun produit validé" in dashboard
    assert "Lancer une analyse Radar" in dashboard


def test_main_loads_only_the_new_guided_frontend():
    main = read("app/main.py")
    dashboard = read("app/templates/dashboard.html")
    assert 'VERSION = "0.24.0"' in main
    assert "simple_ui.js" in dashboard
    assert "simple_ui.css" in dashboard
    for retired in (
        "provider_cleanup.js", "workflow_cleanup.js", "product_research.js",
        "supplier_flow_v2.js", "margin_hunter.js", "shop_spy.js", "catalog_sync.js",
    ):
        assert retired not in main
        assert retired not in dashboard


def test_pwa_caches_only_active_v024_frontend_assets():
    worker = read("app/static/service-worker.js")
    assert "opsbot-v0.24.0-shell" in worker
    assert "/static/simple_ui.css?v=0.24.0" in worker
    assert "/static/simple_ui.js?v=0.24.0" in worker
    for retired in (
        "provider_cleanup.js", "workflow_cleanup.js", "product_research.js",
        "supplier_flow_v2.js", "margin_hunter.js", "shop_spy.js", "catalog_sync.js",
    ):
        assert retired not in worker


def test_ui_status_exposes_market_currency_and_destination_guardrail():
    ui = read("app/routers/ui.py")
    main = read("app/main.py")
    assert 'VERSION = "0.24.0"' in ui
    assert '"marketplace": "EBAY_US"' in ui
    assert '"currency": "USD"' in ui
    assert '"destination_country": "US"' in ui
    assert '"destination_country": "US"' in main
