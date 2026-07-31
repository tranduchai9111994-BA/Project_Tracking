"""Tests Forecast Gantt — tháng UAT/Golive + rule open_max / closed_max."""
from __future__ import annotations

from datetime import date
from pathlib import Path

import openpyxl
import pytest

from analyzer.forecast_gantt import (
    FORECAST_RULE_VI,
    compute_forecast_gantt,
    compute_milestone_for_data,
    compute_project_forecast,
)
from analyzer.project_manager import ProjectManager
from parser.excel_parser import FunctionListParser


TODAY = date(2026, 7, 31)


def _write_fl(path: Path, headers: list[str], rows: list[list]) -> None:
    wb = openpyxl.Workbook()
    ws = wb.active
    for i, h in enumerate(headers, 1):
        ws.cell(1, i, h)
    for r_i, row in enumerate(rows, 2):
        for c_i, v in enumerate(row, 1):
            ws.cell(r_i, c_i, v)
    wb.save(path)
    wb.close()


HEADERS = [
    "STT", "Mã CN", "Tên chức năng", "Module",
    "Analysis - Start", "Analysis - End", "Analysis - Status", "Analysis - PIC",
    "Dev - Start", "Dev - End", "Dev - Status", "Dev - PIC",
    "Config UAT - Start", "Config UAT - End", "Config UAT - Status", "Config UAT - PIC",
    "UAT - Start", "UAT - End", "UAT - Status", "UAT - PIC",
    "Golive - Start", "Golive - End", "Golive - Status", "Golive - PIC",
]


def _row(
    stt, code, name, module,
    a_end=None, a_st=None,
    d_end=None, d_st=None,
    c_end=None, c_st=None,
    u_end=None, u_st=None,
    g_end=None, g_st=None,
):
    return [
        stt, code, name, module,
        None, a_end, a_st, "A",
        None, d_end, d_st, "D",
        None, c_end, c_st, "C",
        None, u_end, u_st, "U",
        None, g_end, g_st, "G",
    ]


@pytest.fixture
def sample_data(tmp_path):
    path = tmp_path / "fl.xlsx"
    _write_fl(
        path,
        HEADERS,
        [
            # Analysis all Closed → closed_max May
            _row(1, "F.01", "F1", "TMS",
                 a_end=date(2026, 5, 10), a_st="Closed",
                 d_end=date(2026, 6, 20), d_st="In-progress",
                 c_end=date(2026, 7, 5), c_st="Open",
                 u_end=date(2026, 8, 15), u_st="Open",
                 g_end=date(2026, 9, 30), g_st="Open"),
            _row(2, "F.02", "F2", "TMS",
                 a_end=date(2026, 5, 25), a_st="Closed",
                 d_end=date(2026, 6, 10), d_st="Closed",
                 c_end=date(2026, 7, 20), c_st="In-progress",
                 u_end=date(2026, 8, 28), u_st="Assigned",
                 g_end=date(2026, 10, 5), g_st="Open"),
        ],
    )
    return FunctionListParser().parse(str(path))


class TestMilestoneRule:
    def test_open_max_preferred(self, sample_data):
        uat = compute_milestone_for_data(sample_data, ("UAT",))
        assert uat["source"] == "open_max"
        assert uat["month"] == "2026-08"
        assert uat["date"] == "2026-08-28"  # max of open ends
        assert uat["open"] == 2

    def test_closed_max_when_all_closed(self, sample_data):
        analysis = compute_milestone_for_data(sample_data, ("Phân tích",))
        assert analysis["source"] == "closed_max"
        assert analysis["month"] == "2026-05"
        assert analysis["date"] == "2026-05-25"
        assert analysis["open"] == 0

    def test_project_forecast_keys(self, sample_data):
        fc = compute_project_forecast(sample_data)
        assert set(fc) >= {"analysis", "dev", "config", "uat", "golive"}
        assert fc["golive"]["month"] == "2026-10"
        assert fc["dev"]["source"] == "open_max"  # 1 still open
        assert fc["dev"]["month"] == "2026-06"


class TestMultiProject:
    def test_two_projects(self, tmp_path):
        root = tmp_path / "projects"
        root.mkdir()
        mgr = ProjectManager(str(root))
        a = mgr.create_project("Alpha")
        b = mgr.create_project("Beta")

        _write_fl(
            Path(mgr.get_project_folder(a.slug)) / "current.xlsx",
            HEADERS,
            [_row(1, "A.01", "A1", "M",
                  a_end=date(2026, 4, 1), a_st="Closed",
                  u_end=date(2026, 8, 1), u_st="Open",
                  g_end=date(2026, 9, 1), g_st="Open")],
        )
        _write_fl(
            Path(mgr.get_project_folder(b.slug)) / "current.xlsx",
            HEADERS,
            [_row(1, "B.01", "B1", "M",
                  a_end=date(2026, 5, 1), a_st="Closed",
                  u_end=date(2026, 7, 15), u_st="Closed",
                  g_end=date(2026, 11, 20), g_st="Open")],
        )

        cache = {}

        def loader(slug):
            if slug in cache:
                return cache[slug]
            p = Path(mgr.get_project_folder(slug)) / "current.xlsx"
            if not p.is_file():
                return None
            data = FunctionListParser().parse(str(p))
            cache[slug] = {"data": data}
            return cache[slug]

        result = compute_forecast_gantt(mgr, loader, slugs=[a.slug, b.slug])
        assert result["rule"] == FORECAST_RULE_VI
        assert result["summary"]["project_count"] == 2
        assert "2026-08" in result["summary"]["uat_by_month"]
        # Beta UAT all closed → closed_max July
        beta = next(p for p in result["projects"] if p["slug"] == b.slug)
        assert beta["milestones"]["uat"]["month"] == "2026-07"
        assert beta["milestones"]["uat"]["source"] == "closed_max"
        assert result["milestone_aggregate"]["golive"]["month"] == "2026-11"
