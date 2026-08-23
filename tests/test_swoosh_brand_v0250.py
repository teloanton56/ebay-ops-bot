from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app


ROOT = Path(__file__).resolve().parents[1]
BRAND_REV = "ops-swoosh-1"


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_swoosh_asset_is_the_active_minimal_logo():
    icon = read("app/static/app-icon.svg")
    assert "Minimal curved arrow symbol" in icon
    assert 'stroke="#35e6a1"' in icon
    assert 'fill="#35e6a1"' in icon
    assert "bolt symbol" not in icon.lower()
    assert "geometric knot" not in icon.lower()


def test_every_visible_brand_surface_uses_the_same_revision():
    files = (
        "app/main.py",
        "app/static/brand.css",
        "app/static/manifest.webmanifest",
        "app/static/service-worker.js",
        "app/templates/dashboard.html",
        "app/templates/login.html",
        "app/static/offline.html",
    )
    for path in files:
        source = read(path)
        assert BRAND_REV in source, f"{path} does not use the current brand revision"
        assert "ops-knot-1" not in source
        assert "ops-bolt-1" not in source


def test_dashboard_and_manifest_expose_fresh_swoosh_urls():
    with TestClient(app) as client:
        dashboard = client.get("/")
        manifest = client.get("/manifest.webmanifest")

    assert dashboard.status_code == 200
    assert f"/static/app-icon.svg?v={BRAND_REV}" in dashboard.text
    assert f"/static/brand.css?v={BRAND_REV}" in dashboard.text
    assert f"/manifest.webmanifest?v={BRAND_REV}" in dashboard.text
    assert manifest.status_code == 200
    assert manifest.headers.get("cache-control") == "no-cache"
    assert manifest.json()["icons"][0]["src"].endswith(f"?v={BRAND_REV}")
