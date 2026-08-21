from __future__ import annotations

import hashlib
import hmac
import os
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

from app.services.connections import AmazonRadarClient, connection_status
from app.services.opportunity_store import _days_from_text, _match_strength, _safe_float


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
        self.app_key = os.getenv("ALIEXPRESS_APP_KEY", "").strip()
        self.app_secret = os.getenv("ALIEXPRESS_APP_SECRET", "").strip()
        self.tracking_id = os.getenv("ALIEXPRESS_TRACKING_ID", "").strip()

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
            raise RuntimeError("ALIEXPRESS_APP_KEY et ALIEXPRESS_APP_SECRET ne sont pas configurés")
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


async def aliexpress_supplier_offers(keyword: str) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    client = AliExpressSupplierClient()
    if not client.configured:
        return [], []
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
    client = AliExpressSupplierClient()
    return {
        "id": "aliexpress",
        "name": "AliExpress",
        "kind": "Marketplace fournisseur",
        "connected": client.configured,
        "configured": client.configured,
        "status": "Configuré" if client.configured else "Clés API à ajouter",
        "catalog": True,
        "available_in_products": client.configured,
        "url": "https://open.aliexpress.com/",
        "note": "Recherche produit AliExpress vers la France. Stock et frais de livraison restent à confirmer avant validation de marge.",
    }
