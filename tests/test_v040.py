from app.services import db
from app.services.profit import suggest_price
from fastapi.testclient import TestClient
from app.main import app
from app.services.analyzer import analyze_catalog
from app.services.cj import CJClient
from app.services.finance import ebay_series, empty_series, summarize
from app.services.radar import analyze_ebay_market, build_rfq_message, source_statuses
from app.services.connections import (DropXLClient, EtsyClient, GelatoClient, PrintfulClient,
                                      PrintifyClient, TikTokClient, YouTubeClient,
                                      connection_status, connection_statuses, delete_credentials, save_credentials,
                                      scan_connected_sources, test_provider as verify_provider)
import app.services.connections as connections_service
import asyncio
from datetime import datetime, timezone
from pathlib import Path
import re
from html.parser import HTMLParser


def test_supplier_crud_and_product_link():
    db.init_db()
    sid = db.save_supplier({"name": "Test Supplier", "country": "FR"})
    assert db.get_supplier(sid)["name"] == "Test Supplier"
    pid = db.upsert_product({"supplier_sku": "V040-1", "title": "Produit test", "supplier_cost": 5,
                             "shipping_cost": 1, "stock": 10, "shipping_days": 2, "target_price": 19.99,
                             "supplier_id": sid, "product_status": "À tester"})
    assert db.get_product(pid)["supplier_id"] == sid
    assert db.set_product_fields(pid, product_status="Winner", opportunity_score=88)
    assert db.get_product(pid)["product_status"] == "Winner"
    assert db.delete_supplier(sid)
    assert db.get_product(pid)["supplier_id"] is None


def test_price_suggestion_meets_thresholds():
    result = suggest_price({"supplier_cost": 10, "shipping_cost": 2})
    assert result["suggested_price"] >= result["minimum_viable_price"]
    assert result["profit"]["estimated_profit"] >= 3
    assert result["profit"]["margin_percent"] >= 15


def test_prepare_is_dry_run():
    db.init_db()
    client = TestClient(app)
    created = client.post("/api/products", json={"supplier_sku":"PREP-1","title":"Produit prêt","supplier_cost":5,
        "shipping_cost":0,"stock":10,"shipping_days":2,"target_price":25,"images":["https://example.test/a.jpg"],
        "category_id":"1","aspects":{"Marque":["Générique"]}}).json()
    response = client.post(f"/api/products/{created['product']['id']}/prepare-ebay")
    assert response.status_code == 200
    assert response.json()["dry_run"] is True
    assert response.json()["message"].startswith("Brouillon local")


def test_automatic_analysis_is_read_only():
    db.init_db()
    db.upsert_product({"supplier_sku": "AUTO-1", "title": "Produit automatique", "supplier_cost": 8,
                       "shipping_cost": 2, "stock": 12, "shipping_days": 3, "target_price": 24.99,
                       "images": ["https://example.test/a.jpg"], "category_id": "1",
                       "aspects": {"Marque": ["Test"]}})
    result = asyncio.run(analyze_catalog())
    assert result["dry_run"] is True
    assert result["mode"] == "CATALOGUE"
    assert result["market_data"] is False
    assert result["products_analyzed"] >= 1
    product = next(p for p in db.list_products() if p["supplier_sku"] == "AUTO-1")
    assert product["opportunity_score"] is None
    assert product["target_price"] == 24.99
    assert product["product_status"] in {"Winner", "À tester", "Rejeté"}


def test_automation_api_status():
    db.init_db()
    client = TestClient(app)
    status = client.get("/api/automation/status")
    assert status.status_code == 200
    assert status.json()["write_enabled"] is False
    assert status.json()["publish_enabled"] is False


def test_cj_starts_unconfigured_and_read_only():
    db.init_db()
    client = TestClient(app)
    status = client.get("/api/cj/settings")
    assert status.status_code == 200
    assert status.json()["read_only"] is True


