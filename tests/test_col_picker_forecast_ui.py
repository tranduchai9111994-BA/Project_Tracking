"""Smoke — column picker markers in HTML/JS."""
from __future__ import annotations

import os

ROOT = os.path.join(os.path.dirname(__file__), "..")


def test_col_picker_storage_and_mount():
    js = open(os.path.join(ROOT, "static", "js", "dashboard.js"), encoding="utf-8").read()
    assert "COL_PICKER_STORAGE_KEY" in js
    assert "ihrp_table_cols_v1" in js
    assert "function applyColumnVisibility" in js
    assert "function mountColumnPicker" in js
    assert 'applyColumnVisibility("overdue")' in js
    assert 'applyColumnVisibility("unassigned")' in js
    assert 'applyColumnVisibility("stalled")' in js
    assert 'applyColumnVisibility("dq")' in js


def test_col_picker_html_hosts():
    html = open(os.path.join(ROOT, "templates", "index.html"), encoding="utf-8").read()
    for tid in ("overdue", "unassigned", "stalled", "rlogCoded", "rlogPlan", "dq"):
        assert f'data-col-picker="{tid}"' in html, tid
    assert 'data-col="code"' in html
    assert 'data-col-locked="1"' in html


def test_forecast_section_present():
    html = open(os.path.join(ROOT, "templates", "index.html"), encoding="utf-8").read()
    js = open(os.path.join(ROOT, "static", "js", "dashboard.js"), encoding="utf-8").read()
    assert 'id="section-forecast-gantt"' in html
    assert "loadForecastGantt" in js
    assert "section-forecast-gantt" in js
