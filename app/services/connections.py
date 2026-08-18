import asyncio
import json
import math
import os
import re
import unicodedata
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone
from statistics import median
from typing import Any

import httpx

from app.services.crypto import decrypt, encrypt
from app.services.db import kv_get, kv_set, save_radar_scan, save_trend_discovery


class IntegrationError(RuntimeError):
    pass


CREDENTIAL_RECOVERY_MESSAGE = "Identifiants locaux incompatibles — reconnectez cette source"


PROVIDERS = {
    "amazon": {
        "name": "Amazon SP-API Radar", "kind": "Marketplace en lecture seule",
        "required": ("client_id", "client_secret", "refresh_token"),
        "mask_field": "refresh_token",
        "docs_url": "https://developer-docs.amazon.com/sp-api/docs/onboarding-overview",
        "note": "Catalogue, catégories et classements Amazon. Aucune annonce, commande ou modification Amazon.",
    },
    "tiktok": {
        "name": "TikTok Commercial Content", "kind": "Tendances publicitaires UE",
        "required": ("client_key", "client_secret"),
        "docs_url": "https://developers.tiktok.com/products/commercial-content-api",
        "note": "Publicités, annonceurs, durée de diffusion et portée déclarée. Pas de ventes concurrentes.",
    },
    "youtube": {
        "name": "YouTube Shorts e-commerce", "kind": "Produits viraux et intérêt public",
        "required": ("api_key",),
        "docs_url": "https://console.cloud.google.com/apis/library/youtube.googleapis.com",
        "note": "Shorts récents associés à l'e-commerce, au dropshipping et aux produits viraux.",
    },
    "etsy": {
        "name": "Etsy Open API", "kind": "Marketplace",
        "required": ("api_key",),
        "docs_url": "https://www.etsy.com/developers/register",
        "note": "Annonces actives, prix et favoris publics. Les ventes concurrentes restent privées.",
    },
    "dropxl": {
        "name": "DropXL / vidaXL", "kind": "Fournisseur européen",
        "required": ("api_email", "api_token"),
        "mask_field": "api_token",
        "docs_url": "https://b2b.dropxl.com/pages/1-api",
        "note": "Catalogue, prix et stock européens. Les commandes restent bloquées par le dry-run.",
    },
    "printful": {
        "name": "Printful", "kind": "Impression à la demande",
        "required": ("api_key",),
        "docs_url": "https://developers.printful.com/tokens",
        "note": "Catalogue d'articles personnalisables. Aucun ordre de production n'est envoyé.",
    },
    "printify": {
        "name": "Printify", "kind": "Impression à la demande",
        "required": ("api_key",),
        "docs_url": "https://printify.com/app/account/api",
        "note": "Catalogue et ateliers d'impression. Aucun produit ni ordre n'est créé.",
    },
    "gelato": {
        "name": "Gelato", "kind": "Impression locale à la demande",
        "required": ("api_key",),
        "docs_url": "https://dashboard.gelato.com/keys",
        "note": "Catalogues d'impression internationaux. Aucun ordre n'est créé.",
    },
}


ASSISTED_SUPPLIERS = [
    {
        "id": "hypersku", "name": "HyperSKU", "kind": "Sourcing mondial",
        "status": "Accès Open API à demander",
        "url": "https://app.hypersku.com/",
        "note": "Créez le compte puis demandez l'activation Open API à votre agent HyperSKU.",
    },
    {
        "id": "banggood", "name": "Banggood Dropshipping", "kind": "Catalogue mondial",
        "status": "Compte dropshipping à valider",
        "url": "https://www.banggood.com/index.php?com=account&t=dropshipGuidance",
        "note": "L'API est fournie aux comptes dropshipping approuvés. Elle sera connectée après réception de la documentation du compte.",
    },
    {
        "id": "wholesale2b", "name": "Wholesale2B", "kind": "Grossistes américains",
        "status": "Formule API requise",
        "url": "https://www.wholesale2b.com/dropship-api-plan.html",
        "note": "À privilégier pour une future activité eBay US ; l'accès API dépend du plan choisi.",
    },
    {
        "id": "alibaba", "name": "Alibaba.com / usines", "kind": "Fabricants directs",
        "status": "Accès partenaire sur dossier",
        "url": "https://sourcing.alibaba.com/",
        "note": "À utiliser pour les devis, échantillons et contrats usine avant toute automatisation.",
    },
]


TREND_STOPWORDS = {
    "avec", "dans", "pour", "sans", "plus", "moins", "tout", "tous", "cette", "mais", "comme", "vous",
    "votre", "notre", "leurs", "elle", "elles", "nous", "des", "les", "une", "sur", "par", "est", "sont",
    "the", "and", "for", "with", "from", "this", "that", "your", "you", "our", "are", "was", "were",
    "official", "video", "music", "clip", "live", "episode", "trailer", "reaction", "shorts", "youtube",
    "nouveau", "nouvelle", "today", "2025", "2026", "feat", "ft", "part", "full", "how", "why", "what",
    "ecommerce", "commerce", "dropshipping", "dropship", "shopify", "amazon", "tiktok", "viral", "virale",
    "product", "products", "produit", "produits", "winning", "winner", "gagnant", "gagnants", "find", "finds",
    "trending", "trend", "tendance", "tendances", "business", "marketing", "seller", "selling", "vente", "store",
    "boutique", "online", "money", "side", "hustle", "must", "have", "best", "top", "ideas", "idea", "2027",
    "review", "unboxing", "setup", "things", "stuff", "need", "buy", "acheter", "avis", "test", "testing",
}

YOUTUBE_COMMERCE_QUERIES = (
    "#shorts #ecommerce|#shorts #dropshipping|#shorts produit gagnant -formation -coaching -agence -course",
    "#shorts #amazonfinds|#shorts #tiktokmademebuyit|#shorts #productfinds|#shorts #viralproducts",
)
YOUTUBE_COMMERCE_MARKERS = {
    "ecommerce", "e commerce", "dropshipping", "dropship", "shopify", "amazonfinds", "amazon finds",
    "tiktokmademebuyit", "tiktok made me buy it", "productfinds", "product finds", "viralproducts",
    "viral products", "produit gagnant", "produits gagnants", "produit viral", "produits viraux",
}