def test_cj_search_normalizes_products(monkeypatch):
    async def fake_request(self, method, path, params=None):
        return {"data": {"pageNumber": 1, "totalRecords": 1, "totalPages": 1, "content": [{"productList": [{
            "id": "PID-1", "sku": "CJ-1", "nameEn": "Car organizer", "nowPrice": "8.50",
            "totalVerifiedInventory": 42, "deliveryCycle": "3-5", "listedNum": 12,
            "threeCategoryName": "Car Storage", "hasCECertification": 0
        }]}]}}
    monkeypatch.setattr(CJClient, "request", fake_request)
    result = asyncio.run(CJClient().search_products(keyword="organizer", country_code="FR"))
    assert result["products"][0]["price_usd"] == 8.5
    assert result["products"][0]["stock"] == 42
    assert result["products"][0]["warehouse_country"] == "FR"


def test_cj_candidate_crud():
    db.init_db()
    candidate_id = db.save_cj_candidate({"cj_pid": "PID-TEST", "sku": "CJ-TEST", "name": "Test CJ",
                                         "price_usd": 4.2, "stock": 10})
    assert any(x["id"] == candidate_id for x in db.list_cj_candidates())
    assert db.delete_cj_candidate(candidate_id)


def test_cj_price_range_uses_lowest_price():
    assert CJClient._number("2.34 -- 2.70") == 2.34


def test_v0110_dashboard_is_simplified_and_real_data_only():
    db.init_db()
    response = TestClient(app).get("/")
    assert response.status_code == 200
    assert "CJ Dropshipping" in response.text
    assert "Finance" in response.text
    assert "Radar 360" in response.text
    assert "CENTRE DE CONNEXIONS" in response.text
    assert "Product Finder" not in response.text
    assert "résultats simulés" not in response.text
    assert "v0.14.3" in response.text
    assert "BigBuy" not in response.text
    assert "DropXL / vidaXL" in response.text
    assert "HyperSKU" in response.text
    assert "Commandes bloquées" in response.text
    assert 'data-provider="aliexpress"' not in response.text
    sections = re.findall(r'data-section="([^"]+)"', response.text)
    assert sections == ["overview", "radar", "suppliers", "catalog", "ebay", "support", "finance", "connections", "help", "settings"]


def test_dashboard_has_unique_html_ids():
    html = TestClient(app).get("/").text
    ids = re.findall(r'\bid="([^"]+)"', html)
    assert len(ids) == len(set(ids))


def test_dashboard_html_tags_are_balanced():
    class BalanceParser(HTMLParser):
        void = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta",
                "param", "source", "track", "wbr"}

        def __init__(self):
            super().__init__()
            self.stack = []
            self.errors = []

        def handle_starttag(self, tag, attrs):
            if tag not in self.void:
                self.stack.append(tag)

        def handle_endtag(self, tag):
            if not self.stack or self.stack[-1] != tag:
                self.errors.append((tag, self.stack[-1] if self.stack else None))
            else:
                self.stack.pop()

    parser = BalanceParser()
    parser.feed(TestClient(app).get("/").text)
    assert parser.errors == []
    assert parser.stack == []


def test_local_security_headers_and_cross_site_post_block():
    client = TestClient(app)
    response = client.get("/")
    assert response.headers["x-frame-options"] == "DENY"
    assert "frame-ancestors 'none'" in response.headers["content-security-policy"]
    blocked = client.post("/api/automation/analyze-now", headers={"Origin": "https://malicious.example"})
    assert blocked.status_code == 403


def test_research_never_returns_simulated_market_data():
    response = TestClient(app).get("/api/research/search", params={"q": "portable fan"})
    assert response.status_code == 400
    assert "Aucune donnée simulée" in response.text


