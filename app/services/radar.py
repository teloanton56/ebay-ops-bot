from collections import Counter
from statistics import median

from app.config import get_settings
from app.services.cj import CJClient
from app.services.connections import AmazonRadarClient, connection_status
from app.services.db import previous_radar_scan, save_radar_scan
from app.services.ebay import EbayClient


MARKETPLACES = {
    "EBAY_FR": "eBay France", "EBAY_DE": "eBay Allemagne", "EBAY_IT": "eBay Italie",
    "EBAY_ES": "eBay Espagne", "EBAY_GB": "eBay Royaume-Uni", "EBAY_US": "eBay États-Unis",
}
AMAZON_MARKETPLACES = {key: value["name"] for key, value in AmazonRadarClient.marketplaces.items()}


def source_statuses() -> list[dict]:
    settings = get_settings()
    ebay_keys = bool(settings.ebay_client_id and settings.ebay_client_secret)
    ebay_live = ebay_keys and settings.ebay_env == "production"
    cj = CJClient().status()
    return [
        {"id": "ebay", "name": "eBay multi-pays", "kind": "Marketplace", "configured": ebay_keys,
         "ready": ebay_live, "status": "Prêt" if ebay_live else "Clés Production requises",
         "note": "Annonces actives et vendeurs observés. Conversion disponible uniquement pour votre boutique."},
        {**connection_status("amazon"),
         "note": "Catalogue, catégories, rangs de vente et prix si le rôle Pricing est accordé. Aucune écriture Amazon."},
        {"id": "cj", "name": "CJ Dropshipping", "kind": "Fournisseur", "configured": cj["configured"],
         "ready": cj["connected"], "status": "Prêt" if cj["connected"] else "À connecter",
         "note": "Produits, variantes, stock, propriétés et devis transport."},
        connection_status("tiktok"),
        connection_status("youtube"),
        connection_status("etsy"),
        connection_status("dropxl"),
        connection_status("printful"),
        connection_status("printify"),
        connection_status("gelato"),
    ]


def _competition_from_listings(listings: int) -> tuple[str, float]:
    if listings <= 100:
        return "Faible", 30
    if listings <= 500:
        return "Modérée", 24
    if listings <= 2000:
        return "Élevée", 15
    if listings <= 5000:
        return "Très élevée", 8
    return "Extrême", 3


def _amazon_rank_signal(best_rank: int) -> tuple[str, float]:
    if best_rank <= 1000:
        return "Fort", 25
    if best_rank <= 5000:
        return "Bon", 21
    if best_rank <= 20000:
        return "Moyen", 16
    if best_rank <= 50000:
        return "Faible à moyen", 11
    if best_rank <= 100000:
        return "Faible", 6
    return "Très faible", 2


