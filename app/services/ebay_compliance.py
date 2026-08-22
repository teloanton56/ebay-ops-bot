"""eBay Marketplace Account Deletion webhook helpers.

The verification challenge uses the exact endpoint and token registered in the
eBay developer portal. Incoming deletion notifications are authenticated with
eBay's ECC signature before any stored user data is touched.
"""

import base64
import hashlib
import json
import re
import time
from typing import Any, Awaitable, Callable
from urllib.parse import quote

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, padding, rsa

from app.config import get_settings
from app.services.db import conn, utc_now
from app.services.ebay import EbayClient, EbayError

TOPIC = "MARKETPLACE_ACCOUNT_DELETION"
_TOKEN_PATTERN = re.compile(r"^[A-Za-z0-9_-]{32,80}$")
_PUBLIC_KEY_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}
_PUBLIC_KEY_TTL_SECONDS = 60 * 60


class EbayComplianceError(RuntimeError):
    pass


def validated_webhook_configuration() -> tuple[str, str]:
    settings = get_settings()
    endpoint = settings.ebay_account_deletion_endpoint.strip()
    token = settings.ebay_account_deletion_verification_token.strip()
    if not endpoint.startswith("https://"):
        raise EbayComplianceError("L'endpoint eBay doit utiliser HTTPS")
    if not _TOKEN_PATTERN.fullmatch(token):
        raise EbayComplianceError(
            "Le jeton de vérification eBay doit être configuré en secret d'environnement et contenir "
            "32 à 80 caractères alphanumériques, _ ou -"
        )
    return endpoint, token


def build_challenge_response(challenge_code: str) -> str:
    challenge = str(challenge_code or "").strip()
    if not challenge or len(challenge) > 512:
        raise EbayComplianceError("Challenge eBay invalide")
    endpoint, token = validated_webhook_configuration()
    digest = hashlib.sha256()
    digest.update(challenge.encode("utf-8"))
    digest.update(token.encode("utf-8"))
    digest.update(endpoint.encode("utf-8"))
    return digest.hexdigest()


def _decode_signature_header(signature_header: str) -> dict[str, str]:
    try:
        raw = base64.b64decode(str(signature_header or ""), validate=True)
        payload = json.loads(raw.decode("ascii"))
    except Exception as exc:
        raise EbayComplianceError("Signature eBay mal formée") from exc
    if not isinstance(payload, dict):
        raise EbayComplianceError("Signature eBay mal formée")
    kid = str(payload.get("kid") or "").strip()
    signature = str(payload.get("signature") or "").strip()
    if not kid or not signature:
        raise EbayComplianceError("Signature eBay incomplète")
    return {"kid": kid, "signature": signature}


def _normalize_public_key(value: str) -> bytes:
    text = str(value or "").strip()
    if not text:
        raise EbayComplianceError("Clé publique eBay vide")
    if "-----BEGIN PUBLIC KEY-----" not in text:
        raise EbayComplianceError("Format de clé publique eBay invalide")
    body = text.replace("-----BEGIN PUBLIC KEY-----", "").replace("-----END PUBLIC KEY-----", "")
    body = "".join(body.split())
    if not body:
        raise EbayComplianceError("Format de clé publique eBay invalide")
    wrapped = "\n".join(body[index:index + 64] for index in range(0, len(body), 64))
    return f"-----BEGIN PUBLIC KEY-----\n{wrapped}\n-----END PUBLIC KEY-----\n".encode("ascii")


def _digest_algorithm(name: str):
    normalized = str(name or "SHA1").replace("-", "").upper()
    if normalized == "SHA256":
        return hashes.SHA256()
    if normalized == "SHA384":
        return hashes.SHA384()
    if normalized == "SHA512":
        return hashes.SHA512()
    if normalized == "SHA1":
        return hashes.SHA1()
    raise EbayComplianceError(f"Digest de signature eBay non pris en charge : {name}")


