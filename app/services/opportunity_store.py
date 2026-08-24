from __future__ import annotations

import asyncio
import hashlib
import json
import re
from typing import Any, Awaitable

from app.services.auto_radar import _ensure_tables as ensure_radar_tables
from app.services.db import conn, utc_now

STAGES = ("DETECTED", "SOURCED", "MARGIN_VALIDATED", "RISK_VALIDATED", "DRAFT_READY", "READY_TO_LAUNCH", "MONITORING", "REJECTED")
STAGE_LABELS = {"DETECTED":"Détectée","SOURCED":"Fournisseur trouvé","MARGIN_VALIDATED":"Marge validée","RISK_VALIDATED":"Risque validé","DRAFT_READY":"Brouillon prêt","READY_TO_LAUNCH":"Prête au lancement","MONITORING":"Sous surveillance","REJECTED":"Écartée"}
_CENTER_LOCK = asyncio.Lock()
MONITOR_LIMIT = 20
SELLER_LIMIT = 6
CJ_DEEP_LIMIT = 4
RESTRICTED_TERMS = {
    "medical": ("médical", "medical", "orthopédique", "orthopedic", "thermometer", "thermomètre"),
    "ingestible": ("complément", "supplement", "vitamine", "vitamin", "gélule", "capsule", "detox"),
    "cosmetic": ("cosmétique", "cosmetic", "serum", "sérum", "crème visage", "cream face", "makeup"),
    "baby": ("bébé", "baby", "nourrisson", "infant", "biberon", "pacifier", "tétine"),
    "weapon": ("arme", "weapon", "couteau", "knife", "taser", "pepper spray"),
}

def _ensure_tables() -> None:
    ensure_radar_tables()
    with conn() as database:
        database.executescript(
            """
            CREATE TABLE IF NOT EXISTS opportunity_workflows (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                opportunity_id INTEGER NOT NULL UNIQUE,
                keyword TEXT NOT NULL,
                marketplace TEXT NOT NULL DEFAULT 'EBAY_US',
                stage TEXT NOT NULL DEFAULT 'DETECTED',
                selected_offer_key TEXT NOT NULL DEFAULT '',
                selected_offer_json TEXT NOT NULL DEFAULT '{}',
                supplier_snapshot_json TEXT NOT NULL DEFAULT '{}',
                seller_snapshot_json TEXT NOT NULL DEFAULT '{}',
                risk_json TEXT NOT NULL DEFAULT '{}',
                listing_json TEXT NOT NULL DEFAULT '{}',
                monitoring_enabled INTEGER NOT NULL DEFAULT 0,
                last_monitored_at TEXT,
                readiness_score REAL NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS opportunity_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                workflow_id INTEGER NOT NULL,
                kind TEXT NOT NULL,
                level TEXT NOT NULL DEFAULT 'INFO',
                message TEXT NOT NULL,
                payload_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL,
                FOREIGN KEY(workflow_id) REFERENCES opportunity_workflows(id)
            );

            CREATE INDEX IF NOT EXISTS idx_opportunity_events_workflow
                ON opportunity_events(workflow_id, id DESC);
            """
        )


def _json_load(value: Any, default: Any) -> Any:
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value or json.dumps(default))
    except (TypeError, json.JSONDecodeError):
        return default


def _decode_workflow(row: dict[str, Any]) -> dict[str, Any]:
    result = dict(row)
    for source, target, default in (
        ("selected_offer_json", "selected_offer", {}),
        ("supplier_snapshot_json", "supplier_snapshot", {}),
        ("seller_snapshot_json", "seller_snapshot", {}),
        ("risk_json", "risk", {}),
        ("listing_json", "listing", {}),
    ):
        result[target] = _json_load(result.pop(source, None), default)
    # Ignore obsolete cross-market snapshot columns when reading an existing database.
    for key in tuple(result):
        if key.endswith("_snapshot_json"):
            result.pop(key, None)
    result["monitoring_enabled"] = bool(result.get("monitoring_enabled"))
    result["stage_label"] = STAGE_LABELS.get(result.get("stage"), result.get("stage"))
    return result


