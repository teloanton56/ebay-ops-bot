from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.services.db import (delete_support_case, get_support_case, list_support_cases,
                             save_support_case, update_support_case_fields)

router = APIRouter(prefix="/api/support", tags=["Support client"])

Status = Literal["Nouveau", "En cours", "En attente client", "Résolu"]
Priority = Literal["Normale", "Haute", "Urgente"]
Category = Literal["Retard de livraison", "Retour / remboursement", "Produit endommagé",
                   "Produit non conforme", "Adresse / commande", "Autre"]


class SupportCaseIn(BaseModel):
    marketplace: str = Field(default="EBAY", min_length=2, max_length=30)
    order_ref: str = Field(default="", max_length=100)
    buyer_alias: str = Field(default="", max_length=100)
    subject: str = Field(min_length=2, max_length=200)
    category: Category = "Autre"
    priority: Priority = "Normale"
    status: Status = "Nouveau"
    due_at: str | None = Field(default=None, max_length=40)
    customer_message: str = Field(default="", max_length=5000)
    internal_notes: str = Field(default="", max_length=5000)
    draft_response: str = Field(default="", max_length=5000)


class SupportStatusIn(BaseModel):
    status: Status


def _summary(rows: list[dict]) -> dict:
    now = datetime.now(timezone.utc)
    overdue = 0
    for row in rows:
        if row["status"] == "Résolu" or not row.get("due_at"):
            continue
        try:
            due = datetime.fromisoformat(str(row["due_at"]).replace("Z", "+00:00"))
            if due.tzinfo is None:
                due = due.replace(tzinfo=timezone.utc)
            overdue += int(due < now)
        except ValueError:
            continue
    return {
        "open": sum(row["status"] != "Résolu" for row in rows),
        "new": sum(row["status"] == "Nouveau" for row in rows),
        "waiting": sum(row["status"] == "En attente client" for row in rows),
        "urgent": sum(row["priority"] == "Urgente" and row["status"] != "Résolu" for row in rows),
        "overdue": overdue,
        "resolved": sum(row["status"] == "Résolu" for row in rows),
    }


@router.get("/cases")
def cases():
    rows = list_support_cases()
    return {"cases": rows, "metrics": _summary(rows), "automatic_send": False,
            "note": "Les réponses restent des brouillons locaux jusqu'à validation humaine."}


@router.post("/cases")
def create_case(payload: SupportCaseIn):
    case_id = save_support_case(payload.model_dump())
    return get_support_case(case_id)


@router.put("/cases/{case_id}")
def update_case(case_id: int, payload: SupportCaseIn):
    if not get_support_case(case_id):
        raise HTTPException(404, "Dossier SAV introuvable")
    save_support_case(payload.model_dump(), case_id)
    return get_support_case(case_id)


@router.patch("/cases/{case_id}/status")
def change_case_status(case_id: int, payload: SupportStatusIn):
    if not update_support_case_fields(case_id, status=payload.status):
        raise HTTPException(404, "Dossier SAV introuvable")
    return get_support_case(case_id)


@router.delete("/cases/{case_id}")
def remove_case(case_id: int):
    if not delete_support_case(case_id):
        raise HTTPException(404, "Dossier SAV introuvable")
    return {"deleted": True}


def _draft_for(case: dict) -> str:
    hello = f"Bonjour {case['buyer_alias']}," if case.get("buyer_alias") else "Bonjour,"
    order = f" concernant votre commande {case['order_ref']}" if case.get("order_ref") else ""
    endings = "\n\nMerci pour votre patience.\nCordialement,\nService client"
    templates = {
        "Retard de livraison": f"{hello}\n\nNous sommes désolés pour le retard{order}. Nous vérifions actuellement le suivi auprès du transporteur et reviendrons vers vous dès que nous aurons une information confirmée.",
        "Retour / remboursement": f"{hello}\n\nNous avons bien reçu votre demande de retour ou de remboursement{order}. Avant de confirmer la procédure, pouvez-vous nous indiquer le motif et joindre une photo si le produit présente un défaut ?",
        "Produit endommagé": f"{hello}\n\nNous sommes désolés que le produit soit arrivé endommagé{order}. Pour résoudre cela rapidement, pouvez-vous envoyer une photo du produit, de l'emballage extérieur et de l'étiquette d'expédition ?",
        "Produit non conforme": f"{hello}\n\nNous sommes désolés que le produit reçu ne corresponde pas à votre attente{order}. Pouvez-vous préciser la différence constatée et joindre une photo du produit reçu ?",
        "Adresse / commande": f"{hello}\n\nNous avons bien reçu votre demande{order}. Nous vérifions immédiatement si la commande peut encore être modifiée avant expédition et vous confirmerons la solution possible.",
        "Autre": f"{hello}\n\nMerci pour votre message{order}. Nous examinons votre demande et reviendrons vers vous avec une réponse précise dès que les informations auront été vérifiées.",
    }
    return templates.get(case.get("category"), templates["Autre"]) + endings


@router.post("/cases/{case_id}/draft-response")
def create_draft_response(case_id: int):
    case = get_support_case(case_id)
    if not case:
        raise HTTPException(404, "Dossier SAV introuvable")
    draft = _draft_for(case)
    update_support_case_fields(case_id, draft_response=draft,
                               status="En cours" if case["status"] == "Nouveau" else case["status"])
    return {"draft": draft, "sent": False,
            "message": "Brouillon préparé localement. Relisez-le avant de l'envoyer depuis la marketplace."}
