from html import escape

from fastapi import APIRouter, Query
from fastapi.responses import RedirectResponse, HTMLResponse

from app.config import get_settings
from app.services.ebay import EbayClient, EbayError

router = APIRouter(prefix="/api/auth/ebay", tags=["eBay OAuth"])


@router.get("/prepare")
def prepare():
    s = get_settings()
    missing = []
    if not s.ebay_client_id:
        missing.append("EBAY_CLIENT_ID")
    if not s.ebay_client_secret:
        missing.append("EBAY_CLIENT_SECRET")
    if not s.ebay_runame:
        missing.append("EBAY_RUNAME")
    status = EbayClient().token_status()
    if missing:
        return {"ready": False, "connected": status.get("connected", False), "missing": missing, "authorization_url": None}
    try:
        url = EbayClient().authorization_url()
    except EbayError as exc:
        return {"ready": False, "connected": status.get("connected", False), "missing": [], "error": str(exc), "authorization_url": None}
    return {"ready": True, "connected": status.get("connected", False), "missing": [], "authorization_url": url}


@router.get("/start")
def start():
    s = get_settings()
    if not s.ebay_client_id or not s.ebay_client_secret or not s.ebay_runame:
        return RedirectResponse("/?notice=ebay_keys_missing")
    try:
        return RedirectResponse(EbayClient().authorization_url())
    except EbayError:
        return RedirectResponse("/?notice=ebay_auth_error")


@router.get("/callback", response_class=HTMLResponse)
async def callback(code: str = Query(...), state: str | None = Query(None)):
    try:
        await EbayClient().exchange_code(code, state)
        return """
        <!doctype html><html lang='fr'><meta charset='utf-8'><title>eBay connecté</title>
        <body style='font-family:Segoe UI,Arial;background:#f5f7fb;padding:50px;color:#111827'>
        <div style='max-width:650px;margin:auto;background:white;padding:30px;border-radius:16px;border:1px solid #e5e7eb'>
        <h2>Compte eBay connecté ✅</h2><p>L'autorisation OAuth a été enregistrée dans votre espace privé.</p>
        <a href='/' style='display:inline-block;padding:10px 14px;background:#2563eb;color:white;text-decoration:none;border-radius:8px'>Retour au dashboard</a>
        </div></body></html>"""
    except EbayError as exc:
        return HTMLResponse(f"""
        <!doctype html><html lang='fr'><meta charset='utf-8'><title>Erreur eBay</title>
        <body style='font-family:Segoe UI,Arial;background:#f5f7fb;padding:50px;color:#111827'>
        <div style='max-width:650px;margin:auto;background:white;padding:30px;border-radius:16px;border:1px solid #fecaca'>
        <h2>Connexion eBay impossible</h2><p>{escape(str(exc))}</p><p>Retourne au dashboard et ouvre « Paramètres eBay ».</p>
        <a href='/' style='display:inline-block;padding:10px 14px;background:#2563eb;color:white;text-decoration:none;border-radius:8px'>Retour au dashboard</a>
        </div></body></html>""", status_code=400)


@router.get("/status")
def status():
    return EbayClient().token_status()
