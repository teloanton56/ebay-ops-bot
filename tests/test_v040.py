import asyncio
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app
from app.services import db
from app.services.cj import CJClient
from app.services.cj_landed import save_cj_product_link
from app.services.finance import ebay_series, empty_series, summarize
from app.services.profit import suggest_price
from app.services.radar import source_statuses

ROOT = Path(__file__).resolve().parents[1]


def test_supplier_crud_still_preserves_historical_data():
    db.init_db()
    sid = db.save_supplier({"name": "Historical Supplier", "country": "FR"})
    assert db.get_supplier(sid)["name"] == "Historical Supplier"
    assert db.delete_supplier(sid)


def test_us_price_suggestion_meets_current_default_thresholds():
    result = suggest_price({"supplier_cost": 10, "shipping_cost": 2})
    assert result["currency"] == "USD"
    assert result["suggested_price"] >= result["minimum_viable_price"]
    assert result["profit"]["estimated_profit"] >= 5
    assert result["profit"]["margin_percent"] >= 20


def test_automation_api_reports_us_cj_mode():
    with TestClient(app) as client:
        status = client.get("/api/automation/status")
    data = status.json()
    assert data["marketplace"] == "EBAY_US"
    assert data["currency"] == "USD"
    assert data["supplier"] == "CJ"


def test_cj_settings_expose_us_first_mode():
    with TestClient(app) as client:
        status = client.get("/api/cj/settings")
    assert status.json()["operating_mode"] == "US_FIRST_CN_FALLBACK"
    assert status.json()["currency"] == "USD"


def test_cj_search_can_filter_us_or_cn_only(monkeypatch):
    captured = {}
    async def fake_request(self, method, path, *, params=None, json_body=None):
        captured.update(params or {})
        return {"data": {"pageNumber": 1, "totalRecords": 1, "totalPages": 1, "content": [{"productList": [{"id": "PID-1", "sku": "CJ-1", "nameEn": "Car organizer", "nowPrice": "8.50", "totalVerifiedInventory": 42, "deliveryCycle": "3-5", "listedNum": 12, "threeCategoryName": "Car Storage", "hasCECertification": 0}]}]}}
    monkeypatch.setattr(CJClient, "request", fake_request)
    result = asyncio.run(CJClient().search_products(keyword="organizer", country_code="US"))
    assert captured["countryCode"] == "US"
    assert result["products"][0]["price_usd"] == 8.5
    assert result["products"][0]["warehouse_country"] == "US"


def test_cj_product_detail_still_detects_battery(monkeypatch):
    async def fake_request(self, method, path, *, params=None, json_body=None):
        return {"data": {"pid": "FAN-1", "productNameEn": "Rechargeable USB fan 900mAh", "productSku": "FAN-SKU", "productProEnSet": ["BATTERY"], "packingWeight": "150.00-288.00", "variants": [{"vid": "VID-1", "variantNameEn": "White fan", "variantSku": "FAN-WHITE", "variantSellPrice": 5.88, "variantWeight": 150, "inventories": [{"countryCode": "US", "totalInventory": 25}]}]}}
    monkeypatch.setattr(CJClient, "request", fake_request)
    detail = asyncio.run(CJClient().product_detail("FAN-1"))
    assert detail["variants"][0]["stock"] == 25
    assert detail["packing_weight_g"] == 150
    assert any(flag["code"] == "BATTERY" for flag in detail["risk_flags"])


def test_cj_freight_calculation_targets_us_when_requested(monkeypatch):
    captured = {}
    async def fake_request(self, method, path, *, params=None, json_body=None):
        captured.update(json_body or {})
        return {"data": [{"logisticName": "USPS", "logisticPrice": 5.81, "logisticAging": "3-5"}]}
    monkeypatch.setattr(CJClient, "request", fake_request)
    rows = asyncio.run(CJClient().freight_options("VID-1", start_country="US", destination_country="US"))
    assert captured["startCountryCode"] == "US"
    assert captured["endCountryCode"] == "US"
    assert rows[0]["price_usd"] == 5.81


def test_dashboard_has_unique_ids_and_balanced_tags():
    html = TestClient(app).get("/").text
    import re
    ids = re.findall(r'\bid="([^"]+)"', html)
    assert len(ids) == len(set(ids))
    class BalanceParser(HTMLParser):
        void = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}
        def __init__(self): super().__init__(); self.stack = []; self.errors = []
        def handle_starttag(self, tag, attrs):
            if tag not in self.void: self.stack.append(tag)
        def handle_endtag(self, tag):
            if not self.stack or self.stack[-1] != tag: self.errors.append((tag, self.stack[-1] if self.stack else None))
            else: self.stack.pop()
    parser = BalanceParser(); parser.feed(html)
    assert parser.errors == []
    assert parser.stack == []


def test_local_security_headers_and_cross_site_post_block():
    client = TestClient(app)
    response = client.get("/")
    assert response.headers["x-frame-options"] == "DENY"
    assert "frame-ancestors 'none'" in response.headers["content-security-policy"]
    blocked = client.post("/api/automation/analyze-now", headers={"Origin": "https://malicious.example"})
    assert blocked.status_code == 403


def test_finance_without_sales_stays_zero_and_usd():
    series = empty_series(30, datetime(2026, 8, 18, tzinfo=timezone.utc))
    result = summarize(series, days=30, target=5_000, source="NO_SALES")
    assert result["currency"] == "USD"
    assert result["marketplace"] == "EBAY_US"
    assert result["totals"]["revenue"] == 0
    assert result["totals"]["net_result"] == 0


def test_finance_uses_active_us_catalog_costs():
    now = datetime(2026, 8, 18, 12, tzinfo=timezone.utc)
    orders = [{"creationDate": now.isoformat(), "pricingSummary": {"total": {"value": "40.00", "currency": "USD"}}, "lineItems": [{"sku": "FIN-US-1", "quantity": 2, "lineItemCost": {"value": "20.00"}}]}]
    supplier_id = db.ensure_provider_supplier("cj", "CJ Dropshipping", "US")
    products = [{
        "supplier_sku": "FIN-US-1",
        "supplier_cost": 5,
        "shipping_cost": 2,
        "marketplace_id": "EBAY_US",
        "currency": "USD",
        "supplier_id": supplier_id,
    }]
    save_cj_product_link("FIN-US-1", {
        "pid": "PID-FIN-US-1",
        "variant_id": "VID-FIN-US-1",
        "warehouse": "US",
        "destination_country": "US",
        "currency": "USD",
    })
    series, completeness = ebay_series(orders, products, 7, now)
    result = summarize(series, days=7, target=5_000, source="EBAY_US", completeness=completeness)
    assert result["totals"]["revenue"] == 40
    assert result["totals"]["supplier_cost"] == 10
    assert result["totals"]["shipping_cost"] == 4
    assert result["currency"] == "USD"


def test_source_statuses_are_limited_to_ebay_and_cj():
    statuses = source_statuses()
    assert [row["id"] for row in statuses] == ["ebay", "cj"]


def test_active_shell_identifies_current_us_cj_mode():
    html = TestClient(app).get("/").text
    main = (ROOT / "app/main.py").read_text(encoding="utf-8")
    version = main.split('VERSION = "', 1)[1].split('"', 1)[0]
    assert app.version == version
    assert "eBay US" in html
    assert "CJ Dropshipping" in html
    assert "EBAY_US_CJ_ONLY" in main
    assert "destination_country" in main
