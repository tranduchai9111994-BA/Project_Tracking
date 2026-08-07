# -*- coding: utf-8 -*-
"""Tests PM Gantt Phase E — resource heatmap + export detail."""
from __future__ import annotations

from pathlib import Path

import openpyxl

from analyzer.pm_plan_gantt import compute_pm_resource_heatmap, compute_pm_week_axis, build_pm_gantt_view
from exporter.pm_exporter import export_pm_report

ROOT = Path(__file__).resolve().parents[1]
DASHBOARD_JS = (ROOT / "static" / "js" / "dashboard.js").read_text(encoding="utf-8")
INDEX_HTML = (ROOT / "templates" / "index.html").read_text(encoding="utf-8")


def test_resource_heatmap_counts():
    plan = {
        "project_start": "2026-03-02",
        "weeks": [{"label": "W1"}, {"label": "W2"}, {"label": "W3"}],
        "schedule": [
            {"name": "T1", "start": "2026-03-02", "end": "2026-03-04", "pic_fpt": ["Alice"], "is_phase_header": False},
            {"name": "T2", "start": "2026-03-03", "end": "2026-03-10", "pic_fpt": ["Bob"], "is_phase_header": False},
        ],
    }
    axis = compute_pm_week_axis(plan)
    hm = compute_pm_resource_heatmap(plan, axis)
    assert hm["max_count"] >= 2
    total_row = hm["rows"][0]
    assert sum(total_row["counts"]) >= 2
    assert any(r["kind"] == "pic" for r in hm["rows"])


def test_gantt_view_has_heatmap():
    plan = {
        "schedule": [{"name": "X", "start": "2026-03-01", "end": "2026-03-05", "is_phase_header": False}],
    }
    view = build_pm_gantt_view(plan)
    assert view and view.get("resource_heatmap")


def test_export_includes_detail_sheet(tmp_path: Path):
    plan = {
        "source_filename": "test.xlsx",
        "schedule": [
            {"name": "Task", "start": "2026-03-02", "end": "2026-03-03", "is_phase_header": False},
        ],
        "day_columns": [
            {"label": "M", "date": "2026-03-02"},
            {"label": "T", "date": "2026-03-03"},
        ],
        "milestones": [],
    }
    path = export_pm_report(plan, None, str(tmp_path), project_code="TST")
    wb = openpyxl.load_workbook(path, read_only=True)
    assert "Gantt Chi tiết ngày" in wb.sheetnames
    wb.close()


class TestStaticPhaseE:
    def test_heatmap_ui(self):
        assert 'id="pmGanttHeatmap"' in INDEX_HTML
        assert "_paintPmGanttHeatmap" in DASHBOARD_JS
        assert "resource_heatmap" in DASHBOARD_JS
