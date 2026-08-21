from fastapi import APIRouter, HTTPException, Query

from app.services.auto_radar import (
    AUTO_MIN_SCORE,
    AutoRadarError,
    auto_radar_status,
    dismiss_auto_opportunity,
    list_auto_opportunities,
    run_auto_discovery,
)


router = APIRouter(prefix="/api/radar/auto", tags=["Radar automatique"])


@router.get("/status")
def status():
    return auto_radar_status()


@router.get("/opportunities")
def opportunities(
    limit: int = Query(default=20, ge=1, le=100),
    min_score: int = Query(default=AUTO_MIN_SCORE, ge=0, le=100),
):
    return {
        "items": list_auto_opportunities(limit=limit, min_score=min_score),
        "status": auto_radar_status(),
    }


@router.post("/run")
async def run_now():
    try:
        return await run_auto_discovery("manual")
    except AutoRadarError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/opportunities/{fingerprint}/dismiss")
def dismiss(fingerprint: str):
    if not dismiss_auto_opportunity(fingerprint):
        raise HTTPException(status_code=404, detail="Opportunité introuvable")
    return {"dismissed": True, "fingerprint": fingerprint}
