from app.config import get_settings
from app.services.analyzer import analyze_catalog
from app.services.db import get_listing_for_product, list_products
from app.services.ebay import EbayClient
from app.services.risk import assess_product
from app.services.supplier_refresh import SupplierRefreshError, refresh_product_from_supplier

try:
    from apscheduler.schedulers.asyncio import AsyncIOScheduler
except ImportError:
    AsyncIOScheduler = None

_scheduler = None


async def scheduled_sync():
    """Refresh CJ first, then push only verified eBay US price/quantity snapshots."""
    settings = get_settings()
    if not settings.ebay_write_enabled:
        return
    client = EbayClient()
    for product in list_products():
        if product.get("marketplace_id") != "EBAY_US" or product.get("currency") != "USD":
            continue
        listing = get_listing_for_product(product["id"])
        if not listing or not listing.get("offer_id"):
            continue
        try:
            refreshed, _ = await refresh_product_from_supplier(product)
            risk = assess_product(refreshed)
            qty = int(refreshed.get("stock") or 0) if risk["pass"] else 0
            await client.update_live_offer_price_quantity(
                refreshed["supplier_sku"],
                listing["offer_id"],
                float(refreshed.get("target_price") or 0),
                qty,
                "USD",
            )
        except (SupplierRefreshError, Exception):
            # A failed supplier refresh must never push stale stock. Try to protect
            # the live offer by setting quantity to zero when possible.
            try:
                await client.update_live_offer_price_quantity(
                    product["supplier_sku"],
                    listing["offer_id"],
                    float(product.get("target_price") or 0),
                    0,
                    "USD",
                )
            except Exception:
                pass


async def scheduled_backup():
    from app.services.backups import create_backup
    try:
        create_backup()
    except Exception:
        pass


def reschedule_radar_jobs() -> bool:
    """Legacy compatibility: v0.23 has no background multi-source Radar jobs."""
    return _scheduler is not None


def start_scheduler():
    global _scheduler
    settings = get_settings()
    if (
        not settings.scheduler_enabled
        and not settings.auto_analysis_enabled
        and not settings.backup_enabled
    ) or _scheduler or AsyncIOScheduler is None:
        return

    _scheduler = AsyncIOScheduler()
    if settings.scheduler_enabled:
        _scheduler.add_job(
            scheduled_sync,
            "interval",
            minutes=max(settings.scheduler_sync_minutes, 5),
            id="sync-cj-ebay-us",
            replace_existing=True,
            max_instances=1,
            coalesce=True,
        )
    if settings.auto_analysis_enabled:
        _scheduler.add_job(
            analyze_catalog,
            "interval",
            minutes=max(settings.auto_analysis_minutes, 15),
            id="analyze-ebay-us-catalog",
            replace_existing=True,
            max_instances=1,
            coalesce=True,
        )
    if settings.backup_enabled:
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
