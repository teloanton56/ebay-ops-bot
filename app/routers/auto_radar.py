from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from app.services import auto_radar as auto_radar_service
from app.services.auto_radar import dismiss_auto_opportunity, list_auto_opportunities
from app.services.radar_quota import RadarQuotaError
from app.services.radar_runtime import (
    estimate_daily_browse_calls,
    load_radar_settings,
    save_radar_settings,
)
from app.services.scheduler import reschedule_radar_jobs
from app.services.tiered_radar import (
    get_quota_status,
    run_full_radar,
    run_quick_radar,
    tiered_radar_status,
)

# Category names arrive localized and are normalized before matching. Normalize
# the configured exclusions once as well so names such as « Véhicules » are
# reliably excluded on the French taxonomy tree.
auto_radar_service.EXCLUDED_CATEGORY_TERMS = {
    auto_radar_service._normalize(term) for term in auto_radar_service.EXCLUDED_CATEGORY_TERMS
}

router = APIRouter(prefix="/api/radar/auto", tags=["Radar automatique"])


class RadarSettingsIn(BaseModel):
    quick_minutes: int = Field(default=30, ge=15, le=120)
    full_hours: int = Field(default=4, ge=1, le=24)
    candidate_pool: int = Field(default=200, ge=50, le=200)
    deep_candidates: int = Field(default=25, ge=10, le=50)
    quick_opportunities: int = Field(default=30, ge=10, le=50)
    quota_reserve_percent: int = Field(default=20, ge=10, le=40)
    browse_daily_budget: int = Field(default=5000, ge=1000, le=100000)


@router.get("/status")
def status():
    return tiered_radar_status()


@router.get("/opportunities")
def opportunities(limit: int = Query(default=30, ge=1, le=100)):
    return {"items": list_auto_opportunities(limit), "status": tiered_radar_status()}


@router.get("/settings")
def settings():
    values = load_radar_settings()
    return {"settings": values, "estimated_daily": estimate_daily_browse_calls(values)}


@router.post("/settings")
def update_settings(payload: RadarSettingsIn):
    values = save_radar_settings(payload.model_dump())
    reschedule_radar_jobs()
    return {
        "saved": True,
        "settings": values,
        "estimated_daily": estimate_daily_browse_calls(values),
        "message": "Rythme du Radar et protection du quota mis à jour.",
    }


@router.get("/quota")
async def quota(force: bool = Query(default=False)):
    return await get_quota_status(force=force)


def _raise_run_error(exc: Exception) -> None:
    if isinstance(exc, RadarQuotaError):
        raise HTTPException(
            status_code=429,
            detail={"message": str(exc), "quota": exc.status},
        ) from exc
    message = str(exc)
    status_code = 409 if "déjà en cours" in message else 400
    raise HTTPException(status_code=status_code, detail=message) from exc


@router.post("/run")
async def run_now():
    try:
        return await run_full_radar(trigger="manual-full")
    except (RuntimeError, RadarQuotaError) as exc:
        _raise_run_error(exc)


@router.post("/run/quick")
async def run_quick_now():
    try:
        return await run_quick_radar(trigger="manual-quick")
    except (RuntimeError, RadarQuotaError) as exc:
        _raise_run_error(exc)


@router.post("/opportunities/{opportunity_id}/dismiss")
def dismiss(opportunity_id: int):
    if not dismiss_auto_opportunity(opportunity_id):
        raise HTTPException(status_code=404, detail="Opportunité introuvable")
    return {"dismissed": True}