async def _fetch_public_key(public_key_id: str) -> dict[str, Any]:
    now = time.monotonic()
    cached = _PUBLIC_KEY_CACHE.get(public_key_id)
    if cached and cached[0] > now:
        return cached[1]

    client = EbayClient()
    try:
        token = await client.get_application_token()
        path = f"/commerce/notification/v1/public_key/{quote(public_key_id, safe='')}"
        payload = await client.public_request("GET", path)
    except EbayError as exc:
        raise EbayComplianceError(f"Impossible de récupérer la clé publique eBay : {exc}") from exc
    if not isinstance(payload, dict) or not payload.get("key"):
        raise EbayComplianceError("eBay n'a pas renvoyé de clé publique exploitable")
    _PUBLIC_KEY_CACHE[public_key_id] = (now + _PUBLIC_KEY_TTL_SECONDS, payload)
    return payload


async def verify_notification_signature(
    payload: dict[str, Any],
    signature_header: str,
    *,
    key_loader: Callable[[str], Awaitable[dict[str, Any]]] | None = None,
) -> bool:
    """Validate X-EBAY-SIGNATURE before processing the notification.

    eBay's official Event Notification SDK decodes the header, uses its `kid` to
    fetch /commerce/notification/v1/public_key/{kid}, then verifies the compact
    JSON payload with the returned public key. We follow the same flow here.
    """
    metadata = _decode_signature_header(signature_header)
    loader = key_loader or _fetch_public_key
    key_payload = await loader(metadata["kid"])
    public_key = serialization.load_pem_public_key(_normalize_public_key(str(key_payload.get("key") or "")))
    try:
        signature = base64.b64decode(metadata["signature"], validate=True)
    except Exception as exc:
        raise EbayComplianceError("Signature eBay illisible") from exc

    message = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    digest = _digest_algorithm(str(key_payload.get("digest") or "SHA1"))
    try:
        if isinstance(public_key, ec.EllipticCurvePublicKey):
            public_key.verify(signature, message, ec.ECDSA(digest))
        elif isinstance(public_key, rsa.RSAPublicKey):
            public_key.verify(signature, message, padding.PKCS1v15(), digest)
        else:
            raise EbayComplianceError("Type de clé publique eBay non pris en charge")
    except InvalidSignature:
        return False
    return True


def process_account_deletion(payload: dict[str, Any]) -> dict[str, Any]:
    metadata = payload.get("metadata") if isinstance(payload, dict) else None
    notification = payload.get("notification") if isinstance(payload, dict) else None
    if not isinstance(metadata, dict) or metadata.get("topic") != TOPIC:
        raise EbayComplianceError("Sujet de notification eBay invalide")
    if not isinstance(notification, dict):
        raise EbayComplianceError("Notification eBay invalide")

    notification_id = str(notification.get("notificationId") or "").strip()
    if not notification_id or len(notification_id) > 200:
        raise EbayComplianceError("Identifiant de notification eBay invalide")

    data = notification.get("data") if isinstance(notification.get("data"), dict) else {}
    identifiers = {
        str(data.get(field) or "").strip().casefold()
        for field in ("username", "userId", "eiasToken")
        if str(data.get(field) or "").strip()
    }

    with conn() as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS ebay_account_deletion_receipts (
                notification_id TEXT PRIMARY KEY,
                received_at TEXT NOT NULL,
                deleted_support_cases INTEGER NOT NULL DEFAULT 0
            )
            """
        )
        existing = connection.execute(
            "SELECT deleted_support_cases FROM ebay_account_deletion_receipts WHERE notification_id=?",
            (notification_id,),
        ).fetchone()
        if existing:
            return {
                "notification_id": notification_id,
                "deleted_support_cases": int(existing["deleted_support_cases"]),
                "duplicate": True,
            }

        deleted_support_cases = 0
        if identifiers:
            placeholders = ",".join("?" for _ in identifiers)
            deleted_support_cases = connection.execute(
                f"""
                DELETE FROM support_cases
                WHERE UPPER(marketplace)='EBAY'
                  AND LOWER(TRIM(buyer_alias)) IN ({placeholders})
                """,
                tuple(identifiers),
            ).rowcount

        connection.execute(
            """
            INSERT INTO ebay_account_deletion_receipts(
                notification_id, received_at, deleted_support_cases
            ) VALUES(?,?,?)
            """,
            (notification_id, utc_now(), deleted_support_cases),
        )

    return {
        "notification_id": notification_id,
        "deleted_support_cases": int(deleted_support_cases),
        "duplicate": False,
    }