def build_product_research_summary(markets: list[dict]) -> dict:
    """Build an explainable market-research score from measured marketplace data only.

    The score intentionally does not invent search volume or competitor conversion.
    It combines observable listing competition, seller concentration, cross-market
    presence and Amazon sales-rank evidence when that evidence is actually returned.
    """
    ebay = [row for row in markets if row.get("source") == "EBAY"]
    amazon = [row for row in markets if row.get("source") == "AMAZON"]
    factors: list[dict] = []
    earned_points = 0.0
    available_points = 0.0

    def add_factor(label: str, earned: float, maximum: float, detail: str) -> None:
        nonlocal earned_points, available_points
        earned = max(0.0, min(float(earned), float(maximum)))
        earned_points += earned
        available_points += maximum
        factors.append({"label": label, "earned": round(earned, 1), "maximum": maximum, "detail": detail})

    measured = [row for row in markets if int(row.get("total_results") or 0) > 0]
    if markets:
        coverage = len(measured) / len(markets)
        add_factor(
            "Présence multi-marchés",
            20 * coverage,
            20,
            f"{len(measured)}/{len(markets)} marché(s) avec des résultats mesurés",
        )

    competition = {"label": "Non mesurée", "listings_reference": None}
    ebay_listing_counts = [int(row.get("total_results") or 0) for row in ebay if int(row.get("total_results") or 0) > 0]
    if ebay_listing_counts:
        listing_reference = int(median(ebay_listing_counts))
        competition_label, competition_points = _competition_from_listings(listing_reference)
        competition = {"label": competition_label, "listings_reference": listing_reference}
        add_factor(
            "Concurrence eBay",
            competition_points,
            30,
            f"Médiane de {listing_reference:,} annonce(s) actives sur les marchés eBay relevés".replace(",", " "),
        )

    seller_shares = [float(row.get("top_seller_share") or 0) for row in ebay if row.get("sellers_sample")]
    if seller_shares:
        concentration = float(median(seller_shares))
        if concentration <= 10:
            concentration_points = 15
        elif concentration <= 20:
            concentration_points = 12
        elif concentration <= 35:
            concentration_points = 8
        else:
            concentration_points = 4
        add_factor(
            "Concentration vendeurs",
            concentration_points,
            15,
            f"Le premier vendeur représente environ {concentration:.1f}% de l'échantillon",
        )

    amazon_ranks = [int(row["best_sales_rank"]) for row in amazon if row.get("best_sales_rank")]
    if amazon_ranks:
        best_rank = min(amazon_ranks)
        demand_label, demand_points = _amazon_rank_signal(best_rank)
        demand_proxy = {
            "label": demand_label,
            "score": round(demand_points / 25 * 100),
            "evidence": f"Meilleur rang Amazon observé : #{best_rank:,}".replace(",", " "),
        }
        add_factor(
            "Signal de demande Amazon",
            demand_points,
            25,
            f"Meilleur rang observé #{best_rank:,}; le rang reste dépendant de la catégorie".replace(",", " "),
        )
    else:
        demand_proxy = {
            "label": "À confirmer",
            "score": None,
            "evidence": "Aucun rang de vente Amazon exploitable dans ce relevé",
        }

    price_candidates = [
        row for row in markets
        if row.get("median_price") is not None and str(row.get("currency") or "").upper() == "EUR"
    ]
    if not price_candidates:
        price_candidates = [row for row in markets if row.get("median_price") is not None]
    reference_price = None
    if price_candidates:
        preferred = next(
            (row for row in price_candidates if row.get("marketplace") in {"EBAY_FR", "AMAZON_FR"}),
            price_candidates[0],
        )
        reference_price = {
            "value": round(float(preferred["median_price"]), 2),
            "currency": preferred.get("currency") or "EUR",
            "marketplace": preferred.get("marketplace_name") or preferred.get("marketplace"),
        }

    history_changes = [
        float(row["listing_change_percent"])
        for row in markets
        if row.get("listing_change_percent") is not None
    ]
    if history_changes:
        average_change = round(sum(history_changes) / len(history_changes), 1)
        if average_change >= 10:
            trend_label = "Offre en hausse"
        elif average_change <= -10:
            trend_label = "Offre en baisse"
        else:
            trend_label = "Offre stable"
        trend = {
            "label": trend_label,
            "change_percent": average_change,
            "meaning": "Évolution du nombre de résultats, pas évolution des ventes",
        }
    else:
        trend = {
            "label": "Premier relevé",
            "change_percent": None,
            "meaning": "Un prochain relevé permettra de comparer l'évolution de l'offre",
        }

    score = round(earned_points / available_points * 100) if available_points else 0
    has_ebay = bool(ebay_listing_counts)
    has_amazon_demand = bool(amazon_ranks)
    has_history = bool(history_changes)
    if has_ebay and has_amazon_demand and has_history:
        confidence = "Élevée"
    elif has_ebay and has_amazon_demand:
        confidence = "Moyenne"
    else:
        confidence = "Faible"

    if has_amazon_demand:
        if score >= 75:
            verdict = "À TESTER"
        elif score >= 55:
            verdict = "À CREUSER"
        elif score >= 35:
            verdict = "PRUDENCE"
        else:
            verdict = "FAIBLE"
    else:
        if score >= 60:
            verdict = "À CREUSER"
        elif score >= 35:
            verdict = "PRUDENCE"
        else:
            verdict = "FAIBLE"

    missing_signals = []
    if not has_ebay:
        missing_signals.append("Concurrence eBay non mesurée")
    if not has_amazon_demand:
        missing_signals.append("Demande Amazon non confirmée par un rang de vente")
    if not has_history:
        missing_signals.append("Historique insuffisant pour mesurer l'évolution de l'offre")
    missing_signals.append("Volume exact de recherches eBay non disponible via Browse API")

    return {
        "method": "MARKET_PROXY_V1",
        "score": score,
        "verdict": verdict,
        "confidence": confidence,
        "demand_proxy": demand_proxy,
        "competition": competition,
        "reference_price": reference_price,
        "trend": trend,
        "search_volume_exact": None,
        "factors": factors,
        "missing_signals": missing_signals,
        "meaning": (
            "Score de recherche produit calculé uniquement avec les données réellement observées. "
            "Il ne prétend pas être un volume de recherche ni un taux de conversion concurrent."
        ),
    }


