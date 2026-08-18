"""Copy one consistent configuration/database pair from the newest local release."""

import re
import shutil
from pathlib import Path


CURRENT_VERSION = (0, 14, 3)


def _version(path: Path) -> tuple[int, int, int]:
    match = re.search(r"ebay-bot-v(\d+)\.(\d+)\.(\d+)", path.name.lower())
    return tuple(int(value) for value in match.groups()) if match else (0, 0, 0)


def _candidate_directories() -> list[Path]:
    current = Path.cwd().resolve()
    roots = [current.parent, current.parent.parent, Path.home() / "Downloads",
             Path.home() / ".codex" / ".chatgpt-projects"]
    found: dict[Path, tuple[tuple[int, int, int], float]] = {}
    for root in roots:
        if not root.is_dir():
            continue
        for env_file in root.rglob(".env"):
            directory = env_file.parent
            version = _version(directory)
            database = directory / "ebay_bot.db"
            if version < CURRENT_VERSION and database.is_file() and directory != current:
                found[directory.resolve()] = (version, max(env_file.stat().st_mtime, database.stat().st_mtime))
    return [row[0] for row in sorted(found.items(), key=lambda item: item[1], reverse=True)]


def migrate() -> str:
    current = Path.cwd()
    target_env, target_db = current / ".env", current / "ebay_bot.db"
    if target_env.exists() and target_db.exists():
        return "Configuration et base locales déjà présentes."
    if target_env.exists() != target_db.exists():
        return "Migration automatique ignorée pour éviter de mélanger une base et une clé différentes."
    candidates = _candidate_directories()
    if not candidates:
        return "Aucune ancienne installation complète trouvée. Une configuration neuve sera créée."
    source = candidates[0]
    shutil.copy2(source / ".env", target_env)
    shutil.copy2(source / "ebay_bot.db", target_db)
    return f"Données locales récupérées depuis {source.name}."


if __name__ == "__main__":
    print(migrate())
