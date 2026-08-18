from fastapi import APIRouter

from app.services.ebay import EbayClient

router = APIRouter(prefix="/api/sales-channels", tags=["Sales channels"])


@router.get("")
def sales_channels():
    ebay_connected = EbayClient().token_status().get("connected", False)
    return {
        "recommended_next": "cdiscount",
        "channels": [
            {"id": "ebay", "name": "eBay", "region": "France / international", "status": "Connecté" if ebay_connected else "À connecter", "priority": 0, "fit": "Canal principal", "formats": "API annonces, commandes et stock", "url": "https://developer.ebay.com/", "note": "Intégration actuelle ; publication toujours bloquée par le Dry-run."},
            {"id": "cdiscount", "name": "Cdiscount / Octopia", "region": "France", "status": "Recommandé ensuite", "priority": 1, "fit": "Très adapté au marché français", "formats": "API catalogue, offres, commandes et retours", "url": "https://developer.octopia-io.net/home/", "note": "Le meilleur prochain canal généraliste pour démarrer en France. Connexion à développer après validation eBay Sandbox."},
            {"id": "kaufland", "name": "Kaufland Global Marketplace", "region": "Europe", "status": "Deuxième étape", "priority": 2, "fit": "Expansion Allemagne et Europe", "formats": "API + fichiers CSV produits, stock et commandes", "url": "https://sellerapi.kaufland.com/", "note": "Très intéressant pour réutiliser le catalogue sur plusieurs vitrines européennes."},
            {"id": "amazon", "name": "Amazon", "region": "France / Europe", "status": "Phase ultérieure", "priority": 3, "fit": "Fort volume, règles strictes", "formats": "Selling Partner API + flux JSON", "url": "https://developer-docs.amazon.com/sp-api/docs/manage-product-listings-guide", "note": "À connecter seulement avec logistique, factures, conformité et SAV déjà solides."},
            {"id": "tiktok_shop", "name": "TikTok Shop", "region": "France / Europe", "status": "Test sélectif", "priority": 4, "fit": "Produits visuels et tendances", "formats": "API produits, commandes, logistique et finance", "url": "https://partner.tiktokshop.com/docv2/page/tts-developer-guide", "note": "À tester uniquement sur quelques Winners adaptés aux contenus vidéo."},
            {"id": "etsy", "name": "Etsy", "region": "International", "status": "Cas particuliers", "priority": 5, "fit": "POD, créations, vintage et fournitures", "formats": "Open API v3", "url": "https://developers.etsy.com/documentation/tutorials/listings/", "note": "Pas adapté au dropshipping générique CJ. À réserver aux produits réellement éligibles."},
        ],
        "guardrail": "Aucune publication multicanale automatique avant une validation séparée du compte, des règles produit, du stock et des retours de chaque marketplace.",
    }
