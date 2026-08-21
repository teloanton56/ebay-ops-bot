from statistics import median


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
