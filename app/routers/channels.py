from fastapi import APIRouter

from app.services.ebay import EbayClient

router = APIRouter(prefix="/api/sales-channels", tags=["Sales channels"])


@router.get("")
def sales_channels():
    ebay_connected = EbayClient().token_status().get("connected", False)
    return {
        "recommended_next": None,
        "channels": [
            {
                "id": "ebay",
                "name": "eBay US",
                "region": "United States",
                "status": "Connecté" if ebay_connected else "À connecter",
                "priority": 0,
                "fit": "Canal unique",
                "formats": "API annonces, commandes et stock",
                "url": "https://developer.ebay.com/",
                "note": "Marché EBAY_US en USD ; publication protégée par les verrous d'écriture.",
            },
        ],
        "operating_mode": "EBAY_US_CJ_ONLY",
        "guardrail": "Aucun autre canal de vente n'est pris en charge.",
    }
