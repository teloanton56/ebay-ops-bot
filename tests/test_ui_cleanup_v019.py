from pathlib import Path


def test_visibility_cleanup_retires_old_sources_and_legacy_blocks():
    script = Path("app/static/provider_cleanup.js").read_text(encoding="utf-8")
    lower = script.lower()
    for retired in ("dropxl", "etsy", "amazon", "aliexpress", "tiktok", "youtube"):
        assert retired in lower
    assert "supplier-network" in script
    assert "niche-directory-panel" in script
    assert "#radarSources" in script
    assert 'data-section="pipeline"' in script
    assert "#section-pipeline" in script
    assert "keepCJOnly" in script


def test_supplier_source_search_supports_only_cj():
    router = Path("app/routers/suppliers.py").read_text(encoding="utf-8")
    assert '@router.get("/source-search")' in router
    assert 'Query(pattern="^cj$")' in router
    assert "CJClient" in router
    assert "amazon_supplier_offers" not in router
    assert "aliexpress_dropship_supplier_offers" not in router


def test_supplier_hub_is_reduced_to_one_active_source():
    router = Path("app/routers/suppliers.py").read_text(encoding="utf-8")
    hub = router.split('@router.get("/hub")', 1)[1].split('@router.get("/source-search")', 1)[0]
    assert '"id": "cj"' in hub
    assert '"name": "CJ Dropshipping"' in hub
    assert '"providers": [provider]' in hub
    assert '"operating_mode": "EBAY_US_CJ_ONLY"' in hub
    assert "Amazon France" not in hub
    assert "aliexpress_supplier_status" not in hub