PRODUCT_FAMILIES = {
    "Auto": {"car", "auto", "voiture", "organizer", "organisateur", "holder", "support", "dashcam", "cleaner"},
    "Maison": {"home", "maison", "kitchen", "cuisine", "storage", "rangement", "lamp", "lampe", "vacuum", "aspirateur"},
    "Électronique": {"charger", "chargeur", "wireless", "usb", "led", "camera", "headphones", "écouteurs", "speaker"},
    "Beauté": {"beauty", "beauté", "hair", "cheveux", "skin", "visage", "makeup", "maquillage", "massage"},
    "Sport": {"fitness", "sport", "gym", "running", "cycling", "yoga", "training", "outdoor"},
    "Animaux": {"pet", "pets", "dog", "dogs", "cat", "cats", "chien", "chat", "animal"},
    "Bureau": {"desk", "office", "bureau", "keyboard", "clavier", "mouse", "souris", "stand"},
    "Cuisine": {"blender", "mixer", "bottle", "bouteille", "cutter", "chopper", "poele", "pan", "dispenser"},
    "Voyage": {"travel", "voyage", "luggage", "valise", "packing", "portable", "backpack", "sac"},
    "Jardin": {"garden", "jardin", "plant", "plante", "watering", "arrosage", "outdoor", "terrasse"},
}


def _trend_tokens(value: str) -> list[str]:
    normalized = unicodedata.normalize("NFKD", str(value or "")).encode("ascii", "ignore").decode().lower()
    return [token for token in re.findall(r"[a-z][a-z0-9-]{2,}", normalized)
            if token not in TREND_STOPWORDS and not token.isdigit()]


def _iso_duration_seconds(value: str) -> int:
    match = re.fullmatch(r"P(?:(\d+)D)?T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", str(value or ""))
    if not match:
        return 0
    days, hours, minutes, seconds = (int(part or 0) for part in match.groups())
    return days * 86400 + hours * 3600 + minutes * 60 + seconds


def _commerce_relevant(*values: Any) -> bool:
    normalized = unicodedata.normalize("NFKD", " ".join(str(value or "") for value in values))
    normalized = normalized.encode("ascii", "ignore").decode().lower().replace("#", "")
    return any(marker.replace("#", "") in normalized for marker in YOUTUBE_COMMERCE_MARKERS)


def extract_trend_themes(videos: list[dict[str, Any]], limit: int = 12) -> list[dict[str, Any]]:
    """Extract explainable recurring themes from public video metadata.

    This is a frequency signal, not a claim about searches, sales or conversion.
    """
    mentions: Counter[str] = Counter()
    weighted: Counter[str] = Counter()
    examples: dict[str, list[str]] = defaultdict(list)
    categories: dict[str, Counter[str]] = defaultdict(Counter)
    for video in videos:
        title = str(video.get("title") or "")
        tokens = _trend_tokens(" ".join([title, *[str(x) for x in video.get("tags") or []]]))
        candidates = set(tokens)
        candidates.update(" ".join(tokens[index:index + 2]) for index in range(len(tokens) - 1))
        view_weight = max(math.log10(int(video.get("views") or 0) + 10), 1)
        for candidate in candidates:
            if len(candidate) < 4:
                continue
            mentions[candidate] += 1
            weighted[candidate] += view_weight
            if title and len(examples[candidate]) < 3:
                examples[candidate].append(title)
            candidate_tokens = set(candidate.split())
            for family, hints in PRODUCT_FAMILIES.items():
                if candidate_tokens & hints:
                    categories[candidate][family] += 1

    ranked = []
    for keyword, count in mentions.items():
        product_family = categories[keyword].most_common(1)[0][0] if categories[keyword] else "Thème général"
        product_hint = product_family != "Thème général"
        if count < 2 and not product_hint:
            continue
        specificity = 1.18 if " " in keyword else 1
        ranked.append((weighted[keyword] * specificity * (1.25 if product_hint else 1), keyword, count, product_family))
    ranked.sort(reverse=True)
    if not ranked:
        ranked = [(weighted[word], word, mentions[word], "Thème général")
                  for word, _ in mentions.most_common(limit)]
    peak = max((row[0] for row in ranked), default=1)
    return [{
        "keyword": keyword,
        "mentions": count,
        "signal_score": round(score / peak * 100),
        "category": family,
        "product_hint": family != "Thème général",
        "confidence": "Forte" if count >= 4 else "Moyenne" if count >= 2 else "Exploration",
        "examples": examples[keyword],
        "meaning": "Fréquence dans les métadonnées des vidéos observées, pas volume de recherche ni ventes.",
    } for score, keyword, count, family in ranked[:limit]]


def _env_credentials(provider: str) -> dict[str, str]:
    mapping = {
        "amazon": {
            "client_id": "AMAZON_SP_API_CLIENT_ID",
            "client_secret": "AMAZON_SP_API_CLIENT_SECRET",
            "refresh_token": "AMAZON_SP_API_REFRESH_TOKEN",
        },
        "tiktok": {"client_key": "TIKTOK_CLIENT_KEY", "client_secret": "TIKTOK_CLIENT_SECRET"},
        "youtube": {"api_key": "YOUTUBE_API_KEY"},
        "etsy": {"api_key": "ETSY_API_KEY"},
        "dropxl": {"api_email": "DROPXL_API_EMAIL", "api_token": "DROPXL_API_TOKEN",
                   "environment": "DROPXL_ENV"},
        "printful": {"api_key": "PRINTFUL_API_KEY"},
        "printify": {"api_key": "PRINTIFY_API_KEY"},
        "gelato": {"api_key": "GELATO_API_KEY"},
    }
    return {field: os.getenv(variable, "") for field, variable in mapping.get(provider, {}).items()
            if os.getenv(variable, "")}