def _get_opportunity(opportunity_id: int) -> dict[str, Any] | None:
    ensure_radar_tables()
    with conn() as database:
        row = database.execute(
            "SELECT * FROM radar_opportunities WHERE id=?", (opportunity_id,)
        ).fetchone()
    if not row:
        return None
    result = dict(row)
    for source, target, default in (
        ("sources_json", "sources", []),
        ("factors_json", "factors", []),
        ("payload_json", "payload", {}),
    ):
        result[target] = _json_load(result.pop(source, None), default)
    result.pop("social_score", None)
    result.pop("social_json", None)
    return result


def _workflow_by_id(workflow_id: int) -> dict[str, Any] | None:
    _ensure_tables()
    with conn() as database:
        row = database.execute(
            "SELECT * FROM opportunity_workflows WHERE id=?", (workflow_id,)
        ).fetchone()
    return _decode_workflow(dict(row)) if row else None


def _workflow_by_opportunity(opportunity_id: int) -> dict[str, Any] | None:
    _ensure_tables()
    with conn() as database:
        row = database.execute(
            "SELECT * FROM opportunity_workflows WHERE opportunity_id=?", (opportunity_id,)
        ).fetchone()
    return _decode_workflow(dict(row)) if row else None


def _add_event(workflow_id: int, kind: str, message: str, *, level: str = "INFO",
               payload: dict[str, Any] | None = None) -> None:
    with conn() as database:
        database.execute(
            """
            INSERT INTO opportunity_events(workflow_id,kind,level,message,payload_json,created_at)
            VALUES(?,?,?,?,?,?)
            """,
            (workflow_id, kind, level, message,
             json.dumps(payload or {}, ensure_ascii=False), utc_now()),
        )


def workflow_events(workflow_id: int, limit: int = 50) -> list[dict[str, Any]]:
    _ensure_tables()
    with conn() as database:
        rows = database.execute(
            "SELECT * FROM opportunity_events WHERE workflow_id=? ORDER BY id DESC LIMIT ?",
            (workflow_id, min(max(int(limit), 1), 200)),
        ).fetchall()
    out = []
    for row in rows:
        item = dict(row)
        item["payload"] = _json_load(item.pop("payload_json", None), {})
        out.append(item)
    return out


def ensure_workflow(opportunity_id: int) -> dict[str, Any]:
    _ensure_tables()
    opportunity = _get_opportunity(opportunity_id)
    if not opportunity:
        raise ValueError("Opportunité Radar introuvable")
    if (
        str(opportunity.get("marketplace") or "") != "EBAY_US"
        or str(opportunity.get("currency") or "").upper() != "USD"
    ):
        raise ValueError("Seules les opportunités eBay US en USD peuvent créer un dossier")
    existing = _workflow_by_opportunity(opportunity_id)
    if existing:
        return _with_opportunity(existing, opportunity)
    now = utc_now()
    with conn() as database:
        cursor = database.execute(
            """
            INSERT INTO opportunity_workflows(
                opportunity_id,keyword,marketplace,stage,created_at,updated_at
            ) VALUES(?,?,?,?,?,?)
            """,
            (
                opportunity_id,
                str(opportunity.get("keyword") or opportunity.get("title") or "Produit"),
                "EBAY_US",
                "DETECTED",
                now,
                now,
            ),
        )
        workflow_id = int(cursor.lastrowid)
    _add_event(workflow_id, "WORKFLOW_CREATED", "Opportunité ajoutée au pipeline de lancement")
    return get_workflow(workflow_id)


def _with_opportunity(workflow: dict[str, Any], opportunity: dict[str, Any] | None = None) -> dict[str, Any]:
    opportunity = opportunity or _get_opportunity(int(workflow["opportunity_id"])) or {}
    merged = dict(workflow)
    merged["opportunity"] = opportunity
    merged["score"] = opportunity.get("score")
    merged["verdict"] = opportunity.get("verdict")
    merged["title"] = opportunity.get("title") or workflow.get("keyword")
    merged["image_url"] = opportunity.get("image_url") or ""
    merged["market_price"] = opportunity.get("median_price")
    merged["currency"] = opportunity.get("currency") or "USD"
    return merged


