import hashlib

from fastapi.testclient import TestClient

from app.config import get_settings
from app.main import app
from app.services import db
from app.services.cloud_auth import public_path


ENDPOINT = "https://ebay-ops-bot.onrender.com/api/ebay/account-deletion"
TOKEN = "elmHFtX9v7eY3YdBkJO5vY_fARVpx8Dw6S6ib-1d98Ar-p_e"


def _configure_cloud(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "compliance.db"))
    monkeypatch.setenv("APP_ACCESS_MODE", "cloud")
    monkeypatch.setenv("APP_ADMIN_EMAIL", "owner@example.com")
    monkeypatch.setenv("APP_ADMIN_PASSWORD", "a-secure-test-password")
    monkeypatch.setenv("APP_SESSION_SECRET", "s" * 40)
    monkeypatch.setenv("APP_ENCRYPTION_KEY", "test-encryption-key")
    monkeypatch.setenv("EBAY_ACCOUNT_DELETION_ENDPOINT", ENDPOINT)
    monkeypatch.setenv("EBAY_ACCOUNT_DELETION_VERIFICATION_TOKEN", TOKEN)
    get_settings.cache_clear()


def test_ebay_challenge_endpoint_is_public_and_matches_required_hash(monkeypatch, tmp_path):
    _configure_cloud(monkeypatch, tmp_path)
    challenge = "ebay-test-123"
    expected = hashlib.sha256((challenge + TOKEN + ENDPOINT).encode("utf-8")).hexdigest()

    assert public_path("/api/ebay/account-deletion") is True
    with TestClient(app) as client:
        response = client.get("/api/ebay/account-deletion", params={"challenge_code": challenge})

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/json")
    assert response.json() == {"challengeResponse": expected}
    get_settings.cache_clear()


def test_account_deletion_notification_removes_matching_ebay_support_data_idempotently(monkeypatch, tmp_path):
    _configure_cloud(monkeypatch, tmp_path)
    now = "2026-08-21T16:00:00+00:00"
    payload = {
        "metadata": {
            "topic": "MARKETPLACE_ACCOUNT_DELETION",
            "schemaVersion": "1.0",
            "deprecated": False,
        },
        "notification": {
            "notificationId": "notification-123",
            "eventDate": now,
            "publishDate": now,
            "publishAttemptCount": 1,
            "data": {
                "username": "buyer-to-delete",
                "userId": "immutable-user-id",
                "eiasToken": "legacy-eias-token",
            },
        },
    }

    with TestClient(app) as client:
        with db.conn() as connection:
            connection.execute(
                """
                INSERT INTO support_cases(
                    marketplace, order_ref, buyer_alias, subject, category, priority,
                    status, customer_message, internal_notes, draft_response,
                    created_at, updated_at
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    "EBAY", "ORDER-1", "buyer-to-delete", "Retard", "Retard de livraison",
                    "Normale", "Nouveau", "Message client", "Note interne", "Brouillon", now, now,
                ),
            )

        first = client.post("/api/ebay/account-deletion", json=payload)
        second = client.post("/api/ebay/account-deletion", json=payload)

        with db.conn() as connection:
            remaining = connection.execute("SELECT COUNT(*) AS count FROM support_cases").fetchone()["count"]
            receipt = connection.execute(
                "SELECT notification_id, deleted_support_cases FROM ebay_account_deletion_receipts"
            ).fetchone()

    assert first.status_code == 204
    assert second.status_code == 204
    assert remaining == 0
    assert dict(receipt) == {"notification_id": "notification-123", "deleted_support_cases": 1}
    get_settings.cache_clear()
