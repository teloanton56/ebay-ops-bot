from __future__ import annotations

import hashlib
import hmac
import time
from typing import Any

import httpx

from app.services.marketplace_supplier_sources import (
    aliexpress_connection_status,
    load_aliexpress_credentials,
)
from app.services.opportunity_store import _safe_float
from app.services.supplier_relevance import rank_supplier_results


ALIEXPRESS_SYNC_ENDPOINT = "https://api-sg.aliexpress.com/sync"
ALIEXPRESS_TEXT_SEARCH_METHOD = "aliexpress.ds.text.search"


def _absolute_url(value: Any) -> str:
    text = str(value or "").strip()
    if text.startswith("//"):
        return "https:" + text
    return text


def _safe_rating(value: Any) -> float | None:
    try:
        rating = float(str(value).strip().replace("%", ""))
    except (TypeError, ValueError):
        return None
    if rating <= 5:
        return round(rating, 2)
    return round(rating / 20, 2)


class AliExpressDropshipSearchClient:
    def __init__(self) -> None:
        credentials = load_aliexpress_credentials()
        self.app_key = str(credentials.get("app_key") or "").strip()
        self.app_secret = str(credentials.get("app_secret") or "").strip()
        self.access_token = str(credentials.get("access_token") or "").strip()

    @property
    def ready(self) -> bool:
        return bool(self.app_key and self.app_secret and self.access_token)

    def _sign(self, params: dict[str, Any]) -> str:
        raw = "".join(f"{key}{params[key]}" for key in sorted(params) if key != "sign")
        return hmac.new(
            self.app_secret.encode("utf-8"),
            raw.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest().upper()

    async def _call(self, method: str, business_params: dict[str, Any]) -> dict[str, Any]:
        if not self.ready:
            raise RuntimeError("Autorisation AliExpress Drop Shipping incomplète")

        params: dict[str, Any] = {
            "app_key": self.app_key,
            "format": "json",
            "method": method,
            "session": self.access_token,
            "sign_method": "sha256",
            "timestamp": str(int(time.time() * 1000)),
            "v": "2.0",
            **business_params,
        }
        params["sign"] = self._sign(params)

        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.get(ALIEXPRESS_SYNC_ENDPOINT, params=params)
        if response.is_error:
            raise RuntimeError(f"AliExpress API HTTP {response.status_code}")
        try:
            payload = response.json()
        except Exception as exc:
            raise RuntimeError("Réponse AliExpress illisible") from exc

        error = payload.get("error_response") or {}
        if error:
            message = error.get("sub_msg") or error.get("msg") or error.get("message") or "AliExpress refuse la requête"
            raise RuntimeError(str(message))
        return payload

    async def search(self, keyword: str, page_size: int = 20) -> list[dict[str, Any]]:
        # Do not force salesDesc here: the supplier screen needs lexical relevance
        # first. Sales volume remains available as evidence after relevant matches
        # have been selected locally.
        payload = await self._call(ALIEXPRESS_TEXT_SEARCH_METHOD, {
            "keyword": keyword,
            "countryCode": "FR",
            "currency": "EUR",
            "local": "fr_FR",
            "page_size": str(min(max(int(page_size), 1), 50)),
            "page_index": "1",
        })
        root = payload.get("aliexpress_ds_text_search_response") or {}
        code = str(root.get("code") or "00")
        if code not in {"00", "0", "200"}:
            raise RuntimeError(str(root.get("message") or root.get("msg") or f"Recherche AliExpress refusée ({code})"))
        data = root.get("data") or {}
        products = (data.get("products") or {}).get("selection_search_product") or []
        if isinstance(products, dict):
            products = [products]
        return [row for row in products if isinstance(row, dict)]


async def aliexpress_dropship_supplier_offers(keyword: str) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    if not aliexpress_connection_status().get("connected"):
        return [], []

    client = AliExpressDropshipSearchClient()
    try:
        products = await client.search(keyword, page_size=50)
    except Exception as exc:
        return [], [{"source": "AliExpress", "message": str(exc)}]

    relevant_products, rejected = rank_supplier_results(
        keyword,
        products,
        title_keys=("title",),
        limit=20,
    )
    if not relevant_products:
        suffix = f" ({len(products)} résultat(s) hors sujet ignoré(s))" if products else ""
        return [], [{
            "source": "AliExpress",
            "message": f"Aucun produit pertinent trouvé pour « {keyword} »{suffix}",
        }]

    offers: list[dict[str, Any]] = []
    for product in relevant_products:
        title = str(product.get("title") or keyword)
        price = _safe_float(product.get("targetSalePrice"))
        currency = str(product.get("targetOriginalPriceCurrency") or product.get("currency") or "EUR")
        rating = _safe_rating(product.get("score") or product.get("evaluateRate"))
        orders = product.get("orders")
        evidence = [
            f"Pertinence recherche : {float(product.get('match_strength') or 0) * 100:.0f}%",
            "Produit observé via l'API AliExpress Drop Shipping",
        ]
        if orders not in (None, ""):
            evidence.append(f"Volume affiché AliExpress : {orders}")
        if rating is not None:
            evidence.append(f"Note produit : {rating:.1f}/5")
        evidence.append("Stock, variantes et livraison sont à confirmer sur le détail produit avant publication")

        offers.append({
            "provider": "AliExpress",
            "provider_code": "aliexpress",
            "supplier_sku": str(product.get("itemId") or ""),
            "variant_id": "",
            "name": title,
            "product_cost": price,
            "shipping_cost": None,
            "currency": currency,
            "stock": None,
            "shipping_days": None,
            "warehouse": "CN/EU selon annonce",
            "image_url": _absolute_url(product.get("itemMainPic")),
            "source_url": _absolute_url(product.get("itemUrl")),
            "reliability_score": round(rating * 20, 1) if rating is not None else None,
            "compliance_flags": [],
            "evidence": evidence,
            "shipping_known": False,
            "match_strength": product.get("match_strength"),
            "marketplace_orders": orders,
            "rating": rating,
            "filtered_out": rejected,
        })
    return offers, []
