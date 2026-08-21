"""eBay Marketplace Account Deletion webhook helpers.

The verification challenge uses the exact endpoint and token registered in the
eBay developer portal.  Deletion notifications are processed idempotently and
only non-personal receipt metadata is retained.
"""

import hashlib
import re
from typing import Any

from app.config import get_settings
from app.services.db import conn, utc_now

TOPIC = "MARKETPLACE_ACCOUNT_DELETION"
_TOKEN_PATTERN = re.compile(r"^[A-Za-z0-9_-]{32,80}$")


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
            "Le jeton de vérification eBay doit contenir 32 à 80 caractères alphanumériques, _ ou -"
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
