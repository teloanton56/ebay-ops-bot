"""Runtime configuration for the tiered automatic Radar.

Settings are stored in the persistent SQLite key/value table so they can be
changed from the application without editing Render environment variables or
waiting for a redeploy.
"""

from __future__ import annotations

import json
import sqlite3
from typing import Any

from app.services.db import init_db, kv_get, kv_set

SETTINGS_KEY = "radar:tiered:settings:v1"

DEFAULT_RADAR_SETTINGS: dict[str, int] = {
    "quick_minutes": 30,
    "full_hours": 4,
    "candidate_pool": 200,
    "deep_candidates": 25,
    "quick_opportunities": 30,
    "quota_reserve_percent": 20,
    "browse_daily_budget": 5000,
}

BOUNDS: dict[str, tuple[int, int]] = {
    "quick_minutes": (15, 120),
    "full_hours": (1, 24),
    "candidate_pool": (50, 200),
    "deep_candidates": (10, 50),
    "quick_opportunities": (10, 50),
    "quota_reserve_percent": (10, 40),
    "browse_daily_budget": (1000, 100000),
}


def _coerce_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def normalize_radar_settings(values: dict[str, Any] | None = None) -> dict[str, int]:
    supplied = values or {}
    normalized: dict[str, int] = {}
    for key, default in DEFAULT_RADAR_SETTINGS.items():
        low, high = BOUNDS[key]
        normalized[key] = min(max(_coerce_int(supplied.get(key), default), low), high)

    normalized["deep_candidates"] = min(
        normalized["deep_candidates"], normalized["candidate_pool"]
    )
    return normalized


def load_radar_settings() -> dict[str, int]:
    try:
        raw = kv_get(SETTINGS_KEY)
    except sqlite3.OperationalError:
        return dict(DEFAULT_RADAR_SETTINGS)
    if not raw:
        return dict(DEFAULT_RADAR_SETTINGS)
    try:
        stored = json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        stored = {}
    return normalize_radar_settings(stored if isinstance(stored, dict) else {})


def save_radar_settings(values: dict[str, Any]) -> dict[str, int]:
    init_db()
    current = load_radar_settings()
    current.update({key: value for key, value in values.items() if key in DEFAULT_RADAR_SETTINGS})
    normalized = normalize_radar_settings(current)
    kv_set(SETTINGS_KEY, json.dumps(normalized, ensure_ascii=False, sort_keys=True))
    return normalized


def estimate_daily_browse_calls(settings: dict[str, int] | None = None) -> dict[str, int]:
    config = normalize_radar_settings(settings or load_radar_settings())
    quick_runs = max(1, 1440 // config["quick_minutes"])
    full_runs = max(1, 24 // config["full_hours"])

    # Quick scans perform one Browse search per monitored opportunity.
    quick_calls = quick_runs * config["quick_opportunities"]

    # Full scans perform two category searches for eight categories, followed by
    # one search and one detail call for every deeply analysed candidate.
    full_calls_per_run = 16 + 2 * config["deep_candidates"]
    full_calls = full_runs * full_calls_per_run

    return {
        "quick_runs_per_day": quick_runs,
        "full_runs_per_day": full_runs,
        "quick_calls_per_day": quick_calls,
        "full_calls_per_day": full_calls,
        "estimated_calls_per_day": quick_calls + full_calls,
    }
