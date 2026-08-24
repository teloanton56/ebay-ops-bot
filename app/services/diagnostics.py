"""Build a support report that deliberately contains no record contents or secrets."""

import platform
import secrets
import sys
from datetime import datetime, timezone
from pathlib import Path

from app.config import get_settings
from app.services.backups import list_backups
from app.services.cj import CJClient
from app.services.db import conn
from app.services.ebay import EbayClient

VERSION = "0.25.3"

TABLES = {
    "Produits": "products",
    "Fournisseurs": "suppliers",
    "Annonces suivies": "listings",
    "Analyses": "analysis_runs",
    "Alertes": "alerts",
    "Produits CJ sélectionnés": "cj_candidates",
    "Surveillances Radar": "radar_watchlist",
    "Relevés Radar": "radar_scans",
    "Dossiers SAV": "support_cases",
}


def _yes(value: bool) -> str:
    return "Oui" if value else "Non"


def _database_facts() -> tuple[str, dict[str, int], int, dict | None, int]:
    settings = get_settings()
    path = Path(settings.database_path)
    counts: dict[str, int] = {}
    latest_run = None
    unread_alerts = 0
    try:
        with conn() as database:
            quick_check = database.execute("PRAGMA quick_check").fetchone()[0]
            for label, table in TABLES.items():
                counts[label] = int(database.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
            latest = database.execute(
                "SELECT status,mode,products_analyzed,winners,rejected,errors,started_at,finished_at "
                "FROM analysis_runs ORDER BY id DESC LIMIT 1"
            ).fetchone()
            latest_run = dict(latest) if latest else None
            unread_alerts = int(database.execute("SELECT COUNT(*) FROM alerts WHERE read=0").fetchone()[0])
        state = "OK" if str(quick_check).lower() == "ok" else "À vérifier"
    except Exception:
        state = "INDISPONIBLE"
    size = path.stat().st_size if path.is_file() else 0
    return state, counts, size, latest_run, unread_alerts


def _safe_connections() -> list[tuple[str, str]]:
    rows: list[tuple[str, str]] = []
    try:
        cj = CJClient().status()
        cj_status = "Connecté" if cj.get("connected") else "À reconnecter" if cj.get("recovery_required") else "Configuré, test requis" if cj.get("configured") else "Non configuré"
    except Exception:
        cj_status = "Vérification indisponible"
    rows.append(("CJ Dropshipping", cj_status))
    try:
        ebay = EbayClient().token_status()
        ebay_status = "Connecté" if ebay.get("connected") else "Non connecté"
    except Exception:
        ebay_status = "Vérification indisponible"
    rows.append(("eBay US", ebay_status))
    return sorted(rows, key=lambda row: row[0].casefold())


def build_safe_diagnostic() -> tuple[str, str]:
    settings = get_settings()
    now = datetime.now(timezone.utc)
    report_id = secrets.token_hex(4).upper()
    db_state, counts, db_size, latest_run, unread_alerts = _database_facts()
    try:
        backups = list_backups()
    except Exception:
        backups = []
    try:
        ebay = EbayClient().token_status()
        ebay_connected = bool(ebay.get("connected"))
    except Exception:
        ebay_connected = False
    ebay_configured = bool(settings.ebay_client_id and settings.ebay_client_secret and settings.ebay_runame)
    protected = not settings.ebay_write_enabled and not settings.ebay_publish_enabled

    lines = [
        "EBAY OPS BOT — DIAGNOSTIC SÉCURISÉ",
        "===================================",
        f"Identifiant du rapport : {report_id}",
        f"Généré le (UTC) : {now.isoformat(timespec='seconds')}",
        "",
        "CONFIDENTIALITÉ",
        "---------------",
        "Ce rapport exclut les mots de passe, clés API, jetons OAuth, adresses e-mail,",
        "noms de clients, références de commandes, titres produits et contenus des messages.",
        "",
        "APPLICATION",
        "-----------",
        f"Version : {VERSION}",
        f"Mode : {'Cloud' if settings.cloud_mode else 'Local'}",
        f"Python : {sys.version.split()[0]}",
        f"Système : {platform.system()} {platform.release()}",
        f"Mode démo : {_yes(settings.demo_mode)}",
        "",
        "SÉCURITÉ EBAY",
        "--------------",
        f"État général : {'PROTÉGÉ' if protected else 'À VÉRIFIER — écriture activée'}",
        f"Environnement : {settings.ebay_env}",
        f"Écriture eBay : {'ACTIVE' if settings.ebay_write_enabled else 'Bloquée'}",
        f"Publication eBay : {'ACTIVE' if settings.ebay_publish_enabled else 'Bloquée'}",
        f"Identifiants eBay configurés : {_yes(ebay_configured)}",
        f"Compte eBay autorisé : {_yes(ebay_connected)}",
        "",
        "BASE DE DONNÉES",
        "----------------",
        f"Intégrité : {db_state}",
        f"Taille : {round(db_size / 1024, 1)} Ko",
        f"Alertes non lues : {unread_alerts}",
    ]
    lines.extend(f"{label} : {value}" for label, value in counts.items())

    lines.extend(["", "CONNEXIONS", "-----------"])
    lines.extend(f"{name} : {status}" for name, status in _safe_connections())

    lines.extend([
        "",
        "AUTOMATISATIONS",
        "---------------",
        f"Synchronisation eBay planifiée : {_yes(settings.scheduler_enabled)}",
        f"Analyse catalogue : {_yes(settings.auto_analysis_enabled)} — toutes les {settings.auto_analysis_minutes} min",
        f"Radar automatique : {_yes(settings.radar_auto_enabled)} — toutes les {settings.radar_auto_hours} h",
        f"Sauvegardes : {_yes(settings.backup_enabled)} — {len(backups)} disponible(s), rétention {settings.backup_retention}",
        "",
        "RISK ENGINE",
        "-----------",
        f"Marge minimum : {settings.min_margin_percent} %",
        f"Profit minimum : {settings.min_profit_usd} USD",
        f"Stock minimum : {settings.min_stock}",
        f"Délai maximum : {settings.max_shipping_days} jours",
    ])
    if latest_run:
        lines.extend([
            "",
            "DERNIÈRE ANALYSE",
            "----------------",
            f"Statut : {latest_run.get('status') or 'Inconnu'}",
            f"Mode : {latest_run.get('mode') or 'Inconnu'}",
            f"Produits analysés : {latest_run.get('products_analyzed') or 0}",
            f"Winners : {latest_run.get('winners') or 0}",
            f"Rejetés : {latest_run.get('rejected') or 0}",
            f"Erreurs : {latest_run.get('errors') or 0}",
            f"Début : {latest_run.get('started_at') or '—'}",
            f"Fin : {latest_run.get('finished_at') or '—'}",
        ])
    lines.extend(["", "FIN DU RAPPORT", "Tu peux transmettre ce fichier pour obtenir de l'aide.", ""])
    filename = f"diagnostic-opsbot-{now.strftime('%Y%m%d-%H%M%S')}.txt"
    return filename, "\ufeff" + "\n".join(lines)