def load_credentials(provider: str) -> dict[str, Any]:
    if provider not in PROVIDERS:
        raise IntegrationError("Source inconnue")
    stored = kv_get(f"integration:{provider}")
    if not stored:
        return _env_credentials(provider)
    try:
        data = json.loads(decrypt(stored) or "{}")
    except (json.JSONDecodeError, RuntimeError) as exc:
        raise IntegrationError("Les identifiants locaux ne peuvent pas être déchiffrés") from exc
    if data.get("disabled"):
        return {}
    return {**_env_credentials(provider), **data}


def save_credentials(provider: str, values: dict[str, Any]) -> None:
    if provider not in PROVIDERS:
        raise IntegrationError("Source inconnue")
    allowed = {*PROVIDERS[provider]["required"], "environment", "verified_at", "last_error"}
    try:
        current = load_credentials(provider)
    except IntegrationError:
        # A user-entered credential must always be able to replace a value that
        # was encrypted by an older installation key.
        current = _env_credentials(provider)
    current.pop("disabled", None)
    for key, value in values.items():
        if key in allowed and value is not None and str(value).strip():
            current[key] = str(value).strip()
    kv_set(f"integration:{provider}", encrypt(json.dumps(current, ensure_ascii=False)) or "")


def delete_credentials(provider: str) -> None:
    if provider not in PROVIDERS:
        raise IntegrationError("Source inconnue")
    kv_set(f"integration:{provider}", encrypt('{"disabled": true}') or '{"disabled": true}')


def _mask(value: str) -> str:
    if not value:
        return ""
    if len(value) < 9:
        return "•" * len(value)
    return value[:4] + "…" + value[-4:]


def connection_status(provider: str) -> dict[str, Any]:
    meta = PROVIDERS[provider]
    recovery_required = False
    try:
        data = load_credentials(provider)
    except IntegrationError:
        data = {}
        recovery_required = True
    configured = all(data.get(field) for field in meta["required"])
    connected = configured and bool(data.get("verified_at")) and not data.get("last_error")
    last_error = CREDENTIAL_RECOVERY_MESSAGE if recovery_required else data.get("last_error", "")
    return {
        "id": provider, "name": meta["name"], "kind": meta["kind"],
        "configured": configured, "connected": connected, "ready": connected,
        "status": "Connecté" if connected else "À reconnecter" if recovery_required else "À tester" if configured else "À connecter",
        "note": meta["note"], "docs_url": meta["docs_url"],
        "verified_at": data.get("verified_at"), "last_error": last_error,
        "credential_masked": _mask(str(data.get(meta.get("mask_field", meta["required"][0]), ""))),
        "environment": data.get("environment", "production"),
        "recovery_required": recovery_required,
    }


def connection_statuses() -> list[dict[str, Any]]:
    return [connection_status(provider) for provider in PROVIDERS]


def _error_message(response: httpx.Response, provider: str) -> str:
    try:
        payload = response.json()
    except ValueError:
        payload = {}
    nested_error = payload.get("error") if isinstance(payload.get("error"), dict) else {}
    message = payload.get("error_description") or payload.get("message") or nested_error.get("message") or ""
    return f"{provider} refuse la connexion" + (f" : {message}" if message else "")


def _rows(payload: Any) -> list[dict]:
    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, dict)]
    if isinstance(payload, dict):
        for key in ("data", "result", "results", "items", "products"):
            if isinstance(payload.get(key), list):
                return [row for row in payload[key] if isinstance(row, dict)]
            if isinstance(payload.get(key), dict):
                nested = _rows(payload[key])
                if nested:
                    return nested
    return []


