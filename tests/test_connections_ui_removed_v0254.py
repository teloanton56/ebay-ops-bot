from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app


ROOT = Path(__file__).resolve().parents[1]


def test_dashboard_has_no_connections_page_or_configuration_controls():
    with TestClient(app) as client:
        response = client.get("/")

    assert response.status_code == 200
    html = response.text
    javascript = (ROOT / "app/static/simple_ui.js").read_text(encoding="utf-8")
    stylesheets = "\n".join(
        (ROOT / path).read_text(encoding="utf-8")
        for path in ("app/static/app.css", "app/static/simple_ui.css")
    )

    for fragment in (
        'data-section="settings"',
        'id="section-settings"',
        'data-action="connect-ebay"',
        'data-action="configure-cj"',
    ):
        assert fragment not in html

    assert 'data-go="settings"' not in javascript
    assert "window.prompt" not in javascript
    assert "configureEbay" not in javascript
    assert "configureCj" not in javascript
    assert ".connection-" not in stylesheets


def test_operational_ebay_and_cj_status_indicators_remain_visible():
    dashboard = (ROOT / "app/templates/dashboard.html").read_text(encoding="utf-8")
    assert 'id="ebayChip"' in dashboard
    assert 'id="cjChip"' in dashboard
    assert 'id="statCj"' in dashboard
