from datetime import datetime, timezone
import re

import httpx

from app.services.crypto import decrypt, encrypt
from app.services.db import kv_get, kv_set


class CJError(RuntimeError):
    pass


class CJClient:
    base_url = "https://developers.cjdropshipping.com/api2.0/v1"

    def save_api_key(self, api_key: str) -> None:
        kv_set("cj_api_key", encrypt(api_key.strip()) or "")
        kv_set("cj_access_token", "")
        kv_set("cj_refresh_token", "")

    def api_key(self) -> str:
        return decrypt(kv_get("cj_api_key")) or ""

    def status(self) -> dict:
        try:
            key = self.api_key()
            token = decrypt(kv_get("cj_access_token")) or ""
        except RuntimeError:
            return {"configured": False, "connected": False, "api_key_masked": "",
                    "access_expires_at": None, "read_only": True,
                    "recovery_required": True,
                    "last_error": "Identifiants CJ incompatibles — reconnectez CJ"}
        expiry = kv_get("cj_access_expiry")
        connected = bool(key and token and expiry and self._valid(expiry))
        return {"configured": bool(key), "connected": connected, "api_key_masked": self._mask(key),
                "access_expires_at": expiry if connected else None, "read_only": True,
                "recovery_required": False, "last_error": ""}

    async def authenticate(self) -> dict:
        key = self.api_key()
        if not key:
            raise CJError("Clé API CJ manquante")
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                response = await client.post(f"{self.base_url}/authentication/getAccessToken", json={"apiKey": key})
        except httpx.HTTPError as exc:
            raise CJError("CJ ne répond pas pour le moment") from exc
        payload = self._payload(response, "Connexion CJ refusée")
        data = payload.get("data") or {}
        if not data.get("accessToken"):
            raise CJError(payload.get("message") or "CJ n'a pas retourné de jeton d'accès")
        kv_set("cj_access_token", encrypt(data["accessToken"]) or "")
        kv_set("cj_refresh_token", encrypt(data.get("refreshToken")) or "")
        kv_set("cj_access_expiry", data.get("accessTokenExpiryDate") or "")
        kv_set("cj_refresh_expiry", data.get("refreshTokenExpiryDate") or "")
        return self.status()

    async def access_token(self) -> str:
        token = decrypt(kv_get("cj_access_token")) or ""
        expiry = kv_get("cj_access_expiry") or ""
        if token and self._valid(expiry):
            return token
        await self.authenticate()
        return decrypt(kv_get("cj_access_token")) or ""

    async def request(self, method: str, path: str, *, params=None, json_body=None) -> dict:
        token = await self.access_token()
        try:
            async with httpx.AsyncClient(timeout=45) as client:
                response = await client.request(method, f"{self.base_url}{path}", params=params,
                                                json=json_body,
                                                headers={"CJ-Access-Token": token, "Accept": "application/json"})
        except httpx.HTTPError as exc:
            raise CJError("CJ ne répond pas pour le moment") from exc
        return self._payload(response, "CJ ne répond pas")

    async def test_connection(self) -> dict:
        await self.authenticate()
        warehouses = await self.request("GET", "/product/globalWarehouseList")
        return {"connected": True, "read_only": True, "warehouses": len(warehouses.get("data") or [])}

    async def warehouses(self) -> list[dict]:
        payload = await self.request("GET", "/product/globalWarehouseList")
        return [{"country_code": x.get("countryCode"), "name": x.get("en") or x.get("areaEn") or "CJ Warehouse"}
                for x in (payload.get("data") or []) if not x.get("disabled")]

    async def categories(self) -> list[dict]:
        payload = await self.request("GET", "/product/getCategory")
        rows = []
        for first in payload.get("data") or []:
            for second in first.get("categoryFirstList") or []:
                for third in second.get("categorySecondList") or []:
                    rows.append({"id": third.get("categoryId"), "name": third.get("categoryName"),
                                 "path": f"{first.get('categoryFirstName', '')} › {second.get('categorySecondName', '')} › {third.get('categoryName', '')}"})
        return rows

    async def search_products(self, *, keyword: str = "", page: int = 1, size: int = 20,
                              category_id: str = "", country_code: str = "", min_price: float | None = None,
                              max_price: float | None = None, min_stock: int = 1, order_by: int = 0) -> dict:
        params = {"page": page, "size": min(max(int(size), 1), 100), "keyWord": keyword,
                  "orderBy": order_by, "sort": "desc", "features": "enable_category"}
        if min_stock and int(min_stock) > 0:
            params["startWarehouseInventory"] = int(min_stock)
        optional = {"categoryId": category_id, "countryCode": country_code,
                    "startSellPrice": min_price, "endSellPrice": max_price}
        params.update({k: v for k, v in optional.items() if v not in (None, "")})
        payload = await self.request("GET", "/product/listV2", params=params)
        data = payload.get("data") or {}
        products = []
        for group in data.get("content") or []:
            for item in group.get("productList") or []:
                products.append({"cj_pid": item.get("id"), "sku": item.get("sku") or item.get("spu"),
                                 "name": item.get("nameEn") or "Produit CJ", "image_url": item.get("bigImage") or "",
                                 "price_usd": self._number(item.get("nowPrice") or item.get("sellPrice")),
                                 "category_id": item.get("categoryId"), "category_name": item.get("threeCategoryName") or "",
                                 "stock": int(item.get("totalVerifiedInventory") or item.get("warehouseInventoryNum") or 0),
                                 "delivery_cycle": item.get("deliveryCycle") or "", "has_ce": bool(item.get("hasCECertification")),
                                 "listed_num": int(item.get("listedNum") or 0), "warehouse_country": country_code})
        return {"page": data.get("pageNumber", page), "total": data.get("totalRecords", len(products)),
                "total_pages": data.get("totalPages", 1), "products": products}

    @staticmethod
    def _normalize_inventory(item: dict) -> dict:
        stock_rows = item.get("stock") or []
        storage_ids = []
        for row in stock_rows:
            stock_id = str(row.get("stockId") or "").strip()
            if stock_id and stock_id not in storage_ids:
                storage_ids.append(stock_id)
        total = item.get("totalInventory")
        if total is None:
            total = item.get("totalInventoryNum")
        if total is None:
            total = item.get("storageNum")
        return {
            "country_code": str(item.get("countryCode") or "").upper(),
            "stock": int(total or 0),
            "cj_stock": int(item.get("cjInventory") or item.get("cjInventoryNum") or 0),
            "factory_stock": int(item.get("factoryInventory") or item.get("factoryInventoryNum") or 0),
            "verified_warehouse": int(item.get("verifiedWarehouse") or 0),
            "storage_ids": storage_ids,
        }

    async def product_inventory(self, pid: str) -> dict:
        """Return CJ's dedicated product/variant inventory snapshot."""
        payload = await self.request("GET", "/product/stock/getInventoryByPid", params={"pid": pid})
        data = payload.get("data") or {}
        product_inventories = [
            self._normalize_inventory(row)
            for row in (data.get("inventories") or [])
            if str(row.get("countryCode") or "").strip()
        ]
        variant_inventories: dict[str, list[dict]] = {}
        for row in data.get("variantInventories") or []:
            vid = str(row.get("vid") or "").strip()
            if not vid:
                continue
            variant_inventories[vid] = [
                self._normalize_inventory(item)
                for item in (row.get("inventory") or [])
                if str(item.get("countryCode") or "").strip()
            ]
        return {
            "pid": pid,
            "product_inventories": product_inventories,
            "variant_inventories": variant_inventories,
        }

    async def variant_inventory(self, vid: str) -> list[dict]:
        """Fetch inventory + sub-warehouse IDs for one CJ variant when PID inventory is incomplete."""
        payload = await self.request(
            "GET",
            "/product/variant/queryByVid",
            params={"vid": vid, "features": "enable_inventory"},
        )
        data = payload.get("data") or {}
        return [
            self._normalize_inventory(row)
            for row in (data.get("inventories") or [])
            if str(row.get("countryCode") or "").strip()
        ]

    async def product_detail(self, pid: str) -> dict:
        payload = await self.request("GET", "/product/query", params={"pid": pid})
        data = payload.get("data") or {}
        variants = []
        for item in data.get("variants") or []:
            inventories = [
                self._normalize_inventory(row)
                for row in (item.get("inventories") or [])
                if str(row.get("countryCode") or "").strip()
            ]
            variants.append({
                "vid": item.get("vid"),
                "name": item.get("variantNameEn") or item.get("variantSku") or "Variante CJ",
                "sku": item.get("variantSku") or "",
                "image_url": item.get("variantImage") or data.get("bigImage") or "",
                "price_usd": self._number(item.get("variantSellPrice")),
                "weight_g": self._number(item.get("variantWeight")),
                "length_mm": self._number(item.get("variantLength")),
                "width_mm": self._number(item.get("variantWidth")),
                "height_mm": self._number(item.get("variantHeight")),
                "stock": sum(int(x.get("stock") or 0) for x in inventories),
                "inventories": inventories,
            })
        variants.sort(key=lambda x: (x["price_usd"] <= 0, x["price_usd"], x["name"]))
        detail = {
            "pid": data.get("pid") or pid,
            "name": data.get("productNameEn") or "Produit CJ",
            "sku": data.get("productSku") or "",
            "image_url": data.get("bigImage") or "",
            "images": data.get("productImageSet") or [],
            "category_name": data.get("categoryName") or "",
            "weight_g": self._number(data.get("productWeight")),
            "packing_weight_g": self._number(data.get("packingWeight")),
            "material": data.get("materialNameEnSet") or [],
            "logistics_properties": data.get("productProEnSet") or [],
            "suggested_retail_usd": data.get("suggestSellPrice") or "",
            "variants": variants,
        }
        detail["risk_flags"] = self.compliance_flags(detail)
        return detail

    @staticmethod
    def _freight_row(item: dict, *, tip: bool = False) -> dict | None:
        if tip:
            base_raw = item.get("wrapPostage")
            if base_raw is None:
                base_raw = item.get("discountFee")
            if base_raw is None:
                base_raw = item.get("postage")
            quoted_total = item.get("totalPostageFee")
            if base_raw is None and quoted_total is None:
                return None
            base = CJClient._number(base_raw)
            taxes = CJClient._number(item.get("taxesFee"))
            clearance = CJClient._number(item.get("clearanceOperationFee"))
            tariff = CJClient._number(item.get("tariff"))
            total = (
                CJClient._number(quoted_total)
                if quoted_total is not None
                else round(base + taxes + clearance + tariff, 2)
            )
            option = item.get("option") or {}
            channel = item.get("channel") or {}
            return {
                "name": option.get("enName") or channel.get("enName") or "Transport CJ",
                "price_usd": total,
                "base_price_usd": base,
                "taxes_usd": taxes,
                "clearance_usd": clearance,
                "tariff_usd": tariff,
                "delivery_days": item.get("arrivalTime") or option.get("arrivalTime") or "Non indiqué",
                "source": "freightCalculateTip",
            }

        price_fields = ("totalPostageFee", "logisticPrice", "taxesFee", "clearanceOperationFee")
        if not any(item.get(key) is not None for key in price_fields):
            return None
        base = CJClient._number(item.get("logisticPrice"))
        taxes = CJClient._number(item.get("taxesFee"))
        clearance = CJClient._number(item.get("clearanceOperationFee"))
        quoted_total = item.get("totalPostageFee")
        total = CJClient._number(quoted_total) if quoted_total is not None else round(base + taxes + clearance, 2)
        return {"name": item.get("logisticName") or "Transport CJ",
                "price_usd": total, "base_price_usd": base,
                "taxes_usd": taxes, "clearance_usd": clearance,
                "delivery_days": item.get("logisticAging") or "Non indiqué",
                "source": "freightCalculate"}

    @staticmethod
    def _require_us_destination(destination_country: str) -> str:
        destination = str(destination_country or "").strip().upper()
        if destination != "US":
            raise CJError("Le mode actif calcule exclusivement le transport CJ vers les États-Unis")
        return destination

    async def freight_options(self, vid: str, *, start_country: str = "CN",
                              destination_country: str = "US", postcode: str = "",
                              storage_ids: list[str] | None = None) -> list[dict]:
        destination_country = self._require_us_destination(destination_country)
        body = {"startCountryCode": start_country, "endCountryCode": destination_country,
                "products": [{"quantity": 1, "vid": vid}]}
        clean_storage_ids = [str(value).strip() for value in (storage_ids or []) if str(value).strip()]
        if clean_storage_ids:
            body["storageIdList"] = clean_storage_ids[:100]
        if postcode.strip():
            body["zip"] = postcode.strip()
        payload = await self.request("POST", "/logistic/freightCalculate", json_body=body)
        rows = [self._freight_row(item) for item in (payload.get("data") or [])]
        return sorted([row for row in rows if row is not None], key=lambda x: (x["price_usd"], x["name"]))

    async def freight_options_tip(self, variant: dict, detail: dict, *, start_country: str = "CN",
                                  destination_country: str = "US", postcode: str = "",
                                  storage_ids: list[str] | None = None) -> list[dict]:
        """Fallback to CJ's richer freight trial endpoint when simple freight has no route."""
        destination_country = self._require_us_destination(destination_country)
        sku = str(variant.get("sku") or "").strip()
        vid = str(variant.get("vid") or "").strip()
        if not sku or not vid:
            return []
        weight = max(float(variant.get("weight_g") or detail.get("packing_weight_g") or detail.get("weight_g") or 0), 1.0)
        length_cm = float(variant.get("length_mm") or 0) / 10.0
        width_cm = float(variant.get("width_mm") or 0) / 10.0
        height_cm = float(variant.get("height_mm") or 0) / 10.0
        volume = max(length_cm * width_cm * height_cm, 0.01)
        properties = [str(value).strip().upper() for value in (detail.get("logistics_properties") or []) if str(value).strip()]
        properties = properties or ["COMMON"]
        req = {
            "srcAreaCode": start_country,
            "destAreaCode": destination_country,
            "wrapWeight": round(weight, 2),
            "weight": round(weight, 2),
            "volume": round(volume, 2),
            "productProp": properties,
            "skuList": [sku],
            "totalGoodsAmount": round(float(variant.get("price_usd") or 0), 2),
            "freightTrialSkuList": [{
                "skuQuantity": 1,
                "sku": sku,
                "vid": vid,
                "skuWeight": round(weight, 2),
                "skuVolume": round(volume, 2),
                "productPropList": properties,
            }],
        }
        if length_cm > 0 and width_cm > 0 and height_cm > 0:
            req.update({
                "length": round(length_cm, 2),
                "width": round(width_cm, 2),
                "height": round(height_cm, 2),
            })
        clean_storage_ids = [str(value).strip() for value in (storage_ids or []) if str(value).strip()]
        if clean_storage_ids:
            req["storageIdList"] = clean_storage_ids[:100]
        if postcode.strip():
            req["zip"] = postcode.strip()
        payload = await self.request("POST", "/logistic/freightCalculateTip", json_body={"reqDTOS": [req]})
        rows = [self._freight_row(item, tip=True) for item in (payload.get("data") or [])]
        return sorted([row for row in rows if row is not None], key=lambda x: (x["price_usd"], x["name"]))

    @staticmethod
    def compliance_flags(detail: dict) -> list[dict]:
        name = f"{detail.get('name', '')} {detail.get('category_name', '')}".lower()
        props = {str(x).upper() for x in detail.get("logistics_properties") or []}
        flags = []
        battery_terms = ("battery", "rechargeable", "charging", "power bank", "mah")
        if any("BATTERY" in x for x in props) or any(x in name for x in battery_terms):
            flags.append({"code": "BATTERY", "level": "high",
                          "label": "Batterie ou recharge détectée : transport et documents à vérifier"})
        liquid_terms = ("liquid", "spray", "humidifier", "water spraying")
        if any("LIQUID" in x for x in props) or any(x in name for x in liquid_terms):
            flags.append({"code": "LIQUID", "level": "high",
                          "label": "Liquide ou pulvérisation potentielle : transport à vérifier"})
        if any(x in name for x in ("electric", "electronic", "usb")) and not any(f["code"] == "BATTERY" for f in flags):
            flags.append({"code": "ELECTRIC", "level": "medium",
                          "label": "Produit électrique : conformité à contrôler avant publication"})
        if any(x in props for x in ("MAGNETISM", "MAGNETIC")):
            flags.append({"code": "MAGNETIC", "level": "medium",
                          "label": "Propriété magnétique déclarée par CJ"})
        return flags

    @staticmethod
    def _payload(response: httpx.Response, fallback: str) -> dict:
        try:
            payload = response.json()
        except Exception as exc:
            raise CJError(f"{fallback} (réponse illisible)") from exc
        if response.is_error or payload.get("success") is False or payload.get("result") is False:
            raise CJError(payload.get("message") or f"{fallback} ({response.status_code})")
        return payload

    @staticmethod
    def _valid(value: str) -> bool:
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")) > datetime.now(timezone.utc)
        except (TypeError, ValueError):
            return False

    @staticmethod
    def _mask(value: str) -> str:
        if len(value) < 12:
            return "•" * len(value)
        return value[:5] + "…" + value[-4:]

    @staticmethod
    def _number(value) -> float:
        match = re.search(r"\d+(?:[.,]\d+)?", str(value or ""))
        return round(float(match.group(0).replace(",", ".")), 2) if match else 0.0
