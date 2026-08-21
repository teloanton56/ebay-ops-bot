from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.services.connections import (IntegrationError, PROVIDERS, connection_status,
                                      connection_statuses, delete_credentials,
                                      save_credentials, scan_connected_sources,
                                      test_provider)
from app.services.marketplace_supplier_sources import (
    aliexpress_connection_status,
    delete_aliexpress_credentials,
    save_aliexpress_credentials,
    test_aliexpress_connection,
)


router = APIRouter(prefix="/api/connections", tags=["Connexions"])


class ConnectionIn(BaseModel):
    api_key: str | None = Field(default=None, max_length=1000)
    api_email: str | None = Field(default=None, max_length=320)
    api_token: str | None = Field(default=None, max_length=2000)
    client_id: str | None = Field(default=None, max_length=1000)
    client_key: str | None = Field(default=None, max_length=1000)
    client_secret: str | None = Field(default=None, max_length=2000)
    refresh_token: str | None = Field(default=None, max_length=4000)
    app_key: str | None = Field(default=None, max_length=1000)
    app_secret: str | None = Field(default=None, max_length=2000)
    tracking_id: str | None = Field(default=None, max_length=1000)
    environment: Literal["production", "sandbox"] | None = None


class SignalScanIn(BaseModel):
    keyword: str = Field(min_length=2, max_length=120)
    sources: list[Literal["tiktok", "youtube", "etsy"]] = Field(min_length=1, max_length=3)
    country: str = Field(default="FR", min_length=2, max_length=2)


@router.get("")
def list_connections():
    hidden = {"etsy", "dropxl", "printful", "printify", "gelato"}
    sources = [row for row in connection_statuses() if row["id"] not in hidden]
    sources.append(aliexpress_connection_status())
    return {
        "sources": sources,
        "restricted": [
            {"id": "google_trends", "name": "Google Trends", "status": "Accès Alpha à demander",
             "url": "https://developers.google.com/search/apis/trends",
             "note": "Le connecteur sera activé uniquement après acceptation officielle de Google."},
            {"id": "meta", "name": "Meta Ad Library", "status": "Autorisation Meta requise",
             "url": "https://www.facebook.com/ads/library/api/",
             "note": "Les annonces peuvent être observées, jamais les conversions concurrentes."},
        ],
        "assisted_suppliers": [],
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
    values = {key: value for key, value in payload.model_dump().items() if value is not None and str(value).strip()}
    if not values:
        raise HTTPException(400, "Aucun identifiant renseigné")

    if provider == "aliexpress":
        save_aliexpress_credentials(values)
        if not aliexpress_connection_status()["configured"]:
            raise HTTPException(400, "Identifiants AliExpress incomplets")
        try:
            tested = await test_aliexpress_connection()
        except Exception as exc:
            raise HTTPException(400, f"Identifiants enregistrés, mais test impossible : {exc}") from exc
        return {"saved": True, "tested": True, "connection": aliexpress_connection_status(),
                "observed": tested.get("observed", 0),
                "message": "Connexion fournisseur AliExpress vérifiée."}

    if provider not in PROVIDERS:
        raise HTTPException(404, "Source inconnue")
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
    if provider == "aliexpress":
        try:
            result = await test_aliexpress_connection()
            return {"tested": True, "connection": aliexpress_connection_status(), **result}
        except Exception as exc:
            raise HTTPException(400, str(exc)) from exc

    if provider not in PROVIDERS:
        raise HTTPException(404, "Source inconnue")
    try:
        result = await test_provider(provider)
        return {"tested": True, "connection": connection_status(provider), **result}
    except IntegrationError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.delete("/{provider}")
def remove_connection(provider: str):
    if provider == "aliexpress":
        delete_aliexpress_credentials()
        return {"deleted": True, "connection": aliexpress_connection_status()}

    if provider not in PROVIDERS:
        raise HTTPException(404, "Source inconnue")
    try:
        delete_credentials(provider)
    except IntegrationError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"deleted": True, "connection": connection_status(provider)}