async def analyze_ebay_market(keyword: str, marketplace: str) -> dict:
    payload = await EbayClient().search_items(keyword, limit=50, marketplace_id=marketplace)
    items = payload.get("itemSummaries") or []
    prices, currencies = [], []
    for item in items:
        price = item.get("price") or {}
        try:
            if price.get("value") is not None:
                prices.append(float(price["value"]))
        except (TypeError, ValueError):
            continue
        if price.get("currency"):
            currencies.append(str(price["currency"]))
    currency = Counter(currencies).most_common(1)[0][0] if currencies else "EUR"
    sellers = [str((item.get("seller") or {}).get("username") or "").strip() for item in items]
    sellers = [seller for seller in sellers if seller]
    seller_counts = Counter(sellers)
    top_seller, top_count = seller_counts.most_common(1)[0] if seller_counts else ("", 0)
    result = {
        "keyword": keyword, "source": "EBAY", "marketplace": marketplace,
        "marketplace_name": MARKETPLACES.get(marketplace, marketplace),
        "total_results": int(payload.get("total") or len(items)),
        "currency": currency,
        "median_price": round(median(prices), 2) if prices else None,
        "min_price": round(min(prices), 2) if prices else None,
        "max_price": round(max(prices), 2) if prices else None,
        "sellers_sample": len(seller_counts), "top_seller": top_seller,
        "top_seller_share": round(top_count / len(sellers) * 100, 1) if sellers else 0,
        "conversion_rate": None, "search_volume": None,
        "items": [{"title": item.get("title") or "Produit", "price": item.get("price") or {},
                   "seller": (item.get("seller") or {}).get("username") or "",
                   "image_url": ((item.get("image") or {}).get("imageUrl") or ""),
                   "item_url": item.get("itemWebUrl") or ""} for item in items[:8]],
    }
    scan_id = save_radar_scan(result)
    previous = previous_radar_scan(keyword, "EBAY", marketplace, scan_id)
    result["history_available"] = bool(previous)
    result["listing_change_percent"] = None
    if previous and int(previous.get("total_results") or 0) > 0:
        result["listing_change_percent"] = round((result["total_results"] - int(previous["total_results"])) /
                                                  int(previous["total_results"]) * 100, 1)
    return result


async def analyze_amazon_market(keyword: str, marketplace: str) -> dict:
    payload = await AmazonRadarClient().search_catalog(keyword, marketplace, page_size=20)
    products = payload.get("products") or []
    prices = [float(row["price"]) for row in products if row.get("price") is not None]
    offers = sum(int(row.get("offer_count") or 0) for row in products)
    ranks = [int(row["sales_rank"]) for row in products if row.get("sales_rank") is not None]
    result = {
        "keyword": keyword,
        "source": "AMAZON",
        "marketplace": marketplace,
        "marketplace_name": AMAZON_MARKETPLACES.get(marketplace, marketplace),
        "total_results": int(payload.get("total") or len(products)),
        "currency": payload.get("currency") or "EUR",
        "median_price": round(median(prices), 2) if prices else None,
        "min_price": round(min(prices), 2) if prices else None,
        "max_price": round(max(prices), 2) if prices else None,
        "sellers_sample": 0,
        "top_seller": "",
        "top_seller_share": 0,
        "offers_sample": offers,
        "ranked_products": len(ranks),
        "best_sales_rank": min(ranks) if ranks else None,
        "pricing_available": bool(payload.get("pricing_available")),
        "conversion_rate": None,
        "search_volume": None,
        "items": products[:8],
    }
    scan_id = save_radar_scan(result)
    previous = previous_radar_scan(keyword, "AMAZON", marketplace, scan_id)
    result["history_available"] = bool(previous)
    result["listing_change_percent"] = None
    if previous and int(previous.get("total_results") or 0) > 0:
        result["listing_change_percent"] = round(
            (result["total_results"] - int(previous["total_results"])) /
            int(previous["total_results"]) * 100, 1
        )
    return result


def build_rfq_message(company: str, product_query: str, quantities: str, specifications: str = "") -> str:
    company_line = f" {company}" if company else ""
    specs = specifications.strip() or "Please provide the full product specifications and available compliance documents."
    return (f"Hello{company_line},\n\n"
            f"We are evaluating a long-term supply partnership for: {product_query}.\n\n"
            f"Please quote the unit price for these quantities: {quantities}.\n"
            "Please also include:\n"
            "- MOQ and sample price\n- DDP shipping cost to France\n- production and delivery lead time\n"
            "- available certifications and test reports\n- packaging and private-label options\n"
            "- warranty, defect policy and payment terms\n\n"
            f"Product requirements: {specs}\n\n"
            "No order is confirmed by this request. We will review the quotation and sample first.\n\n"
            "Best regards")
