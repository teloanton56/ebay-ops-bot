from app.config import get_settings
from app.services.db import get_listing_for_product, list_products, list_radar_watchlist
from app.services.ebay import EbayClient
from app.services.risk import assess_product
from app.services.analyzer import analyze_catalog

try:
    from apscheduler.schedulers.asyncio import AsyncIOScheduler
except ImportError:  # lets the app still boot if optional dependency is missing
    AsyncIOScheduler = None

_scheduler = None


async def scheduled_sync():
    s = get_settings()
    if not s.ebay_write_enabled:
        return
    client = EbayClient()
    for p in list_products():
        listing = get_listing_for_product(p["id"])
        if not listing or not listing.get("offer_id"):
            continue
        risk = assess_product(p)
        qty = int(p.get("stock") or 0) if risk["pass"] else 0
        try:
            await client.update_live_offer_price_quantity(
                p["supplier_sku"], listing["offer_id"], float(p.get("target_price") or 0), qty,
                p.get("currency") or s.ebay_currency,
            )
        except Exception:
            pass


async def scheduled_radar_quick():
    """Refresh the strongest stored opportunities with one Browse call each."""
    from app.services.tiered_radar import run_quick_radar

    try:
        await run_quick_radar(trigger="scheduler-quick")
    except Exception:
        # Quota reserve, a simultaneous full scan or a temporary eBay outage must
        # not stop the scheduler. The next 30-minute pass will retry.
        pass


async def _refresh_explicit_watchlist():
    """Keep manually watched terms longitudinally monitored after a full scan."""
    from app.services.connections import connection_status, connection_statuses, scan_connected_sources
    from app.services.radar import analyze_amazon_market

    statuses = connection_statuses()
    sources = [
        row["id"] for row in statuses
        if row["connected"] and row["id"] in {"tiktok", "youtube", "etsy"}
    ]
    amazon_ready = connection_status("amazon")["connected"]
    if not sources and not amazon_ready:
        return

    for watch in list_radar_watchlist()[:10]:
        if sources:
            try:
                await scan_connected_sources(watch["keyword"], sources, "FR")
            except Exception:
                pass
        if amazon_ready:
            try:
                await analyze_amazon_market(watch["keyword"], "AMAZON_FR")
            except Exception:
                pass


async def scheduled_radar_full():
    """Collect up to 200 candidates and deeply analyse the strongest 25."""
    from app.services.tiered_radar import run_full_radar

    try:
        await run_full_radar(trigger="scheduler-full")
    except Exception:
        # Developer Analytics can intentionally postpone the scan when the quota
        # reserve is reached. A later scheduled pass will retry automatically.
        return
    await _refresh_explicit_watchlist()


async def scheduled_opportunity_monitor():
    """Refresh selected suppliers and market signals for launch candidates."""
    from app.services.opportunity_center import monitor_enabled_workflows

    try:
        await monitor_enabled_workflows()
    except Exception:
        # Monitoring alerts must never stop Radar, catalogue or backup jobs.
        pass


async def scheduled_backup():
    from app.services.backups import create_backup

    try:
        create_backup()
    except Exception:
        # A failed backup must not stop product/radar jobs. It can be retried
        # manually from Settings and will be attempted again the next day.
        pass


def _configure_radar_jobs() -> None:
    if _scheduler is None:
        return
    from app.services.radar_runtime import load_radar_settings

    for job_id in ("radar-watchlist", "radar-quick", "radar-full", "opportunity-monitor"):
        try:
            if _scheduler.get_job(job_id):
                _scheduler.remove_job(job_id)
        except Exception:
            pass

    if not get_settings().radar_auto_enabled:
        return

    runtime = load_radar_settings()
    _scheduler.add_job(
        scheduled_radar_quick,
        "interval",
        minutes=runtime["quick_minutes"],
        id="radar-quick",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    _scheduler.add_job(
        scheduled_radar_full,
        "interval",
        hours=runtime["full_hours"],
        id="radar-full",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    _scheduler.add_job(
        scheduled_opportunity_monitor,
        "interval",
        minutes=max(runtime["quick_minutes"], 60),
        id="opportunity-monitor",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )


def reschedule_radar_jobs() -> bool:
    """Apply new Radar intervals immediately when settings change in the UI."""
    if _scheduler is None:
        return False
    _configure_radar_jobs()
    return True


def start_scheduler():
    global _scheduler
    s = get_settings()
    if (
        not s.scheduler_enabled
        and not s.auto_analysis_enabled
        and not s.radar_auto_enabled
        and not s.backup_enabled
    ) or _scheduler or AsyncIOScheduler is None:
        return
    _scheduler = AsyncIOScheduler()
    if s.scheduler_enabled:
        _scheduler.add_job(
            scheduled_sync,
            "interval",
            minutes=max(s.scheduler_sync_minutes, 5),
            id="sync-all",
            replace_existing=True,
        )
    if s.auto_analysis_enabled:
        _scheduler.add_job(
            analyze_catalog,
            "interval",
            minutes=max(s.auto_analysis_minutes, 15),
            id="analyze-catalog",
            replace_existing=True,
        )
    _configure_radar_jobs()
    if s.backup_enabled:
        _scheduler.add_job(
            scheduled_backup,
            "cron",
            hour=3,
            minute=15,
            id="daily-backup",
            replace_existing=True,
        )
    _scheduler.start()


def stop_scheduler():
    global _scheduler
    if _scheduler is None:
        return
    try:
        if _scheduler.running:
            _scheduler.shutdown(wait=False)
    finally:
        _scheduler = None
