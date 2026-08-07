# -*- coding: utf-8 -*-
"""Postman Collection v2.1 → API Registry integration."""
from __future__ import annotations

from pathlib import Path

import pytest

from analyzer import integrations as integ_mod
from analyzer.postman_import import postman_to_integration, import_postman_collection

ROOT = Path(__file__).resolve().parents[1]
DASHBOARD_JS = (ROOT / "static" / "js" / "dashboard.js").read_text(encoding="utf-8")
INDEX_HTML = (ROOT / "templates" / "index.html").read_text(encoding="utf-8")

POSTMAN_FIXTURE = {
    "info": {
        "name": "iHRP API Sample",
        "schema": "https://schema.getpostman.com/json/collection/v2.1.0/collection.json",
    },
    "auth": {
        "type": "apikey",
        "apikey": [
            {"key": "key", "value": "X-API-Key", "type": "string"},
            {"key": "value", "value": "{{api_key}}", "type": "string"},
            {"key": "in", "value": "header", "type": "string"},
        ],
    },
    "item": [
        {
            "name": "Folder",
            "item": [
                {
                    "name": "List functions",
                    "request": {
                        "method": "GET",
                        "url": {
                            "raw": "https://ihrp.example.com/api/external/functions?module=all",
                            "protocol": "https",
                            "host": ["ihrp", "example", "com"],
                            "path": ["api", "external", "functions"],
                            "query": [{"key": "module", "value": "all"}],
                        },
                    },
                },
            ],
        },
        {
            "name": "Health",
            "request": {
                "method": "GET",
                "url": "https://ihrp.example.com/api/health",
            },
        },
    ],
}


@pytest.fixture
def project_dir(tmp_path) -> str:
    d = tmp_path / "proj"
    d.mkdir()
    return str(d)


def test_postman_to_integration_parses_requests():
    integ = postman_to_integration(POSTMAN_FIXTURE)
    assert integ["name"] == "iHRP API Sample"
    assert integ["base_url"] == "https://ihrp.example.com"
    assert integ["source_app"] == "postman"
    assert len(integ["endpoints"]) == 2
    names = {ep["name"] for ep in integ["endpoints"]}
    assert "Folder / List functions" in names
    assert "Health" in names
    auth = integ["auth"]
    assert auth["method"] == "api_key"
    assert auth["apikey_header"] == "X-API-Key"
    assert "IHRP_API_SAMPLE" in auth["apikey_env"] or auth["apikey_env"]


def test_postman_import_persist(project_dir):
    result = import_postman_collection(project_dir, POSTMAN_FIXTURE, mode="merge")
    assert result["endpoint_count"] == 2
    items = integ_mod.list_integrations(project_dir)
    assert len(items) == 1
    assert items[0]["endpoints"][0]["params"].get("module") == "all"


class TestStaticPostmanUI:
    def test_postman_button(self):
        assert "integPostmanFile" in INDEX_HTML
        assert "_integImportPostmanFile" in DASHBOARD_JS