def test_v0101_migration_removes_old_demo_market_scores():
    db.init_db()
    product_id = db.upsert_product({"supplier_sku": "OLD-DEMO-SCORE", "title": "Ancien score démo",
                                    "supplier_cost": 5, "shipping_cost": 1, "stock": 9,
                                    "shipping_days": 3, "target_price": 20})
    db.set_product_fields(product_id, opportunity_score=77)
    run_id = db.start_analysis_run("DEMO", 1)
    db.save_analysis_result(run_id, product_id, score=77)
    with db.conn() as connection:
        connection.execute("DELETE FROM app_kv WHERE key='migration:v0101:remove_simulated_market_data'")
    db.init_db()
    assert db.get_product(product_id)["opportunity_score"] is None
    assert all(run["mode"] != "DEMO" for run in db.list_analysis_runs(100))


def test_cj_api_supports_following_pages(monkeypatch):
    captured = {}

    async def fake_request(self, method, path, params=None):
        captured.update(params or {})
        return {"data": {"pageNumber": 2, "totalRecords": 600, "totalPages": 30,
                         "content": [{"productList": [{"id": "PID-21", "nameEn": "Page two",
                                                         "sku": "CJ-21", "sellPrice": "3.50"}]}]}}

    monkeypatch.setattr(CJClient, "request", fake_request)
    result = asyncio.run(CJClient().search_products(keyword="phone", page=2, size=20))
    assert captured["page"] == 2
    assert result["page"] == 2
    assert result["total"] == 600
    assert result["total_pages"] == 30


def test_cj_ui_has_progressive_load_button():
    javascript = Path("app/static/app.js").read_text(encoding="utf-8")
    assert "data-cj-more" in javascript
    assert "Afficher 20 produits de plus" in javascript
    assert "produit(s) affiché(s) sur" in javascript


def test_cj_product_detail_detects_battery(monkeypatch):
    async def fake_request(self, method, path, params=None, json_body=None):
        return {"data": {"pid": "FAN-1", "productNameEn": "Rechargeable USB fan 900mAh",
                         "productSku": "FAN-SKU", "productProEnSet": ["BATTERY"],
                         "packingWeight": "150.00-288.00", "variants": [{
                             "vid": "VID-1", "variantNameEn": "White fan", "variantSku": "FAN-WHITE",
                             "variantSellPrice": 5.88, "variantWeight": 150,
                             "inventories": [{"countryCode": "CN", "totalInventory": 25}]
                         }]}}

    monkeypatch.setattr(CJClient, "request", fake_request)
    detail = asyncio.run(CJClient().product_detail("FAN-1"))
    assert detail["variants"][0]["stock"] == 25
    assert detail["packing_weight_g"] == 150
    assert any(x["code"] == "BATTERY" for x in detail["risk_flags"])


def test_cj_freight_calculation_is_normalized(monkeypatch):
    captured = {}

    async def fake_request(self, method, path, params=None, json_body=None):
        captured.update(json_body or {})
        return {"data": [{"logisticName": "CJPacket", "logisticPrice": 5.81,
                           "logisticAging": "7-11"}]}

    monkeypatch.setattr(CJClient, "request", fake_request)
    rows = asyncio.run(CJClient().freight_options("VID-1", destination_country="FR"))
    assert captured["endCountryCode"] == "FR"
    assert captured["products"][0]["vid"] == "VID-1"
    assert rows[0]["price_usd"] == 5.81


