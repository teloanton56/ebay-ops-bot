import asyncio
import base64
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi import HTTPException

from app.services import analyzer
from app.services.cj_landed import resolve_cj_landed_offer
from app.services.compliance import assess_compliance
from app.services.ebay_compliance import verify_notification_signature
from app.services.research import summarize_market


ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def _market_items(count: int = 10, price: float = 19.99) -> list[dict]:
    return [
        {
            "price": {"value": str(price), "currency": "EUR"},
            "seller": {"username": f"seller-{index % 5}"},
        }
        for index in range(count)
    ]


def test_automatic_score_no_longer_rewards_extreme_competition():
    product = {
        "supplier_cost": 4.0,
        "shipping_cost": 2.0,
        "target_price": 19.99,
        "stock": 20,
        "shipping_days": 4,
    }
    items = _market_items()
    workable = summarize_market(items, product, total_results=100)
    saturated = summarize_market(items, product, total_results=6000)

    assert workable["competition_points"] == 25.0
    assert saturated["competition_points"] == 2.0
    assert workable["opportunity_score"] > saturated["opportunity_score"]
    assert "Davantage d'annonces concurrentes ne rapporte jamais davantage de points" in workable["note"]


def test_auto_analysis_preserves_operator_target_price(monkeypatch):
    state = {
        "id": 1,
        "title": "Drawer organizer",
        "supplier_sku": "CJ-1",
        "supplier_cost": 4.0,
        "shipping_cost": 2.0,
        "target_price": 24.99,
        "suggested_price": 24.99,
        "opportunity_score": None,
        "stock": 20,
        "shipping_days": 4,
        "marketplace_id": "EBAY_FR",
        "category_id": "123",
        "product_status": "À tester",
        "currency": "EUR",
    }

    class FakeClient:
        def token_status(self):
            return {"connected": True}

        async def search_items(self, *args, **kwargs):
            return {"total": 250, "itemSummaries": _market_items()}

    def fake_set(product_id, **fields):
        assert product_id == 1
        state.update(fields)
        return True

    monkeypatch.setattr(analyzer, "get_settings", lambda: SimpleNamespace(
        ebay_effective_env="production",
        ebay_client_id="client",
        ebay_client_secret="secret",
    ))
    monkeypatch.setattr(analyzer, "EbayClient", FakeClient)
    monkeypatch.setattr(analyzer, "list_products", lambda: [dict(state)])
    monkeypatch.setattr(analyzer, "get_product", lambda product_id: dict(state))
    monkeypatch.setattr(analyzer, "set_product_fields", fake_set)
    monkeypatch.setattr(analyzer, "start_analysis_run", lambda *args: 1)
    monkeypatch.setattr(analyzer, "save_analysis_result", lambda *args, **kwargs: None)
    monkeypatch.setattr(analyzer, "finish_analysis_run", lambda *args, **kwargs: None)
    monkeypatch.setattr(analyzer, "add_alert", lambda *args, **kwargs: None)
    monkeypatch.setattr(analyzer, "summarize_market", lambda *args, **kwargs: {
        "opportunity_score": 65.0,
        "suggested_price": 14.99,
    })
    monkeypatch.setattr(analyzer, "assess_product", lambda product: {
        "pass": True,
        "blocks": [],
        "profit": {"margin_percent": 25.0, "estimated_profit": 5.0},
    })

    asyncio.run(analyzer.analyze_catalog())

    assert state["target_price"] == 24.99
    assert state["suggested_price"] == 14.99
    assert state["opportunity_score"] == 65.0


def test_unified_cj_resolver_prefers_fast_eu_freight_within_limit():
    class FakeCJ:
        def __init__(self):
            self.freight_calls = []

        async def product_detail(self, pid):
            assert pid == "pid-1"
            return {
                "pid": pid,
                "name": "Drawer organizer",
                "image_url": "https://example.test/product.jpg",
                "risk_flags": [],
                "variants": [{
                    "vid": "variant-1",
                    "sku": "SKU-1",
                    "name": "Black",
                    "price_usd": 5.0,
                    "stock": 20,
                    "inventories": [
                        {"country_code": "CN", "stock": 20},
                        {"country_code": "DE", "stock": 8},
                    ],
                }],
            }

        async def freight_options(self, vid, *, start_country, destination_country):
            self.freight_calls.append((vid, start_country, destination_country))
            return [
                {"name": "Slow", "price_usd": 1.0, "delivery_days": "12-15 Days"},
                {"name": "Fast EU", "price_usd": 3.0, "delivery_days": "4-6 Days"},
            ]

    client = FakeCJ()
    landed = asyncio.run(resolve_cj_landed_offer(
        client,
        "pid-1",
        exchange_rate=0.9,
        max_shipping_days=7,
    ))

    assert client.freight_calls == [("variant-1", "DE", "FR")]
    assert landed["warehouse"] == "DE"
    assert landed["freight_name"] == "Fast EU"
    assert landed["shipping_days"] == 6
    assert landed["supplier_cost"] == 4.5
    assert landed["shipping_cost"] == 2.7
    assert landed["landed_cost"] == 7.2

    hunter = read("app/services/margin_hunter.py")
    flow = read("app/routers/supplier_flow.py")
    refresh = read("app/services/supplier_refresh.py")
    assert "resolve_cj_landed_offer" in hunter
    assert "resolve_cj_landed_offer" in flow
    assert "resolve_cj_landed_offer" in refresh


