from app.config import get_settings
from app.services.db import list_products, get_listing_for_product, list_radar_watchlist
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


async def scheduled_radar():
    # The YouTube chart costs far less quota than keyword searches and provides
    # a safe seed for automatic discovery without pretending to know sales.
    from app.services.connections import YouTubeClient, connection_status, connection_statuses, scan_connected_sources
    from app.services.radar import analyze_amazon_market
    statuses = connection_statuses()
    sources = [row["id"] for row in statuses
               if row["connected"] and row["id"] in {"tiktok", "youtube", "etsy"}]
    amazon_ready = connection_status("amazon")["connected"]
    if not sources and not amazon_ready:
        return
    if "youtube" in sources:
        try:
            await YouTubeClient().discover("FR")
        except Exception:
            pass
    # Ten watched terms every six hours stays inside the configured daily quota.
    for watch in list_radar_watchlist()[:10]:
        if sources:
            try:
                await scan_connected_sources(watch["keyword"], sources, "FR")
            except Exception:
                # A source can be temporarily rate-limited; the next scheduled pass will retry.
                pass
        if amazon_ready:
            try:
                await analyze_amazon_market(watch["keyword"], "AMAZON_FR")
            except Exception:
                # Catalog or Pricing can be temporarily throttled; the next pass will retry.
                pass


async def scheduled_backup():
    from app.services.backups import create_backup

    try:
        create_backup()
    except Exception:
        # A failed backup must not stop product/radar jobs. It can be retried
        # manually from Settings and will be attempted again the next day.
        pass


def start_scheduler():
    global _scheduler
    s = get_settings()
    if (not s.scheduler_enabled and not s.auto_analysis_enabled and not s.radar_auto_enabled and not s.backup_enabled) or _scheduler or AsyncIOScheduler is None:
        return
    _scheduler = AsyncIOScheduler()
    if s.scheduler_enabled:
        _scheduler.add_job(scheduled_sync, "interval", minutes=max(s.scheduler_sync_minutes, 5), id="sync-all", replace_existing=True)
    if s.auto_analysis_enabled:
        _scheduler.add_job(analyze_catalog, "interval", minutes=max(s.auto_analysis_minutes, 15), id="analyze-catalog", replace_existing=True)
    if s.radar_auto_enabled:
        _scheduler.add_job(scheduled_radar, "interval", hours=max(s.radar_auto_hours, 6), id="radar-watchlist", replace_existing=True)
    if s.backup_enabled:
        _scheduler.add_job(scheduled_backup, "cron", hour=3, minute=15, id="daily-backup", replace_existing=True)
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