def test_cj_candidate_analysis_stays_dry_run(monkeypatch):
    db.init_db()
    candidate_id = db.save_cj_candidate({"cj_pid": "PID-ANALYZE", "sku": "SKU-A",
                                         "name": "Rechargeable test fan", "price_usd": 5.88,
                                         "stock": 100})

    async def fake_detail(self, pid):
        return {"pid": pid, "risk_flags": [{"code": "BATTERY", "level": "high", "label": "Batterie"}],
                "variants": [{"vid": "VID-A", "name": "White", "sku": "SKU-A-W", "price_usd": 5.88,
                              "weight_g": 150, "inventories": [{"country_code": "CN", "stock": 100}]}]}

    async def fake_freight(self, vid, **kwargs):
        return [{"name": "CJPacket", "price_usd": 5.81, "delivery_days": "7-11"}]

    async def fake_exchange(self):
        return {"rate": 0.86, "date": "2026-08-18", "source": "BCE"}

    monkeypatch.setattr(CJClient, "product_detail", fake_detail)
    monkeypatch.setattr(CJClient, "freight_options", fake_freight)
    monkeypatch.setattr(CJClient, "usd_to_eur", fake_exchange)
    response = TestClient(app).post(f"/api/cj/candidates/{candidate_id}/analyze",
                                    json={"vid": "VID-A", "destination_country": "FR"})
    assert response.status_code == 200
    result = response.json()["candidate"]
    assert result["analysis"]["dry_run"] is True
    assert result["analysis"]["landed_cost_eur"] == 10.06
    assert result["risk_flags"][0]["code"] == "BATTERY"


def test_finance_without_sales_stays_at_zero():
    series = empty_series(30, datetime(2026, 8, 18, tzinfo=timezone.utc))
    result = summarize(series, days=30, target=5_000, source="NO_SALES")
    assert len(result["series"]) == 30
    assert result["totals"]["revenue"] == 0
    assert result["totals"]["net_result"] == 0
    assert result["totals"]["orders"] == 0
    assert [x["amount"] for x in result["milestones"]] == [5000, 10000, 50000, 100000]
    assert result["goal"]["progress_percent"] == 0


def test_finance_ebay_orders_use_catalog_costs():
    now = datetime(2026, 8, 18, 12, tzinfo=timezone.utc)
    orders = [{"creationDate": now.isoformat(), "pricingSummary": {"total": {"value": "40.00"}},
               "lineItems": [{"sku": "FIN-1", "quantity": 2, "lineItemCost": {"value": "20.00"}}]}]
    products = [{"supplier_sku": "FIN-1", "supplier_cost": 5, "shipping_cost": 2}]
    series, completeness = ebay_series(orders, products, 7, now)
    result = summarize(series, days=7, target=5_000,
                       source="EBAY", completeness=completeness)
    assert result["totals"]["revenue"] == 40
    assert result["totals"]["supplier_cost"] == 10
    assert result["totals"]["shipping_cost"] == 4
    assert result["completeness"]["cost_completeness_percent"] == 100


def test_finance_api_returns_zero_without_ebay_sales():
    db.init_db()
    response = TestClient(app).get("/api/finance/summary?days=30&target=10000")
    assert response.status_code == 200
    payload = response.json()
    assert payload["source"] == "NO_SALES"
    assert payload["totals"]["revenue"] == 0
    assert payload["goal"]["amount"] == 10000
    assert "series" in payload


def test_radar_sources_only_show_usable_connectors():
    db.init_db()
    save_credentials("youtube", {"api_key": "stored-key"})
    sources = {source["id"]: source for source in source_statuses()}
    assert set(sources) == {"ebay", "amazon", "cj", "tiktok", "youtube", "etsy", "dropxl",
                            "printful", "printify", "gelato"}
    assert sources["youtube"]["configured"] is True
    assert sources["youtube"]["ready"] is False
    assert sources["tiktok"]["ready"] is False
    delete_credentials("youtube")


def test_radar_watchlist_crud_is_local():
    db.init_db()
    client = TestClient(app)
    created = client.post("/api/radar/watchlist",
                          json={"keyword": "RADAR-WATCH-TEST", "notes": "Mesure réelle uniquement"})
    assert created.status_code == 200
    watch_id = created.json()["id"]
    rows = client.get("/api/radar/watchlist").json()
    assert any(row["id"] == watch_id and row["keyword"] == "RADAR-WATCH-TEST" for row in rows)
    assert client.delete(f"/api/radar/watchlist/{watch_id}").json()["deleted"] is True


def test_radar_scan_refuses_sandbox_instead_of_simulating():
    db.init_db()
    response = TestClient(app).post("/api/radar/scan",
                                    json={"keyword": "portable fan", "marketplaces": ["EBAY_FR"]})
    assert response.status_code == 400
    assert "Production" in response.json()["detail"]
    assert "Sandbox" in response.json()["detail"]


