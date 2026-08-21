"""Quota protection for automatic eBay Browse API work.

The guard prefers the official Developer Analytics API. When that endpoint is
unavailable, it falls back to a conservative local daily budget. Reservations
are recorded before scans start so concurrent or repeated jobs cannot exhaust
the remaining allowance accidentally.
"""

from __future__ import annotations

import json
import math
import sqlite3
from datetime import datetime, timezone
from typing import Any

import httpx

from app.services.db import init_db, kv_get, kv_set
from app.services.ebay import EbayClient
from app.services.radar_runtime import load_radar_settings

ACTUAL_CACHE_KEY = "radar:quota:actual:v1"
LOCAL_USAGE_PREFIX = "radar:quota:local:"
CACHE_SECONDS = 10 * 60


class RadarQuotaError(RuntimeError):
    def __init__(self, message: str, status: dict[str, Any]):
        super().__init__(message)
        self.status = status


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _today_key() -> str:
    return LOCAL_USAGE_PREFIX + _now().date().isoformat()


def _read_json(key: str, default: Any) -> Any:
    try:
        raw = kv_get(key)
    except sqlite3.OperationalError:
        return default
    if not raw:
        return default
    try:
        return json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return default


def _local_reserved() -> int:
    payload = _read_json(_today_key(), {"reserved": 0})
    try:
        return max(int(payload.get("reserved") or 0), 0) if isinstance(payload, dict) else 0
    except (TypeError, ValueError):
        return 0


def _set_local_reserved(value: int, purpose: str = "") -> None:
    init_db()
    kv_set(
        _today_key(),
        json.dumps(
            {
                "reserved": max(int(value), 0),
                "updated_at": _now().isoformat(),
                "last_purpose": purpose,
            },
            ensure_ascii=False,
        ),
    )


def _cache_fresh(snapshot: dict[str, Any]) -> bool:
    raw = str(snapshot.get("fetched_at") or "")
    if not raw:
        return False
    try:
        fetched = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return False
    return (_now() - fetched).total_seconds() < CACHE_SECONDS


def _parse_browse_limits(payload: dict[str, Any]) -> dict[str, Any] | None:
    candidates: list[dict[str, Any]] = []
    for limit_row in payload.get("rateLimits") or []:
        if not isinstance(limit_row, dict):
            continue
        if str(limit_row.get("apiContext") or "").casefold() != "buy":
            continue
        if str(limit_row.get("apiName") or "").casefold() != "browse":
            continue
        for resource in limit_row.get("resources") or []:
            if not isinstance(resource, dict):
                continue
            resource_name = str(resource.get("name") or "browse")
            for rate in resource.get("rates") or []:
                if not isinstance(rate, dict):
                    continue
                try:
                    limit_value = int(rate.get("limit"))
                    remaining = int(rate.get("remaining"))
                    count = int(rate.get("count"))
                    time_window = int(rate.get("timeWindow"))
                except (TypeError, ValueError):
                    continue
                if limit_value <= 0 or time_window < 3600:
                    continue
                candidates.append(
                    {
                        "resource": resource_name,
                        "limit": limit_value,
                        "remaining": max(remaining, 0),
                        "count": max(count, 0),
                        "reset": rate.get("reset"),
                        "time_window": time_window,
                    }
                )
    if not candidates:
        return None

    # Browse search and item detail can have separate resource counters. The
    # minimum remaining allowance is the safest value for a mixed scan.
    most_constrained = min(
        candidates,
        key=lambda row: (row["remaining"] / max(row["limit"], 1), row["remaining"]),
    )
    return {
        "limit": most_constrained["limit"],
        "remaining": most_constrained["remaining"],
        "count": most_constrained["count"],
        "reset": most_constrained.get("reset"),
        "resource": most_constrained["resource"],
        "resources": candidates,
    }


