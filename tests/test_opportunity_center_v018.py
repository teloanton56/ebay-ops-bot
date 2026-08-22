from pathlib import Path

from app.config import get_settings
from app.services import db
from app.services.opportunity_center import launch_readiness, verify_latest_backup


def configure(tmp_path, monkeypatch):
    monkeypatch.setenv("APP_ACCESS_MODE", "local")
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "center.db"))
    monkeypatch.setenv("APP_RUNTIME_ENV_PATH", str(tmp_path / "runtime.env"))
    monkeypatch.setenv("APP_ENCRYPTION_KEY", "MDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDA=")
    get_settings.cache_clear()
    db.init_db()


def test_backup_integrity_and_global_readiness_remain_dry_run(tmp_path, monkeypatch):
    configure(tmp_path, monkeypatch)
    backup = verify_latest_backup(create=True)
    readiness = launch_readiness()
    assert backup["ok"] is True
    assert readiness["backup"]["ok"] is True
    assert next(row for row in readiness["checks"] if row["id"] == "dry_run")["done"] is True
    get_settings.cache_clear()


def test_opportunity_center_backend_is_legacy_and_not_scheduled():
    main = Path("app/main.py").read_text(encoding="utf-8")
    scheduler = Path("app/services/scheduler.py").read_text(encoding="utf-8")
    router = Path("app/routers/opportunity_center.py").read_text(encoding="utf-8")

    assert "opportunity_center.router" in main
    assert "opportunity_center.css" not in main
    assert "opportunity_center.js" not in main
    assert "opportunity-monitor" not in scheduler
    assert "monitor_enabled_workflows" not in scheduler
    assert "/api/opportunity-center" in router


def test_active_scheduler_does_not_run_old_discovery_engines():
    scheduler = Path("app/services/scheduler.py").read_text(encoding="utf-8")
    assert "YouTubeClient" not in scheduler
    assert "TikTok" not in scheduler
    assert "AmazonRadarClient" not in scheduler
    assert "refresh_product_from_supplier" in scheduler
