import asyncio

import pytest

from app.routers import supplier_flow
from app.services.cj import CJClient, CJError
from app.services.cj_landed import resolve_cj_landed_routes


def test_supplier_search_uses_full_cj_page_and_shows_more_results(monkeypatch):
    captured = {}

    class FakeCJ:
        def status(self):
            return {"connected": True}

        async def search_products(self, **kwargs):
            captured.update(kwargs)
            return {
                "total": 500,
                "products": [
                    {
                        "cj_pid": f"PID-{index}",
                        "sku": f"SKU-{index}",
                        "name": f"Electric car accessory {index}",
                        "price_usd": 9.99 + index,
                        "stock": 100 + index,
                        "image_url": "",
                    }
                    for index in range(80)
                ],
            }

    monkeypatch.setattr(supplier_flow, "CJClient", FakeCJ)
    group, errors = asyncio.run(supplier_flow._cj_group("electric car"))

    assert errors == []
    assert captured["size"] == 100
    assert captured["min_stock"] == 0
    assert captured["order_by"] == 0
    assert group["source_total"] == 500
    assert group["sampled"] == 80
    assert len(group["products"]) == 60


def test_search_products_does_not_force_inventory_filter_when_browsing(monkeypatch):
    captured = {}
    client = CJClient()

    async def fake_request(method, path, *, params=None, json_body=None):
        captured.update({"method": method, "path": path, "params": params})
        return {"data": {"pageNumber": 1, "totalRecords": 0, "totalPages": 0, "content": []}}

    monkeypatch.setattr(client, "request", fake_request)
    result = asyncio.run(client.search_products(keyword="electric car", size=100, min_stock=0))

    assert result["products"] == []
    assert captured["path"] == "/product/listV2"
    assert captured["params"]["size"] == 100
    assert "startWarehouseInventory" not in captured["params"]


def test_product_inventory_uses_dedicated_cj_inventory_endpoint(monkeypatch):
    client = CJClient()

    async def fake_request(method, path, *, params=None, json_body=None):
        assert method == "GET"
        assert path == "/product/stock/getInventoryByPid"
        assert params == {"pid": "PID-1"}
        return {
            "data": {
                "inventories": [
                    {"countryCode": "US", "totalInventoryNum": 12, "cjInventoryNum": 12, "factoryInventoryNum": 0},
                    {"countryCode": "CN", "totalInventoryNum": 50, "cjInventoryNum": 10, "factoryInventoryNum": 40},
                ],
                "variantInventories": [
                    {
                        "vid": "VID-1",
                        "inventory": [
                            {
                                "countryCode": "US",
                                "totalInventory": 7,
                                "cjInventory": 7,
                                "factoryInventory": 0,
                                "verifiedWarehouse": 1,
                                "stock": [{"stockId": "US-STORAGE-1", "inventory": 7, "factoryInventory": 0}],
                            }
                        ],
                    }
                ],
            }
        }

    monkeypatch.setattr(client, "request", fake_request)
    snapshot = asyncio.run(client.product_inventory("PID-1"))

    assert snapshot["product_inventories"][0]["country_code"] == "US"
    assert snapshot["product_inventories"][0]["stock"] == 12
    assert snapshot["variant_inventories"]["VID-1"][0]["stock"] == 7
    assert snapshot["variant_inventories"]["VID-1"][0]["storage_ids"] == ["US-STORAGE-1"]


def test_variant_inventory_fallback_requests_enable_inventory(monkeypatch):
    client = CJClient()

    async def fake_request(method, path, *, params=None, json_body=None):
        assert method == "GET"
        assert path == "/product/variant/queryByVid"
        assert params == {"vid": "VID-US", "features": "enable_inventory"}
        return {
            "data": {
                "inventories": [{
                    "countryCode": "US",
                    "totalInventory": 18,
                    "cjInventory": 18,
                    "factoryInventory": 0,
                    "verifiedWarehouse": 1,
                    "stock": [{"stockId": "US-STORE-A", "inventory": 18, "factoryInventory": 0}],
                }]
            }
        }

    monkeypatch.setattr(client, "request", fake_request)
    rows = asyncio.run(client.variant_inventory("VID-US"))

    assert rows[0]["country_code"] == "US"
    assert rows[0]["stock"] == 18
    assert rows[0]["storage_ids"] == ["US-STORE-A"]


def test_zero_dollar_free_shipping_is_not_discarded(monkeypatch):
    client = CJClient()

    async def fake_request(method, path, *, params=None, json_body=None):
        assert path == "/logistic/freightCalculate"
        return {
            "data": [
                {
                    "logisticName": "CJ Free Shipping",
                    "logisticPrice": 0,
                    "logisticAging": "4-6",
                }
            ]
        }

    monkeypatch.setattr(client, "request", fake_request)
    rows = asyncio.run(client.freight_options("VID-FREE", start_country="CN", destination_country="US"))

    assert len(rows) == 1
    assert rows[0]["price_usd"] == 0
    assert rows[0]["delivery_days"] == "4-6"


