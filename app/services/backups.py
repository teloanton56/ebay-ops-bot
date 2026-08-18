import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from app.config import get_settings

BACKUP_NAME = re.compile(r"^opsbot-\d{8}-\d{6}\.db$")


def backup_directory() -> Path:
    database = Path(get_settings().database_path).resolve()
    return database.parent / "backups"


def create_backup() -> dict:
    settings = get_settings()
    source = Path(settings.database_path).resolve()
    if not source.is_file():
        raise RuntimeError("La base de données n'existe pas encore.")
    directory = backup_directory()
    directory.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    destination = directory / f"opsbot-{stamp}.db"
    with sqlite3.connect(source) as source_db, sqlite3.connect(destination) as backup_db:
        source_db.backup(backup_db)
    _apply_retention(max(settings.backup_retention, 1))
    return backup_info(destination)


def backup_info(path: Path) -> dict:
    stat = path.stat()
    return {
        "name": path.name,
        "size_bytes": stat.st_size,
        "created_at": datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(),
    }


def list_backups() -> list[dict]:
    directory = backup_directory()
    if not directory.is_dir():
        return []
    files = [p for p in directory.iterdir() if p.is_file() and BACKUP_NAME.fullmatch(p.name)]
    return [backup_info(path) for path in sorted(files, key=lambda p: p.stat().st_mtime, reverse=True)]


def resolve_backup(name: str) -> Path | None:
    if not BACKUP_NAME.fullmatch(name):
        return None
    path = backup_directory() / name
    return path if path.is_file() else None


def _apply_retention(retention: int) -> None:
    directory = backup_directory()
    files = sorted(
        (p for p in directory.iterdir() if p.is_file() and BACKUP_NAME.fullmatch(p.name)),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    for expired in files[retention:]:
        expired.unlink()
