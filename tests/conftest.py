import os
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# These values are installed before pytest imports the application modules. This
# prevents router-level paths and settings caches from pointing at a developer's
# real runtime files during collection.
TEST_RUNTIME_ENV = Path(tempfile.gettempdir()) / "ebay-ops-bot-pytest-runtime.env"
TEST_COLLECTION_DB = Path(tempfile.gettempdir()) / "ebay-ops-bot-pytest-collection.db"
os.environ["APP_ACCESS_MODE"] = "local"
os.environ["APP_RUNTIME_ENV_PATH"] = str(TEST_RUNTIME_ENV)
os.environ["DATABASE_PATH"] = str(TEST_COLLECTION_DB)
os.environ["APP_ENCRYPTION_KEY"] = "MDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDA="

from app.config import get_settings
from app.services import db
from app.services.ebay import EbayClient


@pytest.fixture(autouse=True)
def isolated_runtime(tmp_path, monkeypatch):
    """Give every test fresh settings, credentials and a fresh SQLite database."""
    TEST_RUNTIME_ENV.unlink(missing_ok=True)
    for key in (
        "APP_ADMIN_EMAIL",
        "APP_ADMIN_PASSWORD",
        "APP_SESSION_SECRET",
        "EBAY_CLIENT_ID",
        "EBAY_CLIENT_SECRET",
        "EBAY_RUNAME",
        "EBAY_ENV",
    ):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("APP_ACCESS_MODE", "local")
    monkeypatch.setenv("APP_RUNTIME_ENV_PATH", str(TEST_RUNTIME_ENV))
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "test.db"))
    monkeypatch.setenv(
        "APP_ENCRYPTION_KEY",
        "MDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDA=",
    )
    get_settings.cache_clear()
    EbayClient._app_token_cache = None
    EbayClient._app_token_expires = None
    db.init_db()
    yield
    get_settings.cache_clear()
    EbayClient._app_token_cache = None
    EbayClient._app_token_expires = None
    TEST_RUNTIME_ENV.unlink(missing_ok=True)
