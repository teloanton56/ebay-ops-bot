from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.services.connections import (ASSISTED_SUPPLIERS, IntegrationError, PROVIDERS, connection_status,
                                      connection_statuses, delete_credentials,
                                      save_credentials, scan_connected_sources,
                                      test_provider)


router = APIRouter(prefix="/api/connections", tags=["Connexions"])


class ConnectionIn(BaseModel):
    api_key: str | None = Field(default=None, max_length=1000)
    api_email: str | None = Field(default=None, max_length=320)
    api_token: str | None = Field(default=None, max_length=2000)
    client_key: str | None = Field(default=None, max_length=1000)
    client_secret: str | None = Field(default=None, max_length=2000)
    environment: Literal["production", "sandbox"] | None = None


class SignalScanIn(BaseModel):
    keyword: str = Field(min_length=2, max_length=120)
    sources: list[Literal["tiktok", "youtube", "etsy"]] = Field(min_length=1, max_length=3)
    country: str = Field(default="FR", min_length=2, max_length=2)


@router.get("")
def list_connections():
    return {
        "sources": connection_statuses(),
        "restricted": [
            {"id": "aliexpress", "name": "AliExpress", "status": "Recherche uniquement",
             "url": "https://www.aliexpress.com/",
             "note": "Comparaison de produits uniquement : aucune commande eBay ne sera exécutée via une marketplace de détail."},
            {"id": "google_trends", "name": "Google Trends", "status": "Accès Alpha à demander",
             "url": "https://developers.google.com/search/apis/trends",
             "note": "Le connecteur sera activé uniquement après acceptation officielle de Google."},
            {"id": "amazon", "name": "Amazon SP-API", "status": "Compte vendeur professionnel requis",
             "url": "https://developer-docs.amazon.com/sp-api/docs/onboarding-overview",
             "note": "Connexion possible après validation du profil développeur et des rôles Amazon."},
            {"id": "meta", "name": "Meta Ad Library", "status": "Autorisation Meta requise",
             "url": "https://www.facebook.com/ads/library/api/",
             "note": "Les annonces peuvent être observées, jamais les conversions concurrentes."},
        ],
        "assisted_suppliers": ASSISTED_SUPPLIERS,
        "dry_run": True,
    }


@router.post("/signals/scan")
async def scan_signals(payload: SignalScanIn):
    try:
        return await scan_connected_sources(payload.keyword.strip(), payload.sources, payload.country.upper())
    except IntegrationError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.post("/{provider}")
async def save_connection(provider: str, payload: ConnectionIn):
    if provider not in PROVIDERS:
        raise HTTPException(404, "Source inconnue")
    values = {key: value for key, value in payload.model_dump().items() if value is not None and str(value).strip()}
    if not values:
        raise HTTPException(400, "Aucun identifiant renseigné")
    try:
        save_credentials(provider, values)
        missing = [field for field in PROVIDERS[provider]["required"]
                   if not connection_status(provider)["configured"]]
        if missing:
            raise HTTPException(400, "Identifiants incomplets")
        tested = await test_provider(provider)
        return {"saved": True, "tested": True, "connection": connection_status(provider),
                "observed": tested.get("observed", 0),
                "message": "Connexion vérifiée en lecture seule."}
    except HTTPException:
        raise
    except IntegrationError as exc:
        raise HTTPException(400, f"Identifiants enregistrés, mais test impossible : {exc}") from exc


@router.post("/{provider}/test")
async def test_connection(provider: str):
    if provider not in PROVIDERS:
        raise HTTPException(404, "Source inconnue")
    try:
        result = await test_provider(provider)
        return {"tested": True, "connection": connection_status(provider), **result}
    except IntegrationError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.delete("/{provider}")
def remove_connection(provider: str):
    if provider not in PROVIDERS:
        raise HTTPException(404, "Source inconnue")
    try:
        delete_credentials(provider)
    except IntegrationError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"deleted": True, "connection": connection_status(provider)}
