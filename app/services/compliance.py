from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any

from app.services.cj_landed import load_cj_product_link
from app.services.db import kv_get, kv_set


_REVIEW_PREFIX = "product:compliance-review:"

# Hard blocks are intentionally narrow: these phrases are strong evidence that
# an item should never be auto-published. Ambiguous product classes are handled
# as manual-review risks instead of pretending the bot can certify them.
_HARD_BLOCK_PATTERNS = {
    "COUNTERFEIT": (
        r"\bcounterfeit\b",
        r"\bcontrefa(?:c|ç)on\b",
        r"\bfake\s+(?:nike|adidas|apple|samsung|pokemon|pokémon|lego|disney|gucci|louis\s+vuitton)\b",
        r"\breplica\s+(?:nike|adidas|apple|samsung|pokemon|pokémon|lego|disney|gucci|louis\s+vuitton)\b",
    ),
}

_REVIEW_GROUPS: dict[str, tuple[str, tuple[str, ...]]] = {
    "IP_BRAND": (
        "marque / propriété intellectuelle",
        ("pokemon", "pokémon", "disney", "marvel", "lego", "nike", "adidas", "gucci", "louis vuitton", "apple", "samsung"),
    ),
    "BATTERY_ELECTRICAL": (
        "batterie / produit électrique",
        ("battery", "batterie", "power bank", "powerbank", "rechargeable", "charging", "chargeur", "charger", "mah", "electrical"),
    ),
    "MEDICAL_INGESTIBLE": (
        "médical / santé / ingestion",
        ("medical", "médical", "medicine", "médicament", "supplement", "complément alimentaire", "vitamin", "vitamine"),
    ),
    "COSMETIC": (
        "cosmétique / application corporelle",
        ("cosmetic", "cosmétique", "serum", "sérum", "cream", "crème", "makeup", "maquillage"),
    ),
    "BABY_SAFETY": (
        "bébé / sécurité enfant",
        ("baby", "bébé", "infant", "nourrisson", "pacifier", "tétine", "crib", "berceau"),
    ),
    "SURVEILLANCE_PRIVACY": (
        "surveillance / vie privée",
        ("surveillance", "spy camera", "hidden camera", "camera espion", "caméra espion", "voice recorder", "enregistreur vocal"),
    ),
    "WEAPON": (
        "arme / autodéfense",
        ("weapon", "arme", "knife", "couteau", "taser", "pepper spray", "spray au poivre", "brass knuckle"),
    ),
}

_RETAIL_MARKETPLACE_PROVIDERS = {"amazon", "aliexpress"}


def _review_key(product_id: Any) -> str:
    return _REVIEW_PREFIX + str(product_id or "")


def load_compliance_review(product_id: Any) -> dict[str, Any]:
    if not product_id:
        return {"status": "UNREVIEWED", "notes": "", "reviewed_at": None}
    raw = kv_get(_review_key(product_id))
    if not raw:
        return {"status": "UNREVIEWED", "notes": "", "reviewed_at": None}
    try:
        data = json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return {"status": "UNREVIEWED", "notes": "", "reviewed_at": None}
    if not isinstance(data, dict):
        return {"status": "UNREVIEWED", "notes": "", "reviewed_at": None}
    status = str(data.get("status") or "UNREVIEWED").upper()
    if status not in {"UNREVIEWED", "APPROVED", "REJECTED"}:
        status = "UNREVIEWED"
    return {
        "status": status,
        "notes": str(data.get("notes") or ""),
        "reviewed_at": data.get("reviewed_at"),
    }


def save_compliance_review(product_id: int, status: str, notes: str = "") -> dict[str, Any]:
    normalized = str(status or "").strip().upper()
    if normalized not in {"UNREVIEWED", "APPROVED", "REJECTED"}:
        raise ValueError("Statut conformité invalide")
    payload = {
        "status": normalized,
        "notes": str(notes or "").strip(),
        "reviewed_at": datetime.now(timezone.utc).isoformat() if normalized != "UNREVIEWED" else None,
    }
    kv_set(_review_key(product_id), json.dumps(payload, ensure_ascii=False))
    return payload


def _product_text(product: dict[str, Any]) -> str:
    aspects = product.get("aspects") or {}
    aspect_text = " ".join(
        f"{key} {' '.join(map(str, values if isinstance(values, list) else [values]))}"
        for key, values in aspects.items()
    )
    return " ".join((
        str(product.get("title") or ""),
        str(product.get("description") or ""),
        aspect_text,
    )).casefold()


def _provider_code(product: dict[str, Any], supplier: dict[str, Any] | None) -> str:
    if supplier:
        code = str(supplier.get("provider_code") or "").strip().lower()
        if code:
            return code
    sku = str(product.get("supplier_sku") or "").upper()
    if sku.startswith("CJ-"):
        return "cj"
    if sku.startswith("ALI-"):
        return "aliexpress"
    if sku.startswith("AMZ-"):
        return "amazon"
    return ""


def assess_compliance(product: dict[str, Any], supplier: dict[str, Any] | None = None) -> dict[str, Any]:
    text = _product_text(product)
    review = load_compliance_review(product.get("id"))
    status = review["status"]
    blocks: list[str] = []
    warnings: list[str] = []
    publication_blocks: list[str] = []
    detected: list[dict[str, str]] = []

    if status == "REJECTED":
        blocks.append("Conformité rejetée manuellement")

    for code, patterns in _HARD_BLOCK_PATTERNS.items():
        if any(re.search(pattern, text, re.IGNORECASE) for pattern in patterns):
            label = "Suspicion explicite de contrefaçon"
            detected.append({"code": code, "level": "block", "label": label})
            blocks.append(label)

    review_codes: list[tuple[str, str]] = []
    for code, (label, terms) in _REVIEW_GROUPS.items():
        if any(term.casefold() in text for term in terms):
            review_codes.append((code, label))

    provider = _provider_code(product, supplier)
    if provider == "cj":
        link = load_cj_product_link(str(product.get("supplier_sku") or ""))
        for flag in link.get("risk_flags") or []:
            code = str(flag.get("code") or "CJ_RISK")
            label = str(flag.get("label") or "Risque logistique/conformité CJ")
            if not any(existing_code == code for existing_code, _ in review_codes):
                review_codes.append((code, label))

    for code, label in review_codes:
        detected.append({"code": code, "level": "review", "label": label})
        if status == "APPROVED":
            warnings.append(f"Conformité validée manuellement : {label}")
        else:
            blocks.append(f"Validation conformité requise : {label}")

    if provider in _RETAIL_MARKETPLACE_PROVIDERS:
        publication_blocks.append(
            f"Publication directe bloquée depuis {supplier.get('name') if supplier else provider.title()} : "
            "cette source marketplace reste utilisable pour recherche/sourcing, pas comme fulfillment retail automatique eBay."
        )

    if status == "REJECTED" and "Conformité rejetée manuellement" not in publication_blocks:
        publication_blocks.append("Conformité rejetée manuellement")

    # A hard/manual-review block is also a publication block. Retail-marketplace
    # restrictions are publication-only so these products can still be researched.
    all_publication_blocks = list(dict.fromkeys([*blocks, *publication_blocks]))
    return {
        "pass": not blocks,
        "publication_pass": not all_publication_blocks,
        "status": status,
        "notes": review["notes"],
        "reviewed_at": review["reviewed_at"],
        "provider_code": provider,
        "detected": detected,
        "blocks": list(dict.fromkeys(blocks)),
        "warnings": list(dict.fromkeys(warnings)),
        "publication_blocks": all_publication_blocks,
    }