class AmazonRadarClient:
    """Read-only Amazon SP-API client used only by the market Radar."""

    token_url = "https://api.amazon.com/auth/o2/token"
    marketplaces = {
        "AMAZON_FR": {"id": "A13V1IB3VIYZZH", "name": "Amazon France", "endpoint": "https://sellingpartnerapi-eu.amazon.com", "domain": "amazon.fr", "currency": "EUR"},
        "AMAZON_DE": {"id": "A1PA6795UKMFR9", "name": "Amazon Allemagne", "endpoint": "https://sellingpartnerapi-eu.amazon.com", "domain": "amazon.de", "currency": "EUR"},
        "AMAZON_IT": {"id": "APJ6JRA9NG5V4", "name": "Amazon Italie", "endpoint": "https://sellingpartnerapi-eu.amazon.com", "domain": "amazon.it", "currency": "EUR"},
        "AMAZON_ES": {"id": "A1RKKUPIHCS9HS", "name": "Amazon Espagne", "endpoint": "https://sellingpartnerapi-eu.amazon.com", "domain": "amazon.es", "currency": "EUR"},
        "AMAZON_GB": {"id": "A1F83G8C2ARO7P", "name": "Amazon Royaume-Uni", "endpoint": "https://sellingpartnerapi-eu.amazon.com", "domain": "amazon.co.uk", "currency": "GBP"},
        "AMAZON_US": {"id": "ATVPDKIKX0DER", "name": "Amazon États-Unis", "endpoint": "https://sellingpartnerapi-na.amazon.com", "domain": "amazon.com", "currency": "USD"},
    }

    def __init__(self):
        self.credentials = load_credentials("amazon")
        self._cached_access_token = ""

    @staticmethod
    def _safe_error(response: httpx.Response) -> str:
        try:
            payload = response.json()
        except ValueError:
            payload = {}
        if not isinstance(payload, dict):
            payload = {}
        message = payload.get("error_description") or payload.get("message") or payload.get("error") or "Accès refusé"
        if isinstance(message, dict):
            message = message.get("message") or message.get("code") or "Accès refusé"
        return str(message)[:300]

    async def _access_token(self) -> str:
        if self._cached_access_token:
            return self._cached_access_token
        missing = [field for field in PROVIDERS["amazon"]["required"] if not self.credentials.get(field)]
        if missing:
            raise IntegrationError("Identifiants Amazon SP-API incomplets")
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(self.token_url, data={
                "grant_type": "refresh_token",
                "refresh_token": self.credentials["refresh_token"],
                "client_id": self.credentials["client_id"],
                "client_secret": self.credentials["client_secret"],
            }, headers={"Content-Type": "application/x-www-form-urlencoded;charset=UTF-8"})
        if response.is_error:
            raise IntegrationError("Amazon LWA refuse la connexion : " + self._safe_error(response))
        payload = response.json()
        token = str(payload.get("access_token") or "") if isinstance(payload, dict) else ""
        if not token:
            raise IntegrationError("Amazon n'a pas renvoyé de jeton d'accès")
        self._cached_access_token = token
        return token

    async def _get(self, market: dict[str, str], path: str, params: dict[str, Any]) -> dict:
        token = await self._access_token()
        headers = {
            "x-amz-access-token": token,
            "x-amz-date": datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"),
            "user-agent": "eBayOpsBot/0.14.3 (Language=Python)",
        }
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.get(market["endpoint"] + path, params=params, headers=headers)
        if response.is_error:
            raise IntegrationError("Amazon SP-API refuse le relevé : " + self._safe_error(response))
        try:
            return response.json()
        except ValueError as exc:
            raise IntegrationError("Réponse Amazon illisible") from exc

    @staticmethod
    def _market_group(groups: Any, marketplace_id: str) -> dict[str, Any]:
        if not isinstance(groups, list):
            return {}
        return next((row for row in groups if isinstance(row, dict) and row.get("marketplaceId") == marketplace_id),
                    next((row for row in groups if isinstance(row, dict)), {}))

    @classmethod
    def normalize_catalog(cls, payload: dict, marketplace: str) -> dict:
        market = cls.marketplaces[marketplace]
        marketplace_id = market["id"]
        products = []
        for row in payload.get("items") or []:
            if not isinstance(row, dict):
                continue
            asin = str(row.get("asin") or "").strip()
            summary = cls._market_group(row.get("summaries"), marketplace_id)
            image_group = cls._market_group(row.get("images"), marketplace_id)
            rank_group = cls._market_group(row.get("salesRanks"), marketplace_id)
            class_group = cls._market_group(row.get("classifications"), marketplace_id)
            images = image_group.get("images") or []
            image = next((item for item in images if item.get("variant") == "MAIN"), images[0] if images else {})
            ranks = []
            for key in ("classificationRanks", "displayGroupRanks"):
                for item in rank_group.get(key) or []:
                    try:
                        rank = int(item.get("rank"))
                    except (AttributeError, TypeError, ValueError):
                        continue
                    ranks.append((rank, item))
            best_rank, best_rank_row = min(ranks, key=lambda pair: pair[0]) if ranks else (None, {})
            classifications = class_group.get("classifications") or []
            category = str((classifications[0] if classifications else {}).get("displayName") or
                           best_rank_row.get("title") or "Catégorie non fournie")
            products.append({
                "asin": asin,
                "title": str(summary.get("itemName") or asin or "Produit Amazon"),
                "brand": str(summary.get("brand") or ""),
                "category": category,
                "sales_rank": best_rank,
                "image_url": str(image.get("link") or ""),
                "url": f"https://www.{market['domain']}/dp/{asin}" if asin else "",
                "price": None,
                "currency": market["currency"],
                "offer_count": None,
            })
        total = payload.get("numberOfResults")
        if total is None and isinstance(payload.get("pagination"), dict):
            total = payload["pagination"].get("numberOfResults")
        try:
            total = int(total)
        except (TypeError, ValueError):
            total = len(products)
        return {"products": products, "total": total}

    @staticmethod
    def apply_pricing(products: list[dict], payload: dict) -> None:
        rows = payload.get("payload") if isinstance(payload, dict) else payload
        if not isinstance(rows, list):
            return
        by_asin = {str(row.get("ASIN") or row.get("asin") or ""): row for row in rows if isinstance(row, dict)}
        for product in products:
            row = by_asin.get(product["asin"]) or {}
            competitive = ((row.get("Product") or {}).get("CompetitivePricing") or {})
            amounts, currencies = [], []
            for price_row in competitive.get("CompetitivePrices") or []:
                price = price_row.get("Price") or {}
                landed = price.get("LandedPrice") or price.get("ListingPrice") or {}
                try:
                    amounts.append(float(landed.get("Amount")))
                except (TypeError, ValueError):
                    continue
                if landed.get("CurrencyCode"):
                    currencies.append(str(landed["CurrencyCode"]))
            offers = competitive.get("NumberOfOfferListings") or []
            product["price"] = min(amounts) if amounts else None
            product["currency"] = currencies[0] if currencies else product["currency"]
            offer_count = 0
            for item in offers:
                try:
                    offer_count += int(item.get("Count") or 0)
                except (AttributeError, TypeError, ValueError):
                    continue
            product["offer_count"] = offer_count or None

    async def search_catalog(self, keyword: str, marketplace: str = "AMAZON_FR", page_size: int = 20,
                             include_pricing: bool = True) -> dict:
        if marketplace not in self.marketplaces:
            raise IntegrationError("Marketplace Amazon inconnue")
        market = self.marketplaces[marketplace]
        payload = await self._get(market, "/catalog/2022-04-01/items", {
            "marketplaceIds": market["id"],
            "keywords": keyword,
            "includedData": "summaries,images,salesRanks,classifications",
            "pageSize": min(max(int(page_size), 1), 20),
        })
        result = self.normalize_catalog(payload, marketplace)
        result.update({"marketplace": marketplace, "marketplace_name": market["name"],
                       "currency": market["currency"], "pricing_available": False})
        asins = [row["asin"] for row in result["products"] if row.get("asin")]
        if include_pricing and asins:
            try:
                pricing = await self._get(market, "/products/pricing/v0/competitivePrice", {
                    "MarketplaceId": market["id"], "ItemType": "Asin", "Asins": ",".join(asins[:20]),
                })
                self.apply_pricing(result["products"], pricing)
                result["pricing_available"] = any(row.get("price") is not None for row in result["products"])
            except IntegrationError:
                # Catalog access remains useful when Amazon has not granted the optional Pricing role.
                result["pricing_available"] = False
        return result

    async def test(self) -> dict:
        result = await self.search_catalog("portable fan", "AMAZON_FR", page_size=1, include_pricing=False)
        return {"ok": True, "observed": len(result["products"]), "marketplace": "Amazon France"}


