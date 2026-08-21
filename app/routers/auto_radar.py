from fastapi import APIRouter, HTTPException, Query

from app.services.auto_radar import (
    auto_radar_status,
    dismiss_auto_opportunity,
    list_auto_opportunities,
    run_auto_radar,
)


router = APIRouter(prefix="/api/radar/auto", tags=["Radar automatique"])


@router.get("/status")
def status():
    return auto_radar_status()


@router.get("/opportunities")
def opportunities(limit: int = Query(default=30, ge=1, le=100)):
    return {"items": list_auto_opportunities(limit), "status": auto_radar_status()}


@router.post("/run")
async def run_now():
    try:
        return await run_auto_radar(trigger="manual")
    except RuntimeError as exc:
        message = str(exc)
        status_code = 409 if "déjà en cours" in message else 400
        raise HTTPException(status_code=status_code, detail=message) from exc


@router.post("/opportunities/{opportunity_id}/dismiss")
def dismiss(opportunity_id: int):
    if not dismiss_auto_opportunity(opportunity_id):
        raise HTTPException(status_code=404, detail="Opportunité introuvable")
    return {"dismissed": True}
