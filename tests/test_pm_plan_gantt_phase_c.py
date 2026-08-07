# -*- coding: utf-8 -*-
"""Tests PM Gantt Phase C — week axis, master grid, gantt view API."""
from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from analyzer.pm_plan_gantt import (
    build_pm_gantt_view,
    build_pm_master_week_grid,
    compute_pm_milestone_markers,
    compute_pm_week_axis,
)
from parser.pm_plan_parser import propose_sheet_mapping


ROOT = Path(__file__).resolve().parents[1]
DASHBOARD_JS = (ROOT / "static" / "js" / "dashboard.js").read_text(encoding="utf-8")
INDEX_HTML = (ROOT / "templates" / "index.html").read_text(encoding="utf-8")


def _sample_plan() -> dict:
    return {
        "project_start": "2026-03-02",
        "weeks": [{"label": "W1", "month": "THÁNG 3/2026"}, {"label": "W2", "month": ""}],
        "milestones": [{"stt": "1", "name": "Kickoff"}],
        "schedule": [
            {
                "name": "Section A",
                "stt": "A",
                "start": "2026-03-02",
                "end": "2026-03-11",
                "is_phase_header": True,
            },
            {
                "name": "Task 1",
                "stt": "1",
                "start": "2026-03-02",
                "end": "2026-03-04",
                "status": "Open",
                "is_phase_header": False,
            },
        ],
    }


def test_week_axis_from_plan():
    axis = compute_pm_week_axis(_sample_plan())
    assert len(axis) >= 2
    assert axis[0]["label"] == "W1"
    assert axis[0]["start"] == "2026-03-02"  # Monday anchor


def test_master_grid_marks_active_weeks():
    plan = _sample_plan()
    axis = compute_pm_week_axis(plan)
    grid = build_pm_master_week_grid(plan, axis, today=date(2026, 8, 6))
    tasks = [r for r in grid["rows"] if r["kind"] == "task"]
    assert tasks[0]["week_active"]


def test_milestone_markers_from_section():
    markers = compute_pm_milestone_markers(_sample_plan())
    assert any(m["kind"] == "section" for m in markers)


def test_build_pm_gantt_view_bundle():
    view = build_pm_gantt_view(_sample_plan())
    assert view is not None
    assert view["week_axis"]
    assert view["master_grid"]["rows"]
    assert view["default_window_weeks"] == 12


class TestStaticPhaseC:
    def test_html_view_toggle_and_master_wrap(self):
        assert 'id="pmGanttViewTimeline"' in INDEX_HTML
        assert 'id="pmPlanMasterWrap"' in INDEX_HTML
        assert 'id="pmGanttWeekSlider"' in INDEX_HTML

    def test_js_master_renderer(self):
        assert "function renderPmPlanMasterGrid(" in DASHBOARD_JS
        assert "setPmGanttViewMode" in DASHBOARD_JS
        assert "pm_gantt_view" in DASHBOARD_JS or "pm_gantt_view" in DASHBOARD_JS
        assert "pm-gantt-milestone" in DASHBOARD_JS

    def test_vietinak_mapping_keywords(self):
        m = propose_sheet_mapping(["Kế hoạch khung", "Kế hoạch chi tiết"])
        assert m["Kế hoạch khung"] == "gantt"
        assert m["Kế hoạch chi tiết"] == "schedule"
