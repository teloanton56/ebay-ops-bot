from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field


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


class SignalScanIn(BaseModel):
    keyword: str = Field(min_length=2, max_length=120)
    sources: list[str] = Field(default_factory=list)
    country: str = Field(default="US", min_length=2, max_length=2)


RETIRED = {"amazon", "aliexpress", "youtube", "tiktok", "etsy", "dropxl", "printful", "printify", "gelato"}


@router.get("")
def list_connections():
    return {
        "sources": [],
        "restricted": [],
        "assisted_suppliers": [],
        "operating_mode": "EBAY_US_CJ_ONLY",
        "message": "v0.23 utilise uniquement eBay US et CJ. eBay et CJ se configurent dans leurs blocs dédiés.",
        "dry_run": True,
    }


@router.post("/signals/scan")
async def scan_signals(_: SignalScanIn):
    raise HTTPException(
        410,
        "Les signaux YouTube/TikTok ont été retirés. Le Radar utilise uniquement les données eBay US.",
    )


@router.get("/aliexpress/authorize")
def authorize_aliexpress():
    raise HTTPException(410, "AliExpress est désactivé dans le mode eBay US / CJ only")


@router.get("/aliexpress/callback", name="aliexpress_oauth_callback")
def aliexpress_oauth_callback():
    raise HTTPException(410, "AliExpress est désactivé dans le mode eBay US / CJ only")


@router.post("/{provider}")
async def save_connection(provider: str, _: ConnectionIn):
    if provider.lower() in RETIRED:
        raise HTTPException(410, f"{provider} est désactivé dans le mode eBay US / CJ only")
    raise HTTPException(404, "Source inconnue")


@router.post("/{provider}/test")
async def test_connection(provider: str):
    if provider.lower() in RETIRED:
        raise HTTPException(410, f"{provider} est désactivé dans le mode eBay US / CJ only")
    raise HTTPException(404, "Source inconnue")


@router.delete("/{provider}")
def remove_connection(provider: str):
    if provider.lower() in RETIRED:
        return {"deleted": True, "disabled": True, "provider": provider.lower()}
    raise HTTPException(404, "Source inconnue")