class YouTubeClient:
    base_url = "https://www.googleapis.com/youtube/v3"

    def __init__(self):
        self.credentials = load_credentials("youtube")

    @property
    def key(self) -> str:
        return str(self.credentials.get("api_key") or "")

    async def _get(self, path: str, params: dict) -> dict:
        if not self.key:
            raise IntegrationError("Clé API YouTube manquante")
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.get(self.base_url + path, params={**params, "key": self.key})
        if response.is_error:
            raise IntegrationError(_error_message(response, "YouTube"))
        return response.json()

    async def test(self) -> dict:
        payload = await self._get("/videos", {"part": "id", "chart": "mostPopular", "regionCode": "FR", "maxResults": 1})
        return {"ok": True, "observed": len(payload.get("items") or [])}

    async def discover(self, country: str = "FR") -> dict:
        since = (datetime.now(timezone.utc) - timedelta(days=21)).isoformat(timespec="seconds").replace("+00:00", "Z")
        languages = {"FR": "fr", "DE": "de", "IT": "it", "ES": "es", "GB": "en", "US": "en"}
        search_items = []
        for query in YOUTUBE_COMMERCE_QUERIES:
            search = await self._get("/search", {
                "part": "snippet", "q": query, "type": "video",
                "videoDuration": "short", "order": "viewCount", "publishedAfter": since,
                "regionCode": country, "relevanceLanguage": languages.get(country, "en"),
                "safeSearch": "moderate", "maxResults": 25,
            })
            search_items.extend(search.get("items") or [])
        ids = [str((item.get("id") or {}).get("videoId") or "") for item in search_items]
        ids = list(dict.fromkeys(video_id for video_id in ids if video_id))[:50]
        payload = {"items": []}
        if ids:
            payload = await self._get("/videos", {
                "part": "snippet,statistics,contentDetails", "id": ",".join(ids), "maxResults": 50,
            })
        videos = []
        for item in payload.get("items") or []:
            snippet, stats = item.get("snippet") or {}, item.get("statistics") or {}
            duration = _iso_duration_seconds((item.get("contentDetails") or {}).get("duration") or "")
            title = snippet.get("title") or "Vidéo"
            description = snippet.get("description") or ""
            tags = [str(tag) for tag in snippet.get("tags") or []]
            hashtags = list(dict.fromkeys(re.findall(r"#[\w-]{3,}", title + " " + description, flags=re.UNICODE)))
            if not 0 < duration <= 180 or not _commerce_relevant(title, description, " ".join(tags), " ".join(hashtags)):
                continue
            thumbs = snippet.get("thumbnails") or {}
            videos.append({
                "video_id": str(item.get("id") or ""),
                "title": title,
                "channel": snippet.get("channelTitle") or "",
                "tags": [*tags, *hashtags],
                "hashtags": hashtags,
                "duration_seconds": duration,
                "views": int(stats.get("viewCount") or 0),
                "likes": int(stats.get("likeCount") or 0),
                "comments": int(stats.get("commentCount") or 0),
                "published_at": snippet.get("publishedAt") or "",
                "image_url": (thumbs.get("medium") or thumbs.get("default") or {}).get("url") or "",
                "url": f"https://www.youtube.com/watch?v={item.get('id')}",
            })
        videos.sort(key=lambda row: row["views"], reverse=True)
        themes = extract_trend_themes(videos)
        scanned_at = datetime.now(timezone.utc).isoformat()
        discovery_id = save_trend_discovery("YOUTUBE_SHORTS_COMMERCE", country, themes, videos[:20])
        return {
            "id": discovery_id, "source": "YOUTUBE_SHORTS_COMMERCE",
            "source_name": "YouTube Shorts · e-commerce", "country": country,
            "scanned_at": scanned_at,
            "observed_count": len(videos), "themes": themes, "items": videos[:8],
            "searched_count": len(ids),
            "seed_hashtags": ["#ecommerce", "#dropshipping", "#amazonfinds", "#tiktokmademebuyit", "#productfinds"],
            "measured_only": True,
            "note": "Shorts récents associés à l'e-commerce et aux produits viraux. Les vues Shorts comptent les démarrages et relectures, pas des ventes.",
        }

    async def scan(self, keyword: str, region: str = "FR") -> dict:
        since = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat().replace("+00:00", "Z")
        search = await self._get("/search", {"part": "snippet", "q": keyword, "type": "video",
                                             "order": "viewCount", "publishedAfter": since,
                                             "regionCode": region, "relevanceLanguage": "fr", "maxResults": 25})
        ids = [str((item.get("id") or {}).get("videoId") or "") for item in search.get("items") or []]
        ids = [video_id for video_id in ids if video_id]
        details = {"items": []}
        if ids:
            details = await self._get("/videos", {"part": "snippet,statistics", "id": ",".join(ids), "maxResults": 25})
        videos, view_counts = [], []
        for item in details.get("items") or []:
            snippet, stats = item.get("snippet") or {}, item.get("statistics") or {}
            views = int(stats.get("viewCount") or 0)
            view_counts.append(views)
            thumbs = snippet.get("thumbnails") or {}
            thumb = (thumbs.get("medium") or thumbs.get("default") or {}).get("url") or ""
            videos.append({
                "title": snippet.get("title") or "Vidéo", "subtitle": snippet.get("channelTitle") or "",
                "metric": f"{views:,} vues".replace(",", " "), "views": views,
                "likes": int(stats.get("likeCount") or 0), "comments": int(stats.get("commentCount") or 0),
                "published_at": snippet.get("publishedAt") or "", "image_url": thumb,
                "url": f"https://www.youtube.com/watch?v={item.get('id')}"
            })
        videos.sort(key=lambda row: row["views"], reverse=True)
        total = int((search.get("pageInfo") or {}).get("totalResults") or len(videos))
        result = {
            "source": "YOUTUBE", "source_name": "YouTube", "keyword": keyword,
            "observed_count": len(videos), "total_results": total,
            "metrics": [
                {"label": "Vidéos observées", "value": len(videos)},
                {"label": "Vues médianes", "value": int(median(view_counts)) if view_counts else 0},
                {"label": "Meilleure vidéo", "value": max(view_counts) if view_counts else 0},
            ],
            "items": videos[:8],
            "note": "Vidéos publiques des 30 derniers jours, triées par vues. Les ventes ne sont pas connues.",
        }
        save_radar_scan({"keyword": keyword, "source": "YOUTUBE", "marketplace": region,
                         "total_results": total, "sellers_sample": len({v["subtitle"] for v in videos}),
                         "top_seller": videos[0]["subtitle"] if videos else "", "payload": result})
        return result