def test_radar_ebay_snapshot_uses_observed_currency_and_sellers(monkeypatch):
    db.init_db()

    async def fake_search(self, query, limit=20, marketplace_id=None, category_id=None):
        assert query == "RADAR-USD-TEST"
        assert marketplace_id == "EBAY_US"
        return {"total": 120, "itemSummaries": [
            {"title": "Fan A", "price": {"value": "12.00", "currency": "USD"},
             "seller": {"username": "seller-one"}},
            {"title": "Fan B", "price": {"value": "18.00", "currency": "USD"},
             "seller": {"username": "seller-one"}},
            {"title": "Fan C", "price": {"value": "not-a-number", "currency": "USD"},
             "seller": {"username": "seller-two"}},
        ]}

    from app.services.ebay import EbayClient
    monkeypatch.setattr(EbayClient, "search_items", fake_search)
    result = asyncio.run(analyze_ebay_market("RADAR-USD-TEST", "EBAY_US"))
    assert result["currency"] == "USD"
    assert result["median_price"] == 15
    assert result["total_results"] == 120
    assert result["sellers_sample"] == 2
    assert result["top_seller"] == "seller-one"
    assert result["conversion_rate"] is None
    assert result["search_volume"] is None


def test_factory_rfq_stays_a_local_draft():
    db.init_db()
    client = TestClient(app)
    factory = client.post("/api/radar/factories", json={
        "company": "Factory Test v090", "source": "Salon", "country": "CN",
        "email": "sales@example.test"
    })
    assert factory.status_code == 200
    factory_id = factory.json()["id"]
    response = client.post("/api/radar/rfqs", json={
        "factory_id": factory_id, "product_query": "Portable fan",
        "quantities": "10, 100", "specifications": "CE documents and EU plug"
    })
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "BROUILLON"
    assert payload["sent"] is False
    assert "MOQ" in payload["message"]
    assert "DDP shipping cost to France" in payload["message"]
    assert "No order is confirmed" in payload["message"]
    assert client.delete(f"/api/radar/factories/{factory_id}").status_code == 200


def test_rfq_template_is_explicitly_non_binding():
    message = build_rfq_message("Example Factory", "Car organizer", "50, 200")
    assert "sample price" in message
    assert "certifications and test reports" in message
    assert "No order is confirmed" in message


def test_connections_endpoint_has_no_pinterest_or_reddit():
    db.init_db()
    payload = TestClient(app).get("/api/connections").json()
    ids = {source["id"] for source in payload["sources"]}
    assert ids == {"amazon", "tiktok", "youtube", "etsy", "dropxl", "printful", "printify", "gelato"}
    assert "Pinterest" not in str(payload)
    assert "Reddit" not in str(payload)
    assert any(row["id"] == "aliexpress" for row in payload["restricted"])
    assert {row["id"] for row in payload["assisted_suppliers"]} == {
        "hypersku", "banggood", "wholesale2b", "alibaba"
    }
    assert payload["dry_run"] is True


def test_connection_is_only_ready_after_real_test(monkeypatch):
    db.init_db()
    delete_credentials("youtube")
    save_credentials("youtube", {"api_key": "youtube-secret-test"})
    before = connection_status("youtube")
    assert before["configured"] is True
    assert before["connected"] is False
    assert "youtube-secret-test" not in str(before)

    async def fake_test(self):
        return {"ok": True, "observed": 1}

    monkeypatch.setattr(YouTubeClient, "test", fake_test)
    asyncio.run(verify_provider("youtube"))
    assert connection_status("youtube")["connected"] is True
    delete_credentials("youtube")