def test_freight_tip_includes_separate_tax_and_clearance_when_total_is_missing(monkeypatch):
    client = CJClient()
    captured = {}

    async def fake_request(method, path, *, params=None, json_body=None):
        assert method == "POST"
        assert path == "/logistic/freightCalculateTip"
        captured.update(json_body or {})
        return {
            "data": [{
                "arrivalTime": "5-8",
                "wrapPostage": 4.0,
                "taxesFee": 1.0,
                "clearanceOperationFee": 0.5,
                "tariff": 0.25,
                "option": {"enName": "CJPacket"},
            }]
        }

    monkeypatch.setattr(client, "request", fake_request)
    rows = asyncio.run(client.freight_options_tip(
        {
            "vid": "VID-TIP",
            "sku": "SKU-TIP",
            "price_usd": 6.0,
            "weight_g": 200,
            "length_mm": 100,
            "width_mm": 80,
            "height_mm": 50,
        },
        {"logistics_properties": ["COMMON"], "packing_weight_g": 200},
        start_country="CN",
        destination_country="US",
        storage_ids=["CN-STORAGE-1"],
    ))

    assert rows[0]["price_usd"] == 5.75
    assert rows[0]["taxes_usd"] == 1.0
    assert rows[0]["clearance_usd"] == 0.5
    assert rows[0]["tariff_usd"] == 0.25
    req = captured["reqDTOS"][0]
    assert req["storageIdList"] == ["CN-STORAGE-1"]
    assert req["totalGoodsAmount"] == 6.0


def test_route_uses_variant_inventory_fallback_when_pid_inventory_is_only_product_level():
    class FakeCJ:
        def __init__(self):
            self.variant_checks = []

        async def product_detail(self, pid):
            return {
                "pid": pid,
                "name": "US warehouse item",
                "image_url": "",
                "risk_flags": [],
                "variants": [{
                    "vid": "VID-US",
                    "sku": "SKU-US",
                    "name": "US variant",
                    "price_usd": 7.0,
                    "weight_g": 100,
                    "inventories": [],
                }],
            }

        async def product_inventory(self, pid):
            return {
                "pid": pid,
                "product_inventories": [{"country_code": "US", "stock": 18}],
                "variant_inventories": {},
            }

        async def variant_inventory(self, vid):
            self.variant_checks.append(vid)
            return [{"country_code": "US", "stock": 18, "storage_ids": ["US-STORE-A"]}]

        async def freight_options(self, vid, *, start_country, destination_country, storage_ids=None):
            assert start_country == "US"
            assert destination_country == "US"
            assert storage_ids == ["US-STORE-A"]
            return [{"name": "USPS", "price_usd": 2.5, "delivery_days": "3-5"}]

    client = FakeCJ()
    routes = asyncio.run(resolve_cj_landed_routes(client, "PID-US-FALLBACK"))

    assert client.variant_checks == ["VID-US"]
    assert routes["US"]["variant_id"] == "VID-US"
    assert routes["US"]["stock"] == 18
    assert routes["US"]["shipping_cost"] == 2.5


def test_route_tries_another_variant_when_cheapest_has_no_freight():
    class FakeCJ:
        async def product_detail(self, pid):
            return {
                "pid": pid,
                "name": "Electric car light",
                "image_url": "",
                "risk_flags": [],
                "variants": [
                    {
                        "vid": "VID-CHEAP",
                        "sku": "SKU-CHEAP",
                        "name": "Cheap variant",
                        "price_usd": 4.0,
                        "weight_g": 100,
                        "length_mm": 100,
                        "width_mm": 100,
                        "height_mm": 50,
                        "inventories": [{"country_code": "CN", "stock": 30, "storage_ids": []}],
                    },
                    {
                        "vid": "VID-WORKS",
                        "sku": "SKU-WORKS",
                        "name": "Working variant",
                        "price_usd": 5.0,
                        "weight_g": 100,
                        "length_mm": 100,
                        "width_mm": 100,
                        "height_mm": 50,
                        "inventories": [{"country_code": "CN", "stock": 40, "storage_ids": []}],
                    },
                ],
            }

        async def product_inventory(self, pid):
            return {
                "pid": pid,
                "product_inventories": [{"country_code": "CN", "stock": 70}],
                "variant_inventories": {
                    "VID-CHEAP": [{"country_code": "CN", "stock": 30, "storage_ids": []}],
                    "VID-WORKS": [{"country_code": "CN", "stock": 40, "storage_ids": []}],
                },
            }

        async def freight_options(self, vid, *, start_country, destination_country, storage_ids=None):
            if vid == "VID-CHEAP":
                return []
            return [{"name": "CJPacket", "price_usd": 3.0, "delivery_days": "6-9", "source": "freightCalculate"}]

    routes = asyncio.run(resolve_cj_landed_routes(FakeCJ(), "PID-ROUTE"))

    assert "US" not in routes
    assert routes["CN"]["variant_id"] == "VID-WORKS"
    assert routes["CN"]["shipping_cost"] == 3.0
    assert routes["CN"]["landed_cost"] == 8.0


def test_route_failure_exposes_us_and_cn_diagnostics():
    class EmptyCJ:
        async def product_detail(self, pid):
            return {
                "pid": pid,
                "name": "No stock item",
                "risk_flags": [],
                "variants": [{"vid": "VID-0", "sku": "SKU-0", "price_usd": 2.0, "inventories": []}],
            }

        async def product_inventory(self, pid):
            return {"pid": pid, "product_inventories": [], "variant_inventories": {}}

    with pytest.raises(CJError) as exc_info:
        asyncio.run(resolve_cj_landed_routes(EmptyCJ(), "PID-EMPTY"))

    message = str(exc_info.value)
    assert "Détail" in message
    assert "US:" in message
    assert "CN:" in message
