# -*- coding: utf-8 -*-
"""T-B — API Registry catalog: filter, export/import, curl preview."""
from __future__ import annotations

from pathlib import Path

import pytest

from analyzer import integrations as integ_mod

ROOT = Path(__file__).resolve().parents[1]
DASHBOARD_JS = (ROOT / "static" / "js" / "dashboard.js").read_text(encoding="utf-8")
INDEX_HTML = (ROOT / "templates" / "index.html").read_text(encoding="utf-8")


@pytest.fixture
def project_dir(tmp_path) -> str:
    d = tmp_path / "proj"
    d.mkdir()
    return str(d)


def _catalog_payload(name: str, source_app: str, env: str = "prod") -> dict:
    return {
        "name": name,
        "base_url": "https://api.example.com",
        "source_app": source_app,
        "env": env,
        "visibility": "external",
        "owner_contact": "pmo@example.com",
        "docs_url": "https://docs.example.com",
        "auth": {
            "method": "api_key",
            "apikey_env": "TEST_API",
            "apikey_header": "X-API-Key",
            "apikey_location": "header",
        },
        "endpoints": [{
            "name": "List",
            "path": "/v1/items",
            "http_method": "GET",
            "response_type": "json",
            "target_action": "snapshot",
        }],
    }


def test_list_integrations_filter_source_app(project_dir):
    integ_mod.create_integration(project_dir, _catalog_payload("A", "iHRP"))
    integ_mod.create_integration(project_dir, _catalog_payload("B", "TaskDaily"))
    out = integ_mod.list_integrations(project_dir, source_app="iHRP")
    assert len(out) == 1
    assert out[0]["name"] == "A"


def test_catalog_fields_round_trip(project_dir):
    created = integ_mod.create_integration(project_dir, _catalog_payload("X", "iHRP"))
    updated = integ_mod.update_integration(project_dir, created["id"], {
        "owner_contact": "ba@example.com",
        "env": "uat",
    })
    assert updated["owner_contact"] == "ba@example.com"
    assert updated["env"] == "uat"


def test_export_import_merge(project_dir):
    integ_mod.create_integration(project_dir, _catalog_payload("One", "iHRP"))
    exported = integ_mod.export_registry(project_dir)
    assert exported["version"] == 1
    assert len(exported["integrations"]) == 1
    payload = {
        "integrations": [_catalog_payload("Two", "Other")],
    }
    result = integ_mod.import_registry(project_dir, payload, mode="merge")
    assert result["total"] == 2
    names = {it["name"] for it in integ_mod.list_integrations(project_dir)}
    assert names == {"One", "Two"}


def test_build_curl_preview_masks_secrets():
    integ = _catalog_payload("T", "iHRP")
    ep = integ["endpoints"][0]
    curl = integ_mod.build_curl_preview(integ, ep)
    assert "curl" in curl
    assert "TEST_API_KEY" in curl or "${TEST_API_KEY}" in curl
    assert "sk-" not in curl


class TestStaticCatalogUI:
    def test_filter_and_catalog_fields(self):
        assert 'id="integFilterQ"' in INDEX_HTML
        assert 'id="integSourceApp"' in INDEX_HTML
        assert 'id="integDetailPane"' in INDEX_HTML
        assert "_integFilterClient" in DASHBOARD_JS
        assert "_integExportRegistry" in DASHBOARD_JS
        assert "_integImportPostmanFile" in DASHBOARD_JS
