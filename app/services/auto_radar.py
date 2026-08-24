"""Automatic eBay-first product opportunity discovery.

The engine never invents search volume or competitor conversion. It discovers
candidate product phrases from official eBay category and best-selling data,
measures each candidate through the eBay Browse API, then stores explainable
eBay US opportunities and creates persistent in-app alerts.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import math
import re
import unicodedata
from collections import Counter, defaultdict
from datetime import datetime, timezone
from statistics import median
from typing import Any, Awaitable
from urllib.parse import quote

from app.config import get_settings
from app.services.db import add_alert, conn, previous_radar_scan, save_radar_scan, utc_now
from app.services.ebay import EbayClient, EbayError


AUTO_ALERT_THRESHOLD = 75
MAX_CATEGORIES = 5
MAX_CANDIDATES = 8
_AUTO_LOCK = asyncio.Lock()

CATEGORY_GROUPS = (
    ("Maison", ("maison", "home", "household", "haushalt", "hogar", "casa")),
    ("Cuisine", ("cuisine", "kitchen", "küche", "cocina")),
    ("Auto", ("pièces et accessoires", "auto", "moto", "vehicle parts", "autoteile", "recambios")),
    ("Animaux", ("animaux", "pet supplies", "haustier", "mascotas", "animali")),
    ("Sport", ("sports", "fitness", "sporting goods", "sportartikel")),
    ("Beauté", ("beauté", "beauty", "pflege", "belleza", "bellezza")),
    ("Jardin", ("jardin", "garden", "garten", "jardín", "giardino")),
    ("Bureau", ("bureau", "office", "computing", "informatique", "computer")),
)

EXCLUDED_CATEGORY_TERMS = {
    "immobilier", "real estate", "véhicules", "cars", "automobiles", "billets", "tickets",
    "monnaies", "coins", "timbres", "stamps", "art", "antiquités", "antiques", "vêtements",
    "clothing", "fashion", "bijoux", "jewelry", "montres", "watches", "adult", "armes", "weapons",
}

FALLBACK_DISCOVERY_SEEDS = (
    ("Maison", "rangement maison"),
    ("Cuisine", "accessoire cuisine"),
    ("Auto", "accessoire voiture"),
    ("Animaux", "accessoire animaux"),
    ("Sport", "fitness maison"),
    ("Jardin", "accessoire jardin"),
)

TITLE_STOPWORDS = {
    "avec", "sans", "pour", "dans", "sur", "sous", "chez", "vers", "tout", "tous", "toute", "toutes",
    "les", "des", "une", "un", "du", "de", "la", "le", "et", "ou", "plus", "lot", "pack", "piece",
    "pieces", "pièce", "pièces", "neuf", "neuve", "nouveau", "nouvelle", "livraison", "gratuite", "gratuit",
    "france", "français", "compatible", "universel", "universelle", "qualité", "premium", "original",
    "noir", "noire", "blanc", "blanche", "rouge", "bleu", "verte", "vert", "rose", "gris", "grise",
    "taille", "petit", "petite", "grand", "grande", "mini", "maxi", "modèle", "modele", "version",
    "the", "and", "for", "with", "without", "from", "into", "new", "brand", "free", "shipping", "fast",
    "black", "white", "red", "blue", "green", "grey", "gray", "pink", "small", "large", "size", "model",
    "set", "kit", "pcs", "piece", "pieces", "universal", "compatible", "genuine", "premium", "quality",
    "usb", "led", "pro", "plus", "ultra", "2024", "2025", "2026", "2027",
}


def _normalize(value: str) -> str:
    return unicodedata.normalize("NFKD", str(value or "")).encode("ascii", "ignore").decode().casefold()


def _tokens(title: str) -> list[str]:
    normalized = _normalize(title)
    tokens = []
    for token in re.findall(r"[a-z][a-z0-9-]{2,}", normalized):
        if token in TITLE_STOPWORDS or token.isdigit():
            continue
        if re.fullmatch(r"\d+(?:mm|cm|m|ml|l|w|v|kg|g|gb|tb)", token):
            continue
        if sum(char.isdigit() for char in token) >= 2:
            continue
        tokens.append(token)
    return tokens[:12]


def _title_phrases(title: str) -> list[str]:
    tokens = _tokens(title)
    phrases: list[str] = []
    for size in (3, 2):
        for index in range(max(0, len(tokens) - size + 1)):
            phrase_tokens = tokens[index:index + size]
            if len(set(phrase_tokens)) != len(phrase_tokens):
                continue
            phrase = " ".join(phrase_tokens)
            if 7 <= len(phrase) <= 55:
                phrases.append(phrase)
    return list(dict.fromkeys(phrases))[:10]


def _safe_float(value: Any) -> float | None:
    try:
        return float(value) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _safe_int(value: Any) -> int | None:
    try:
        return int(value) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _parse_date(value: Any) -> datetime | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None


def _age_days(value: Any) -> float | None:
    created = _parse_date(value)
    if not created:
        return None
    return max((datetime.now(timezone.utc) - created).total_seconds() / 86400, 0.25)


def _ensure_tables() -> None:
    with conn() as database:
        database.executescript(
            """
            CREATE TABLE IF NOT EXISTS radar_auto_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                trigger TEXT NOT NULL,
                marketplace TEXT NOT NULL,
                status TEXT NOT NULL,
                categories_scanned INTEGER NOT NULL DEFAULT 0,
                candidates_measured INTEGER NOT NULL DEFAULT 0,
                opportunities_found INTEGER NOT NULL DEFAULT 0,
                alerts_created INTEGER NOT NULL DEFAULT 0,
                errors_json TEXT NOT NULL DEFAULT '[]',
                started_at TEXT NOT NULL,
                finished_at TEXT
            );

            CREATE TABLE IF NOT EXISTS radar_opportunities (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                opportunity_key TEXT NOT NULL,
                marketplace TEXT NOT NULL,
                keyword TEXT NOT NULL,
                title TEXT NOT NULL,
                category_id TEXT NOT NULL DEFAULT '',
                category_name TEXT NOT NULL DEFAULT '',
                score REAL NOT NULL,
                score_change REAL,
                verdict TEXT NOT NULL,
                confidence TEXT NOT NULL,
                demand_score REAL NOT NULL DEFAULT 0,
                competition_score REAL NOT NULL DEFAULT 0,
                momentum_score REAL NOT NULL DEFAULT 0,
                market_quality_score REAL NOT NULL DEFAULT 0,
                total_results INTEGER NOT NULL DEFAULT 0,
                median_price REAL,
                currency TEXT NOT NULL DEFAULT 'USD',
                sellers_sample INTEGER NOT NULL DEFAULT 0,
                top_seller_share REAL NOT NULL DEFAULT 0,
                sold_quantity INTEGER,
                sales_velocity REAL,
                recent_listing_share REAL,
                item_url TEXT NOT NULL DEFAULT '',
                image_url TEXT NOT NULL DEFAULT '',
                sources_json TEXT NOT NULL DEFAULT '[]',
                factors_json TEXT NOT NULL DEFAULT '[]',
                payload_json TEXT NOT NULL DEFAULT '{}',
                first_seen_at TEXT NOT NULL,
                last_seen_at TEXT NOT NULL,
                last_alert_score REAL,
                dismissed INTEGER NOT NULL DEFAULT 0,
                UNIQUE(opportunity_key, marketplace)
            );
            """
        )


def _start_run(trigger: str, marketplace: str) -> int:
    _ensure_tables()
    with conn() as database:
        cursor = database.execute(
            "INSERT INTO radar_auto_runs(trigger,marketplace,status,started_at) VALUES(?,?,?,?)",
            (trigger, marketplace, "RUNNING", utc_now()),
        )
        return int(cursor.lastrowid)


def _finish_run(run_id: int, *, status: str, categories: int, candidates: int,
                opportunities: int, alerts: int, errors: list[dict[str, Any]]) -> None:
    with conn() as database:
        database.execute(
            """
            UPDATE radar_auto_runs SET status=?,categories_scanned=?,candidates_measured=?,
                opportunities_found=?,alerts_created=?,errors_json=?,finished_at=? WHERE id=?
            """,
            (status, categories, candidates, opportunities, alerts,
             json.dumps(errors, ensure_ascii=False), utc_now(), run_id),
        )


def _decode_row(row: dict[str, Any]) -> dict[str, Any]:
    result = dict(row)
    for source, target, default in (
        ("sources_json", "sources", []),
        ("factors_json", "factors", []),
        ("payload_json", "payload", {}),
    ):
        raw = result.pop(source, None)
        try:
            result[target] = json.loads(raw or json.dumps(default))
        except (TypeError, json.JSONDecodeError):
            result[target] = default
    result.pop("social_score", None)
    result.pop("social_json", None)
    result["dismissed"] = bool(result.get("dismissed"))
    return result


def list_auto_opportunities(limit: int = 30, include_dismissed: bool = False) -> list[dict[str, Any]]:
    _ensure_tables()
    where = "WHERE marketplace='EBAY_US' AND currency='USD'"
    if not include_dismissed:
        where += " AND dismissed=0"
    with conn() as database:
        rows = database.execute(
            f"SELECT * FROM radar_opportunities {where} ORDER BY score DESC,last_seen_at DESC LIMIT ?",
            (min(max(int(limit), 1), 100),),
        ).fetchall()
    return [_decode_row(dict(row)) for row in rows]


def latest_auto_run() -> dict[str, Any] | None:
    _ensure_tables()
    with conn() as database:
        row = database.execute(
            "SELECT * FROM radar_auto_runs WHERE marketplace='EBAY_US' ORDER BY id DESC LIMIT 1"
        ).fetchone()
    if not row:
        return None
    result = dict(row)
    try:
        result["errors"] = json.loads(result.pop("errors_json") or "[]")
    except json.JSONDecodeError:
        result["errors"] = []
    return result


def dismiss_auto_opportunity(opportunity_id: int) -> bool:
    _ensure_tables()
    with conn() as database:
        return database.execute(
            "UPDATE radar_opportunities SET dismissed=1 WHERE id=? AND marketplace='EBAY_US' AND currency='USD'",
            (opportunity_id,),
        ).rowcount > 0


def auto_radar_status() -> dict[str, Any]:
    settings = get_settings()
    ready = bool(
        settings.ebay_effective_env == "production"
        and settings.ebay_client_id
        and settings.ebay_client_secret
    )
    opportunities = list_auto_opportunities(100)
    return {
        "enabled": settings.radar_auto_enabled,
        "interval_hours": max(settings.radar_auto_hours, 6),
        "ready": ready,
        "running": _AUTO_LOCK.locked(),
        "marketplace": settings.ebay_marketplace_id,
        "last_run": latest_auto_run(),
        "opportunity_count": len(opportunities),
        "high_score_count": sum(1 for row in opportunities if float(row.get("score") or 0) >= AUTO_ALERT_THRESHOLD),
        "method": "EBAY_US_ONLY_V2",
        "note": "Découverte fondée uniquement sur les catégories, annonces et signaux officiels eBay US.",
    }


def select_discovery_categories(tree: dict[str, Any], limit: int = MAX_CATEGORIES) -> list[dict[str, str]]:
    root = tree.get("rootCategoryNode") if isinstance(tree, dict) else None
    children = (root or {}).get("childCategoryTreeNodes") or []
    rows = []
    for node in children:
        category = node.get("category") if isinstance(node, dict) else None
        if not isinstance(category, dict):
            continue
        category_id = str(category.get("categoryId") or "").strip()
        name = str(category.get("categoryName") or "").strip()
        if not category_id or not name:
            continue
        normalized = _normalize(name)
        if any(term in normalized for term in EXCLUDED_CATEGORY_TERMS):
            continue
        rows.append({"id": category_id, "name": name, "normalized": normalized})

    selected: list[dict[str, str]] = []
    used: set[str] = set()
    for label, hints in CATEGORY_GROUPS:
        match = next(
            (row for row in rows if row["id"] not in used and any(_normalize(hint) in row["normalized"] for hint in hints)),
            None,
        )
        if match:
            selected.append({"id": match["id"], "name": match["name"], "group": label})
            used.add(match["id"])
        if len(selected) >= limit:
            break
    for row in rows:
        if len(selected) >= limit:
            break
        if row["id"] not in used:
            selected.append({"id": row["id"], "name": row["name"], "group": row["name"]})
            used.add(row["id"])
    return selected


async def _limited(coroutines: list[Awaitable[Any]], concurrency: int = 5) -> list[Any]:
    semaphore = asyncio.Semaphore(max(concurrency, 1))

    async def run(coroutine: Awaitable[Any]) -> Any:
        async with semaphore:
            try:
                return await coroutine
            except Exception as exc:  # the caller receives the exception as data
                return exc

    return await asyncio.gather(*(run(coroutine) for coroutine in coroutines))


async def _load_category_tree(client: EbayClient, marketplace: str) -> dict[str, Any]:
    tree_id = await client.get_default_category_tree_id(marketplace)
    return await client.public_request(
        "GET", f"/commerce/taxonomy/v1/category_tree/{tree_id}", marketplace_id=marketplace
    )


async def _browse_category(client: EbayClient, category: dict[str, str], marketplace: str,
                           sort: str | None = None) -> dict[str, Any]:
    params: dict[str, Any] = {"category_ids": category["id"], "limit": 35}
    if sort:
        params["sort"] = sort
    payload = await client.public_request(
        "GET", "/buy/browse/v1/item_summary/search", params=params, marketplace_id=marketplace
    )
    return {"category": category, "sort": sort or "best_match", "items": payload.get("itemSummaries") or []}


async def _browse_seed(client: EbayClient, group: str, query: str, marketplace: str,
                       sort: str | None = None) -> dict[str, Any]:
    params: dict[str, Any] = {"q": query, "limit": 35}
    if sort:
        params["sort"] = sort
    payload = await client.public_request(
        "GET", "/buy/browse/v1/item_summary/search", params=params, marketplace_id=marketplace
    )
    return {
        "category": {"id": "", "name": group, "group": group},
        "sort": sort or "best_match",
        "items": payload.get("itemSummaries") or [],
    }


async def _marketing_products(client: EbayClient, category: dict[str, str], marketplace: str) -> dict[str, Any]:
    payload = await client.public_request(
        "GET",
        "/buy/marketing/v1/merchandised_product",
        params={"category_id": category["id"], "metric_name": "BEST_SELLING"},
        marketplace_id=marketplace,
    )
    return {"category": category, "products": payload.get("merchandisedProducts") or []}


def extract_candidate_phrases(browse_rows: list[dict[str, Any]], marketing_rows: list[dict[str, Any]],
                              limit: int = MAX_CANDIDATES) -> list[dict[str, Any]]:
    weights: Counter[str] = Counter()
    mentions: Counter[str] = Counter()
    sellers: dict[str, set[str]] = defaultdict(set)
    categories: dict[str, Counter[str]] = defaultdict(Counter)
    examples: dict[str, list[dict[str, Any]]] = defaultdict(list)
    sources: dict[str, set[str]] = defaultdict(set)
    marketing_rank: dict[str, int] = {}

    for row in browse_rows:
        category = row.get("category") or {}
        category_name = str(category.get("name") or category.get("group") or "eBay")
        weight = 1.35 if row.get("sort") == "newlyListed" else 1.0
        for item in row.get("items") or []:
            title = str(item.get("title") or "")
            seller = str((item.get("seller") or {}).get("username") or "")
            for phrase in set(_title_phrases(title)):
                weights[phrase] += weight
                mentions[phrase] += 1
                if seller:
                    sellers[phrase].add(seller)
                categories[phrase][category_name] += 1
                sources[phrase].add("eBay nouvelles annonces" if row.get("sort") == "newlyListed" else "eBay Best Match")
                if len(examples[phrase]) < 4:
                    examples[phrase].append(item)

    rank = 0
    for row in marketing_rows:
        category = row.get("category") or {}
        category_name = str(category.get("name") or category.get("group") or "eBay")
        for product in row.get("products") or []:
            rank += 1
            title = str(product.get("title") or "")
            phrases = _title_phrases(title)
            if not phrases:
                continue
            for phrase in phrases[:4]:
                weights[phrase] += max(6.0 - rank * 0.08, 2.0)
                mentions[phrase] += 1
                categories[phrase][category_name] += 1
                sources[phrase].add("eBay Best Selling")
                marketing_rank[phrase] = min(marketing_rank.get(phrase, rank), rank)
                if len(examples[phrase]) < 4:
                    examples[phrase].append({
                        "title": title,
                        "image": product.get("image") or {},
                        "epid": product.get("epid"),
                        "marketing": True,
                    })

    ranked = []
    for phrase, weight in weights.items():
        if mentions[phrase] < 2 and phrase not in marketing_rank:
            continue
        category_name = categories[phrase].most_common(1)[0][0] if categories[phrase] else "eBay"
        distinct_sellers = len(sellers[phrase])
        rank_score = weight + min(distinct_sellers, 8) * 0.35 + len(categories[phrase]) * 0.4
        ranked.append((rank_score, phrase, category_name))
    ranked.sort(reverse=True)

    selected: list[dict[str, Any]] = []
    selected_tokens: list[set[str]] = []
    for rank_score, phrase, category_name in ranked:
        tokens = set(phrase.split())
        if any(len(tokens & existing) / max(len(tokens | existing), 1) >= 0.66 for existing in selected_tokens):
            continue
        sample = examples[phrase][0] if examples[phrase] else {}
        image = sample.get("image") or {}
        selected.append({
            "keyword": phrase,
            "seed_score": round(rank_score, 2),
            "seed_mentions": mentions[phrase],
            "seed_sellers": len(sellers[phrase]),
            "category_name": category_name,
            "marketing_rank": marketing_rank.get(phrase),
            "sources": sorted(sources[phrase]),
            "sample_title": str(sample.get("title") or phrase).strip(),
            "sample_image": str(image.get("imageUrl") or sample.get("image_url") or ""),
        })
        selected_tokens.append(tokens)
        if len(selected) >= limit:
            break
    return selected


async def _measure_candidate(client: EbayClient, candidate: dict[str, Any], marketplace: str) -> dict[str, Any]:
    if marketplace != "EBAY_US":
        raise ValueError("La mesure automatique est limitée à eBay US")
    payload = await client.public_request(
        "GET", "/buy/browse/v1/item_summary/search",
        params={"q": candidate["keyword"], "limit": 50}, marketplace_id=marketplace,
    )
    items = [
        row for row in payload.get("itemSummaries") or []
        if str((row.get("price") or {}).get("currency") or "USD").upper() == "USD"
    ]
    prices: list[float] = []
    sellers: list[str] = []
    recent = 0
    dated = 0
    fixed = 0
    origins: list[datetime] = []
    for item in items:
        price_block = item.get("price") or {}
        price = _safe_float(price_block.get("value"))
        if price is not None:
            prices.append(price)
        seller = str((item.get("seller") or {}).get("username") or "").strip()
        if seller:
            sellers.append(seller)
        options = item.get("buyingOptions") or []
        if "FIXED_PRICE" in options:
            fixed += 1
        origin = _parse_date(item.get("itemOriginDate"))
        if origin:
            dated += 1
            origins.append(origin)
            if (datetime.now(timezone.utc) - origin).total_seconds() <= 30 * 86400:
                recent += 1

    seller_counts = Counter(sellers)
    top_seller, top_count = seller_counts.most_common(1)[0] if seller_counts else ("", 0)
    representative = next((item for item in items if item.get("itemId") and "FIXED_PRICE" in (item.get("buyingOptions") or [])),
                          next((item for item in items if item.get("itemId")), {}))
    detail: dict[str, Any] = {}
    if representative.get("itemId"):
        try:
            item_id = quote(str(representative["itemId"]), safe="")
            detail = await client.public_request(
                "GET", f"/buy/browse/v1/item/{item_id}", marketplace_id=marketplace
            )
        except EbayError:
            detail = {}

    sold_values = [
        _safe_int(row.get("estimatedSoldQuantity"))
        for row in detail.get("estimatedAvailabilities") or []
        if isinstance(row, dict)
    ]
    sold_values = [value for value in sold_values if value is not None]
    sold_quantity = max(sold_values) if sold_values else None
    origin_value = detail.get("itemOriginDate") or representative.get("itemOriginDate")
    age_days = _age_days(origin_value)
    sales_velocity = round(sold_quantity / age_days, 3) if sold_quantity is not None and age_days else None
    result = {
        "keyword": candidate["keyword"],
        "source": "EBAY_AUTO",
        "marketplace": marketplace,
        "marketplace_name": marketplace,
        "total_results": int(payload.get("total") or len(items)),
        "currency": "USD",
        "median_price": round(median(prices), 2) if prices else None,
        "min_price": round(min(prices), 2) if prices else None,
        "max_price": round(max(prices), 2) if prices else None,
        "sellers_sample": len(seller_counts),
        "top_seller": top_seller,
        "top_seller_share": round(top_count / len(sellers) * 100, 1) if sellers else 0,
        "recent_listing_share": round(recent / dated * 100, 1) if dated else None,
        "fixed_price_share": round(fixed / len(items) * 100, 1) if items else None,
        "sold_quantity": sold_quantity,
        "sales_velocity": sales_velocity,
        "listing_age_days": round(age_days, 1) if age_days else None,
        "item_url": str(detail.get("itemWebUrl") or representative.get("itemWebUrl") or ""),
        "image_url": str(((detail.get("image") or representative.get("image") or {}).get("imageUrl")) or candidate.get("sample_image") or ""),
        "representative_title": str(detail.get("title") or representative.get("title") or candidate.get("sample_title") or candidate["keyword"]),
        "items_observed": len(items),
    }
    scan_id = save_radar_scan(result)
    previous = previous_radar_scan(candidate["keyword"], "EBAY_AUTO", marketplace, scan_id)
    result["history_available"] = bool(previous)
    result["listing_change_percent"] = None
    if previous and int(previous.get("total_results") or 0) > 0:
        result["listing_change_percent"] = round(
            (result["total_results"] - int(previous["total_results"])) /
            int(previous["total_results"]) * 100,
            1,
        )
    return result


def score_auto_opportunity(candidate: dict[str, Any], measurement: dict[str, Any]) -> dict[str, Any]:
    factors: list[dict[str, Any]] = []

    marketing_rank = _safe_int(candidate.get("marketing_rank"))
    marketing_points = max(0.0, 18 - (marketing_rank - 1) * 0.55) if marketing_rank else 0.0
    velocity = _safe_float(measurement.get("sales_velocity"))
    if velocity is None:
        velocity_points = 0.0
        velocity_detail = "Quantité vendue estimée non fournie par l'annonce observée"
    elif velocity >= 5:
        velocity_points = 17
        velocity_detail = f"Meilleure annonce observée : {velocity:.1f} vente(s) estimée(s)/jour"
    elif velocity >= 2:
        velocity_points = 14
        velocity_detail = f"Meilleure annonce observée : {velocity:.1f} vente(s) estimée(s)/jour"
    elif velocity >= 0.8:
        velocity_points = 10
        velocity_detail = f"Meilleure annonce observée : {velocity:.1f} vente(s) estimée(s)/jour"
    elif velocity >= 0.2:
        velocity_points = 5
        velocity_detail = f"Meilleure annonce observée : {velocity:.2f} vente(s) estimée(s)/jour"
    else:
        velocity_points = 1
        velocity_detail = "Vitesse de vente estimée faible sur l'annonce observée"
    demand = min(marketing_points + velocity_points, 35)
    demand_detail = []
    if marketing_rank:
        demand_detail.append(f"Best Selling eBay rang {marketing_rank}")
    demand_detail.append(velocity_detail)
    factors.append({"label": "Demande observée", "earned": round(demand, 1), "maximum": 35,
                    "detail": " · ".join(demand_detail)})

    total = int(measurement.get("total_results") or 0)
    if total <= 0:
        listing_points = 0
    elif total < 20:
        listing_points = 8
    elif total <= 100:
        listing_points = 18
    elif total <= 500:
        listing_points = 20
    elif total <= 1500:
        listing_points = 14
    elif total <= 5000:
        listing_points = 8
    else:
        listing_points = 3
    concentration = float(measurement.get("top_seller_share") or 0)
    concentration_points = 5 if concentration <= 12 else 4 if concentration <= 22 else 2 if concentration <= 40 else 0.5
    competition = min(listing_points + concentration_points, 25)
    factors.append({"label": "Concurrence", "earned": round(competition, 1), "maximum": 25,
                    "detail": f"{total:,} annonce(s) · premier vendeur ≈ {concentration:.1f}%".replace(",", " ")})

    recent_share = _safe_float(measurement.get("recent_listing_share"))
    momentum = min((recent_share or 0) / 100 * 6, 6)
    age_days = _safe_float(measurement.get("listing_age_days"))
    if velocity and age_days and age_days <= 60:
        momentum += min(4, math.log10(velocity * 10 + 1) * 2.5)
    momentum = round(min(momentum, 10), 1)
    factors.append({"label": "Momentum", "earned": momentum, "maximum": 10,
                    "detail": (f"{recent_share:.1f}% d'annonces observées ont moins de 30 jours" if recent_share is not None
                               else "Dates de mise en ligne insuffisantes")})

    price = _safe_float(measurement.get("median_price"))
    price_points = 5 if price is not None and 15 <= price <= 80 else 4 if price is not None and 8 <= price <= 150 else 1 if price is not None else 0
    seller_points = 3 if int(measurement.get("sellers_sample") or 0) >= 15 else 2 if int(measurement.get("sellers_sample") or 0) >= 5 else 0
    fixed_share = _safe_float(measurement.get("fixed_price_share"))
    fixed_points = 2 if fixed_share is not None and fixed_share >= 80 else 1 if fixed_share is not None and fixed_share >= 50 else 0
    market_quality = min(price_points + seller_points + fixed_points, 10)
    factors.append({"label": "Qualité du marché", "earned": round(market_quality, 1), "maximum": 10,
                    "detail": f"Prix médian {price:.2f} {measurement.get('currency') or 'USD'} · {measurement.get('sellers_sample') or 0} vendeur(s)" if price is not None
                              else "Prix médian non disponible"})

    confidence = 0.0
    confidence += 8 if marketing_rank else 0
    confidence += 8 if measurement.get("sold_quantity") is not None else 0
    confidence += 4 if measurement.get("history_available") else 0
    factors.append({"label": "Confiance des données eBay", "earned": confidence, "maximum": 20,
                    "detail": "Best Selling, quantité vendue estimée et historique augmentent la confiance"})

    score = round(min(demand + competition + momentum + market_quality + confidence, 100))
    if score >= 75:
        verdict = "À TESTER"
    elif score >= 60:
        verdict = "À CREUSER"
    elif score >= 45:
        verdict = "SURVEILLER"
    else:
        verdict = "FAIBLE"
    confidence_label = "Élevée" if confidence >= 16 else "Moyenne" if confidence >= 8 else "Faible"
    return {
        "score": score,
        "verdict": verdict,
        "confidence": confidence_label,
        "demand_score": round(demand, 1),
        "competition_score": round(competition, 1),
        "momentum_score": momentum,
        "market_quality_score": round(market_quality, 1),
        "factors": factors,
        "method": "EBAY_US_ONLY_V2",
        "meaning": (
            "Score fondé uniquement sur les catégories eBay US, les annonces actives, la quantité vendue estimée "
            "lorsqu'elle est fournie et l'historique observé. Ce n'est pas un volume exact de recherches ni le "
            "chiffre d'affaires d'un concurrent."
        ),
    }


def _upsert_opportunity(
    candidate: dict[str, Any],
    measurement: dict[str, Any],
    score: dict[str, Any],
    marketplace: str,
) -> tuple[dict[str, Any], bool]:
    if marketplace != "EBAY_US":
        raise ValueError("Seules les opportunités eBay US sont autorisées")
    if str(measurement.get("currency") or "").upper() != "USD":
        raise ValueError("Seules les opportunités en USD sont autorisées")
    _ensure_tables()
    key_raw = f"{marketplace}|{_normalize(candidate['keyword'])}"
    opportunity_key = hashlib.sha256(key_raw.encode()).hexdigest()[:24]
    now = utc_now()
    with conn() as database:
        existing_row = database.execute(
            "SELECT * FROM radar_opportunities WHERE opportunity_key=? AND marketplace=?",
            (opportunity_key, marketplace),
        ).fetchone()
        existing = dict(existing_row) if existing_row else None
        previous_score = float(existing.get("score") or 0) if existing else None
        score_change = round(score["score"] - previous_score, 1) if previous_score is not None else None
        first_seen = existing.get("first_seen_at") if existing else now
        last_alert_score = existing.get("last_alert_score") if existing else None
        alert_needed = bool(
            score["score"] >= AUTO_ALERT_THRESHOLD
            and (last_alert_score is None or score["score"] >= float(last_alert_score) + 8)
        )
        values = {
            "opportunity_key": opportunity_key,
            "marketplace": marketplace,
            "keyword": candidate["keyword"],
            "title": measurement.get("representative_title") or candidate.get("sample_title") or candidate["keyword"],
            "category_id": str(candidate.get("category_id") or ""),
            "category_name": str(candidate.get("category_name") or ""),
            "score": score["score"],
            "score_change": score_change,
            "verdict": score["verdict"],
            "confidence": score["confidence"],
            "demand_score": score["demand_score"],
            "competition_score": score["competition_score"],
            "momentum_score": score["momentum_score"],
            "market_quality_score": score["market_quality_score"],
            "total_results": int(measurement.get("total_results") or 0),
            "median_price": measurement.get("median_price"),
            "currency": "USD",
            "sellers_sample": int(measurement.get("sellers_sample") or 0),
            "top_seller_share": float(measurement.get("top_seller_share") or 0),
            "sold_quantity": measurement.get("sold_quantity"),
            "sales_velocity": measurement.get("sales_velocity"),
            "recent_listing_share": measurement.get("recent_listing_share"),
            "item_url": measurement.get("item_url") or "",
            "image_url": measurement.get("image_url") or candidate.get("sample_image") or "",
            "sources_json": json.dumps(candidate.get("sources") or [], ensure_ascii=False),
            "factors_json": json.dumps(score.get("factors") or [], ensure_ascii=False),
            "payload_json": json.dumps({"candidate": candidate, "measurement": measurement, "score": score}, ensure_ascii=False),
            "first_seen_at": first_seen,
            "last_seen_at": now,
            "last_alert_score": score["score"] if alert_needed else last_alert_score,
        }
        if existing:
            assignments = ",".join(f"{name}=?" for name in values if name not in {"opportunity_key", "marketplace", "first_seen_at"})
            update_values = [values[name] for name in values if name not in {"opportunity_key", "marketplace", "first_seen_at"}]
            database.execute(
                f"UPDATE radar_opportunities SET {assignments},dismissed=0 WHERE opportunity_key=? AND marketplace=?",
                (*update_values, opportunity_key, marketplace),
            )
        else:
            columns = ",".join(values)
            placeholders = ",".join("?" for _ in values)
            database.execute(
                f"INSERT INTO radar_opportunities({columns}) VALUES({placeholders})",
                tuple(values.values()),
            )
        row = database.execute(
            "SELECT * FROM radar_opportunities WHERE opportunity_key=? AND marketplace=?",
            (opportunity_key, marketplace),
        ).fetchone()
    if alert_needed:
        delta = f" · {score_change:+.0f} pts" if score_change is not None else ""
        add_alert(
            None,
            "HIGH" if score["score"] >= 85 else "MEDIUM",
            "RADAR_OPPORTUNITY",
            f"Radar automatique : {candidate['keyword']} — {score['score']}/100 ({score['verdict']}){delta}",
        )
    return _decode_row(dict(row)), alert_needed


async def run_auto_radar(marketplace: str | None = None, trigger: str = "manual") -> dict[str, Any]:
    settings = get_settings()
    market = marketplace or settings.ebay_marketplace_id or "EBAY_US"
    if market != "EBAY_US":
        raise RuntimeError("Le Radar automatique est limité à eBay US")
    if settings.ebay_effective_env != "production" or not settings.ebay_client_id or not settings.ebay_client_secret:
        raise RuntimeError("Des clés eBay Production sont nécessaires pour la découverte automatique")
    if _AUTO_LOCK.locked():
        raise RuntimeError("Une analyse automatique du Radar est déjà en cours")

    async with _AUTO_LOCK:
        run_id = _start_run(trigger, market)
        errors: list[dict[str, Any]] = []
        categories: list[dict[str, str]] = []
        candidates: list[dict[str, Any]] = []
        stored: list[dict[str, Any]] = []
        alerts_created = 0
        try:
            client = EbayClient()
            await client.get_application_token()
            try:
                tree = await _load_category_tree(client, market)
                categories = select_discovery_categories(tree)
            except Exception as exc:
                errors.append({"source": "Taxonomy", "message": str(exc)})

            browse_calls: list[Awaitable[Any]] = []
            marketing_calls: list[Awaitable[Any]] = []
            if categories:
                for category in categories:
                    browse_calls.extend([
                        _browse_category(client, category, market),
                        _browse_category(client, category, market, "newlyListed"),
                    ])
                    marketing_calls.append(_marketing_products(client, category, market))
            else:
                categories = [{"id": "", "name": group, "group": group} for group, _ in FALLBACK_DISCOVERY_SEEDS]
                for group, query in FALLBACK_DISCOVERY_SEEDS:
                    browse_calls.extend([
                        _browse_seed(client, group, query, market),
                        _browse_seed(client, group, query, market, "newlyListed"),
                    ])

            browse_raw = await _limited(browse_calls, concurrency=5)
            browse_rows = []
            for item in browse_raw:
                if isinstance(item, Exception):
                    errors.append({"source": "Browse", "message": str(item)})
                else:
                    browse_rows.append(item)

            marketing_rows = []
            if marketing_calls:
                marketing_raw = await _limited(marketing_calls, concurrency=3)
                marketing_denied = False
                for item in marketing_raw:
                    if isinstance(item, Exception):
                        if not marketing_denied:
                            errors.append({
                                "source": "Marketing API",
                                "message": "Accès Best Selling indisponible; le Radar continue avec Browse API.",
                            })
                            marketing_denied = True
                    else:
                        marketing_rows.append(item)

            candidates = extract_candidate_phrases(browse_rows, marketing_rows)
            measurements_raw = await _limited(
                [_measure_candidate(client, candidate, market) for candidate in candidates],
                concurrency=4,
            )
            measured_pairs = []
            for candidate, measurement in zip(candidates, measurements_raw):
                if isinstance(measurement, Exception):
                    errors.append({"source": "Mesure eBay", "keyword": candidate["keyword"], "message": str(measurement)})
                else:
                    measured_pairs.append((candidate, measurement))

            for candidate, measurement in measured_pairs:
                scored = score_auto_opportunity(candidate, measurement)
                opportunity, alerted = _upsert_opportunity(candidate, measurement, scored, market)
                stored.append(opportunity)
                alerts_created += int(alerted)

            stored.sort(key=lambda row: float(row.get("score") or 0), reverse=True)
            _finish_run(
                run_id,
                status="COMPLETED",
                categories=len(categories),
                candidates=len(measured_pairs),
                opportunities=len(stored),
                alerts=alerts_created,
                errors=errors,
            )
            return {
                "run_id": run_id,
                "status": "COMPLETED",
                "marketplace": market,
                "categories_scanned": len(categories),
                "candidates_measured": len(measured_pairs),
                "opportunities": stored,
                "alerts_created": alerts_created,
                "errors": errors,
                "method": "EBAY_US_ONLY_V2",
            }
        except Exception as exc:
            errors.append({"source": "Radar automatique", "message": str(exc)})
            _finish_run(
                run_id,
                status="FAILED",
                categories=len(categories),
                candidates=len(candidates),
                opportunities=len(stored),
                alerts=alerts_created,
                errors=errors,
            )
            raise
