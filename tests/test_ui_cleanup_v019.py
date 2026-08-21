from pathlib import Path


def test_visibility_cleanup_script_keeps_requested_structure():
    script = Path("app/static/provider_cleanup.js").read_text(encoding="utf-8")
    assert "'dropxl'" in script
    assert "'etsy'" in script
    assert "sales-channel-panel" in script
    assert "supplier-network" in script
    assert "niche-directory-panel" in script
    assert "#section-radar #radarSources" in script
    assert 'data-section="pipeline"' in script
    assert "#section-pipeline" in script
    assert 'data-supplier-tab="cj"' in script
    assert 'data-supplier-tab="amazon"' in script
    assert 'data-supplier-tab="aliexpress"' in script


def test_supplier_source_search_supports_amazon_and_aliexpress():
    router = Path("app/routers/suppliers.py").read_text(encoding="utf-8")
    assert '@router.get("/source-search")' in router
    assert "amazon_supplier_offers" in router
    assert "aliexpress_supplier_offers" in router
    assert 'provider == "amazon"' in router


def test_supplier_hub_is_reduced_to_three_api_sources():
    router = Path("app/routers/suppliers.py").read_text(encoding="utf-8")
    hub = router.split('@router.get("/hub")', 1)[1].split('@router.get("/source-search")', 1)[0]
    assert '"id": "cj"' in hub
    assert '"name": "Amazon France"' in hub
    assert "aliexpress_supplier_status()" in hub
    assert 'for provider_id in ("dropxl"' not in hub
    assert "ASSISTED_SUPPLIERS" not in hub
