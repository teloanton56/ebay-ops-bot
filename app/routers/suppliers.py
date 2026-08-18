from urllib.parse import quote_plus

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from app.services.cj import CJClient
from app.services.connections import ASSISTED_SUPPLIERS, connection_statuses
from app.services.db import (delete_supplier, get_supplier, list_factory_leads, list_rfqs,
                             list_suppliers, list_trend_discoveries, save_supplier)
from app.services.supplier_directory import SUPPLIER_DIRECTORY, search_supplier_directory

router = APIRouter(prefix="/api/suppliers", tags=["Suppliers"])


class SupplierIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    contact_name: str = ""
    email: str = ""
    website: str = ""
    country: str = Field(default="FR", min_length=2, max_length=2)
    notes: str = ""
    provider_code: str = Field(default="", max_length=50)
    supplier_type: str = Field(default="MANUEL", max_length=30)
    catalog_url: str = Field(default="", max_length=500)
    catalog_status: str = Field(default="À importer", max_length=80)
    reliability_score: float | None = Field(default=None, ge=0, le=100)
    last_checked_at: str | None = None
    active: bool = True


class FactoryDiscoveryIn(BaseModel):
    query: str = Field(default="", max_length=120)


@router.get("")
def suppliers():
    return list_suppliers()


@router.get("/directory")
def supplier_directory(q: str = Query(default="", max_length=80),
                       category: str = Query(default="", max_length=40),
                       catalog: str = Query(default="", max_length=20)):
    rows = search_supplier_directory(q, category, catalog)
    categories = sorted({category for row in SUPPLIER_DIRECTORY for category in row["categories"]})
    return {
        "results": rows, "total": len(rows), "categories": categories,
        "checked_at": "2026-08-18",
        "note": "Annuaire de pistes. Un badge CSV à demander n'est pas une garantie : confirmez le format, les droits d'utilisation, le stock et la fréquence de mise à jour avec le fournisseur.",
    }


@router.get("/hub")
def supplier_hub():
    connected = {row["id"]: row for row in connection_statuses()}
    cj = CJClient().status()
    providers = [{
        "id": "cj", "name": "CJ Dropshipping", "kind": "Catalogue dropshipping",
        "connected": cj["connected"], "configured": cj["configured"],
        "status": "Connecté" if cj["connected"] else "À reconnecter" if cj.get("recovery_required") else "À connecter",
        "catalog": True, "available_in_products": cj["connected"], "url": "https://cjdropshipping.com/",
        "note": "Catalogue, stock, variantes et devis transport en lecture seule.",
    }]
    for provider_id in ("dropxl", "printful", "printify", "gelato"):
        row = connected[provider_id]
        providers.append({**row, "catalog": True, "available_in_products": row["connected"],
                          "url": row["docs_url"]})
    providers.extend([{**row, "connected": False, "configured": False, "catalog": True,
                       "available_in_products": False} for row in ASSISTED_SUPPLIERS])
    manual, factories, rfqs = list_suppliers(), list_factory_leads(), list_rfqs()
    return {
        "providers": providers, "manual": manual, "factories": factories, "rfqs": rfqs,
        "metrics": {
            "connected_catalogs": sum(1 for row in providers if row.get("connected")),
            "registered_suppliers": len(manual), "factory_contacts": len(factories),
            "rfq_drafts": sum(1 for row in rfqs if row.get("status") == "BROUILLON"),
        },
        "dry_run": True,
    }


@router.post("/factory-discovery")
def factory_discovery(payload: FactoryDiscoveryIn):
    query = payload.query.strip()
    origin = "manual"
    if not query:
        latest = [row for row in list_trend_discoveries(12)
                  if row.get("source") == "YOUTUBE_SHORTS_COMMERCE"][:1]
        themes = latest[0]["themes"] if latest else []
        chosen = next((row for row in themes if row.get("product_hint")), themes[0] if themes else None)
        query = str((chosen or {}).get("keyword") or "").strip()
        origin = "trend" if query else "manual"
    if len(query) < 2:
        raise HTTPException(400, "Indiquez un produit ou lancez d’abord la détection automatique des tendances.")
    encoded = quote_plus(query)
    directories = [
        {"name": "Alibaba.com", "url": f"https://www.alibaba.com/trade/search?SearchText={encoded}",
         "strength": "Usines, MOQ, Trade Assurance et RFQ"},
        {"name": "Global Sources", "url": "https://www.globalsources.com/manufacturers/",
         "strength": f"Rechercher « {query} » parmi les fabricants export"},
        {"name": "Made-in-China", "url": f"https://www.made-in-china.com/productdirectory.do?word={encoded}",
         "strength": "Fabricants audités et fiches export"},
        {"name": "Europages", "url": f"https://www.europages.co.uk/companies/{encoded}.html",
         "strength": "Fabricants et grossistes européens"},
    ]
    matches = [row for row in list_factory_leads()
               if query.lower() in f"{row.get('company', '')} {row.get('notes', '')}".lower()]
    return {
        "query": query, "origin": origin, "directories": directories, "known_contacts": matches,
        "next_step": "Vérifiez l'identité, les certifications et l'échantillon avant d'enregistrer un fabricant.",
        "automatic_limits": "Sans API ou flux public autorisé, le bot n'invente ni email ni lien CSV et vous laisse valider la fiche source.",
    }


@router.post("")
def create(payload: SupplierIn):
    try:
        supplier_id = save_supplier(payload.model_dump())
    except Exception as exc:
        raise HTTPException(400, "Un fournisseur porte déjà ce nom.") from exc
    return get_supplier(supplier_id)


@router.put("/{supplier_id}")
def update(supplier_id: int, payload: SupplierIn):
    if not get_supplier(supplier_id):
        raise HTTPException(404, "Fournisseur introuvable")
    try:
        save_supplier(payload.model_dump(), supplier_id)
    except Exception as exc:
        raise HTTPException(400, "Un fournisseur porte déjà ce nom.") from exc
    return get_supplier(supplier_id)


@router.delete("/{supplier_id}")
def remove(supplier_id: int):
    if not delete_supplier(supplier_id):
        raise HTTPException(404, "Fournisseur introuvable")
    return {"deleted": True}