def test_compliance_engine_blocks_risky_products_and_retail_marketplace_fulfillment():
    generic = {
        "title": "Drawer organizer kitchen storage",
        "description": "Plastic organizer",
        "aspects": {},
        "supplier_sku": "GEN-1",
    }
    generic_assessment = assess_compliance(generic)
    assert generic_assessment["pass"] is True
    assert generic_assessment["publication_pass"] is True

    spy_camera = assess_compliance({
        **generic,
        "title": "Mini spy camera surveillance hidden camera",
    })
    assert spy_camera["pass"] is False
    assert any("surveillance" in block.lower() or "vie privée" in block.lower() for block in spy_camera["blocks"])

    counterfeit = assess_compliance({
        **generic,
        "title": "Fake Nike replica shoes",
    })
    assert counterfeit["pass"] is False
    assert any("contrefaçon" in block.lower() for block in counterfeit["blocks"])

    amazon = assess_compliance(generic, {"provider_code": "amazon", "name": "Amazon France"})
    assert amazon["pass"] is True
    assert amazon["publication_pass"] is False
    assert any("publication directe bloquée" in block.lower() for block in amazon["publication_blocks"])


def test_ebay_notification_signature_is_cryptographically_verified():
    private_key = ec.generate_private_key(ec.SECP256R1())
    public_pem = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode("ascii")
    payload = {
        "metadata": {"topic": "MARKETPLACE_ACCOUNT_DELETION"},
        "notification": {"notificationId": "signed-123", "data": {"username": "buyer"}},
    }
    message = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    signature = private_key.sign(message, ec.ECDSA(hashes.SHA1()))
    signature_payload = {
        "kid": "test-key-1",
        "signature": base64.b64encode(signature).decode("ascii"),
    }
    header = base64.b64encode(json.dumps(signature_payload).encode("ascii")).decode("ascii")

    async def loader(kid):
        assert kid == "test-key-1"
        return {"key": public_pem, "digest": "SHA1", "algorithm": "ECDSA"}

    assert asyncio.run(verify_notification_signature(payload, header, key_loader=loader)) is True
    tampered = {
        **payload,
        "notification": {"notificationId": "tampered", "data": {"username": "buyer"}},
    }
    assert asyncio.run(verify_notification_signature(tampered, header, key_loader=loader)) is False

    config_source = read("app/config.py")
    assert "elmHFtX9v7eY3YdBkJO5vY_fARVpx8Dw6S6ib-1d98Ar-p_e" not in config_source
    assert 'EBAY_ACCOUNT_DELETION_VERIFICATION_TOKEN", ""' in config_source


def test_ebay_write_revalidates_supplier_before_risk(monkeypatch):
    from app.routers import ebay as ebay_router

    product = {
        "id": 7,
        "title": "Safe product",
        "supplier_sku": "CJ-SAFE",
        "supplier_cost": 4.0,
        "shipping_cost": 2.0,
        "stock": 20,
        "shipping_days": 4,
        "target_price": 19.99,
        "category_id": "123",
        "images": ["https://example.test/image.jpg"],
        "aspects": {"Type": ["Organizer"]},
        "currency": "EUR",
    }
    calls = []

    async def refresh(current):
        calls.append("supplier")
        return {**current, "stock": 0}, {"provider": "cj", "verified": True, "stock": 0}

    def risk(current):
        calls.append("risk")
        return {
            "pass": False,
            "blocks": ["Stock 0 < minimum 3"],
            "warnings": [],
            "profit": {},
            "compliance": {"publication_blocks": []},
        }

    monkeypatch.setattr(ebay_router, "get_product", lambda product_id: dict(product))
    monkeypatch.setattr(ebay_router, "refresh_product_from_supplier", refresh)
    monkeypatch.setattr(ebay_router, "assess_product", risk)

    with pytest.raises(HTTPException) as exc:
        asyncio.run(ebay_router._revalidate_for_ebay(7, actual_write=True))

    assert exc.value.status_code == 409
    assert calls == ["supplier", "risk"]

    source = read("app/routers/ebay.py")
    publish_section = source.split('async def publish_listing', 1)[1].split('@router.post("/listings/{product_id}/sync")', 1)[0]
    assert "_revalidate_for_ebay" in publish_section
    assert publish_section.index("update_live_offer_price_quantity") < publish_section.index("publish_offer")
