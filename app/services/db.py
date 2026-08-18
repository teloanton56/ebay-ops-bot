import json
import sqlite3
import shutil
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.config import get_settings


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@contextmanager
def conn():
    settings = get_settings()
    path = Path(settings.database_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    try:
        yield connection
        connection.commit()
    finally:
        connection.close()


def init_db() -> None:
    settings = get_settings()
    target = Path(settings.database_path)
    if not target.exists() and target.name == "ebay_bot.db":
        roots = [Path.cwd().parent, *list(Path.cwd().parents)[:2], Path.home() / "Downloads"]
        candidates = []
        for root in roots:
            for version in ("ebay-bot-v0.13.0", "ebay-bot-v0.12.0", "ebay-bot-v0.11.0", "ebay-bot-v0.10.1", "ebay-bot-v0.10.0", "ebay-bot-v0.9.0", "ebay-bot-v0.8.1", "ebay-bot-v0.8.0", "ebay-bot-v0.7.0", "ebay-bot-v0.6.2", "ebay-bot-v0.6.1", "ebay-bot-v0.6.0", "ebay-bot-v0.5.0", "ebay-bot-v0.4.0", "ebay-bot-v0.3.0"):
                candidates.extend((root / version / "ebay_bot.db", root / version / version / "ebay_bot.db"))
        for previous in candidates:
            if previous.is_file() and previous.resolve() != target.resolve():
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(previous, target)
                break
    with conn() as c:
        c.executescript(
            """
            CREATE TABLE IF NOT EXISTS app_kv (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS oauth_tokens (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                access_token TEXT NOT NULL,
                refresh_token TEXT,
                access_expires_at TEXT NOT NULL,
                refresh_expires_at TEXT,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS suppliers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                contact_name TEXT NOT NULL DEFAULT '',
                email TEXT NOT NULL DEFAULT '',
                website TEXT NOT NULL DEFAULT '',
                country TEXT NOT NULL DEFAULT 'FR',
                notes TEXT NOT NULL DEFAULT '',
                provider_code TEXT NOT NULL DEFAULT '',
                supplier_type TEXT NOT NULL DEFAULT 'MANUEL',
                catalog_url TEXT NOT NULL DEFAULT '',
                catalog_status TEXT NOT NULL DEFAULT 'À importer',
                reliability_score REAL,
                last_checked_at TEXT,
                active INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS products (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                supplier_sku TEXT NOT NULL UNIQUE,
                title TEXT NOT NULL,
                description TEXT NOT NULL DEFAULT '',
                supplier_cost REAL NOT NULL,
                shipping_cost REAL NOT NULL DEFAULT 0,
                stock INTEGER NOT NULL DEFAULT 0,
                shipping_days INTEGER NOT NULL DEFAULT 0,
                target_price REAL,
                previous_supplier_cost REAL,
                category_id TEXT,
                condition TEXT NOT NULL DEFAULT 'NEW',
                marketplace_id TEXT,
                currency TEXT,
                images_json TEXT NOT NULL DEFAULT '[]',
                aspects_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS listings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                product_id INTEGER NOT NULL,
                offer_id TEXT,
                listing_id TEXT,
                status TEXT NOT NULL DEFAULT 'DRAFT',
                last_price REAL,
                last_quantity INTEGER,
                last_error TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY(product_id) REFERENCES products(id)
            );

            CREATE TABLE IF NOT EXISTS analysis_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                status TEXT NOT NULL,
                mode TEXT NOT NULL,
                products_total INTEGER NOT NULL DEFAULT 0,
                products_analyzed INTEGER NOT NULL DEFAULT 0,
                winners INTEGER NOT NULL DEFAULT 0,
                rejected INTEGER NOT NULL DEFAULT 0,
                errors INTEGER NOT NULL DEFAULT 0,
                started_at TEXT NOT NULL,
                finished_at TEXT
            );

            CREATE TABLE IF NOT EXISTS analysis_results (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id INTEGER NOT NULL,
                product_id INTEGER NOT NULL,
                score REAL,
                suggested_price REAL,
                margin_percent REAL,
                estimated_profit REAL,
                previous_status TEXT,
                new_status TEXT,
                error TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY(run_id) REFERENCES analysis_runs(id),
                FOREIGN KEY(product_id) REFERENCES products(id)
            );

            CREATE TABLE IF NOT EXISTS alerts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                product_id INTEGER,
                level TEXT NOT NULL,
                kind TEXT NOT NULL,
                message TEXT NOT NULL,
                read INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                FOREIGN KEY(product_id) REFERENCES products(id)
            );

            CREATE TABLE IF NOT EXISTS cj_candidates (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                cj_pid TEXT NOT NULL UNIQUE,
                sku TEXT NOT NULL,
                name TEXT NOT NULL,
                image_url TEXT NOT NULL DEFAULT '',
                price_usd REAL NOT NULL DEFAULT 0,
                category_name TEXT NOT NULL DEFAULT '',
                stock INTEGER NOT NULL DEFAULT 0,
                warehouse_country TEXT NOT NULL DEFAULT '',
                delivery_cycle TEXT NOT NULL DEFAULT '',
                raw_json TEXT NOT NULL DEFAULT '{}',
                analysis_json TEXT NOT NULL DEFAULT '{}',
                risk_flags_json TEXT NOT NULL DEFAULT '[]',
                analyzed_at TEXT,
                selected_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS radar_watchlist (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                keyword TEXT NOT NULL UNIQUE,
                notes TEXT NOT NULL DEFAULT '',
                active INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS radar_scans (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                keyword TEXT NOT NULL,
                source TEXT NOT NULL,
                marketplace TEXT NOT NULL,
                total_results INTEGER NOT NULL DEFAULT 0,
                median_price REAL,
                min_price REAL,
                max_price REAL,
                sellers_sample INTEGER NOT NULL DEFAULT 0,
                top_seller TEXT NOT NULL DEFAULT '',
                top_seller_share REAL NOT NULL DEFAULT 0,
                payload_json TEXT NOT NULL DEFAULT '{}',
                scanned_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS factory_leads (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                company TEXT NOT NULL,
                source TEXT NOT NULL DEFAULT '',
                website TEXT NOT NULL DEFAULT '',
                email TEXT NOT NULL DEFAULT '',
                country TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'À contacter',
                notes TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS rfq_requests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                factory_id INTEGER,
                product_query TEXT NOT NULL,
                quantities TEXT NOT NULL,
                specifications TEXT NOT NULL DEFAULT '',
                message TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'BROUILLON',
                created_at TEXT NOT NULL,
                FOREIGN KEY(factory_id) REFERENCES factory_leads(id)
            );

            CREATE TABLE IF NOT EXISTS trend_discoveries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source TEXT NOT NULL,
                country TEXT NOT NULL,
                themes_json TEXT NOT NULL DEFAULT '[]',
                items_json TEXT NOT NULL DEFAULT '[]',
                scanned_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS support_cases (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                marketplace TEXT NOT NULL DEFAULT 'EBAY',
                order_ref TEXT NOT NULL DEFAULT '',
                buyer_alias TEXT NOT NULL DEFAULT '',
                subject TEXT NOT NULL,
                category TEXT NOT NULL DEFAULT 'Autre',
                priority TEXT NOT NULL DEFAULT 'Normale',
                status TEXT NOT NULL DEFAULT 'Nouveau',
                due_at TEXT,
                customer_message TEXT NOT NULL DEFAULT '',
                internal_notes TEXT NOT NULL DEFAULT '',
                draft_response TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            """
        )
        supplier_columns = {row["name"] for row in c.execute("PRAGMA table_info(suppliers)").fetchall()}
        for name, definition in {
            "provider_code": "TEXT NOT NULL DEFAULT ''",
            "supplier_type": "TEXT NOT NULL DEFAULT 'MANUEL'",
            "catalog_url": "TEXT NOT NULL DEFAULT ''",
            "catalog_status": "TEXT NOT NULL DEFAULT 'À importer'",
            "reliability_score": "REAL",
            "last_checked_at": "TEXT",
        }.items():
            if name not in supplier_columns:
                c.execute(f"ALTER TABLE suppliers ADD COLUMN {name} {definition}")
        columns = {row["name"] for row in c.execute("PRAGMA table_info(products)").fetchall()}
        for name, definition in {
            "supplier_id": "INTEGER REFERENCES suppliers(id)",
            "product_status": "TEXT NOT NULL DEFAULT 'À tester'",
            "opportunity_score": "REAL",
            "suggested_price": "REAL",
        }.items():
            if name not in columns:
                c.execute(f"ALTER TABLE products ADD COLUMN {name} {definition}")
        cj_columns = {row["name"] for row in c.execute("PRAGMA table_info(cj_candidates)").fetchall()}
        for name, definition in {
            "analysis_json": "TEXT NOT NULL DEFAULT '{}'",
            "risk_flags_json": "TEXT NOT NULL DEFAULT '[]'",
            "analyzed_at": "TEXT",
        }.items():
            if name not in cj_columns:
                c.execute(f"ALTER TABLE cj_candidates ADD COLUMN {name} {definition}")
        cleanup_key = "migration:v0101:remove_simulated_market_data"
        if not c.execute("SELECT 1 FROM app_kv WHERE key=?", (cleanup_key,)).fetchone():
            # Older releases could calculate marketplace scores from invented demo listings.
            # Keep user products and prices, but remove unverified scores, demo runs and their alerts.
            c.execute("""UPDATE products SET opportunity_score=NULL
                         WHERE opportunity_score IS NOT NULL AND id NOT IN (
                           SELECT DISTINCT ar.product_id FROM analysis_results ar
                           JOIN analysis_runs run ON run.id=ar.run_id WHERE run.mode='EBAY'
                         )""")
            c.execute("DELETE FROM alerts WHERE kind='WINNER' OR (kind='RISK' AND message LIKE '%score%')")
            c.execute("DELETE FROM analysis_results WHERE run_id IN (SELECT id FROM analysis_runs WHERE mode='DEMO')")
            c.execute("DELETE FROM analysis_runs WHERE mode='DEMO'")
            c.execute("INSERT INTO app_kv(key,value,updated_at) VALUES(?,?,?)",
                      (cleanup_key, "done", utc_now()))
        # BigBuy was retired in v0.11.0. Remove its encrypted token instead of
        # leaving an inaccessible credential in a migrated user database.
        c.execute("DELETE FROM app_kv WHERE key='integration:bigbuy'")


def kv_set(key: str, value: str) -> None:
    with conn() as c:
        c.execute(
            "INSERT INTO app_kv(key,value,updated_at) VALUES(?,?,?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
            (key, value, utc_now()),
        )


def kv_get(key: str) -> str | None:
    with conn() as c:
        row = c.execute("SELECT value FROM app_kv WHERE key=?", (key,)).fetchone()
        return row["value"] if row else None


def product_row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    d = dict(row)
    d["images"] = json.loads(d.pop("images_json") or "[]")
    d["aspects"] = json.loads(d.pop("aspects_json") or "{}")
    return d


def list_products() -> list[dict[str, Any]]:
    with conn() as c:
        rows = c.execute("SELECT * FROM products ORDER BY id DESC").fetchall()
        return [product_row_to_dict(r) for r in rows]


def get_product(product_id: int) -> dict[str, Any] | None:
    with conn() as c:
        row = c.execute("SELECT * FROM products WHERE id=?", (product_id,)).fetchone()
        return product_row_to_dict(row) if row else None


def upsert_product(data: dict[str, Any]) -> int:
    now = utc_now()
    with conn() as c:
        existing = c.execute("SELECT id, supplier_cost FROM products WHERE supplier_sku=?", (data["supplier_sku"],)).fetchone()
        images_json = json.dumps(data.get("images", []), ensure_ascii=False)
        aspects_json = json.dumps(data.get("aspects", {}), ensure_ascii=False)
        if existing:
            c.execute(
                """
                UPDATE products SET
                    title=?, description=?, previous_supplier_cost=supplier_cost, supplier_cost=?, shipping_cost=?,
                    stock=?, shipping_days=?, target_price=?, category_id=?, condition=?, marketplace_id=?, currency=?,
                    images_json=?, aspects_json=?, supplier_id=?, product_status=?, opportunity_score=?, suggested_price=?, updated_at=?
                WHERE id=?
                """,
                (
                    data["title"], data.get("description", ""), data["supplier_cost"], data.get("shipping_cost", 0),
                    data.get("stock", 0), data.get("shipping_days", 0), data.get("target_price"), data.get("category_id"),
                    data.get("condition", "NEW"), data.get("marketplace_id"), data.get("currency"), images_json,
                    aspects_json, data.get("supplier_id"), data.get("product_status", "À tester"),
                    data.get("opportunity_score"), data.get("suggested_price"), now, existing["id"],
                ),
            )
            return int(existing["id"])
        cur = c.execute(
            """
            INSERT INTO products(
                supplier_sku,title,description,supplier_cost,shipping_cost,stock,shipping_days,target_price,
                category_id,condition,marketplace_id,currency,images_json,aspects_json,supplier_id,product_status,
                opportunity_score,suggested_price,created_at,updated_at
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                data["supplier_sku"], data["title"], data.get("description", ""), data["supplier_cost"],
                data.get("shipping_cost", 0), data.get("stock", 0), data.get("shipping_days", 0), data.get("target_price"),
                data.get("category_id"), data.get("condition", "NEW"), data.get("marketplace_id"), data.get("currency"),
                images_json, aspects_json, data.get("supplier_id"), data.get("product_status", "À tester"),
                data.get("opportunity_score"), data.get("suggested_price"), now, now,
            ),
        )
        return int(cur.lastrowid)


def delete_product(product_id: int) -> bool:
    with conn() as c:
        c.execute("DELETE FROM listings WHERE product_id=?", (product_id,))
        return c.execute("DELETE FROM products WHERE id=?", (product_id,)).rowcount > 0


def set_product_fields(product_id: int, **fields: Any) -> bool:
    allowed = {"product_status", "opportunity_score", "suggested_price", "target_price", "supplier_id"}
    values = {k: v for k, v in fields.items() if k in allowed}
    if not values:
        return False
    values["updated_at"] = utc_now()
    clause = ", ".join(f"{key}=?" for key in values)
    with conn() as c:
        return c.execute(f"UPDATE products SET {clause} WHERE id=?", (*values.values(), product_id)).rowcount > 0


def list_suppliers() -> list[dict[str, Any]]:
    with conn() as c:
        rows = c.execute("SELECT s.*, COUNT(p.id) AS product_count FROM suppliers s LEFT JOIN products p ON p.supplier_id=s.id GROUP BY s.id ORDER BY s.name COLLATE NOCASE").fetchall()
        return [dict(row) for row in rows]


def get_supplier(supplier_id: int) -> dict[str, Any] | None:
    with conn() as c:
        row = c.execute("SELECT * FROM suppliers WHERE id=?", (supplier_id,)).fetchone()
        return dict(row) if row else None


def save_supplier(data: dict[str, Any], supplier_id: int | None = None) -> int:
    now = utc_now()
    fields = (data["name"].strip(), data.get("contact_name", "").strip(), data.get("email", "").strip(),
              data.get("website", "").strip(), data.get("country", "FR").strip().upper(),
              data.get("notes", "").strip(), data.get("provider_code", "").strip().lower(),
              data.get("supplier_type", "MANUEL").strip().upper(), data.get("catalog_url", "").strip(),
              data.get("catalog_status", "À importer").strip(), data.get("reliability_score"),
              data.get("last_checked_at"), int(data.get("active", True)))
    with conn() as c:
        if supplier_id:
            c.execute("""UPDATE suppliers SET name=?,contact_name=?,email=?,website=?,country=?,notes=?,
                         provider_code=?,supplier_type=?,catalog_url=?,catalog_status=?,reliability_score=?,
                         last_checked_at=?,active=?,updated_at=? WHERE id=?""", (*fields, now, supplier_id))
            return supplier_id
        cur = c.execute("""INSERT INTO suppliers(name,contact_name,email,website,country,notes,provider_code,
                         supplier_type,catalog_url,catalog_status,reliability_score,last_checked_at,active,created_at,updated_at)
                         VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", (*fields, now, now))
        return int(cur.lastrowid)


def ensure_provider_supplier(provider_code: str, name: str, country: str = "") -> int:
    with conn() as c:
        row = c.execute("SELECT id,provider_code FROM suppliers WHERE provider_code=? OR name=? ORDER BY provider_code<>'' DESC LIMIT 1",
                        (provider_code.lower(), name)).fetchone()
        if row:
            if not row["provider_code"]:
                c.execute("UPDATE suppliers SET provider_code=?,supplier_type='API',catalog_status='Connecté',updated_at=? WHERE id=?",
                          (provider_code.lower(), utc_now(), row["id"]))
            return int(row["id"])
    return save_supplier({"name": name, "country": country or "CN", "provider_code": provider_code,
                          "supplier_type": "API", "catalog_status": "Connecté", "active": True})


def delete_supplier(supplier_id: int) -> bool:
    with conn() as c:
        c.execute("UPDATE products SET supplier_id=NULL WHERE supplier_id=?", (supplier_id,))
        return c.execute("DELETE FROM suppliers WHERE id=?", (supplier_id,)).rowcount > 0


def start_analysis_run(mode: str, total: int) -> int:
    with conn() as c:
        cur = c.execute("INSERT INTO analysis_runs(status,mode,products_total,started_at) VALUES('RUNNING',?,?,?)", (mode, total, utc_now()))
        return int(cur.lastrowid)


def save_analysis_result(run_id: int, product_id: int, *, score=None, suggested_price=None,
                         margin_percent=None, estimated_profit=None, previous_status=None,
                         new_status=None, error=None) -> None:
    with conn() as c:
        c.execute("INSERT INTO analysis_results(run_id,product_id,score,suggested_price,margin_percent,estimated_profit,previous_status,new_status,error,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
                  (run_id, product_id, score, suggested_price, margin_percent, estimated_profit,
                   previous_status, new_status, error, utc_now()))


def finish_analysis_run(run_id: int, analyzed: int, winners: int, rejected: int, errors: int) -> None:
    with conn() as c:
        c.execute("UPDATE analysis_runs SET status=?,products_analyzed=?,winners=?,rejected=?,errors=?,finished_at=? WHERE id=?",
                  ("COMPLETED" if not errors else "COMPLETED_WITH_ERRORS", analyzed, winners, rejected, errors, utc_now(), run_id))


def list_analysis_runs(limit: int = 20) -> list[dict[str, Any]]:
    with conn() as c:
        return [dict(row) for row in c.execute("SELECT * FROM analysis_runs ORDER BY id DESC LIMIT ?", (limit,)).fetchall()]


def add_alert(product_id: int | None, level: str, kind: str, message: str) -> None:
    with conn() as c:
        recent = c.execute("SELECT id FROM alerts WHERE product_id IS ? AND kind=? AND message=? AND read=0 LIMIT 1", (product_id, kind, message)).fetchone()
        if not recent:
            c.execute("INSERT INTO alerts(product_id,level,kind,message,created_at) VALUES(?,?,?,?,?)", (product_id, level, kind, message, utc_now()))


def list_alerts(limit: int = 50) -> list[dict[str, Any]]:
    with conn() as c:
        rows = c.execute("SELECT a.*,p.title AS product_title,p.supplier_sku FROM alerts a LEFT JOIN products p ON p.id=a.product_id ORDER BY a.id DESC LIMIT ?", (limit,)).fetchall()
        return [dict(row) for row in rows]


def mark_alerts_read() -> int:
    with conn() as c:
        return c.execute("UPDATE alerts SET read=1 WHERE read=0").rowcount


def save_cj_candidate(data: dict[str, Any]) -> int:
    raw = json.dumps(data, ensure_ascii=False)
    with conn() as c:
        c.execute("""INSERT INTO cj_candidates(cj_pid,sku,name,image_url,price_usd,category_name,stock,warehouse_country,delivery_cycle,raw_json,selected_at)
                     VALUES(?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(cj_pid) DO UPDATE SET sku=excluded.sku,name=excluded.name,image_url=excluded.image_url,
                     price_usd=excluded.price_usd,category_name=excluded.category_name,stock=excluded.stock,warehouse_country=excluded.warehouse_country,
                     delivery_cycle=excluded.delivery_cycle,raw_json=excluded.raw_json,selected_at=excluded.selected_at""",
                  (data["cj_pid"], data.get("sku", ""), data.get("name", ""), data.get("image_url", ""),
                   float(data.get("price_usd") or 0), data.get("category_name", ""), int(data.get("stock") or 0),
                   data.get("warehouse_country", ""), data.get("delivery_cycle", ""), raw, utc_now()))
        row = c.execute("SELECT id FROM cj_candidates WHERE cj_pid=?", (data["cj_pid"],)).fetchone()
        return int(row["id"])


def list_cj_candidates() -> list[dict[str, Any]]:
    with conn() as c:
        return [cj_candidate_row_to_dict(row) for row in c.execute("SELECT * FROM cj_candidates ORDER BY id DESC").fetchall()]


def cj_candidate_row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    data = dict(row)
    data["analysis"] = json.loads(data.pop("analysis_json", "{}") or "{}")
    data["risk_flags"] = json.loads(data.pop("risk_flags_json", "[]") or "[]")
    return data


def get_cj_candidate(candidate_id: int) -> dict[str, Any] | None:
    with conn() as c:
        row = c.execute("SELECT * FROM cj_candidates WHERE id=?", (candidate_id,)).fetchone()
        return cj_candidate_row_to_dict(row) if row else None


def save_cj_candidate_analysis(candidate_id: int, analysis: dict[str, Any], risk_flags: list[dict]) -> bool:
    with conn() as c:
        return c.execute("UPDATE cj_candidates SET analysis_json=?,risk_flags_json=?,analyzed_at=? WHERE id=?",
                         (json.dumps(analysis, ensure_ascii=False), json.dumps(risk_flags, ensure_ascii=False),
                          utc_now(), candidate_id)).rowcount > 0


def delete_cj_candidate(candidate_id: int) -> bool:
    with conn() as c:
        return c.execute("DELETE FROM cj_candidates WHERE id=?", (candidate_id,)).rowcount > 0


def save_radar_watch(keyword: str, notes: str = "") -> int:
    now = utc_now()
    with conn() as c:
        c.execute("INSERT INTO radar_watchlist(keyword,notes,created_at,updated_at) VALUES(?,?,?,?) "
                  "ON CONFLICT(keyword) DO UPDATE SET notes=excluded.notes,active=1,updated_at=excluded.updated_at",
                  (keyword.strip(), notes.strip(), now, now))
        return int(c.execute("SELECT id FROM radar_watchlist WHERE keyword=?", (keyword.strip(),)).fetchone()["id"])


def list_radar_watchlist() -> list[dict[str, Any]]:
    with conn() as c:
        return [dict(row) for row in c.execute("SELECT * FROM radar_watchlist WHERE active=1 ORDER BY updated_at DESC").fetchall()]


def delete_radar_watch(watch_id: int) -> bool:
    with conn() as c:
        return c.execute("DELETE FROM radar_watchlist WHERE id=?", (watch_id,)).rowcount > 0


def save_radar_scan(data: dict[str, Any]) -> int:
    with conn() as c:
        cur = c.execute("""INSERT INTO radar_scans(keyword,source,marketplace,total_results,median_price,min_price,max_price,
                         sellers_sample,top_seller,top_seller_share,payload_json,scanned_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
                        (data["keyword"], data["source"], data["marketplace"], int(data.get("total_results") or 0),
                         data.get("median_price"), data.get("min_price"), data.get("max_price"),
                         int(data.get("sellers_sample") or 0), data.get("top_seller", ""),
                         float(data.get("top_seller_share") or 0), json.dumps(data, ensure_ascii=False), utc_now()))
        return int(cur.lastrowid)


def previous_radar_scan(keyword: str, source: str, marketplace: str, before_id: int) -> dict[str, Any] | None:
    with conn() as c:
        row = c.execute("SELECT * FROM radar_scans WHERE keyword=? AND source=? AND marketplace=? AND id<? ORDER BY id DESC LIMIT 1",
                        (keyword, source, marketplace, before_id)).fetchone()
        return dict(row) if row else None


def list_radar_scans(limit: int = 100) -> list[dict[str, Any]]:
    with conn() as c:
        return [dict(row) for row in c.execute("SELECT * FROM radar_scans ORDER BY id DESC LIMIT ?", (limit,)).fetchall()]


def save_trend_discovery(source: str, country: str, themes: list[dict], items: list[dict]) -> int:
    with conn() as c:
        cur = c.execute("INSERT INTO trend_discoveries(source,country,themes_json,items_json,scanned_at) VALUES(?,?,?,?,?)",
                        (source, country, json.dumps(themes, ensure_ascii=False),
                         json.dumps(items, ensure_ascii=False), utc_now()))
        return int(cur.lastrowid)


def list_trend_discoveries(limit: int = 12) -> list[dict[str, Any]]:
    with conn() as c:
        rows = c.execute("SELECT * FROM trend_discoveries ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        results = []
        for row in rows:
            data = dict(row)
            data["themes"] = json.loads(data.pop("themes_json") or "[]")
            data["items"] = json.loads(data.pop("items_json") or "[]")
            results.append(data)
        return results


def save_factory_lead(data: dict[str, Any]) -> int:
    now = utc_now()
    with conn() as c:
        cur = c.execute("""INSERT INTO factory_leads(company,source,website,email,country,status,notes,created_at,updated_at)
                         VALUES(?,?,?,?,?,?,?,?,?)""",
                        (data["company"].strip(), data.get("source", "").strip(), data.get("website", "").strip(),
                         data.get("email", "").strip(), data.get("country", "").strip().upper(),
                         data.get("status", "À contacter"), data.get("notes", "").strip(), now, now))
        return int(cur.lastrowid)


def list_factory_leads() -> list[dict[str, Any]]:
    with conn() as c:
        return [dict(row) for row in c.execute("SELECT * FROM factory_leads ORDER BY id DESC").fetchall()]


def delete_factory_lead(factory_id: int) -> bool:
    with conn() as c:
        return c.execute("DELETE FROM factory_leads WHERE id=?", (factory_id,)).rowcount > 0


def save_rfq(data: dict[str, Any]) -> int:
    with conn() as c:
        cur = c.execute("INSERT INTO rfq_requests(factory_id,product_query,quantities,specifications,message,status,created_at) VALUES(?,?,?,?,?,'BROUILLON',?)",
                        (data.get("factory_id"), data["product_query"], data["quantities"],
                         data.get("specifications", ""), data["message"], utc_now()))
        return int(cur.lastrowid)


def list_rfqs() -> list[dict[str, Any]]:
    with conn() as c:
        return [dict(row) for row in c.execute("""SELECT r.*,f.company AS factory_company,f.email AS factory_email
                                                 FROM rfq_requests r LEFT JOIN factory_leads f ON f.id=r.factory_id
                                                 ORDER BY r.id DESC""").fetchall()]


def delete_rfq(rfq_id: int) -> bool:
    with conn() as c:
        return c.execute("DELETE FROM rfq_requests WHERE id=? AND status='BROUILLON'", (rfq_id,)).rowcount > 0


def save_support_case(data: dict[str, Any], case_id: int | None = None) -> int:
    now = utc_now()
    values = (
        str(data.get("marketplace") or "EBAY").strip().upper(), str(data.get("order_ref") or "").strip(),
        str(data.get("buyer_alias") or "").strip(), str(data.get("subject") or "").strip(),
        str(data.get("category") or "Autre").strip(), str(data.get("priority") or "Normale").strip(),
        str(data.get("status") or "Nouveau").strip(), data.get("due_at") or None,
        str(data.get("customer_message") or "").strip(), str(data.get("internal_notes") or "").strip(),
        str(data.get("draft_response") or "").strip(),
    )
    with conn() as c:
        if case_id:
            c.execute("""UPDATE support_cases SET marketplace=?,order_ref=?,buyer_alias=?,subject=?,category=?,
                         priority=?,status=?,due_at=?,customer_message=?,internal_notes=?,draft_response=?,updated_at=?
                         WHERE id=?""", (*values, now, case_id))
            return case_id
        cur = c.execute("""INSERT INTO support_cases(marketplace,order_ref,buyer_alias,subject,category,priority,
                         status,due_at,customer_message,internal_notes,draft_response,created_at,updated_at)
                         VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""", (*values, now, now))
        return int(cur.lastrowid)


def get_support_case(case_id: int) -> dict[str, Any] | None:
    with conn() as c:
        row = c.execute("SELECT * FROM support_cases WHERE id=?", (case_id,)).fetchone()
        return dict(row) if row else None


def list_support_cases() -> list[dict[str, Any]]:
    with conn() as c:
        rows = c.execute("""SELECT * FROM support_cases
                          ORDER BY CASE status WHEN 'Nouveau' THEN 0 WHEN 'En cours' THEN 1
                          WHEN 'En attente client' THEN 2 ELSE 3 END,
                          CASE priority WHEN 'Urgente' THEN 0 WHEN 'Haute' THEN 1 ELSE 2 END,
                          updated_at DESC""").fetchall()
        return [dict(row) for row in rows]


def delete_support_case(case_id: int) -> bool:
    with conn() as c:
        return c.execute("DELETE FROM support_cases WHERE id=?", (case_id,)).rowcount > 0


def update_support_case_fields(case_id: int, **fields: Any) -> bool:
    allowed = {"status", "priority", "due_at", "draft_response", "internal_notes"}
    values = {key: value for key, value in fields.items() if key in allowed}
    if not values:
        return False
    values["updated_at"] = utc_now()
    clause = ", ".join(f"{key}=?" for key in values)
    with conn() as c:
        return c.execute(f"UPDATE support_cases SET {clause} WHERE id=?", (*values.values(), case_id)).rowcount > 0


def save_listing(product_id: int, offer_id: str | None, listing_id: str | None, status: str,
                 price: float | None, quantity: int | None, error: str | None = None) -> int:
    now = utc_now()
    with conn() as c:
        row = c.execute("SELECT id FROM listings WHERE product_id=? ORDER BY id DESC LIMIT 1", (product_id,)).fetchone()
        if row:
            c.execute(
                "UPDATE listings SET offer_id=?, listing_id=?, status=?, last_price=?, last_quantity=?, last_error=?, updated_at=? WHERE id=?",
                (offer_id, listing_id, status, price, quantity, error, now, row["id"]),
            )
            return int(row["id"])
        cur = c.execute(
            "INSERT INTO listings(product_id,offer_id,listing_id,status,last_price,last_quantity,last_error,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?)",
            (product_id, offer_id, listing_id, status, price, quantity, error, now, now),
        )
        return int(cur.lastrowid)


def get_listing_for_product(product_id: int) -> dict[str, Any] | None:
    with conn() as c:
        row = c.execute("SELECT * FROM listings WHERE product_id=? ORDER BY id DESC LIMIT 1", (product_id,)).fetchone()
        return dict(row) if row else None


def save_research(query: str, marketplace_id: str, payload: dict) -> int:
    import json as _json
    now = utc_now()
    with conn() as c:
        c.execute("""
            CREATE TABLE IF NOT EXISTS research_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                query TEXT NOT NULL,
                marketplace_id TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
        """)
        cur = c.execute(
            "INSERT INTO research_runs(query,marketplace_id,payload_json,created_at) VALUES(?,?,?,?)",
            (query, marketplace_id, _json.dumps(payload, ensure_ascii=False), now),
        )
        return int(cur.lastrowid)


def list_research(limit: int = 20) -> list[dict]:
    import json as _json
    with conn() as c:
        c.execute("""
            CREATE TABLE IF NOT EXISTS research_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                query TEXT NOT NULL,
                marketplace_id TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
        """)
        rows = c.execute("SELECT * FROM research_runs ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["payload"] = _json.loads(d.pop("payload_json"))
            out.append(d)
        return out


def list_listings() -> list[dict[str, Any]]:
    """Return listings joined with their product for the UI."""
    with conn() as c:
        rows = c.execute(
            """
            SELECT l.*, p.supplier_sku, p.title AS product_title, p.marketplace_id, p.currency
            FROM listings l
            JOIN products p ON p.id = l.product_id
            ORDER BY l.id DESC
            """
        ).fetchall()
        return [dict(r) for r in rows]
