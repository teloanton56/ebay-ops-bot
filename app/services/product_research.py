from statistics import median


MODEL_MAX_POINTS = 100.0


def _competition_from_listings(listings: int) -> tuple[str, float]:
    if listings <= 0:
        return "Non mesurée", 0
    if listings <= 100:
        return "Faible", 35
    if listings <= 500:
        return "Modérée", 28
    if listings <= 2000:
        return "Élevée", 18
    if listings <= 5000:
        return "Très élevée", 9
    return "Extrême", 3


def build_product_research_summary(markets: list[dict]) -> dict:
    """Explain eBay US market structure without inventing search volume or sales."""
    ebay = [row for row in markets if row.get("source") == "EBAY" and row.get("marketplace") == "EBAY_US"]
    factors: list[dict] = []
    earned_points = 0.0

    def add_factor(label: str, earned: float, maximum: float, detail: str) -> None:
        nonlocal earned_points
        earned = max(0.0, min(float(earned), float(maximum)))
        earned_points += earned
        factors.append({"label": label, "earned": round(earned, 1), "maximum": maximum, "detail": detail})

    measured = [row for row in ebay if int(row.get("total_results") or 0) > 0]
    add_factor(
        "Données eBay US",
        10 if measured else 0,
        10,
        "Marché eBay US mesuré" if measured else "Aucun résultat eBay US exploitable",
    )

    competition = {"label": "Non mesurée", "listings_reference": None}
    listing_counts = [int(row.get("total_results") or 0) for row in ebay if int(row.get("total_results") or 0) > 0]
    if listing_counts:
        listing_reference = int(median(listing_counts))
        label, points = _competition_from_listings(listing_reference)
        competition = {"label": label, "listings_reference": listing_reference}
        add_factor("Concurrence eBay US", points, 35, f"{listing_reference:,} annonce(s) actives".replace(",", " "))
    else:
        add_factor("Concurrence eBay US", 0, 35, "Non mesurée")

    seller_shares = [float(row.get("top_seller_share") or 0) for row in ebay if row.get("sellers_sample")]
    if seller_shares:
        concentration = float(median(seller_shares))
        if concentration <= 10:
            concentration_points = 20
        elif concentration <= 20:
            concentration_points = 16
        elif concentration <= 35:
            concentration_points = 10
        else:
            concentration_points = 4
        add_factor("Concentration vendeurs", concentration_points, 20,
                   f"Premier vendeur ≈ {concentration:.1f}% de l'échantillon")
    else:
        add_factor("Concentration vendeurs", 0, 20, "Échantillon vendeur insuffisant")

    reference_price = None
    prices = [row for row in ebay if row.get("median_price") is not None]
    if prices:
        preferred = prices[0]
        reference_price = {
            "value": round(float(preferred["median_price"]), 2),
            "currency": "USD",
            "marketplace": "eBay United States",
        }
        median_price = float(preferred["median_price"])
        min_price = preferred.get("min_price")
        max_price = preferred.get("max_price")
        if min_price is not None and max_price is not None and median_price > 0:
            spread = (float(max_price) - float(min_price)) / median_price * 100
            if spread <= 60:
                price_points = 20
            elif spread <= 120:
                price_points = 14
            elif spread <= 200:
                price_points = 8
            else:
                price_points = 4
            add_factor("Cohérence des prix", price_points, 20, f"Écart min/max ≈ {spread:.0f}% du prix médian")
        else:
            add_factor("Cohérence des prix", 8, 20, "Prix médian disponible, dispersion incomplète")
    else:
        add_factor("Cohérence des prix", 0, 20, "Prix eBay US indisponible")

    history_changes = [float(row["listing_change_percent"]) for row in ebay if row.get("listing_change_percent") is not None]
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
            "meaning": "Évolution du nombre d'annonces, pas des ventes",
        }
        add_factor("Historique eBay US", 15, 15, f"Comparaison disponible : {average_change:+.1f}% d'annonces")
    else:
        trend = {
            "label": "Premier relevé",
            "change_percent": None,
            "meaning": "Un prochain relevé permettra de comparer l'offre",
        }
        add_factor("Historique eBay US", 0, 15, "Premier relevé")

    score = round(earned_points / MODEL_MAX_POINTS * 100) if ebay else 0
    if score >= 70:
        verdict = "MARCHÉ INTÉRESSANT"
    elif score >= 50:
        verdict = "À CREUSER"
    elif score >= 30:
        verdict = "PRUDENCE"
    else:
        verdict = "FAIBLE"

    confidence = "Moyenne" if listing_counts and history_changes else "Faible"
    demand_proxy = {
        "label": "Non mesurée",
        "score": None,
        "evidence": "Browse API n'expose ni volume de recherche ni ventes exactes des concurrents",
    }
    missing_signals = []
    if not listing_counts:
        missing_signals.append("Concurrence eBay US non mesurée")
    if not history_changes:
        missing_signals.append("Historique eBay US encore insuffisant")
    missing_signals.extend([
        "Volume exact de recherches eBay non public",
        "Ventes exactes des annonces concurrentes non exposées par ce flux",
    ])

    return {
        "method": "EBAY_US_MARKET_STRUCTURE_V1",
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
            "Score de structure du marché eBay US. Il mesure concurrence, concentration, prix et historique ; "
            "il ne prétend pas mesurer les recherches ou les ventes concurrentes."
        ),
    }
