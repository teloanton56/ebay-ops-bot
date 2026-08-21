from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlencode

import httpx

from app.services.db import kv_get, kv_set
from app.services.marketplace_supplier_sources import (
    ALIEXPRESS_OAUTH_STATE_KEY,
    load_aliexpress_credentials,
    save_aliexpress_credentials,
)


ALIEXPRESS_AUTHORIZE_URL = "https://api-sg.aliexpress.com/oauth/authorize"
ALIEXPRESS_REST_BASE = "https://api-sg.aliexpress.com/rest"
TOKEN_PATH = "/auth/token/create"


def authorization_url(redirect_uri: str) -> str:
    credentials = load_aliexpress_credentials()
    app_key = str(credentials.get("app_key") or "").strip()
    app_secret = str(credentials.get("app_secret") or "").strip()
    if not app_key or not app_secret:
        raise RuntimeError("Enregistrez d'abord l'App Key et l'App Secret AliExpress")

    state = secrets.token_urlsafe(32)
    kv_set(ALIEXPRESS_OAUTH_STATE_KEY, state)
    query = urlencode({
        "response_type": "code",
        "force_auth": "true",
        "redirect_uri": redirect_uri,
        "client_id": app_key,
        "state": state,
    })
    return f"{ALIEXPRESS_AUTHORIZE_URL}?{query}"


def _sign(path: str, params: dict[str, Any], app_secret: str) -> str:
    ordered = "".join(f"{key}{params[key]}" for key in sorted(params) if key != "sign")
    payload = f"{path}{ordered}".encode("utf-8")
    return hmac.new(app_secret.encode("utf-8"), payload, hashlib.sha256).hexdigest().upper()


async def exchange_authorization(code: str, state: str, redirect_uri: str) -> dict[str, Any]:
    expected = kv_get(ALIEXPRESS_OAUTH_STATE_KEY)
    if not expected or state != expected:
        raise RuntimeError("État OAuth AliExpress invalide. Relancez l'autorisation depuis le bot.")

    credentials = load_aliexpress_credentials()
    app_key = str(credentials.get("app_key") or "").strip()
    app_secret = str(credentials.get("app_secret") or "").strip()
    if not app_key or not app_secret:
        raise RuntimeError("Identifiants AliExpress incomplets")

    params: dict[str, Any] = {
        "app_key": app_key,
        "code": code,
        "sign_method": "sha256",
        "timestamp": str(int(datetime.now(timezone.utc).timestamp() * 1000)),
    }
    params["sign"] = _sign(TOKEN_PATH, params, app_secret)

    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.post(f"{ALIEXPRESS_REST_BASE}{TOKEN_PATH}", data=params)

    try:
        payload = response.json()
    except Exception as exc:
        raise RuntimeError("AliExpress a renvoyé une réponse OAuth illisible") from exc

    error_code = payload.get("code")
    if response.is_error or not payload.get("access_token") or str(error_code or "0") not in {"0", "200"}:
        message = (
            payload.get("message")
            or payload.get("msg")
            or payload.get("error_description")
            or payload.get("error")
            or payload.get("sub_msg")
            or f"AliExpress refuse l'autorisation ({error_code})"
        )
        save_aliexpress_credentials({"last_error": str(message), "verified_at": ""})
        raise RuntimeError(str(message))

    now = datetime.now(timezone.utc).isoformat()
    save_aliexpress_credentials({
        "access_token": payload.get("access_token"),
        "refresh_token": payload.get("refresh_token"),
        "expire_time": payload.get("expires_in") or payload.get("expire_time"),
        "refresh_token_valid_time": payload.get("refresh_expires_in") or payload.get("refresh_token_valid_time"),
        "user_id": payload.get("user_id") or payload.get("account_id") or payload.get("seller_id"),
        "user_nick": payload.get("account") or payload.get("user_nick"),
        "authorized_at": now,
        "verified_at": now,
        "last_error": "",
    })
    kv_set(ALIEXPRESS_OAUTH_STATE_KEY, "")
    return payload


async def test_connection() -> dict[str, Any]:
    credentials = load_aliexpress_credentials()
    if not credentials.get("app_key") or not credentials.get("app_secret"):
        raise RuntimeError("Clés AliExpress manquantes")
    if not credentials.get("access_token"):
        raise RuntimeError("Autorisation OAuth AliExpress requise")
    if credentials.get("last_error"):
        raise RuntimeError(str(credentials["last_error"]))
    if not credentials.get("verified_at"):
        save_aliexpress_credentials({"verified_at": datetime.now(timezone.utc).isoformat(), "last_error": ""})
    return {
        "ok": True,
        "observed": 1,
        "marketplace": "AliExpress",
        "api": "AliExpress Open Platform (overseas)",
    }
