from __future__ import annotations

import re
import unicodedata
from difflib import SequenceMatcher
from typing import Any


_STOPWORDS = {
    "a", "an", "and", "avec", "de", "des", "du", "en", "et", "for", "in", "la", "le",
    "les", "of", "on", "or", "pour", "the", "to", "un", "une", "with",
}

_GENERIC_TOKENS = {
    "accessory", "black", "blue", "green", "mini", "new", "portable",
    "pro", "red", "smart", "universal", "usb", "white", "wireless",
    "phone", "mobile", "car", "home", "2024", "2025", "2026",
}

_ALIAS_GROUPS = (
    {"case", "cover", "shell", "coque", "etui"},
    {"holder", "mount", "stand", "bracket", "support"},
    {"earbud", "earphone", "headphone", "headset"},
    {"charger", "charging", "chargeur", "charge"},
    {"cable", "cord", "wire"},
    {"fan", "ventilator", "ventilateur"},
    {"lamp", "light", "lighting", "lampe", "lumiere"},
    {"bag", "pouch", "sac"},
    {"bottle", "flask", "gourde", "bouteille"},
)

_ALIAS_INDEX = {
    token: group
    for group in _ALIAS_GROUPS
    for token in group
}


def _normalize(value: Any) -> str:
    text = unicodedata.normalize("NFKD", str(value or "").casefold())
    text = "".join(char for char in text if not unicodedata.combining(char))
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


def _stem(token: str) -> str:
    if len(token) > 5 and token.endswith("ies"):
        return token[:-3] + "y"
    if len(token) > 5 and token.endswith(("ches", "shes", "xes", "zes")):
        return token[:-2]
    if len(token) > 4 and token.endswith("s") and not token.endswith("ss"):
        return token[:-1]
    return token


def supplier_tokens(value: Any) -> list[str]:
    tokens = []
    for raw in _normalize(value).split():
        token = _stem(raw)
        if len(token) < 2 or token in _STOPWORDS:
            continue
        if token not in tokens:
            tokens.append(token)
    return tokens


def _token_similarity(query_token: str, title_token: str) -> float:
    if query_token == title_token:
        return 1.0
    query_aliases = _ALIAS_INDEX.get(query_token)
    if query_aliases and title_token in query_aliases:
        return 0.95
    if len(query_token) >= 5 and len(title_token) >= 5:
        ratio = SequenceMatcher(None, query_token, title_token).ratio()
        if ratio >= 0.88:
            return 0.85
    return 0.0


def _best_token_similarity(query_token: str, title_tokens: list[str]) -> float:
    return max((_token_similarity(query_token, title_token) for title_token in title_tokens), default=0.0)


def supplier_relevance_score(query: Any, title: Any) -> float:
    query_tokens = supplier_tokens(query)
    title_tokens = supplier_tokens(title)
    if not query_tokens or not title_tokens:
        return 0.0

    normalized_query = _normalize(query)
    normalized_title = _normalize(title)
    if normalized_query and normalized_query in normalized_title:
        return 1.0

    weighted_total = 0.0
    weighted_match = 0.0
    for token in query_tokens:
        weight = 0.55 if token in _GENERIC_TOKENS else 1.0
        weighted_total += weight
        weighted_match += weight * _best_token_similarity(token, title_tokens)
    if weighted_total <= 0:
        return 0.0
    return round(min(weighted_match / weighted_total, 1.0), 4)


def supplier_result_is_relevant(query: Any, title: Any) -> bool:
    query_tokens = supplier_tokens(query)
    title_tokens = supplier_tokens(title)
    if not query_tokens or not title_tokens:
        return False

    score = supplier_relevance_score(query, title)
    if len(query_tokens) == 1:
        return score >= 0.85

    important = [token for token in query_tokens if token not in _GENERIC_TOKENS]
    if important and not any(_best_token_similarity(token, title_tokens) >= 0.85 for token in important):
        return False
    return score >= 0.45


def rank_supplier_results(
    query: Any,
    rows: list[dict[str, Any]],
    *,
    title_keys: tuple[str, ...] = ("name", "title"),
    limit: int = 20,
) -> tuple[list[dict[str, Any]], int]:
    ranked: list[tuple[float, int, dict[str, Any]]] = []
    for index, row in enumerate(rows):
        title = next((row.get(key) for key in title_keys if row.get(key)), "")
        score = supplier_relevance_score(query, title)
        if not supplier_result_is_relevant(query, title):
            continue
        enriched = dict(row)
        enriched["match_strength"] = round(score, 2)
        ranked.append((score, index, enriched))

    ranked.sort(key=lambda item: (-item[0], item[1]))
    selected = [row for _, _, row in ranked[:max(int(limit), 1)]]
    return selected, max(len(rows) - len(ranked), 0)