async def _fetch_actual_snapshot() -> dict[str, Any]:
    client = EbayClient()
    token = await client.get_application_token()
    url = f"{client.s.ebay_api_base}/developer/analytics/v1_beta/rate_limit/"
    async with httpx.AsyncClient(timeout=20) as http:
        response = await http.get(
            url,
            headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
        )
    if response.is_error:
        raise RuntimeError(f"Developer Analytics indisponible ({response.status_code})")
    try:
        payload = response.json()
    except ValueError as exc:
        raise RuntimeError("Réponse Developer Analytics illisible") from exc
    parsed = _parse_browse_limits(payload if isinstance(payload, dict) else {})
    if not parsed:
        raise RuntimeError("Quota Browse absent de Developer Analytics")
    snapshot = {
        **parsed,
        "source": "EBAY_ANALYTICS",
        "fetched_at": _now().isoformat(),
        "local_reserved_at_fetch": _local_reserved(),
    }
    kv_set(ACTUAL_CACHE_KEY, json.dumps(snapshot, ensure_ascii=False))
    return snapshot


async def quota_status(force: bool = False) -> dict[str, Any]:
    init_db()
    config = load_radar_settings()
    local_reserved = _local_reserved()
    cached = _read_json(ACTUAL_CACHE_KEY, {})
    snapshot: dict[str, Any] | None = cached if isinstance(cached, dict) else None
    error = ""

    if force or not snapshot or not _cache_fresh(snapshot):
        try:
            snapshot = await _fetch_actual_snapshot()
        except Exception as exc:
            error = str(exc)
            snapshot = cached if isinstance(cached, dict) and cached else None

    fallback_limit = int(config["browse_daily_budget"])
    local_remaining = max(fallback_limit - local_reserved, 0)
    actual_remaining: int | None = None
    actual_limit: int | None = None
    reset = None
    resource = None

    if snapshot:
        try:
            actual_limit = int(snapshot.get("limit"))
            raw_remaining = int(snapshot.get("remaining"))
            reserved_at_fetch = int(snapshot.get("local_reserved_at_fetch") or 0)
            pending = max(local_reserved - reserved_at_fetch, 0)
            actual_remaining = max(raw_remaining - pending, 0)
            reset = snapshot.get("reset")
            resource = snapshot.get("resource")
        except (TypeError, ValueError):
            actual_limit = None
            actual_remaining = None

    effective_limit = min(actual_limit, fallback_limit) if actual_limit else fallback_limit
    effective_remaining = min(actual_remaining, local_remaining) if actual_remaining is not None else local_remaining
    reserve_calls = int(math.ceil(effective_limit * config["quota_reserve_percent"] / 100))
    usable_remaining = max(effective_remaining - reserve_calls, 0)

    return {
        "source": "EBAY_ANALYTICS" if actual_remaining is not None else "LOCAL_BUDGET",
        "limit": effective_limit,
        "remaining": effective_remaining,
        "usable_remaining": usable_remaining,
        "reserve_calls": reserve_calls,
        "reserve_percent": config["quota_reserve_percent"],
        "local_reserved": local_reserved,
        "local_remaining": local_remaining,
        "actual_limit": actual_limit,
        "actual_remaining": actual_remaining,
        "reset": reset,
        "resource": resource,
        "analytics_error": error,
        "fetched_at": snapshot.get("fetched_at") if snapshot else None,
    }


async def reserve_browse_calls(estimated_calls: int, purpose: str, force_actual: bool = False) -> dict[str, Any]:
    estimated = max(int(estimated_calls), 0)
    status = await quota_status(force=force_actual)
    if estimated > int(status["usable_remaining"]):
        raise RadarQuotaError(
            (
                f"Quota eBay protégé : {status['usable_remaining']} appel(s) Browse utilisable(s), "
                f"mais ce passage en prévoit {estimated}. Le Radar reprendra après la remise à zéro."
            ),
            status,
        )
    _set_local_reserved(_local_reserved() + estimated, purpose)
    updated = await quota_status(force=False)
    return {**updated, "reserved_for_run": estimated, "purpose": purpose}
