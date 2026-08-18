from typing import Any


# Curated starting points only. "À demander" never means that a CSV is guaranteed:
# the seller must confirm rights, price, stock frequency and redistribution terms.
SUPPLIER_DIRECTORY: list[dict[str, Any]] = [
    {"id": "syncee", "name": "Syncee", "url": "https://syncee.com/", "region": "International", "categories": ["Généraliste"], "model": "Dropshipping", "catalog": "Datafeed / intégration", "catalog_level": "feed", "note": "Réseau de fournisseurs ; disponibilité des flux selon le fournisseur et le plan."},
    {"id": "avasam", "name": "Avasam", "url": "https://www.avasam.com/", "region": "Royaume-Uni", "categories": ["Généraliste", "Maison", "Beauté"], "model": "Dropshipping", "catalog": "API / intégration", "catalog_level": "api", "note": "Plateforme automatisée ; vérifier livraison, douane et retours vers la France."},
    {"id": "appscenic", "name": "AppScenic", "url": "https://appscenic.com/", "region": "International", "categories": ["Généraliste", "Maison", "Animaux"], "model": "Dropshipping", "catalog": "Intégration / export selon offre", "catalog_level": "feed", "note": "Catalogue multi-fournisseurs ; valider le stock européen produit par produit."},
    {"id": "spocket", "name": "Spocket", "url": "https://www.spocket.co/", "region": "Europe / USA", "categories": ["Généraliste", "Mode", "Maison"], "model": "Dropshipping", "catalog": "Intégration", "catalog_level": "feed", "note": "Permet de repérer des fournisseurs UE/USA ; disponibilité réelle à confirmer."},
    {"id": "brands_gateway", "name": "BrandsGateway", "url": "https://brandsgateway.com/", "region": "Europe / International", "categories": ["Mode", "Luxe"], "model": "Grossiste / dropshipping", "catalog": "CSV / XML / API selon formule", "catalog_level": "csv", "note": "Mode premium ; contrôler autorisations de marque et conditions de revente."},
    {"id": "bdroppy", "name": "BDroppy", "url": "https://www.bdroppy.com/", "region": "Europe", "categories": ["Mode", "Accessoires"], "model": "Dropshipping", "catalog": "Connecteur / flux selon formule", "catalog_level": "feed", "note": "Catalogue mode de Brandsdistribution ; accès dépendant de la formule."},
    {"id": "matterhorn", "name": "Matterhorn Wholesale", "url": "https://matterhorn-wholesale.com/", "region": "Europe", "categories": ["Mode", "Chaussures"], "model": "Grossiste", "catalog": "XML / fichier partenaire", "catalog_level": "csv", "note": "Mode européenne ; demander la documentation du flux et la fréquence de stock."},
    {"id": "bts_wholesaler", "name": "BTSWholesaler", "url": "https://www.btswholesaler.com/", "region": "Europe", "categories": ["Beauté", "Parfumerie"], "model": "Grossiste / dropshipping", "catalog": "CSV / XML à confirmer", "catalog_level": "csv", "note": "Beauté et parfumerie ; vérifier authenticité, restrictions de marque et transport."},
    {"id": "griffati", "name": "Griffati B2B", "url": "https://www.griffati.com/", "region": "Europe", "categories": ["Mode", "Luxe", "Chaussures"], "model": "Grossiste / dropshipping", "catalog": "Flux / intégration selon contrat", "catalog_level": "feed", "note": "Mode de marque ; exiger factures, droits de revente et politique de retours."},
    {"id": "ankorstore", "name": "Ankorstore", "url": "https://www.ankorstore.com/", "region": "Europe", "categories": ["Maison", "Beauté", "Épicerie", "Enfants"], "model": "Marketplace B2B", "catalog": "CSV à demander à la marque", "catalog_level": "request", "note": "Bon point de départ pour trouver des marques européennes plus niches."},
    {"id": "faire", "name": "Faire", "url": "https://www.faire.com/", "region": "Europe / International", "categories": ["Maison", "Cadeaux", "Beauté", "Enfants"], "model": "Marketplace B2B", "catalog": "CSV à demander à la marque", "catalog_level": "request", "note": "Nombreuses petites marques ; vérifier si la revente marketplace est autorisée."},
    {"id": "orderchamp", "name": "Orderchamp", "url": "https://www.orderchamp.com/", "region": "Europe", "categories": ["Maison", "Cadeaux", "Beauté", "Mode"], "model": "Marketplace B2B", "catalog": "CSV à demander à la marque", "catalog_level": "request", "note": "Sourcing de marques européennes ; les conditions diffèrent par fournisseur."},
    {"id": "europages", "name": "Europages", "url": "https://www.europages.fr/", "region": "Europe", "categories": ["Fabricants", "Industrie", "Généraliste"], "model": "Annuaire B2B", "catalog": "Contact / CSV à négocier", "catalog_level": "request", "note": "Utile pour contacter directement fabricants et grossistes européens."},
    {"id": "kompass", "name": "Kompass", "url": "https://fr.kompass.com/", "region": "International", "categories": ["Fabricants", "Industrie", "Généraliste"], "model": "Annuaire B2B", "catalog": "Contact / données sous licence", "catalog_level": "request", "note": "Annuaire d'entreprises ; demander catalogue, tarif revendeur et flux au contact."},
    {"id": "solostocks", "name": "SoloStocks", "url": "https://www.solostocks.fr/", "region": "France / Europe", "categories": ["Généraliste", "Industrie"], "model": "Marketplace B2B", "catalog": "CSV à demander au vendeur", "catalog_level": "request", "note": "Lots et grossistes ; contrôler chaque vendeur et commander un échantillon."},
    {"id": "merkandi", "name": "Merkandi", "url": "https://merkandi.fr/", "region": "Europe / International", "categories": ["Déstockage", "Généraliste"], "model": "Annuaire grossistes", "catalog": "CSV potentiel sur demande", "catalog_level": "request", "note": "Lots et déstockage ; stock souvent ponctuel, donc prudence pour la synchronisation."},
    {"id": "global_sources", "name": "Global Sources", "url": "https://www.globalsources.com/manufacturers/", "region": "Asie / International", "categories": ["Fabricants", "Électronique", "Maison"], "model": "Annuaire fabricants", "catalog": "RFQ / CSV à négocier", "catalog_level": "request", "note": "Pour négocier usine, échantillons, conformité et éventuel flux produit."},
    {"id": "made_in_china", "name": "Made-in-China", "url": "https://www.made-in-china.com/", "region": "Chine / International", "categories": ["Fabricants", "Industrie", "Électronique"], "model": "Annuaire fabricants", "catalog": "RFQ / CSV à négocier", "catalog_level": "request", "note": "Recherche de fabricants ; vérifier audit, certificats et échantillons."},
    {"id": "thomasnet", "name": "Thomasnet", "url": "https://www.thomasnet.com/", "region": "Amérique du Nord", "categories": ["Fabricants", "Industrie"], "model": "Annuaire fabricants", "catalog": "Contact / fichier à négocier", "catalog_level": "request", "note": "Intéressant pour produits techniques et fabricants nord-américains."},
]


def search_supplier_directory(query: str = "", category: str = "", catalog_level: str = "") -> list[dict[str, Any]]:
    needle = query.strip().lower()
    category = category.strip().lower()
    catalog_level = catalog_level.strip().lower()
    rows = []
    for item in SUPPLIER_DIRECTORY:
        haystack = " ".join([item["name"], item["region"], item["model"], item["catalog"], item["note"], *item["categories"]]).lower()
        if needle and needle not in haystack:
            continue
        if category and category not in [value.lower() for value in item["categories"]]:
            continue
        if catalog_level and item["catalog_level"] != catalog_level:
            continue
        rows.append(item)
    return rows