def test_unreadable_credential_does_not_break_sources_and_can_be_replaced(monkeypatch):
    stored = {"integration:youtube": "encrypted-with-an-old-key"}

    monkeypatch.setattr(connections_service, "kv_get", lambda key: stored.get(key))
    monkeypatch.setattr(connections_service, "kv_set", lambda key, value: stored.__setitem__(key, value))
    monkeypatch.setattr(connections_service, "encrypt", lambda value: value)

    def fake_decrypt(value):
        if value == "encrypted-with-an-old-key":
            raise RuntimeError("wrong local key")
        return value

    monkeypatch.setattr(connections_service, "decrypt", fake_decrypt)

    statuses = {row["id"]: row for row in connection_statuses()}
    assert statuses["youtube"]["status"] == "À reconnecter"
    assert statuses["youtube"]["recovery_required"] is True
    assert statuses["etsy"]["status"] == "À connecter"

    save_credentials("youtube", {"api_key": "replacement-key"})
    assert connection_status("youtube")["configured"] is True
    assert connection_status("youtube")["recovery_required"] is False


def test_youtube_scan_normalizes_public_metrics(monkeypatch):
    db.init_db()
    save_credentials("youtube", {"api_key": "youtube-scan-test"})

    async def fake_get(self, path, params):
        if path == "/search":
            return {"pageInfo": {"totalResults": 123}, "items": [
                {"id": {"videoId": "v1"}}, {"id": {"videoId": "v2"}}
            ]}
        return {"items": [
            {"id": "v1", "snippet": {"title": "Fan viral", "channelTitle": "Channel A",
                                         "publishedAt": "2026-08-10", "thumbnails": {}},
             "statistics": {"viewCount": "1000", "likeCount": "50", "commentCount": "4"}},
            {"id": "v2", "snippet": {"title": "Fan test", "channelTitle": "Channel B",
                                         "publishedAt": "2026-08-12", "thumbnails": {}},
             "statistics": {"viewCount": "3000", "likeCount": "100", "commentCount": "9"}},
        ]}

    monkeypatch.setattr(YouTubeClient, "_get", fake_get)
    result = asyncio.run(YouTubeClient().scan("portable fan"))
    assert result["total_results"] == 123
    assert result["metrics"][1]["value"] == 2000
    assert result["items"][0]["title"] == "Fan test"
    delete_credentials("youtube")


def test_multi_source_scan_reports_disconnected_sources(monkeypatch):
    db.init_db()
    delete_credentials("youtube")
    delete_credentials("etsy")
    save_credentials("youtube", {"api_key": "youtube-scan-test",
                                  "verified_at": datetime.now(timezone.utc).isoformat()})

    calls = []

    async def fake_scan(self, keyword, country="FR"):
        calls.append(keyword)
        return {"source": "YouTube", "keyword": keyword, "metrics": [], "items": []}

    monkeypatch.setattr(YouTubeClient, "scan", fake_scan)
    result = asyncio.run(scan_connected_sources("portable fan", ["youtube", "youtube", "etsy"]))
    assert result["results"][0]["source"] == "YouTube"
    assert result["errors"] == [{"source": "etsy", "message": "Source non connectée"}]
    assert calls == ["portable fan"]
    delete_credentials("youtube")


def test_etsy_scan_uses_listings_prices_and_favorites(monkeypatch):
    db.init_db()
    save_credentials("etsy", {"api_key": "etsy-scan-test"})

    async def fake_get(self, path, params):
        return {"count": 80, "results": [
            {"title": "Organizer A", "shop_id": 1, "num_favorers": 5,
             "price": {"amount": 1200, "divisor": 100, "currency_code": "EUR"}, "url": "https://etsy.test/a"},
            {"title": "Organizer B", "shop_id": 2, "num_favorers": 25,
             "price": {"amount": 1800, "divisor": 100, "currency_code": "EUR"}, "url": "https://etsy.test/b"},
        ]}

    monkeypatch.setattr(EtsyClient, "_get", fake_get)
    result = asyncio.run(EtsyClient().scan("organizer"))
    assert result["total_results"] == 80
    assert result["metrics"][1]["value"] == 15
    assert result["items"][0]["favorites"] == 25
    delete_credentials("etsy")


