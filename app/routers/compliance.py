from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.services.compliance import assess_compliance, load_compliance_review, save_compliance_review
from app.services.db import get_product, get_supplier
from app.services.supplier_refresh import is_verified_cj_product


router = APIRouter(prefix="/api/compliance", tags=["Compliance"])


class ComplianceReviewIn(BaseModel):
    status: str = Field(pattern="^(UNREVIEWED|APPROVED|REJECTED)$")
    notes: str = Field(default="", max_length=1000)


def _product_and_supplier(product_id: int):
    product = get_product(product_id)
    if not product:
        raise HTTPException(404, "Produit introuvable")
    supplier = get_supplier(int(product["supplier_id"])) if product.get("supplier_id") else None
    if not is_verified_cj_product(product, supplier):
        raise HTTPException(410, "Produit hors flux CJ vérifié pour eBay US / USD")
    return product, supplier


@router.get("/products/{product_id}")
def compliance_status(product_id: int):
    product, supplier = _product_and_supplier(product_id)
    return {
        "review": load_compliance_review(product_id),
        "assessment": assess_compliance(product, supplier),
    }


@router.post("/products/{product_id}")
def review_product(product_id: int, payload: ComplianceReviewIn):
    product, supplier = _product_and_supplier(product_id)
    review = save_compliance_review(product_id, payload.status, payload.notes)
    return {
        "saved": True,
        "review": review,
        "assessment": assess_compliance(product, supplier),
    }
