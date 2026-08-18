import base64
import json
import secrets
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

import httpx

from app.config import get_settings
from app.services.crypto import encrypt, decrypt
from app.services.db import conn, kv_set, kv_get, utc_now


class EbayError(RuntimeError):
    def __init__(self, message: str, status_code: int | None = None, payload=None):
        super().__init__(message)
        self.status_code = status_code
        self.payload = payload


class EbayClient:
    _app_token_cache = None
    _app_token_expires = None

    def __init__(self):
        self.s = get_settings()

    def _basic_auth(self) -> str:
        raw = f"{self.s.ebay_client_id}:{self.s.ebay_client_secret}".encode()
        return "Basic " + base64.b64encode(raw).decode()

    def authorization_url(self) -> str:
        if not self.s.ebay_client_id or not self.s.ebay_runame:
            raise EbayError("Missing EBAY_CLIENT_ID or EBAY_RUNAME")
        state = secrets.token_urlsafe(32)
        kv_set("oauth_state", state)
        params = {
            "client_id": self.s.ebay_client_id,
            "redirect_uri": self.s.ebay_runame,
            "response_type": "code",
            "scope": " ".join(self.s.ebay_oauth_scopes),
            "state": state,
            "locale": self.s.ebay_locale,
            "prompt": "login",
        }
        return f"{self.s.ebay_auth_base}/oauth2/authorize?{urlencode(params)}"

    async def exchange_code(self, code: str, state: str | None) -> None:
        if not self.s.app_encryption_key.strip():
            raise EbayError("APP_ENCRYPTION_KEY must be configured before storing OAuth tokens")
        expected = kv_get("oauth_state")
        if not expected or state != expected:
            raise EbayError("OAuth state mismatch")
        url = f"{self.s.ebay_api_base}/identity/v1/oauth2/token"
        headers = {"Content-Type": "application/x-www-form-urlencoded", "Authorization": self._basic_auth()}
        data = {"grant_type": "authorization_code", "code": code, "redirect_uri": self.s.ebay_runame}
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.post(url, headers=headers, data=data)
        if r.is_error:
            raise EbayError("OAuth code exchange failed", r.status_code, self._safe_json(r))
        self._store_tokens(r.json())

    def _store_tokens(self, data: dict) -> None:
        now = datetime.now(timezone.utc)
        access_exp = now + timedelta(seconds=int(data.get("expires_in", 7200)) - 60)
        refresh_exp = None
        if data.get("refresh_token_expires_in"):
            refresh_exp = now + timedelta(seconds=int(data["refresh_token_expires_in"]) - 60)
        with conn() as c:
            c.execute(
                """
                INSERT INTO oauth_tokens(id,access_token,refresh_token,access_expires_at,refresh_expires_at,updated_at)
                VALUES(1,?,?,?,?,?)
                ON CONFLICT(id) DO UPDATE SET
                    access_token=excluded.access_token,
                    refresh_token=COALESCE(excluded.refresh_token, oauth_tokens.refresh_token),
                    access_expires_at=excluded.access_expires_at,
                    refresh_expires_at=COALESCE(excluded.refresh_expires_at, oauth_tokens.refresh_expires_at),
                    updated_at=excluded.updated_at
                """,
                (encrypt(data["access_token"]), encrypt(data.get("refresh_token")), access_exp.isoformat(),
                 refresh_exp.isoformat() if refresh_exp else None, utc_now()),
            )

    def token_status(self) -> dict:
        with conn() as c:
            row = c.execute("SELECT * FROM oauth_tokens WHERE id=1").fetchone()
        if not row:
            return {"connected": False}
        expires = datetime.fromisoformat(row["access_expires_at"])
        return {
            "connected": True,
            "access_expires_at": row["access_expires_at"],
            "access_expired": expires <= datetime.now(timezone.utc),
            "has_refresh_token": bool(row["refresh_token"]),
            "environment": self.s.ebay_env,
            "marketplace": self.s.ebay_marketplace_id,
        }

    async def _get_access_token(self) -> str:
        with conn() as c:
            row = c.execute("SELECT * FROM oauth_tokens WHERE id=1").fetchone()
        if not row:
            raise EbayError("eBay account is not connected. Complete OAuth first.")
        expires = datetime.fromisoformat(row["access_expires_at"])
        if expires > datetime.now(timezone.utc):
            return decrypt(row["access_token"])
        refresh_token = decrypt(row["refresh_token"])
        if not refresh_token:
            raise EbayError("Access token expired and no refresh token is stored")
        await self._refresh(refresh_token)
        with conn() as c:
            new_row = c.execute("SELECT access_token FROM oauth_tokens WHERE id=1").fetchone()
        return decrypt(new_row["access_token"])

    async def _refresh(self, refresh_token: str) -> None:
        url = f"{self.s.ebay_api_base}/identity/v1/oauth2/token"
        headers = {"Content-Type": "application/x-www-form-urlencoded", "Authorization": self._basic_auth()}
        data = {
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "scope": " ".join(self.s.ebay_oauth_scopes),
        }
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.post(url, headers=headers, data=data)
        if r.is_error:
            raise EbayError("OAuth refresh failed", r.status_code, self._safe_json(r))
        self._store_tokens(r.json())

    @staticmethod
    def _safe_json(response: httpx.Response):
        try:
            return response.json()
        except Exception:
            return {"text": response.text[:2000]}

    async def request(self, method: str, path: str, *, json_body=None, params=None, marketplace_header=True) -> dict:
        token = await self._get_access_token()
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json", "Accept": "application/json"}
        if marketplace_header:
            headers["X-EBAY-C-MARKETPLACE-ID"] = self.s.ebay_marketplace_id
        async with httpx.AsyncClient(timeout=45) as client:
            r = await client.request(method, f"{self.s.ebay_api_base}{path}", headers=headers, json=json_body, params=params)
        if r.is_error:
            raise EbayError(f"eBay API call failed: {method} {path}", r.status_code, self._safe_json(r))
        if r.status_code == 204 or not r.content:
            return {"ok": True}
        return self._safe_json(r)

    async def get_application_token(self) -> str:
        now = datetime.now(timezone.utc)
        if self.__class__._app_token_cache and self.__class__._app_token_expires and self.__class__._app_token_expires > now:
            return self.__class__._app_token_cache
        if not self.s.ebay_client_id or not self.s.ebay_client_secret:
            raise EbayError("Missing EBAY_CLIENT_ID or EBAY_CLIENT_SECRET")
        url = f"{self.s.ebay_api_base}/identity/v1/oauth2/token"
        headers = {"Content-Type": "application/x-www-form-urlencoded", "Authorization": self._basic_auth()}
        data = {"grant_type": "client_credentials", "scope": "https://api.ebay.com/oauth/api_scope"}
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.post(url, headers=headers, data=data)
        if r.is_error:
            raise EbayError("Application token request failed", r.status_code, self._safe_json(r))
        payload = r.json()
        self.__class__._app_token_cache = payload["access_token"]
        self.__class__._app_token_expires = now + timedelta(seconds=int(payload.get("expires_in", 7200)) - 60)
        return self.__class__._app_token_cache

    async def public_request(self, method: str, path: str, *, params=None, marketplace_id: str | None = None) -> dict:
        token = await self.get_application_token()
        headers = {"Authorization": f"Bearer {token}", "Accept": "application/json", "X-EBAY-C-MARKETPLACE-ID": marketplace_id or self.s.ebay_marketplace_id}
        async with httpx.AsyncClient(timeout=45) as client:
            r = await client.request(method, f"{self.s.ebay_api_base}{path}", headers=headers, params=params)
        if r.is_error:
            raise EbayError(f"eBay public API call failed: {method} {path}", r.status_code, self._safe_json(r))
        return self._safe_json(r)

    async def search_items(self, query: str, limit: int = 20, marketplace_id: str | None = None, category_id: str | None = None) -> dict:
        params = {"q": query, "limit": min(max(limit, 1), 200)}
        if category_id:
            params["category_ids"] = category_id
        return await self.public_request("GET", "/buy/browse/v1/item_summary/search", params=params, marketplace_id=marketplace_id)

    async def get_default_category_tree_id(self, marketplace_id: str | None = None) -> str:
        data = await self.public_request("GET", "/commerce/taxonomy/v1/get_default_category_tree_id", params={"marketplace_id": marketplace_id or self.s.ebay_marketplace_id}, marketplace_id=marketplace_id)
        return str(data["categoryTreeId"])

    async def get_category_suggestions(self, query: str, marketplace_id: str | None = None) -> dict:
        if self.s.ebay_env == "sandbox":
            return {"sandbox_notice": "eBay category suggestions are not meaningful in Sandbox. Switch EBAY_ENV=production for real suggestions.", "categorySuggestions": []}
        tree = await self.get_default_category_tree_id(marketplace_id)
        return await self.public_request("GET", f"/commerce/taxonomy/v1/category_tree/{tree}/get_category_suggestions", params={"q": query}, marketplace_id=marketplace_id)

    async def get_item_aspects(self, category_id: str, marketplace_id: str | None = None) -> dict:
        tree = await self.get_default_category_tree_id(marketplace_id)
        return await self.public_request("GET", f"/commerce/taxonomy/v1/category_tree/{tree}/get_item_aspects_for_category", params={"category_id": category_id}, marketplace_id=marketplace_id)

    async def get_policies(self) -> dict:
        market = self.s.ebay_marketplace_id
        return {
            "payment": await self.request("GET", "/sell/account/v1/payment_policy", params={"marketplace_id": market}),
            "return": await self.request("GET", "/sell/account/v1/return_policy", params={"marketplace_id": market}),
            "fulfillment": await self.request("GET", "/sell/account/v1/fulfillment_policy", params={"marketplace_id": market}),
        }

    async def get_orders(self, limit: int = 50) -> dict:
        return await self.request("GET", "/sell/fulfillment/v1/order", params={"limit": min(max(limit, 1), 200)})

    async def create_inventory_location(self) -> dict:
        s = self.s
        if not s.ebay_write_enabled:
            return {"dry_run": True, "reason": "EBAY_WRITE_ENABLED=false", "merchantLocationKey": s.ebay_merchant_location_key}
        if not s.ebay_location_country or not s.ebay_location_postal_code:
            raise EbayError("EBAY_LOCATION_COUNTRY and EBAY_LOCATION_POSTAL_CODE are required")
        body = {
            "location": {
                "address": {
                    "country": s.ebay_location_country,
                    "postalCode": s.ebay_location_postal_code,
                }
            },
            "name": "Main dispatch location",
            "merchantLocationStatus": "ENABLED",
            "locationTypes": ["WAREHOUSE"],
        }
        if s.ebay_location_city:
            body["location"]["address"]["city"] = s.ebay_location_city
        return await self.request("POST", f"/sell/inventory/v1/location/{s.ebay_merchant_location_key}", json_body=body)

    def build_inventory_item_payload(self, product: dict) -> dict:
        return {
            "availability": {"shipToLocationAvailability": {"quantity": max(int(product.get("stock") or 0), 0)}},
            "condition": product.get("condition") or "NEW",
            "product": {
                "title": product["title"][:80],
                "description": product.get("description") or product["title"],
                "aspects": product.get("aspects") or {},
                "imageUrls": product.get("images") or [],
            },
        }

    def build_offer_payload(self, product: dict, price: float) -> dict:
        s = self.s
        missing = [name for name, val in {
            "EBAY_PAYMENT_POLICY_ID": s.ebay_payment_policy_id,
            "EBAY_RETURN_POLICY_ID": s.ebay_return_policy_id,
            "EBAY_FULFILLMENT_POLICY_ID": s.ebay_fulfillment_policy_id,
            "EBAY_MERCHANT_LOCATION_KEY": s.ebay_merchant_location_key,
        }.items() if not val]
        if missing:
            raise EbayError("Missing eBay listing configuration: " + ", ".join(missing))
        category_id = product.get("category_id")
        if not category_id:
            raise EbayError("Product category_id is required before an offer can be created")
        return {
            "sku": product["supplier_sku"],
            "marketplaceId": product.get("marketplace_id") or s.ebay_marketplace_id,
            "format": "FIXED_PRICE",
            "availableQuantity": max(int(product.get("stock") or 0), 0),
            "categoryId": str(category_id),
            "merchantLocationKey": s.ebay_merchant_location_key,
            "listingDescription": product.get("description") or product["title"],
            "listingDuration": "GTC",
            "listingPolicies": {
                "paymentPolicyId": s.ebay_payment_policy_id,
                "returnPolicyId": s.ebay_return_policy_id,
                "fulfillmentPolicyId": s.ebay_fulfillment_policy_id,
            },
            "pricingSummary": {"price": {"value": f"{price:.2f}", "currency": product.get("currency") or s.ebay_currency}},
        }

    async def create_offer_for_product(self, product: dict, price: float) -> dict:
        inventory_payload = self.build_inventory_item_payload(product)
        offer_payload = self.build_offer_payload(product, price)
        if not self.s.ebay_write_enabled:
            return {"dry_run": True, "inventory_payload": inventory_payload, "offer_payload": offer_payload}
        sku = product["supplier_sku"]
        await self.request("PUT", f"/sell/inventory/v1/inventory_item/{sku}", json_body=inventory_payload)
        offer = await self.request("POST", "/sell/inventory/v1/offer", json_body=offer_payload)
        return {"dry_run": False, "offer": offer, "inventory_payload": inventory_payload, "offer_payload": offer_payload}

    async def publish_offer(self, offer_id: str) -> dict:
        if not self.s.ebay_publish_enabled:
            return {"dry_run": True, "reason": "EBAY_PUBLISH_ENABLED=false", "offer_id": offer_id}
        if not self.s.ebay_write_enabled:
            raise EbayError("EBAY_WRITE_ENABLED must be true before publishing")
        return await self.request("POST", f"/sell/inventory/v1/offer/{offer_id}/publish")

    async def create_shipping_fulfillment(self, order_id: str, tracking_number: str, carrier: str, line_item_ids: list[str] | None = None) -> dict:
        body = {"shippedDate": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"), "shippingCarrierCode": carrier, "trackingNumber": tracking_number}
        if line_item_ids:
            body["lineItems"] = [{"lineItemId": x, "quantity": 1} for x in line_item_ids]
        if not self.s.ebay_write_enabled:
            return {"dry_run": True, "order_id": order_id, "payload": body}
        return await self.request("POST", f"/sell/fulfillment/v1/order/{order_id}/shipping_fulfillment", json_body=body)

    async def update_live_offer_price_quantity(self, sku: str, offer_id: str, price: float, quantity: int, currency: str) -> dict:
        body = {
            "requests": [{
                "sku": sku,
                "shipToLocationAvailability": {"quantity": max(quantity, 0)},
                "offers": [{
                    "offerId": offer_id,
                    "availableQuantity": max(quantity, 0),
                    "price": {"value": f"{price:.2f}", "currency": currency},
                }],
            }]
        }
        if not self.s.ebay_write_enabled:
            return {"dry_run": True, "payload": body}
        return await self.request("POST", "/sell/inventory/v1/bulk_update_price_quantity", json_body=body)