def get_workflow(workflow_id: int) -> dict[str, Any]:
    workflow = _workflow_by_id(workflow_id)
    if not workflow:
        raise ValueError("Dossier de lancement introuvable")
    if workflow.get("marketplace") != "EBAY_US":
        raise ValueError("Dossier legacy hors mode eBay US / USD")
    result = _with_opportunity(workflow)
    if str(result.get("currency") or "").upper() != "USD":
        raise ValueError("Dossier hors mode eBay US / USD")
    result["events"] = workflow_events(workflow_id, 30)
    from app.services.opportunity_monitor import workflow_readiness
    result["readiness"] = workflow_readiness(result)
    return result


def list_workflows(limit: int = 100) -> list[dict[str, Any]]:
    _ensure_tables()
    with conn() as database:
        rows = database.execute(
            "SELECT * FROM opportunity_workflows WHERE marketplace='EBAY_US' ORDER BY updated_at DESC LIMIT ?",
            (min(max(int(limit), 1), 200),),
        ).fetchall()
    workflows = [_with_opportunity(_decode_workflow(dict(row))) for row in rows]
    return [row for row in workflows if str(row.get("currency") or "").upper() == "USD"]


def _update_workflow(workflow_id: int, **fields: Any) -> dict[str, Any]:
    allowed = {
        "stage", "selected_offer_key", "selected_offer_json", "supplier_snapshot_json",
        "seller_snapshot_json", "risk_json", "listing_json",
        "monitoring_enabled", "last_monitored_at", "readiness_score",
    }
    values = {key: value for key, value in fields.items() if key in allowed}
    if not values:
        return get_workflow(workflow_id)
    values["updated_at"] = utc_now()
    clause = ",".join(f"{key}=?" for key in values)
    with conn() as database:
        updated = database.execute(
            f"UPDATE opportunity_workflows SET {clause} WHERE id=?",
            (*values.values(), workflow_id),
        ).rowcount
    if not updated:
        raise ValueError("Dossier de lancement introuvable")
    return get_workflow(workflow_id)


def _tokens(value: str) -> set[str]:
    normalized = re.sub(r"[^a-z0-9à-ÿ]+", " ", str(value or "").casefold())
    ignored = {
        "avec", "sans", "pour", "dans", "sur", "les", "des", "une", "un", "the", "and",
        "for", "with", "new", "lot", "pack", "kit", "produit", "product", "neuf", "nouveau",
    }
    return {token for token in normalized.split() if len(token) >= 3 and token not in ignored}


def _match_strength(query: str, title: str) -> float:
    query_tokens, title_tokens = _tokens(query), _tokens(title)
    if not query_tokens or not title_tokens:
        return 0.0
    return len(query_tokens & title_tokens) / max(len(query_tokens), 1)


def _safe_float(value: Any) -> float | None:
    try:
        return float(value) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _safe_int(value: Any) -> int | None:
    try:
        return int(float(value)) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _days_from_text(value: Any) -> int | None:
    values = [int(item) for item in re.findall(r"\d+", str(value or ""))]
    return max(values) if values else None


def _offer_key(provider: str, sku: str, variant: str = "") -> str:
    raw = f"{provider.casefold()}|{sku.casefold()}|{variant.casefold()}"
    return hashlib.sha256(raw.encode()).hexdigest()[:24]



async def _limited(coroutines: list[Awaitable[Any]], concurrency: int = 4) -> list[Any]:
    semaphore = asyncio.Semaphore(max(int(concurrency), 1))
    async def run(coroutine: Awaitable[Any]) -> Any:
        async with semaphore:
            try:
                return await coroutine
            except Exception as exc:
                return exc
    return await asyncio.gather(*(run(coroutine) for coroutine in coroutines))
