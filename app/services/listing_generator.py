from html import escape
import re


STOP_WORDS = {
    "the", "a", "an", "and", "or", "for", "with", "of", "to", "in", "on", "by",
    "new", "hot", "sale", "best", "quality", "dropshipping", "product",
}

# Small, deliberately conservative vocabulary. A market term that is not already
# present in the verified CJ identity can only be added when it is a generic
# product descriptor from this list. Brand names and competitor model numbers are
# therefore never copied from an observed eBay title.
SAFE_MARKET_EXPANSIONS = {
    "adjustable", "auto", "car", "charger", "charging", "cleaner", "compact",
    "cordless", "desk", "desktop", "electric", "fast", "foldable", "handheld",
    "home", "indoor", "led", "magnetic", "mini", "mount", "organizer", "outdoor",
    "portable", "rechargeable", "storage", "travel", "usb", "vacuum", "waterproof",
    "wireless",
}


def _tokens(value: str) -> list[str]:
    return [token for token in re.findall(r"[A-Za-z0-9]+(?:[+'-][A-Za-z0-9]+)?", value or "") if token]


def _key(token: str) -> str:
    return token.lower().strip(",.;:/")


def _dedupe_tokens(sources: list[str]) -> list[str]:
    words: list[str] = []
    seen: set[str] = set()
    for source in sources:
        for raw in _tokens(source):
            key = _key(raw)
            if not key or key in seen or key in STOP_WORDS:
                continue
            seen.add(key)
            words.append(raw.strip())
    return words


def _safe_market_suffix(identity_keys: set[str], market_keywords: list[str] | None) -> list[str]:
    """Return at most one short, relevant market phrase.

    Full competitor titles are rejected. Unknown brand/model tokens are also
    rejected, even when the rest of the phrase overlaps the product identity.
    """
    for phrase in market_keywords or []:
        raw_tokens = [token for token in _tokens(phrase) if _key(token) not in STOP_WORDS]
        if not raw_tokens or len(raw_tokens) > 6:
            continue
        overlap = sum(1 for token in raw_tokens if _key(token) in identity_keys)
        if len(raw_tokens) == 1:
            if overlap == 1:
                return raw_tokens
            continue
        if overlap < 2 or overlap / len(raw_tokens) < 0.60:
            continue
        safe = [
            token for token in raw_tokens
            if _key(token) in identity_keys or _key(token) in SAFE_MARKET_EXPANSIONS
        ]
        safe_overlap = sum(1 for token in safe if _key(token) in identity_keys)
        if safe_overlap >= 2:
            return safe
    return []


def optimize_title(
    title: str,
    max_len: int = 80,
    market_keywords: list[str] | None = None,
    *,
    variant_name: str = "",
    category_name: str = "",
    aspects: dict | None = None,
) -> str:
    """Build a compact eBay US title from one verified product identity.

    The product/CJ wording is authoritative. Observed eBay terms are only short
    relevance hints; a competitor title can never replace the product identity.
    """
    aspect_sources: list[str] = []
    for key, values in (aspects or {}).items():
        if str(key).startswith("_"):
            continue
        if not isinstance(values, list):
            values = [values]
        aspect_sources.extend(str(value) for value in values if str(value).strip())

    identity_sources = [title, variant_name, category_name, *aspect_sources]
    identity_words = _dedupe_tokens(identity_sources)
    identity_keys = {_key(word) for word in identity_words}
    market_suffix = _safe_market_suffix(identity_keys, market_keywords)

    # Identity comes first. This guarantees that two different CJ products cannot
    # be replaced by the same competitor title merely because the same Radar was
    # open when the user clicked the SEO button.
    ordered = _dedupe_tokens([*identity_sources, " ".join(market_suffix)])

    out = ""
    for word in ordered:
        candidate = (out + " " + word).strip()
        if len(candidate) > max_len:
            continue
        out = candidate
    return out or title[:max_len]


def generate_description(product: dict) -> str:
    title = escape(product.get("title") or "Product")
    aspects = product.get("aspects") or {}
    bullets = []
    for key, values in aspects.items():
        if str(key).startswith("_"):
            continue
        if not isinstance(values, list):
            values = [str(values)]
        bullets.append(f"<li><strong>{escape(str(key))}:</strong> {escape(', '.join(map(str, values)))}</li>")
    details = "".join(bullets) or "<li>Product specifications will be completed from the verified supplier data before publication.</li>"
    days = int(product.get("shipping_days") or 0)
    return f"""
<div style="font-family:Arial,sans-serif;line-height:1.5;color:#222">
  <h2>{title}</h2>
  <p>Brand-new item supplied through CJ Dropshipping and dispatched according to the shipping details shown in this listing.</p>
  <h3>Key Features</h3>
  <ul>
    <li>New condition.</li>
    <li>Tracking provided when available for the selected CJ shipping method.</li>
    <li>Customer support handled directly by our eBay store.</li>
  </ul>
  <h3>Specifications</h3>
  <ul>{details}</ul>
  <h3>Shipping</h3>
  <p>Current verified supplier transit estimate: {days} day(s). The dispatch route and stock are rechecked before publication.</p>
</div>
""".strip()
