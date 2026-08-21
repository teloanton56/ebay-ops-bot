from __future__ import annotations

import hashlib
import hmac
import json
import os
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

from app.services.connections import AmazonRadarClient, connection_status
from app.services.crypto import decrypt, encrypt
from app.services.db import kv_get, kv_set
from app.services.opportunity_store import _days_from_text, _match_strength, _safe_float


ALIEXPRESS_STORAGE_KEY = "integration:aliexpress"
ALIEXPRESS_REQUIRED = ("app_key", "app_secret")


def _aliexpress_env_credentials() -> dict[str, str]:
    mapping = {
        "app_key": "ALIEXPRESS_APP_KEY",
        "app_secret": "ALIEXPRESS_APP_SECRET",
        "tracking_id": "ALIEXPRESS_TRACKING_ID",
    }
    return {field: os.getenv(variable, "").strip() for field, variable in mapping.items()
            if os.getenv(variable, "").strip()}


def load_aliexpress_credentials() -> dict[str, Any]:
    stored = kv_get(ALIEXPRESS_STORAGE_KEY)
    if not stored:
        return _aliexpress_env_credentials()
    try:
        data = json.loads(decrypt(stored) or "{}")
    except (json.JSONDecodeError, RuntimeError) as exc:
        raise RuntimeError("Les identifiants AliExpress ne peuvent pas être déchiffrés") from exc
    if data.get("disabled"):
        return {}
    return {**_aliexpress_env_credentials(), **data}


def save_aliexpress_credentials(values: dict[str, Any]) -> None:
    allowed = {*ALIEXPRESS_REQUIRED, "tracking_id", "verified_at", "last_error"}
    try:
        current = load_aliexpress_credentials()
    except RuntimeError:
        current = _aliexpress_env_credentials()
    current.pop("disabled", None)
    for key, value in values.items():
        if key not in allowed or value is None:
            continue
        text = str(value).strip()
        if key == "last_error":
            current[key] = text
        elif text:
            current[key] = text
    kv_set(ALIEXPRESS_STORAGE_KEY, encrypt(json.dumps(current, ensure_ascii=False)) or "")


def delete_aliexpress_credentials() -> None:
    kv_set(ALIEXPRESS_STORAGE_KEY, encrypt('{"disabled": true}') or '{"disabled": true}')


def _mask(value: str) -> str:
    if not value:
        return ""
    if len(value) < 9:
        return "•" * len(value)
    return value[:4] + "…" + value[-4:]


def aliexpress_connection_status() -> dict[str, Any]:
    recovery_required = False
    try:
        data = load_aliexpress_credentials()
    except RuntimeError:
        data = {}
        recovery_required = True
    configured = all(data.get(field) for field in ALIEXPRESS_REQUIRED)
    connected = configured and bool(data.get("verified_at")) and not data.get("last_error")
    return {
        "id": "aliexpress",
        "name": "AliExpress",
        "kind": "Fournisseur marketplace",
        "configured": configured,
        "connected": connected,
        "ready": connected,
        "status": "Connecté" if connected else "À reconnecter" if recovery_required else "À tester" if configured else "À connecter",
        "note": "Catalogue fournisseur AliExpress : recherche produit, prix, délai et données logistiques disponibles sont normalisés pour le sourcing.",
        "docs_url": "https://open.aliexpress.com/",
        "verified_at": data.get("verified_at"),
        "last_error": "Identifiants AliExpress incompatibles — reconnectez AliExpress" if recovery_required else data.get("last_error", ""),
        "credential_masked": _mask(str(data.get("app_key") or "")),
        "environment": "production",
        "recovery_required": recovery_required,
        "supplier": True,
        "catalog": True,
        "available_in_products": connected,
        "capabilities": {
            "search": True,
            "price": True,
            "stock": "when_available",
            "shipping": "when_available",
            "variants": "when_available",
            "margin_analysis": True,
        },
    }


async def amazon_supplier_offers(keyword: str) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    if not connection_status("amazon").get("connected"):
        return [], []
    try:
        result = await AmazonRadarClient().search_catalog(
            keyword,
            marketplace="AMAZON_FR",
            page_size=10,
            include_pricing=True,
        )
    except Exception as exc:
        return [], [{"source": "Amazon", "message": str(exc)}]

    offers: list[dict[str, Any]] = []
    for product in result.get("products") or []:
        price = _safe_float(product.get("price"))
        offers.append({
            "provider": "Amazon France",
            "provider_code": "amazon",
            "supplier_sku": str(product.get("asin") or ""),
            "variant_id": "",
            "name": product.get("title") or keyword,
            "product_cost": price,
            "shipping_cost": None,
            "currency": product.get("currency") or "EUR",
            "stock": None,
            "shipping_days": None,
            "warehouse": "FR/EU",
            "image_url": product.get("image_url") or "",
            "source_url": product.get("url") or "",
            "reliability_score": 90,
            "compliance_flags": [],
            "evidence": [
                "Produit observé dans le catalogue Amazon France",
                "Prix compétitif Amazon observé" if price is not None else "Prix Amazon non disponible",
                "Stock et livraison doivent être confirmés avant sélection",
            ],
            "shipping_known": False,
            "match_strength": round(_match_strength(keyword, product.get("title") or ""), 2),
            "marketplace_offer_count": product.get("offer_count"),
            "sales_rank": product.get("sales_rank"),
        })
    return offers, []