class EtsyClient:
    base_url = "https://openapi.etsy.com/v3/application"

    def __init__(self):
        self.credentials = load_credentials("etsy")

    async def _get(self, path: str, params: dict) -> dict:
        key = str(self.credentials.get("api_key") or "")
        if not key:
            raise IntegrationError("Clé API Etsy manquante")
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.get(self.base_url + path, params=params, headers={"x-api-key": key})
        if response.is_error:
            raise IntegrationError(_error_message(response, "Etsy"))
        return response.json()

    async def test(self) -> dict:
        payload = await self._get("/listings/active", {"limit": 1})
        return {"ok": True, "observed": len(payload.get("results") or [])}

    @staticmethod
    def _money(value: Any) -> tuple[float | None, str]:
        if not isinstance(value, dict):
            return None, "EUR"
        divisor = int(value.get("divisor") or 100)
        return round(float(value.get("amount") or 0) / divisor, 2), str(value.get("currency_code") or "EUR")

    async def scan(self, keyword: str) -> dict:
        payload = await self._get("/listings/active", {"keywords": keyword, "limit": 50,
                                                        "sort_on": "score", "sort_order": "desc"})
        items, prices, shops = [], [], []
        for listing in payload.get("results") or []:
            price, currency = self._money(listing.get("price"))
            if price is not None:
                prices.append(price)
            shops.append(str(listing.get("shop_id") or ""))
            items.append({
                "title": listing.get("title") or "Annonce Etsy",
                "subtitle": f"Boutique {listing.get('shop_id') or '—'}",
                "metric": f"{int(listing.get('num_favorers') or 0)} favoris",
                "favorites": int(listing.get("num_favorers") or 0), "price": price, "currency": currency,
                "image_url": "", "url": listing.get("url") or "",
            })
        items.sort(key=lambda row: row["favorites"], reverse=True)
        total = int(payload.get("count") or len(items))
        currency = next((item["currency"] for item in items if item.get("currency")), "EUR")
        result = {
            "source": "ETSY", "source_name": "Etsy", "keyword": keyword,
            "observed_count": len(items), "total_results": total,
            "metrics": [
                {"label": "Annonces actives", "value": total},
                {"label": "Prix médian", "value": round(median(prices), 2) if prices else None,
                 "format": "money", "currency": currency},
                {"label": "Boutiques observées", "value": len({shop for shop in shops if shop})},
            ],
            "items": items[:8],
            "note": "Annonces et favoris publics. Les recherches, conversions et ventes concurrentes restent privées.",
        }
        save_radar_scan({"keyword": keyword, "source": "ETSY", "marketplace": "ETSY",
                         "total_results": total, "median_price": round(median(prices), 2) if prices else None,
                         "min_price": min(prices) if prices else None, "max_price": max(prices) if prices else None,
                         "sellers_sample": len({shop for shop in shops if shop}), "payload": result})
        return result


def _reach_number(value: str) -> int:
    text = str(value or "0").strip().upper()
    multiplier = 1
    if text.endswith("K"):
        multiplier, text = 1_000, text[:-1]
    elif text.endswith("M"):
        multiplier, text = 1_000_000, text[:-1]
    elif text.endswith("B"):
        multiplier, text = 1_000_000_000, text[:-1]
    try:
        return int(float(text) * multiplier)
    except ValueError:
        return 0


