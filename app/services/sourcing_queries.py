from __future__ import annotations

import re
from typing import Any

from app.services.supplier_relevance import supplier_tokens


# eBay titles are often long SEO strings while supplier catalogs are mostly English.
# Keep this deliberately small and product-oriented: unknown words are preserved.
_FR_TO_EN = {
    "animal": "pet",
    "aspirateur": "vacuum",
    "automobile": "car",
    "bain": "bathroom",
    "bijou": "jewelry",
    "bijoux": "jewelry",
    "bouteille": "bottle",
    "bouton": "knob",
    "brosse": "brush",
    "cable": "cable",
    "camera": "camera",
    "carte": "card",
    "casque": "headset",
    "chat": "cat",
    "chargeur": "charger",
    "chien": "dog",
    "classeur": "binder",
    "coffre": "trunk",
    "collection": "collection",
    "console": "console",
    "crochet": "hook",
    "cuisine": "kitchen",
    "detecteur": "detector",
    "diamant": "diamond",
    "ecran": "screen",
    "ecouteur": "earphone",
    "etagere": "shelf",
    "figurine": "figure",
    "filtre": "filter",
    "gamelle": "bowl",
    "gourde": "bottle",
    "laisse": "leash",
    "lampe": "lamp",
    "maison": "home",
    "montre": "watch",
    "mural": "wall",
    "mur": "wall",
    "nettoyage": "cleaning",
    "organiseur": "organizer",
    "organisation": "organizer",
    "pierre": "gemstone",
    "poignee": "handle",
    "precieuse": "gemstone",
    "presentoir": "display stand",
    "protection": "protector",
    "rangement": "organizer",
    "remplacement": "replacement",
    "sac": "bag",
    "securite": "security",
    "siege": "seat",
    "stylo": "pen",
    "support": "stand",
    "surveillance": "security",
    "tapis": "mat",
    "telephone": "phone",
    "testeur": "tester",
    "tiroir": "drawer",
    "ventilateur": "fan",
    "verre": "glass",
    "voiture": "car",
}

_NOISE = {
    "article", "articles", "authentique", "best", "choix", "excellent", "fr", "france",
    "gratuit", "gratuite", "livraison", "lot", "meilleur", "neuf", "nouveau", "nouvelle",
    "outil", "pack", "piece", "pieces", "premium", "pro", "professionnel", "professionnelle",
    "professional", "qualite", "rapide", "stock", "top", "tool",
}


def _clean_title_tokens(value: Any) -> list[str]:
    cleaned: list[str] = []
    for token in supplier_tokens(value):
        if token in _NOISE:
            continue
        if re.fullmatch(r"v\d+", token) or re.fullmatch(r"20\d{2}", token):
            continue
        if token not in cleaned:
            cleaned.append(token)
    return cleaned


def _canonical_tokens(tokens: list[str]) -> list[str]:
    out: list[str] = []
    for token in tokens:
        mapped = _FR_TO_EN.get(token, token)
        for part in mapped.split():
            if part and part not in out:
                out.append(part)
    return out


def build_supplier_search_queries(value: Any, *, max_queries: int = 3) -> list[str]:
    """Build short supplier-friendly queries from a long eBay listing title.

    Priority is: compact canonical/English query, compact original-language query,
    then the untouched title as a final fallback. The provider is never queried
    with more than max_queries variants.
    """
    original = str(value or "").strip()
    if not original:
        return []

    tokens = _clean_title_tokens(original)
    if not tokens:
        return [original]

    canonical = _canonical_tokens(tokens)
    candidates = [
        " ".join(canonical[:4]),
        " ".join(tokens[:4]),
        original,
    ]

    out: list[str] = []
    seen: set[str] = set()
    for query in candidates:
        query = re.sub(r"\s+", " ", query).strip()
        key = query.casefold()
        if len(query) < 2 or key in seen:
            continue
        seen.add(key)
        out.append(query)
        if len(out) >= max(max_queries, 1):
            break
    return out
