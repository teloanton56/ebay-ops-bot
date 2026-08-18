"""Small single-owner authentication layer for the hosted application.

The bot is a personal operations console, not a public multi-tenant service.  A
signed, HTTP-only cookie is therefore enough while keeping deployment simple.
"""

import base64
import hashlib
import hmac
import json
import time
from collections import defaultdict, deque
from urllib.parse import urlsplit

from app.config import Settings

COOKIE_NAME = "ops_session"
_FAILURES: dict[str, deque[float]] = defaultdict(deque)
_FAILURE_WINDOW_SECONDS = 15 * 60
_MAX_FAILURES = 5


def validate_cloud_configuration(settings: Settings) -> None:
    if not settings.cloud_mode:
        return
    missing = []
    if not settings.app_admin_email.strip():
        missing.append("APP_ADMIN_EMAIL")
    if len(settings.app_admin_password) < 12:
        missing.append("APP_ADMIN_PASSWORD (12 caractères minimum)")
    if len(settings.app_session_secret) < 32:
        missing.append("APP_SESSION_SECRET (32 caractères minimum)")
    if not settings.app_encryption_key.strip():
        missing.append("APP_ENCRYPTION_KEY")
    if missing:
        raise RuntimeError("Configuration cloud incomplète : " + ", ".join(missing))


def _b64encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode().rstrip("=")


def _b64decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def create_session(email: str, settings: Settings) -> str:
    payload = json.dumps(
        {"email": email.strip().lower(), "exp": int(time.time()) + max(settings.app_session_days, 1) * 86400},
        separators=(",", ":"),
    ).encode()
    encoded = _b64encode(payload)
    signature = hmac.new(settings.app_session_secret.encode(), encoded.encode(), hashlib.sha256).digest()
    return encoded + "." + _b64encode(signature)


def session_email(token: str | None, settings: Settings) -> str | None:
    if not token or "." not in token or not settings.app_session_secret:
        return None
    encoded, supplied = token.split(".", 1)
    expected = hmac.new(settings.app_session_secret.encode(), encoded.encode(), hashlib.sha256).digest()
    try:
        if not hmac.compare_digest(expected, _b64decode(supplied)):
            return None
        payload = json.loads(_b64decode(encoded))
        if int(payload.get("exp", 0)) <= int(time.time()):
            return None
        email = str(payload.get("email", "")).strip().lower()
        return email if hmac.compare_digest(email, settings.app_admin_email.strip().lower()) else None
    except (ValueError, TypeError, json.JSONDecodeError):
        return None


def credentials_match(email: str, password: str, settings: Settings) -> bool:
    expected_email = settings.app_admin_email.strip().lower().encode()
    expected_password = settings.app_admin_password.encode()
    return hmac.compare_digest(email.strip().lower().encode(), expected_email) and hmac.compare_digest(
        password.encode(), expected_password
    )


def login_blocked(client_id: str) -> tuple[bool, int]:
    now = time.monotonic()
    failures = _FAILURES[client_id]
    while failures and now - failures[0] > _FAILURE_WINDOW_SECONDS:
        failures.popleft()
    if len(failures) < _MAX_FAILURES:
        return False, 0
    return True, max(1, int(_FAILURE_WINDOW_SECONDS - (now - failures[0])))


def record_login_failure(client_id: str) -> None:
    _FAILURES[client_id].append(time.monotonic())


def clear_login_failures(client_id: str) -> None:
    _FAILURES.pop(client_id, None)


def public_path(path: str) -> bool:
    return (
        path == "/health"
        or path == "/login"
        or path == "/api/cloud/login"
        or path == "/manifest.webmanifest"
        or path == "/service-worker.js"
        or path == "/offline"
        or path.startswith("/static/")
    )


def allowed_origins(settings: Settings) -> set[str]:
    origins = {"http://127.0.0.1:8765", "http://localhost:8765", "http://testserver", "https://testserver"}
    if settings.app_base_url.strip():
        origins.add(settings.app_base_url.rstrip("/"))
    import os

    render_host = os.getenv("RENDER_EXTERNAL_HOSTNAME", "").strip()
    if render_host:
        origins.add(f"https://{render_host}")
    return origins


def allowed_hosts(settings: Settings) -> list[str]:
    hosts = {"127.0.0.1", "localhost", "testserver"}
    parsed = urlsplit(settings.app_base_url)
    if parsed.hostname:
        hosts.add(parsed.hostname)
    hosts.update(host.strip() for host in settings.app_allowed_hosts.split(",") if host.strip())
    # Render injects this hostname automatically; accepting it avoids a manual
    # second configuration step while still not trusting arbitrary Host headers.
    import os

    render_host = os.getenv("RENDER_EXTERNAL_HOSTNAME", "").strip()
    if render_host:
        hosts.add(render_host)
    return sorted(hosts)