class TikTokClient:
    base_url = "https://open.tiktokapis.com"

    def __init__(self):
        self.credentials = load_credentials("tiktok")

    async def token(self) -> str:
        client_key = str(self.credentials.get("client_key") or "")
        client_secret = str(self.credentials.get("client_secret") or "")
        if not client_key or not client_secret:
            raise IntegrationError("Client Key et Client Secret TikTok manquants")
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(self.base_url + "/v2/oauth/token/",
                                         data={"client_key": client_key, "client_secret": client_secret,
                                               "grant_type": "client_credentials"},
                                         headers={"Content-Type": "application/x-www-form-urlencoded"})
        if response.is_error:
            raise IntegrationError(_error_message(response, "TikTok"))
        payload = response.json()
        if not payload.get("access_token"):
            raise IntegrationError("TikTok n'a pas fourni de jeton d'accès")
        return str(payload["access_token"])

    async def test(self) -> dict:
        await self.token()
        return {"ok": True, "observed": 0}

    async def scan(self, keyword: str, country: str = "FR") -> dict:
        token = await self.token()
        today = date.today()
        body = {
            "filters": {"ad_published_date_range": {"min": (today - timedelta(days=30)).strftime("%Y%m%d"),
                                                        "max": today.strftime("%Y%m%d")},
                        "country_code": country},
            "search_term": keyword[:50], "search_type": "fuzzy_phrase", "max_count": 50,
        }
        fields = ("ad.id,ad.first_shown_date,ad.last_shown_date,ad.status,ad.videos,ad.image_urls,ad.reach,"
                  "advertiser.business_id,advertiser.business_name,advertiser.paid_for_by")
        async with httpx.AsyncClient(timeout=45) as client:
            response = await client.post(self.base_url + "/v2/research/adlib/ad/query/",
                                         params={"fields": fields}, json=body,
                                         headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"})
        if response.is_error:
            raise IntegrationError(_error_message(response, "TikTok"))
        payload = response.json()
        api_error = payload.get("error") or {}
        if api_error.get("code") not in (None, "", "ok"):
            raise IntegrationError("TikTok refuse la recherche : " + str(api_error.get("message") or api_error["code"]))
        ads, advertisers, active, max_reach = [], [], 0, 0
        for row in (payload.get("data") or {}).get("ads") or []:
            ad, advertiser = row.get("ad") or {}, row.get("advertiser") or {}
            reach_text = str((ad.get("reach") or {}).get("unique_users_seen") or "0")
            reach = _reach_number(reach_text)
            max_reach = max(max_reach, reach)
            active += int(str(ad.get("status") or "").lower() == "active")
            advertisers.append(str(advertiser.get("business_name") or ""))
            images = ad.get("image_urls") or []
            videos = ad.get("videos") or []
            media = (images[0] if images else "")
            video_url = (videos[0].get("url") if videos and isinstance(videos[0], dict) else "")
            ads.append({
                "title": advertiser.get("business_name") or "Annonceur TikTok",
                "subtitle": f"{ad.get('first_shown_date') or '—'} → {ad.get('last_shown_date') or '—'}",
                "metric": f"Portée {reach_text}", "reach": reach, "status": ad.get("status") or "",
                "image_url": media, "url": video_url,
            })
        ads.sort(key=lambda row: row["reach"], reverse=True)
        result = {
            "source": "TIKTOK", "source_name": "TikTok Ads UE", "keyword": keyword,
            "observed_count": len(ads), "total_results": len(ads),
            "metrics": [
                {"label": "Publicités observées", "value": len(ads)},
                {"label": "Publicités actives", "value": active},
                {"label": "Portée maximale", "value": max_reach},
            ],
            "items": ads[:8],
            "note": "Publicités TikTok ciblant le pays sur 30 jours. La portée n'est ni une vente ni une conversion.",
        }
        save_radar_scan({"keyword": keyword, "source": "TIKTOK", "marketplace": country,
                         "total_results": len(ads), "sellers_sample": len({x for x in advertisers if x}),
                         "top_seller": ads[0]["title"] if ads else "", "payload": result})
        return result


def _keyword_tokens(keyword: str) -> list[str]:
    return [token for token in keyword.casefold().split() if len(token) > 1]


def _keyword_match(keyword: str, *values: Any) -> bool:
    tokens = _keyword_tokens(keyword)
    haystack = " ".join(str(value or "") for value in values).casefold()
    return not tokens or all(token in haystack for token in tokens)


def _number(value: Any) -> float | None:
    try:
        return float(value) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


class DropXLClient:
    def __init__(self):
        self.credentials = load_credentials("dropxl")
        environment = self.credentials.get("environment", "production")
        self.base_url = "https://sandbox.b2b.dropxl.com" if environment == "sandbox" else "https://b2b.dropxl.com"

    async def _get(self, path: str, params: dict | None = None) -> Any:
        email = str(self.credentials.get("api_email") or "")
        token = str(self.credentials.get("api_token") or "")
        if not email or not token:
            raise IntegrationError("Email API et jeton DropXL manquants")
        async with httpx.AsyncClient(timeout=45) as client:
            response = await client.get(self.base_url + path, params=params or {}, auth=(email, token),
                                        headers={"Accept": "application/json"})
        if response.is_error:
            raise IntegrationError(_error_message(response, "DropXL"))
        return response.json()

    async def test(self) -> dict:
        payload = await self._get("/api_customer/products", {"limit": 1, "offset": 0})
        return {"ok": True, "observed": len(_rows(payload))}

    async def search(self, keyword: str) -> dict:
        rows = _rows(await self._get("/api_customer/products", {"limit": 500, "offset": 0}))
        products = []
        for row in rows:
            if not _keyword_match(keyword, row.get("name"), row.get("category_path"), row.get("code")):
                continue
            stock = _number(row.get("quantity"))
            products.append({
                "provider": "DROPXL", "supplier_sku": str(row.get("code") or row.get("id") or ""),
                "name": str(row.get("name") or "Produit DropXL"), "price": _number(row.get("price")),
                "currency": "EUR", "stock": int(stock) if stock is not None else None, "image_url": "",
                "quality_verified": False,
                "quality_evidence": ["Prix et stock DropXL observés", "Échantillon et conformité à valider"],
            })
            if len(products) >= 12:
                break
        return {"source": "DropXL", "products": products, "total": len(products),
                "note": f"{len(rows)} références européennes ont été contrôlées en lecture seule."}


class PrintfulClient:
    base_url = "https://api.printful.com"

    def __init__(self):
        self.credentials = load_credentials("printful")

    async def _get(self, path: str) -> dict:
        key = str(self.credentials.get("api_key") or "")
        if not key:
            raise IntegrationError("Jeton privé Printful manquant")
        async with httpx.AsyncClient(timeout=45) as client:
            response = await client.get(self.base_url + path,
                                        headers={"Authorization": f"Bearer {key}", "Accept": "application/json"})
        if response.is_error:
            raise IntegrationError(_error_message(response, "Printful"))
        return response.json()

    async def test(self) -> dict:
        payload = await self._get("/stores")
        return {"ok": True, "observed": len(_rows(payload))}

    async def search(self, keyword: str) -> dict:
        rows = _rows(await self._get("/products"))
        products = []
        for row in rows:
            if not _keyword_match(keyword, row.get("title"), row.get("type_name"), row.get("brand"), row.get("model")):
                continue
            products.append({
                "provider": "PRINTFUL", "supplier_sku": f"PF-{row.get('id')}",
                "name": str(row.get("title") or row.get("type_name") or "Produit Printful"),
                "price": None, "currency": str(row.get("currency") or "EUR"), "stock": None,
                "image_url": str(row.get("image") or ""), "quality_verified": False,
                "quality_evidence": ["Produit personnalisable", "Coût final après variante, impression et livraison"],
            })
            if len(products) >= 12:
                break
        return {"source": "Printful", "products": products, "total": len(products),
                "note": "Catalogue POD réel ; le prix final dépend du modèle, de l'impression et de la destination."}


class PrintifyClient:
    base_url = "https://api.printify.com"

    def __init__(self):
        self.credentials = load_credentials("printify")

    async def _get(self, path: str) -> Any:
        key = str(self.credentials.get("api_key") or "")
        if not key:
            raise IntegrationError("Jeton API Printify manquant")
        async with httpx.AsyncClient(timeout=45) as client:
            response = await client.get(self.base_url + path,
                                        headers={"Authorization": f"Bearer {key}", "Accept": "application/json"})
        if response.is_error:
            raise IntegrationError(_error_message(response, "Printify"))
        return response.json()

    async def test(self) -> dict:
        payload = await self._get("/v1/shops.json")
        return {"ok": True, "observed": len(_rows(payload))}

    async def search(self, keyword: str) -> dict:
        rows = _rows(await self._get("/v1/catalog/blueprints.json"))
        products = []
        for row in rows:
            if not _keyword_match(keyword, row.get("title"), row.get("description"), row.get("brand"), row.get("model")):
                continue
            images = row.get("images") if isinstance(row.get("images"), list) else []
            products.append({
                "provider": "PRINTIFY", "supplier_sku": f"PY-{row.get('id')}",
                "name": str(row.get("title") or "Produit Printify"), "price": None, "currency": "EUR",
                "stock": None, "image_url": str(images[0] if images else ""), "quality_verified": False,
                "quality_evidence": ["Blueprint Printify", "Atelier, variante, coût et livraison à sélectionner"],
            })
            if len(products) >= 12:
                break
        return {"source": "Printify", "products": products, "total": len(products),
                "note": "Catalogue POD réel ; comparez ensuite les ateliers, variantes et frais de livraison."}


class GelatoClient:
    base_url = "https://product.gelatoapis.com"

    def __init__(self):
        self.credentials = load_credentials("gelato")

    async def _get(self, path: str) -> Any:
        key = str(self.credentials.get("api_key") or "")
        if not key:
            raise IntegrationError("Clé API Gelato manquante")
        async with httpx.AsyncClient(timeout=45) as client:
            response = await client.get(self.base_url + path,
                                        headers={"X-API-KEY": key, "Accept": "application/json"})
        if response.is_error:
            raise IntegrationError(_error_message(response, "Gelato"))
        return response.json()

    async def test(self) -> dict:
        payload = await self._get("/v3/catalogs")
        return {"ok": True, "observed": len(_rows(payload))}

    async def search(self, keyword: str) -> dict:
        rows = _rows(await self._get("/v3/catalogs"))
        products = []
        for row in rows:
            if not _keyword_match(keyword, row.get("title"), row.get("catalogUid")):
                continue
            products.append({
                "provider": "GELATO", "supplier_sku": f"GE-{row.get('catalogUid')}",
                "name": str(row.get("title") or row.get("catalogUid") or "Catalogue Gelato"),
                "price": None, "currency": "EUR", "stock": None, "image_url": "", "quality_verified": False,
                "quality_evidence": ["Catalogue d'impression Gelato", "Produit et prix à configurer"],
            })
            if len(products) >= 12:
                break
        return {"source": "Gelato", "products": products, "total": len(products),
                "note": "Familles POD disponibles ; le produit exact et son coût sont calculés après configuration."}


async def test_provider(provider: str) -> dict:
    clients = {
        "amazon": AmazonRadarClient,
        "youtube": YouTubeClient, "etsy": EtsyClient, "tiktok": TikTokClient,
        "dropxl": DropXLClient, "printful": PrintfulClient,
        "printify": PrintifyClient, "gelato": GelatoClient,
    }
    if provider not in clients:
        raise IntegrationError("Source inconnue")
    try:
        result = await clients[provider]().test()
    except Exception as exc:
        message = str(exc) or "Connexion refusée"
        save_credentials(provider, {"last_error": message, "verified_at": "-"})
        raise IntegrationError(message) from exc
    current = load_credentials(provider)
    current["verified_at"] = datetime.now(timezone.utc).isoformat()
    current["last_error"] = ""
    kv_set(f"integration:{provider}", encrypt(json.dumps(current, ensure_ascii=False)) or "")
    return result


async def scan_connected_sources(keyword: str, sources: list[str], country: str = "FR") -> dict:
    calls = []
    selected = []
    unavailable = []
    for provider in dict.fromkeys(sources):
        status = connection_status(provider)
        if not status["connected"]:
            unavailable.append({"source": provider, "message": "Source non connectée"})
            continue
        if provider == "youtube":
            calls.append(YouTubeClient().scan(keyword, country))
        elif provider == "etsy":
            calls.append(EtsyClient().scan(keyword))
        elif provider == "tiktok":
            calls.append(TikTokClient().scan(keyword, country))
        else:
            continue
        selected.append(provider)
    if not calls:
        raise IntegrationError("Aucune source de tendances sélectionnée n'est connectée")
    raw = await asyncio.gather(*calls, return_exceptions=True)
    results, errors = [], unavailable
    for provider, item in zip(selected, raw):
        if isinstance(item, Exception):
            errors.append({"source": provider, "message": str(item)})
        else:
            results.append(item)
    if not results:
        raise IntegrationError(errors[0]["message"] if errors else "Aucun résultat disponible")
    return {"keyword": keyword, "results": results, "errors": errors, "measured_only": True}


async def match_connected_suppliers(keyword: str) -> tuple[list[dict], list[dict]]:
    calls, providers = [], []
    supplier_clients = {
        "dropxl": DropXLClient, "printful": PrintfulClient,
        "printify": PrintifyClient, "gelato": GelatoClient,
    }
    for provider, client in supplier_clients.items():
        if connection_status(provider)["connected"]:
            calls.append(client().search(keyword))
            providers.append(provider)
    raw = await asyncio.gather(*calls, return_exceptions=True) if calls else []
    groups, errors = [], []
    for provider, item in zip(providers, raw):
        if isinstance(item, Exception):
            errors.append({"source": provider, "message": str(item)})
        else:
            groups.append(item)
    return groups, errors
