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
    title = escape(product.get("title") or "Produit")
    aspects = product.get("aspects") or {}
    bullets = []
    for key, values in aspects.items():
        if not isinstance(values, list):
            values = [str(values)]
        bullets.append(f"<li><strong>{escape(str(key))} :</strong> {escape(', '.join(map(str, values)))}</li>")
    details = "".join(bullets) or "<li>Caractéristiques à compléter depuis la fiche fournisseur.</li>"
    return f"""
<div style="font-family:Arial,sans-serif;line-height:1.5;color:#222">
  <h2>{title}</h2>
  <p>Produit neuf, expédié avec suivi selon les conditions indiquées sur l'annonce.</p>
  <h3>Points forts</h3>
  <ul>
    <li>Produit sélectionné auprès d'un fournisseur identifié.</li>
    <li>Suivi d'expédition lorsque disponible.</li>
    <li>Service client assuré par notre boutique.</li>
  </ul>
  <h3>Caractéristiques</h3>
  <ul>{details}</ul>
  <h3>Livraison</h3>
  <p>Délai fournisseur indicatif : {int(product.get('shipping_days') or 0)} jour(s).</p>
</div>
""".strip()
