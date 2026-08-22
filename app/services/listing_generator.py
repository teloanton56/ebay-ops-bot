from html import escape


def optimize_title(title: str, max_len: int = 80) -> str:
    words = []
    seen = set()
    for raw in title.replace("|", " ").replace("-", " ").split():
        key = raw.lower().strip(",.;:/")
        if not key or key in seen:
            continue
        seen.add(key)
        words.append(raw.strip())
    out = ""
    for word in words:
        candidate = (out + " " + word).strip()
        if len(candidate) > max_len:
            break
        out = candidate
    return out or title[:max_len]


def generate_description(product: dict) -> str:
    title = escape(product.get("title") or "Product")
    aspects = product.get("aspects") or {}
    bullets = []
    for key, values in aspects.items():
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
