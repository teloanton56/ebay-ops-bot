from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from app.services.opportunity_center import (
    amazon_intelligence,
    build_risk_report,
    command_center_status,
    compare_suppliers,
    ensure_workflow,
    get_workflow,
    launch_readiness,
    list_workflows,
    monitor_enabled_workflows,
    monitor_workflow,
    prepare_listing_draft,
    select_supplier_offer,
    seller_intelligence,
    set_monitoring,
    set_workflow_stage,
    verify_latest_backup,
    workflow_events,
)


router = APIRouter(prefix="/api/opportunity-center", tags=["Opportunity Command Center"])


class SelectOfferIn(BaseModel):
    offer_key: str = Field(min_length=8, max_length=80)


class MonitoringIn(BaseModel):
    enabled: bool


class StageIn(BaseModel):
    stage: str = Field(min_length=3, max_length=40)


def _bad_request(exc: Exception) -> HTTPException:
    return HTTPException(status_code=400, detail=str(exc))


@router.get("/status")
def status():
    return command_center_status()


@router.get("/workflows")
def workflows(limit: int = Query(default=100, ge=1, le=200)):
    return {"items": list_workflows(limit), "status": command_center_status()}


@router.post("/workflows/from-opportunity/{opportunity_id}")
def create_workflow(opportunity_id: int):
    try:
        return ensure_workflow(opportunity_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/workflows/{workflow_id}")
def workflow(workflow_id: int):
    try:
        return get_workflow(workflow_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/workflows/{workflow_id}/events")
def events(workflow_id: int, limit: int = Query(default=50, ge=1, le=200)):
    return {"items": workflow_events(workflow_id, limit)}


@router.post("/workflows/{workflow_id}/suppliers/compare")
async def suppliers_compare(workflow_id: int):
    try:
        return await compare_suppliers(workflow_id)
    except ValueError as exc:
        raise _bad_request(exc) from exc


@router.post("/workflows/{workflow_id}/suppliers/select")
def supplier_select(workflow_id: int, payload: SelectOfferIn):
    try:
        return select_supplier_offer(workflow_id, payload.offer_key)
    except ValueError as exc:
        raise _bad_request(exc) from exc


@router.post("/workflows/{workflow_id}/risk")
def risk(workflow_id: int):
    try:
        return build_risk_report(workflow_id)
    except ValueError as exc:
        raise _bad_request(exc) from exc


@router.post("/workflows/{workflow_id}/seller-intelligence")
async def sellers(workflow_id: int):
    try:
        return await seller_intelligence(workflow_id)
    except ValueError as exc:
        raise _bad_request(exc) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Analyse vendeurs indisponible : {exc}") from exc


@router.post("/workflows/{workflow_id}/amazon")
async def amazon(workflow_id: int):
    try:
        return await amazon_intelligence(workflow_id)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Analyse Amazon indisponible : {exc}") from exc


@router.post("/workflows/{workflow_id}/prepare-draft")
async def prepare_draft(workflow_id: int):
    try:
        return await prepare_listing_draft(workflow_id)
    except ValueError as exc:
        raise _bad_request(exc) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Préparation du brouillon impossible : {exc}") from exc


@router.post("/workflows/{workflow_id}/monitoring")
def monitoring(workflow_id: int, payload: MonitoringIn):
    try:
        return set_monitoring(workflow_id, payload.enabled)
    except ValueError as exc:
        raise _bad_request(exc) from exc


@router.post("/workflows/{workflow_id}/monitor-now")
async def monitor_now(workflow_id: int):
    try:
        return await monitor_workflow(workflow_id)
    except ValueError as exc:
        raise _bad_request(exc) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Surveillance impossible : {exc}") from exc


@router.post("/monitor-all")
async def monitor_all(limit: int = Query(default=20, ge=1, le=100)):
    return await monitor_enabled_workflows(limit)


@router.patch("/workflows/{workflow_id}/stage")
def stage(workflow_id: int, payload: StageIn):
    try:
        return set_workflow_stage(workflow_id, payload.stage)
    except ValueError as exc:
        raise _bad_request(exc) from exc


@router.get("/readiness")
def readiness():
    return launch_readiness()


@router.post("/backup-test")
def backup_test():
    return verify_latest_backup(create=True)