class AliExpressSupplierClient:
    endpoint = "https://eco.taobao.com/router/rest"

    def __init__(self) -> None:
        credentials = load_aliexpress_credentials()
        self.app_key = str(credentials.get("app_key") or "").strip()
        self.app_secret = str(credentials.get("app_secret") or "").strip()
        self.tracking_id = str(credentials.get("tracking_id") or "").strip()

    @property
    def configured(self) -> bool:
        return bool(self.app_key and self.app_secret)

    def _timestamp(self) -> str:
        return (datetime.now(timezone.utc) + timedelta(hours=8)).strftime("%Y-%m-%d %H:%M:%S")

    def _sign(self, params: dict[str, Any]) -> str:
        raw = "".join(f"{key}{params[key]}" for key in sorted(params) if key != "sign")
        return hmac.new(self.app_secret.encode(), raw.encode(), hashlib.md5).hexdigest().upper()

    async def search(self, keyword: str, page_size: int = 10) -> dict[str, Any]:
        if not self.configured:
            raise RuntimeError("Clé App et secret AliExpress manquants")
        params: dict[str, Any] = {
            "app_key": self.app_key,
            "format": "json",
            "method": "aliexpress.affiliate.product.query",
            "sign_method": "hmac",
            "timestamp": self._timestamp(),
            "v": "2.0",
            "keywords": keyword,
            "page_no": 1,
            "page_size": min(max(int(page_size), 1), 50),
            "target_currency": "EUR",
            "target_language": "FR",
            "ship_to_country": "FR",
            "fields": (
                "product_id,product_title,product_main_image_url,product_detail_url,"
                "sale_price,sale_price_currency,target_sale_price,target_sale_price_currency,"
                "ship_to_days,shop_id,shop_url"
            ),
        }
        if self.tracking_id:
            params["tracking_id"] = self.tracking_id
        params["sign"] = self._sign(params)
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(self.endpoint, data=params)
        if response.is_error:
            raise RuntimeError(f"AliExpress API HTTP {response.status_code}")
        payload = response.json()
        if payload.get("error_response"):
            error = payload["error_response"]
            raise RuntimeError(str(error.get("sub_msg") or error.get("msg") or "AliExpress refuse la recherche"))
        return payload

    @staticmethod
    def products(payload: dict[str, Any]) -> list[dict[str, Any]]:
        root = payload.get("aliexpress_affiliate_product_query_response") or payload
        response = root.get("resp_result") or {}
        result = response.get("result") or {}
        products = (result.get("products") or {}).get("product") or []
        return [row for row in products if isinstance(row, dict)]

    async def test(self) -> dict[str, Any]:
        payload = await self.search("portable fan", page_size=1)
        return {"ok": True, "observed": len(self.products(payload)), "marketplace": "AliExpress"}


async def test_aliexpress_connection() -> dict[str, Any]:
    try:
        result = await AliExpressSupplierClient().test()
    except Exception as exc:
        save_aliexpress_credentials({"last_error": str(exc) or "Connexion refusée", "verified_at": "-"})
        raise
    save_aliexpress_credentials({"verified_at": datetime.now(timezone.utc).isoformat(), "last_error": ""})
    return result


async def aliexpress_supplier_offers(keyword: str) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    if not aliexpress_connection_status().get("connected"):
        return [], []
    client = AliExpressSupplierClient()
    try:
        payload = await client.search(keyword, page_size=10)
    except Exception as exc:
        return [], [{"source": "AliExpress", "message": str(exc)}]

    offers: list[dict[str, Any]] = []
    for product in client.products(payload):
        price = _safe_float(product.get("target_sale_price"))
        if price is None:
            price = _safe_float(product.get("sale_price"))
        currency = product.get("target_sale_price_currency") or product.get("sale_price_currency") or "EUR"
        offers.append({
            "provider": "AliExpress",
            "provider_code": "aliexpress",
            "supplier_sku": str(product.get("product_id") or ""),
            "variant_id": "",
            "name": product.get("product_title") or keyword,
            "product_cost": price,
            "shipping_cost": None,
            "currency": currency,
            "stock": None,
            "shipping_days": _days_from_text(product.get("ship_to_days")),
            "warehouse": "CN/EU selon annonce",
            "image_url": product.get("product_main_image_url") or "",
            "source_url": product.get("product_detail_url") or "",
            "reliability_score": None,
            "compliance_flags": [],
            "evidence": [
                "Produit et prix observés via l'API AliExpress",
                "Délai vers la France observé" if product.get("ship_to_days") else "Délai non fourni",
                "Frais de livraison et stock doivent être confirmés avant sélection",
            ],
            "shipping_known": False,
            "match_strength": round(_match_strength(keyword, product.get("product_title") or ""), 2),
            "shop_id": product.get("shop_id"),
            "shop_url": product.get("shop_url") or "",
        })
    return offers, []


def aliexpress_supplier_status() -> dict[str, Any]:
    status = aliexpress_connection_status()
    return {
        **status,
        "name": "AliExpress",
        "kind": "Fournisseur marketplace",
        "url": status["docs_url"],
        "note": "Catalogue AliExpress intégré au sourcing avec le même schéma fournisseur que CJ : SKU, prix, stock/délai/livraison lorsqu'ils sont disponibles et analyse de marge.",
    }
