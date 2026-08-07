# -*- coding: utf-8 -*-
"""Tests PM Gantt Phase F — PIC/status filters + schedule export columns."""
from __future__ import annotations

from pathlib import Path

import openpyxl

from exporter.pm_exporter import export_pm_report

ROOT = Path(__file__).resolve().parents[1]
DASHBOARD_JS = (ROOT / "static" / "js" / "dashboard.js").read_text(encoding="utf-8")
INDEX_HTML = (ROOT / "templates" / "index.html").read_text(encoding="utf-8")


class TestStaticPhaseF:
    def test_filter_controls_in_html(self):
        assert 'id="pmGanttFilterPic"' in INDEX_HTML
        assert 'id="pmGanttFilterStatus"' in INDEX_HTML
        assert "onPmGanttFilterChange()" in INDEX_HTML
        assert "Hoàn thành" in INDEX_HTML

    def test_filter_logic_in_js(self):
        assert "_pmFilteredSchedule" in DASHBOARD_JS
        assert "_pmPopulateGanttFilters" in DASHBOARD_JS
        assert "onPmGanttFilterChange" in DASHBOARD_JS
        assert "_pmRefreshGanttViews" in DASHBOARD_JS
        assert "_pmFilterGridRows" in DASHBOARD_JS
        assert "_pmComputeHeatmapClient" in DASHBOARD_JS
        assert "filterStatus" in DASHBOARD_JS
        assert "filterPic" in DASHBOARD_JS

    def test_render_dimension_wires_refresh(self):
        idx = DASHBOARD_JS.index("function renderPmDimension(")
        chunk = DASHBOARD_JS[idx: idx + 2800]
        assert "_pmRefreshGanttViews()" in chunk
        assert "_pmPopulateGanttFilters(plan)" in chunk


def test_export_schedule_has_status_columns(tmp_path: Path):
    plan = {
        "source_filename": "test.xlsx",
        "schedule": [
            {
                "name": "Task A",
                "start": "2026-03-02",
                "end": "2026-03-05",
                "status": "In-progress",
                "actual_end": "2026-03-06",
                "percent_complete": 80,
                "is_phase_header": False,
            },
        ],
        "milestones": [],
    }
    path = export_pm_report(plan, None, str(tmp_path), project_code="TST")
    wb = openpyxl.load_workbook(path, read_only=True)
    ws = wb["Lịch trình"]
    rows = list(ws.iter_rows(min_row=4, max_row=4, values_only=True))
    wb.close()
    assert rows[0][4] == "In-progress"
    assert rows[0][5] == "2026-03-06"
    assert rows[0][6] == 80
