import json

from fastapi import APIRouter, Header, HTTPException, Query, Request, Response
from fastapi.responses import JSONResponse

from app.services.ebay_compliance import (
    EbayComplianceError,
    build_challenge_response,
    process_account_deletion,
    verify_notification_signature,
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
async def receive_account_deletion_notification(
    request: Request,
    x_ebay_signature: str | None = Header(default=None),
):
    if not x_ebay_signature:
        raise HTTPException(status_code=412, detail="Signature eBay manquante")

    try:
        raw = await request.body()
        payload = json.loads(raw.decode("utf-8"))
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Corps JSON eBay invalide") from exc
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="Corps JSON eBay invalide")

    try:
        signature_valid = await verify_notification_signature(payload, x_ebay_signature)
    except EbayComplianceError as exc:
        # eBay's notification contract expects 412 for signature verification
        # failures. A non-2xx response also causes eBay to retry the notification.
        raise HTTPException(status_code=412, detail=str(exc)) from exc
    if not signature_valid:
        raise HTTPException(status_code=412, detail="Signature eBay invalide")

    try:
        process_account_deletion(payload)
    except EbayComplianceError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return Response(status_code=204)