def test_tiktok_scan_uses_official_ad_fields(monkeypatch):
    db.init_db()
    save_credentials("tiktok", {"client_key": "client-test", "client_secret": "secret-test"})

    async def fake_token(self):
        return "test-token"

    class FakeResponse:
        is_error = False

        @staticmethod
        def json():
            return {"data": {"ads": [
                {"ad": {"id": 1, "first_shown_date": "20260801", "last_shown_date": "20260818",
                        "status": "active", "reach": {"unique_users_seen": "11K"}, "videos": [], "image_urls": []},
                 "advertiser": {"business_name": "Brand A"}}
            ]}, "error": {"code": "ok", "message": ""}}

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def post(self, *args, **kwargs):
            return FakeResponse()

    monkeypatch.setattr(TikTokClient, "token", fake_token)
    monkeypatch.setattr("app.services.connections.httpx.AsyncClient", FakeClient)
    result = asyncio.run(TikTokClient().scan("portable fan"))
    assert result["metrics"][0]["value"] == 1
    assert result["metrics"][2]["value"] == 11000
    assert "vente" in result["note"].lower()
    delete_credentials("tiktok")


def test_dropxl_supplier_search_is_read_only_and_bounded(monkeypatch):
    save_credentials("dropxl", {"api_email": "buyer@example.test", "api_token": "dropxl-test",
                                 "environment": "sandbox"})
    calls = []

    async def fake_get(self, path, params=None):
        calls.append((path, params))
        return [{"id": 10, "code": "DX-10", "name": "Portable fan", "category_path": "Home/Fans",
                 "quantity": "8", "price": "12.50"}]

    monkeypatch.setattr(DropXLClient, "_get", fake_get)
    result = asyncio.run(DropXLClient().search("portable fan"))
    assert result["products"][0]["supplier_sku"] == "DX-10"
    assert result["products"][0]["price"] == 12.5
    assert result["products"][0]["stock"] == 8
    assert result["products"][0]["quality_verified"] is False
    assert calls == [("/api_customer/products", {"limit": 500, "offset": 0})]
    delete_credentials("dropxl")


def test_pod_connectors_use_catalogs_without_creating_orders(monkeypatch):
    save_credentials("printful", {"api_key": "printful-test"})
    save_credentials("printify", {"api_key": "printify-test"})
    save_credentials("gelato", {"api_key": "gelato-test"})

    async def fake_printful_get(self, path):
        assert path == "/products"
        return {"result": [{"id": 7, "title": "Ceramic mug", "type_name": "Mug",
                             "image": "https://example.test/mug.jpg", "currency": "EUR"}]}

    async def fake_printify_get(self, path):
        assert path == "/v1/catalog/blueprints.json"
        return [{"id": 8, "title": "Ceramic mug", "description": "POD", "images": []}]

    async def fake_gelato_get(self, path):
        assert path == "/v3/catalogs"
        return [{"catalogUid": "mugs", "title": "Mugs"}]

    monkeypatch.setattr(PrintfulClient, "_get", fake_printful_get)
    monkeypatch.setattr(PrintifyClient, "_get", fake_printify_get)
    monkeypatch.setattr(GelatoClient, "_get", fake_gelato_get)
    assert asyncio.run(PrintfulClient().search("mug"))["products"][0]["provider"] == "PRINTFUL"
    assert asyncio.run(PrintifyClient().search("mug"))["products"][0]["provider"] == "PRINTIFY"
    assert asyncio.run(GelatoClient().search("mug"))["products"][0]["provider"] == "GELATO"
    delete_credentials("printful")
    delete_credentials("printify")
    delete_credentials("gelato")


def test_retired_bigbuy_token_is_removed_by_migration():
    db.kv_set("integration:bigbuy", "retired-secret")
    db.init_db()
    assert db.kv_get("integration:bigbuy") is None
