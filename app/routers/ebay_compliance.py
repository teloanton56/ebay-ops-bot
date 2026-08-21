from fastapi import APIRouter, HTTPException, Query, Request, Response
from fastapi.responses import JSONResponse

from app.services.ebay_compliance import (
    EbayComplianceError,
    build_challenge_response,
    process_account_deletion,
)


router = APIRouter(tags=["eBay compliance"])
ENDPOINT_PATH = "/api/ebay/account-deletion"


@router.get(ENDPOINT_PATH)
def verify_account_deletion_endpoint(
    challenge_code: str = Query(min_length=1, max_length=512),
):
    try:
        challenge_response = build_challenge_response(challenge_code)
    except EbayComplianceError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return JSONResponse({"challengeResponse": challenge_response})


@router.post(ENDPOINT_PATH, status_code=204)
async def receive_account_deletion_notification(request: Request):
    try:
        payload = await request.json()
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Corps JSON eBay invalide") from exc
    try:
        process_account_deletion(payload)
    except EbayComplianceError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return Response(status_code=204)
