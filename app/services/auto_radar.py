"""Automatic, eBay-first market opportunity discovery.

The engine deliberately uses official eBay APIs and observable marketplace
signals only. It does not scrape eBay and does not invent search volume,
conversion, or exact competitor revenue.
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
from typing import Any
from urllib.parse import quote

from app.config import get_settings
from app.services.db import add_alert, conn, kv_get, kv_set, utc_now
from app.services.ebay import EbayClient, EbayError


MARKETPLACE_ID = "EBAY_FR"
AUTO_MIN_SCORE = 58
TEST_SCORE = 72
NOTIFICATION_SCORE = 82
MAX_DETAILS_PER_LANE = 8
MAX_ENRICHED_CANDIDATES = 12
SOCIAL_CONFIRMATION_LIMIT = 3

DISCOVERY_LANES = (
    {
        "id": "home_storage",
        "name": "Maison & rangement",
        "category_query": "rangement organisation maison",
        "fallback_query": "organisateur rangement maison",
    },
    {
        "id": "kitchen_tools",
        "name": "Cuisine pratique",
        "category_query": "accessoires ustensiles cuisine",
        "fallback_query": "accessoire cuisine pratique",
    },
    {
        "id": "car_accessories",
        "name": "Accessoires voiture",
        "category_query": "accessoires automobile intérieur",
        "fallback_query": "accessoire intérieur voiture",
    },
    {
        "id": "pets",
        "name": "Animaux",
        "category_query": "accessoires animaux chien chat",
        "fallback_query": "accessoire chien chat",
    },
    {
        "id": "fitness",
        "name": "Sport & récupération",
        "category_query": "accessoires fitness entraînement",
        "fallback_query": "accessoire fitness maison",
    },
    {
        "id": "desk",
        "name": "Bureau & ergonomie",
        "category_query": "accessoires bureau ergonomie",
        "fallback_query": "support rangement bureau",
    },
    {
        "id": "travel",
        "name": "Voyage",
        "category_query": "accessoires voyage bagages",
        "fallback_query": "organisateur accessoire voyage",
    },
    {
        "id": "garden",
        "name": "Jardin & extérieur",
        "category_query": "accessoires jardin extérieur",
        "fallback_query": "accessoire jardin pratique",
    },
)

TITLE_STOPWORDS = {
    "avec", "pour", "sans", "dans", "sur", "une", "des", "les", "lot", "pack", "pcs", "piece", "pieces",
    "new", "neuf", "neuve", "nouveau", "nouvelle", "officiel", "official", "original", "promo", "promotion",
    "livraison", "gratuite", "gratuit", "free", "shipping", "france", "fr", "eu", "europe", "stock",
    "couleur", "color", "taille", "size", "version", "modele", "model", "universel", "universal",
    "qualite", "quality", "premium", "professionnel", "professional", "best", "top", "hot", "vente",
}

BLOCKED_TERMS = {
    # Regulated, unsafe, or high-compliance categories.
    "vape", "cigarette", "tabac", "nicotine", "cbd", "thc", "cannabis", "alcool", "alcohol",
    "medicament", "médicament", "medical", "médical", "supplement", "complément", "complement alimentaire",
    "pesticide", "poison", "knife", "couteau", "arme", "weapon", "gun", "pistolet", "airbag", "frein",
    "brake", "adulte", "adult", "sex", "sexe", "casino", "betting", "paris sportif",
    # Strong counterfeit/IP-risk magnets that are poor automatic dropshipping candidates.
    "iphone", "airpods", "samsung", "nike", "adidas", "lego", "pokemon", "pokémon", "disney", "marvel",
    "gucci", "prada", "rolex", "louis vuitton", "chanel", "dior", "hermes", "hermès",
}

_RUN_LOCK = asyncio.Lock()


class AutoRadarError(RuntimeError):
    pass


def _ensure_schema() -> None:
    with conn() as database:
        database.executescript(
            """
            CREATE TABLE IF NOT EXISTS radar_auto_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                trigger TEXT NOT NULL,
                status TEXT NOT NULL,
                lanes_total INTEGER NOT NULL DEFAULT 0,
                lanes_scanned INTEGER NOT NULL DEFAULT 0,
                items_observed INTEGER NOT NULL DEFAULT 0,
                candidates_scored INTEGER NOT NULL DEFAULT 0,
                opportunities_saved INTEGER NOT NULL DEFAULT 0,
                errors_json TEXT NOT NULL DEFAULT '[]',
                started_at TEXT NOT NULL,
                finished_at TEXT
            );

            CREATE TABLE IF NOT EXISTS radar_auto_opportunities (
                fingerprint TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                keyword TEXT NOT NULL,
                category_lane TEXT NOT NULL,
                category_id TEXT NOT NULL DEFAULT '',
                marketplace TEXT NOT NULL DEFAULT 'EBAY_FR',
                score REAL NOT NULL,
                previous_score REAL,
                score_change REAL NOT NULL DEFAULT 0,
                demand_score REAL NOT NULL DEFAULT 0,
                momentum_score REAL NOT NULL DEFAULT 0,
                competition_score REAL NOT NULL DEFAULT 0,
                price_score REAL NOT NULL DEFAULT 0,
                evidence_score REAL NOT NULL DEFAULT 0,
                verdict TEXT NOT NULL,
                confidence TEXT NOT NULL,
                estimated_sold INTEGER,
                sales_velocity REAL,
                youngest_listing_days REAL,
                market_results INTEGER,
                seller_count INTEGER NOT NULL DEFAULT 0,
                top_seller_share REAL NOT NULL DEFAULT 0,
                emerging_seller_count INTEGER NOT NULL DEFAULT 0,
                price REAL,
                currency TEXT NOT NULL DEFAULT 'EUR',
                image_url TEXT NOT NULL DEFAULT '',
                item_url TEXT NOT NULL DEFAULT '',
                source_item_id TEXT NOT NULL DEFAULT '',
                reasons_json TEXT NOT NULL DEFAULT '[]',
                limitations_json TEXT NOT NULL DEFAULT '[]',
                social_json TEXT NOT NULL DEFAULT '{}',
                payload_json TEXT NOT NULL DEFAULT '{}',
                first_seen_at TEXT NOT NULL,
                last_seen_at TEXT NOT NULL,
                notified_at TEXT,
                dismissed INTEGER NOT NULL DEFAULT 0
            );

            CREATE INDEX IF NOT EXISTS idx_radar_auto_score
                ON radar_auto_opportunities(dismissed, score DESC, last_seen_at DESC);
            CREATE INDEX IF NOT EXISTS idx_radar_auto_runs
                ON radar_auto_runs(id DESC);
            """
        )


def _normalize_text(value: str) -> str:
    return unicodedata.normalize("NFKD", str(value or "")).encode("ascii", "ignore").decode().lower()


def _blocked_title(title: str) -> bool:
    normalized = _normalize_text(title)
    return any(term in normalized for term in BLOCKED_TERMS)


def _title_tokens(title: str) -> list[str]:
    normalized = _normalize_text(title)
    tokens = []
    for token in re.findall(r"[a-z][a-z0-9-]{2,}", normalized):
        if token in TITLE_STOPWORDS or token.isdigit():
            continue
        if len(token) > 20:
            continue
        if token not in tokens:
            tokens.append(token)
    return tokens


def _identity_for_item(item: dict[str, Any], lane_id: str) -> tuple[str, str]:
    epid = str(item.get("epid") or "").strip()
    gtin = str(item.get("gtin") or "").strip()
    tokens = _title_tokens(str(item.get("title") or ""))
    keyword_tokens = tokens[:5]
    keyword = " ".join(keyword_tokens) or str(item.get("title") or "Produit")[:80]
    identity = epid or gtin or " ".join(sorted(keyword_tokens[:5])) or keyword
    fingerprint = hashlib.sha256(f"{lane_id}|{identity}".encode("utf-8")).hexdigest()[:24]
    return fingerprint, keyword


def _parse_datetime(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _number(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _integer(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _availability_metrics(item: dict[str, Any]) -> tuple[int | None, int | None, bool]:
    rows = item.get("estimatedAvailabilities") or []
    if not isinstance(rows, list):
        rows = []
    sold_total = 0
    available_total = 0
    sold_observed = False
    available_observed = False
    for row in rows:
        if not isinstance(row, dict):
            continue
        if row.get("estimatedSoldQuantity") is not None:
            sold_observed = True
            sold_total += max(_integer(row.get("estimatedSoldQuantity")), 0)
        available = row.get("estimatedAvailableQuantity")
        if available is None:
            available = row.get("estimatedRemainingQuantity")
        if available is not None:
            available_observed = True
            available_total += max(_integer(available), 0)
    return (
        sold_total if sold_observed else None,
        available_total if available_observed else None,
        sold_observed,
    )


def _seller_data(item: dict[str, Any]) -> dict[str, Any]:
    seller = item.get("seller") if isinstance(item.get("seller"), dict) else {}
    return {
        "username": str(seller.get("username") or "").strip(),
        "feedback_score": _integer(seller.get("feedbackScore"), 0),
        "feedback_percent": _number(seller.get("feedbackPercentage"), 0),
        "account_type": str(seller.get("sellerAccountType") or seller.get("accountType") or "").upper(),
    }


def _record_from_item(
    detail: dict[str, Any],
    summary: dict[str, Any],
    lane: dict[str, str],
    now: datetime,
) -> dict[str, Any] | None:
    merged = {**summary, **detail}
    title = str(merged.get("title") or "").strip()
    if len(title) < 4 or _blocked_title(title):
        return None

    price_container = merged.get("price") if isinstance(merged.get("price"), dict) else {}
    price = _number(price_container.get("value"), -1)
    if price < 8 or price > 180:
        return None
    currency = str(price_container.get("currency") or "EUR").upper()
    if currency != "EUR":
        return None

    sold, available, sold_observed = _availability_metrics(merged)
    created_at = _parse_datetime(merged.get("itemCreationDate") or summary.get("itemCreationDate"))
    age_days = None
    if created_at:
        age_days = max((now - created_at).total_seconds() / 86400, 0.25)
    velocity = None
    if sold is not None and age_days is not None:
        velocity = round(sold / age_days, 3)

    fingerprint, keyword = _identity_for_item(merged, lane["id"])
    image = merged.get("image") if isinstance(merged.get("image"), dict) else {}
    seller = _seller_data(merged)
    return {
        "fingerprint": fingerprint,
        "keyword": keyword,
        "title": title[:180],
        "lane_id": lane["id"],
        "lane_name": lane["name"],
        "category_id": str(merged.get("categoryId") or summary.get("categoryId") or ""),
        "item_id": str(merged.get("itemId") or summary.get("itemId") or ""),
        "item_url": str(merged.get("itemWebUrl") or summary.get("itemWebUrl") or ""),
        "image_url": str(image.get("imageUrl") or ""),
        "price": round(price, 2),
        "currency": currency,
        "estimated_sold": sold,
        "estimated_available": available,
        "sold_observed": sold_observed,
        "age_days": round(age_days, 2) if age_days is not None else None,
        "velocity": velocity,
        "seller": seller,
        "epid": str(merged.get("epid") or ""),
        "gtin": str(merged.get("gtin") or ""),
    }


def _log_score(value: float, multiplier: float) -> float:
    return min(100.0, math.log1p(max(value, 0.0)) * multiplier)


def _price_score(price: float | None) -> float:
    if price is None:
        return 25.0
    if 15 <= price <= 70:
        return 100.0
    if 10 <= price <= 120:
        return 75.0
    if 8 <= price <= 180:
        return 50.0
    return 10.0


def _recency_score(days: float | None) -> float:
    if days is None:
        return 20.0
    if days <= 14:
        return 100.0
    if days <= 30:
        return 90.0
    if days <= 60:
        return 72.0
    if days <= 120:
        return 50.0
    return 25.0


def _competition_score(total_results: int | None, top_seller_share: float, seller_count: int) -> float:
    if total_results is None:
        result_score = 25.0
    elif total_results <= 40:
        result_score = 88.0
    elif total_results <= 150:
        result_score = 82.0
    elif total_results <= 500:
        result_score = 68.0
    elif total_results <= 1500:
        result_score = 48.0
    elif total_results <= 5000:
        result_score = 28.0
    else:
        result_score = 12.0

    if seller_count <= 1:
        concentration_score = 25.0
    elif top_seller_share <= 15:
        concentration_score = 100.0
    elif top_seller_share <= 30:
        concentration_score = 78.0
    elif top_seller_share <= 50:
        concentration_score = 52.0
    else:
        concentration_score = 25.0
    return round(result_score * 0.72 + concentration_score * 0.28, 1)


def _score_group(records: list[dict[str, Any]]) -> dict[str, Any]:
    sold_values = [row["estimated_sold"] for row in records if row.get("estimated_sold") is not None]
    total_sold = sum(int(value) for value in sold_values) if sold_values else None
    velocities = [float(row["velocity"]) for row in records if row.get("velocity") is not None]
    velocity = round(sum(velocities), 3) if velocities else None
    ages = [float(row["age_days"]) for row in records if row.get("age_days") is not None]
    youngest_age = min(ages) if ages else None
    prices = [float(row["price"]) for row in records if row.get("price") is not None]
    price = round(median(prices), 2) if prices else None

    sold_signal = _log_score(float(total_sold or 0), 20.0)
    velocity_signal = _log_score(float(velocity or 0), 42.0)
    demand_score = round(velocity_signal * 0.62 + sold_signal * 0.38, 1)
    momentum_score = round(_recency_score(youngest_age) * 0.48 + velocity_signal * 0.52, 1)
    price_fit = _price_score(price)

    sold_evidence = len(sold_values) / max(len(records), 1)
    age_evidence = len(ages) / max(len(records), 1)
    evidence_score = round((sold_evidence * 0.72 + age_evidence * 0.28) * 100, 1)
    confidence_multiplier = 0.50 + evidence_score / 100 * 0.50
    preliminary = (demand_score * 0.52 + momentum_score * 0.36 + price_fit * 0.12) * confidence_multiplier

    representative = max(
        records,
        key=lambda row: (
            float(row.get("velocity") or 0),
            int(row.get("estimated_sold") or 0),
            -float(row.get("age_days") or 99999),
        ),
    )
    sellers = {row["seller"]["username"] for row in records if row["seller"].get("username")}
    emerging = {
        row["seller"]["username"]
        for row in records
        if row["seller"].get("username")
        and 0 < int(row["seller"].get("feedback_score") or 0) < 500
        and int(row.get("estimated_sold") or 0) >= 10
    }

    return {
        "fingerprint": representative["fingerprint"],
        "keyword": representative["keyword"],
        "title": representative["title"],
        "category_lane": representative["lane_name"],
        "category_id": representative["category_id"],
        "marketplace": MARKETPLACE_ID,
        "preliminary_score": round(preliminary, 1),
        "demand_score": demand_score,
        "momentum_score": momentum_score,
        "price_score": round(price_fit, 1),
        "evidence_score": evidence_score,
        "estimated_sold": total_sold,
        "sales_velocity": velocity,
        "youngest_listing_days": round(youngest_age, 1) if youngest_age is not None else None,
        "price": price,
        "currency": representative["currency"],
        "seller_count_initial": len(sellers),
        "emerging_seller_count": len(emerging),
        "image_url": representative["image_url"],
        "item_url": representative["item_url"],
        "source_item_id": representative["item_id"],
        "records": records,
    }


async def _resolve_category(client: EbayClient, lane: dict[str, str]) -> tuple[str, str] | None:
    cache_key = f"auto_radar:category:{MARKETPLACE_ID}:{lane['id']}"
    cached = kv_get(cache_key)
    if cached:
        try:
            payload = json.loads(cached)
            if payload.get("category_id"):
                return str(payload["category_id"]), str(payload.get("category_name") or lane["name"])
        except json.JSONDecodeError:
            pass

    tree_id = await client.get_default_category_tree_id(MARKETPLACE_ID)
    result = await client.public_request(
        "GET",
        f"/commerce/taxonomy/v1/category_tree/{quote(tree_id, safe='')}/get_category_suggestions",
        params={"q": lane["category_query"]},
        marketplace_id=MARKETPLACE_ID,
    )
    suggestions = result.get("categorySuggestions") or []
    for suggestion in suggestions:
        category = suggestion.get("category") if isinstance(suggestion, dict) else None
        if not isinstance(category, dict) or not category.get("categoryId"):
            continue
        payload = {
            "category_id": str(category["categoryId"]),
            "category_name": str(category.get("categoryName") or lane["name"]),
        }
        kv_set(cache_key, json.dumps(payload, ensure_ascii=False))
        return payload["category_id"], payload["category_name"]
    return None


async def _search_lane(client: EbayClient, lane: dict[str, str]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    category = None
    errors: list[str] = []
    try:
        category = await _resolve_category(client, lane)
    except Exception as exc:
        errors.append(f"Catégorie : {exc}")

    filters = "conditions:{NEW},price:[8..180],priceCurrency:EUR"
    params: dict[str, Any] = {
        "limit": 30,
        "sort": "newlyListed",
        "filter": filters,
    }
    if category:
        params["category_ids"] = category[0]
    else:
        params["q"] = lane["fallback_query"]

    try:
        payload = await client.public_request(
            "GET",
            "/buy/browse/v1/item_summary/search",
            params=params,
            marketplace_id=MARKETPLACE_ID,
        )
    except EbayError as exc:
        if category:
            errors.append(f"Recherche catégorie : {exc}")
            payload = await client.public_request(
                "GET",
                "/buy/browse/v1/item_summary/search",
                params={
                    "q": lane["fallback_query"],
                    "limit": 30,
                    "sort": "newlyListed",
                    "filter": filters,
                },
                marketplace_id=MARKETPLACE_ID,
            )
        else:
            raise

    summaries = [
        row for row in (payload.get("itemSummaries") or [])
        if isinstance(row, dict) and row.get("itemId") and not _blocked_title(str(row.get("title") or ""))
    ][:MAX_DETAILS_PER_LANE]
    meta = {
        "lane": lane["name"],
        "category_id": category[0] if category else "",
        "category_name": category[1] if category else "Recherche de secours",
        "observed": len(payload.get("itemSummaries") or []),
        "selected": len(summaries),
        "errors": errors,
    }
    return summaries, meta


async def _fetch_detail(
    client: EbayClient,
    summary: dict[str, Any],
    lane: dict[str, str],
    semaphore: asyncio.Semaphore,
    now: datetime,
) -> dict[str, Any] | None:
    async with semaphore:
        try:
            detail = await client.public_request(
                "GET",
                f"/buy/browse/v1/item/{quote(str(summary['itemId']), safe='')}",
                marketplace_id=MARKETPLACE_ID,
            )
        except Exception:
            detail = {}
    return _record_from_item(detail, summary, lane, now)


def _competition_from_search(payload: dict[str, Any]) -> dict[str, Any]:
    items = [row for row in (payload.get("itemSummaries") or []) if isinstance(row, dict)]
    sellers = [str((row.get("seller") or {}).get("username") or "").strip() for row in items]
    sellers = [value for value in sellers if value]
    seller_counts = Counter(sellers)
    top_count = seller_counts.most_common(1)[0][1] if seller_counts else 0
    top_share = round(top_count / len(sellers) * 100, 1) if sellers else 0.0
    prices = []
    for row in items:
        price = row.get("price") if isinstance(row.get("price"), dict) else {}
        if price.get("value") is not None:
            value = _number(price.get("value"), -1)
            if value >= 0:
                prices.append(value)
    total_results = _integer(payload.get("total"), len(items))
    return {
        "market_results": total_results,
        "seller_count": len(seller_counts),
        "top_seller_share": top_share,
        "market_price": round(median(prices), 2) if prices else None,
        "competition_score": _competition_score(total_results, top_share, len(seller_counts)),
    }


def _finalize_score(candidate: dict[str, Any], competition: dict[str, Any]) -> dict[str, Any]:
    evidence_multiplier = 0.55 + float(candidate["evidence_score"]) / 100 * 0.45
    base = (
        float(candidate["demand_score"]) * 0.40
        + float(candidate["momentum_score"]) * 0.27
        + float(competition["competition_score"]) * 0.23
        + float(candidate["price_score"]) * 0.10
    )
    score = round(min(100.0, base * evidence_multiplier))
    if score >= NOTIFICATION_SCORE:
        verdict = "FORTE OPPORTUNITÉ"
    elif score >= TEST_SCORE:
        verdict = "À TESTER"
    elif score >= AUTO_MIN_SCORE:
        verdict = "À SURVEILLER"
    else:
        verdict = "FAIBLE"

    evidence = float(candidate["evidence_score"])
    confidence = "Élevée" if evidence >= 80 else "Moyenne" if evidence >= 50 else "Faible"
    reasons = []
    if candidate.get("sales_velocity") is not None:
        reasons.append(f"Vélocité estimée : {candidate['sales_velocity']:.2f} vente(s)/jour sur l'échantillon")
    if candidate.get("estimated_sold") is not None:
        reasons.append(f"Environ {candidate['estimated_sold']} vente(s) estimée(s) observée(s)")
    if candidate.get("youngest_listing_days") is not None:
        reasons.append(f"Annonce la plus récente : {candidate['youngest_listing_days']:.0f} jour(s)")
    reasons.append(
        f"{competition['market_results']} résultat(s) actifs et {competition['seller_count']} vendeur(s) dans l'échantillon"
    )
    if candidate.get("emerging_seller_count"):
        reasons.append(
            f"{candidate['emerging_seller_count']} vendeur(s) à historique limité avec déjà des ventes estimées"
        )

    limitations = [
        "Les quantités vendues sont des estimations eBay lorsqu'elles sont exposées, pas le chiffre d'affaires exact.",
        "Le nombre d'annonces actives mesure l'offre, pas le volume exact de recherches.",
        "La conversion et les ventes complètes des concurrents ne sont pas publiques.",
    ]
    return {
        **candidate,
        **competition,
        "score": score,
        "verdict": verdict,
        "confidence": confidence,
        "reasons": reasons,
        "limitations": limitations,
    }


async def _enrich_candidate(client: EbayClient, candidate: dict[str, Any]) -> dict[str, Any] | None:
    try:
        payload = await client.search_items(
            candidate["keyword"],
            limit=50,
            marketplace_id=MARKETPLACE_ID,
        )
    except Exception:
        payload = {"itemSummaries": [], "total": None}
    enriched = _finalize_score(candidate, _competition_from_search(payload))
    return enriched if enriched["score"] >= AUTO_MIN_SCORE else None


def _social_score(payload: dict[str, Any]) -> tuple[int, int]:
    results = payload.get("results") if isinstance(payload, dict) else None
    if not isinstance(results, list):
        return 0, 0
    observed = 0
    confirmed_sources = 0
    for row in results:
        if not isinstance(row, dict):
            continue
        count = _integer(row.get("observed_count"), len(row.get("items") or []))
        observed += max(count, 0)
        if count > 0:
            confirmed_sources += 1
    score = min(100, observed * 5 + confirmed_sources * 15)
    return score, confirmed_sources


async def _confirm_social(opportunities: list[dict[str, Any]]) -> None:
    try:
        from app.services.connections import connection_statuses, scan_connected_sources
    except ImportError:
        return
    sources = [
        row["id"] for row in connection_statuses()
        if row.get("connected") and row.get("id") in {"youtube", "tiktok", "etsy"}
    ]
    if not sources:
        return
    for opportunity in opportunities[:SOCIAL_CONFIRMATION_LIMIT]:
        try:
            payload = await scan_connected_sources(opportunity["keyword"], sources, "FR")
            score, confirmed = _social_score(payload)
            opportunity["social"] = {
                "score": score,
                "confirmed_sources": confirmed,
                "sources_checked": sources,
                "meaning": "Confirmation secondaire ciblée; ce score ne remplace pas les signaux eBay.",
                "payload": payload,
            }
        except Exception as exc:
            opportunity["social"] = {
                "score": None,
                "confirmed_sources": 0,
                "sources_checked": sources,
                "error": str(exc),
            }


def _save_run_start(trigger: str) -> int:
    _ensure_schema()
    with conn() as database:
        cursor = database.execute(
            """
            INSERT INTO radar_auto_runs(trigger,status,lanes_total,started_at)
            VALUES(?,?,?,?)
            """,
            (trigger, "RUNNING", len(DISCOVERY_LANES), utc_now()),
        )
        return int(cursor.lastrowid)


def _finish_run(run_id: int, status: str, metrics: dict[str, int], errors: list[dict[str, Any]]) -> None:
    with conn() as database:
        database.execute(
            """
            UPDATE radar_auto_runs SET status=?,lanes_scanned=?,items_observed=?,candidates_scored=?,
                opportunities_saved=?,errors_json=?,finished_at=? WHERE id=?
            """,
            (
                status,
                int(metrics.get("lanes_scanned", 0)),
                int(metrics.get("items_observed", 0)),
                int(metrics.get("candidates_scored", 0)),
                int(metrics.get("opportunities_saved", 0)),
                json.dumps(errors, ensure_ascii=False),
                utc_now(),
                run_id,
            ),
        )


def _save_opportunities(opportunities: list[dict[str, Any]]) -> list[dict[str, Any]]:
    _ensure_schema()
    now = utc_now()
    alerts: list[dict[str, Any]] = []
    with conn() as database:
        for item in opportunities:
            existing = database.execute(
                "SELECT score,first_seen_at,notified_at,dismissed FROM radar_auto_opportunities WHERE fingerprint=?",
                (item["fingerprint"],),
            ).fetchone()
            previous_score = float(existing["score"]) if existing else None
            score_change = round(float(item["score"]) - previous_score, 1) if previous_score is not None else 0.0
            first_seen_at = existing["first_seen_at"] if existing else now
            notified_at = existing["notified_at"] if existing else None
            dismissed = int(existing["dismissed"]) if existing else 0
            should_alert = (
                item["score"] >= NOTIFICATION_SCORE
                and (existing is None or previous_score is None or previous_score < NOTIFICATION_SCORE)
            ) or (
                previous_score is not None
                and score_change >= 10
                and item["score"] >= TEST_SCORE
            )
            if should_alert:
                notified_at = now
                alerts.append({**item, "score_change": score_change})

            payload = {
                key: value for key, value in item.items()
                if key not in {"records", "reasons", "limitations", "social"}
            }
            database.execute(
                """
                INSERT INTO radar_auto_opportunities(
                    fingerprint,title,keyword,category_lane,category_id,marketplace,score,previous_score,
                    score_change,demand_score,momentum_score,competition_score,price_score,evidence_score,
                    verdict,confidence,estimated_sold,sales_velocity,youngest_listing_days,market_results,
                    seller_count,top_seller_share,emerging_seller_count,price,currency,image_url,item_url,
                    source_item_id,reasons_json,limitations_json,social_json,payload_json,first_seen_at,
                    last_seen_at,notified_at,dismissed
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(fingerprint) DO UPDATE SET
                    title=excluded.title,keyword=excluded.keyword,category_lane=excluded.category_lane,
                    category_id=excluded.category_id,marketplace=excluded.marketplace,
                    previous_score=radar_auto_opportunities.score,score=excluded.score,
                    score_change=excluded.score-radar_auto_opportunities.score,
                    demand_score=excluded.demand_score,momentum_score=excluded.momentum_score,
                    competition_score=excluded.competition_score,price_score=excluded.price_score,
                    evidence_score=excluded.evidence_score,verdict=excluded.verdict,
                    confidence=excluded.confidence,estimated_sold=excluded.estimated_sold,
                    sales_velocity=excluded.sales_velocity,youngest_listing_days=excluded.youngest_listing_days,
                    market_results=excluded.market_results,seller_count=excluded.seller_count,
                    top_seller_share=excluded.top_seller_share,
                    emerging_seller_count=excluded.emerging_seller_count,price=excluded.price,
                    currency=excluded.currency,image_url=excluded.image_url,item_url=excluded.item_url,
                    source_item_id=excluded.source_item_id,reasons_json=excluded.reasons_json,
                    limitations_json=excluded.limitations_json,social_json=excluded.social_json,
                    payload_json=excluded.payload_json,last_seen_at=excluded.last_seen_at,
                    notified_at=excluded.notified_at,dismissed=radar_auto_opportunities.dismissed
                """,
                (
                    item["fingerprint"], item["title"], item["keyword"], item["category_lane"],
                    item.get("category_id") or "", item.get("marketplace") or MARKETPLACE_ID,
                    float(item["score"]), previous_score, score_change, float(item["demand_score"]),
                    float(item["momentum_score"]), float(item["competition_score"]),
                    float(item["price_score"]), float(item["evidence_score"]), item["verdict"],
                    item["confidence"], item.get("estimated_sold"), item.get("sales_velocity"),
                    item.get("youngest_listing_days"), item.get("market_results"),
                    int(item.get("seller_count") or 0), float(item.get("top_seller_share") or 0),
                    int(item.get("emerging_seller_count") or 0), item.get("price"),
                    item.get("currency") or "EUR", item.get("image_url") or "",
                    item.get("item_url") or "", item.get("source_item_id") or "",
                    json.dumps(item.get("reasons") or [], ensure_ascii=False),
                    json.dumps(item.get("limitations") or [], ensure_ascii=False),
                    json.dumps(item.get("social") or {}, ensure_ascii=False),
                    json.dumps(payload, ensure_ascii=False), first_seen_at, now, notified_at, dismissed,
                ),
            )

    for item in alerts:
        change = f" · +{item['score_change']:.0f} points" if item.get("score_change", 0) >= 10 else ""
        add_alert(
            None,
            "success",
            "RADAR_OPPORTUNITY",
            f"🔥 {item['title'][:100]} — score {item['score']}/100{change} — {item['verdict']}",
        )
    return alerts


def _decode_opportunity(row: Any) -> dict[str, Any]:
    data = dict(row)
    for source, target, default in (
        ("reasons_json", "reasons", []),
        ("limitations_json", "limitations", []),
        ("social_json", "social", {}),
        ("payload_json", "payload", {}),
    ):
        raw = data.pop(source, None)
        try:
            data[target] = json.loads(raw or json.dumps(default))
        except json.JSONDecodeError:
            data[target] = default
    return data


def list_auto_opportunities(limit: int = 20, min_score: int = AUTO_MIN_SCORE) -> list[dict[str, Any]]:
    _ensure_schema()
    with conn() as database:
        rows = database.execute(
            """
            SELECT * FROM radar_auto_opportunities
            WHERE dismissed=0 AND score>=?
            ORDER BY score DESC,last_seen_at DESC LIMIT ?
            """,
            (max(min_score, 0), min(max(limit, 1), 100)),
        ).fetchall()
    return [_decode_opportunity(row) for row in rows]


def dismiss_auto_opportunity(fingerprint: str) -> bool:
    _ensure_schema()
    if not re.fullmatch(r"[0-9a-f]{24}", fingerprint):
        return False
    with conn() as database:
        return database.execute(
            "UPDATE radar_auto_opportunities SET dismissed=1 WHERE fingerprint=?",
            (fingerprint,),
        ).rowcount > 0


def auto_radar_status() -> dict[str, Any]:
    _ensure_schema()
    settings = get_settings()
    with conn() as database:
        latest = database.execute("SELECT * FROM radar_auto_runs ORDER BY id DESC LIMIT 1").fetchone()
        counts = database.execute(
            """
            SELECT COUNT(*) AS total,
                   SUM(CASE WHEN score>=? THEN 1 ELSE 0 END) AS strong,
                   SUM(CASE WHEN score>=? THEN 1 ELSE 0 END) AS testable
            FROM radar_auto_opportunities WHERE dismissed=0
            """,
            (NOTIFICATION_SCORE, TEST_SCORE),
        ).fetchone()
    try:
        from app.services.connections import connection_statuses
        social_sources = [
            row["id"] for row in connection_statuses()
            if row.get("connected") and row.get("id") in {"youtube", "tiktok", "etsy"}
        ]
    except Exception:
        social_sources = []
    return {
        "ready": bool(
            settings.ebay_effective_env == "production"
            and settings.ebay_client_id
            and settings.ebay_client_secret
        ),
        "marketplace": MARKETPLACE_ID,
        "interval_hours": max(settings.radar_auto_hours, 6),
        "notification_score": NOTIFICATION_SCORE,
        "minimum_score": AUTO_MIN_SCORE,
        "lanes": [{"id": row["id"], "name": row["name"]} for row in DISCOVERY_LANES],
        "social_sources": social_sources,
        "latest_run": dict(latest) if latest else None,
        "counts": {
            "total": int(counts["total"] or 0),
            "strong": int(counts["strong"] or 0),
            "testable": int(counts["testable"] or 0),
        },
        "method": "EBAY_CATEGORY_VELOCITY_V1",
        "note": (
            "Découverte par catégories eBay, annonces récentes, quantités vendues estimées, "
            "concurrence et concentration vendeurs. Les réseaux sociaux ne servent qu'à confirmer."
        ),
    }


async def run_auto_discovery(trigger: str = "manual") -> dict[str, Any]:
    settings = get_settings()
    if settings.ebay_effective_env != "production" or not settings.ebay_client_id or not settings.ebay_client_secret:
        raise AutoRadarError("Les clés eBay Production sont nécessaires pour la découverte automatique.")
    if _RUN_LOCK.locked():
        raise AutoRadarError("Une détection automatique est déjà en cours.")

    async with _RUN_LOCK:
        run_id = _save_run_start(trigger)
        metrics = {
            "lanes_scanned": 0,
            "items_observed": 0,
            "candidates_scored": 0,
            "opportunities_saved": 0,
        }
        errors: list[dict[str, Any]] = []
        try:
            client = EbayClient()
            now = datetime.now(timezone.utc)
            lane_results = await asyncio.gather(
                *[_search_lane(client, lane) for lane in DISCOVERY_LANES],
                return_exceptions=True,
            )
            details_tasks = []
            semaphore = asyncio.Semaphore(8)
            lane_meta = []
            for lane, result in zip(DISCOVERY_LANES, lane_results):
                if isinstance(result, Exception):
                    errors.append({"lane": lane["name"], "message": str(result)})
                    continue
                summaries, meta = result
                metrics["lanes_scanned"] += 1
                metrics["items_observed"] += int(meta.get("observed") or 0)
                lane_meta.append(meta)
                for summary in summaries:
                    details_tasks.append(_fetch_detail(client, summary, lane, semaphore, now))

            records = [
                row for row in await asyncio.gather(*details_tasks, return_exceptions=False)
                if isinstance(row, dict)
            ]
            groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
            for record in records:
                groups[record["fingerprint"]].append(record)
            candidates = sorted(
                (_score_group(group) for group in groups.values()),
                key=lambda row: row["preliminary_score"],
                reverse=True,
            )[:MAX_ENRICHED_CANDIDATES]
            metrics["candidates_scored"] = len(candidates)

            enriched_rows = await asyncio.gather(
                *[_enrich_candidate(client, candidate) for candidate in candidates],
                return_exceptions=True,
            )
            opportunities = [row for row in enriched_rows if isinstance(row, dict)]
            opportunities.sort(key=lambda row: row["score"], reverse=True)
            await _confirm_social(opportunities)
            alerts = _save_opportunities(opportunities)
            metrics["opportunities_saved"] = len(opportunities)
            _finish_run(run_id, "DONE", metrics, errors)
            return {
                "run_id": run_id,
                "trigger": trigger,
                "status": "DONE",
                "metrics": metrics,
                "errors": errors,
                "lanes": lane_meta,
                "alerts_created": len(alerts),
                "opportunities": opportunities,
                "method": "EBAY_CATEGORY_VELOCITY_V1",
                "note": (
                    "Les opportunités sont classées avec des signaux eBay observables. "
                    "Aucun volume de recherche, taux de conversion ou chiffre d'affaires concurrent n'est inventé."
                ),
            }
        except Exception as exc:
            errors.append({"lane": "global", "message": str(exc)})
            _finish_run(run_id, "FAILED", metrics, errors)
            if isinstance(exc, AutoRadarError):
                raise
            raise AutoRadarError(f"Détection automatique impossible : {exc}") from exc
