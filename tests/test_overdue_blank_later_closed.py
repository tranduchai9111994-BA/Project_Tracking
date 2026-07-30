"""Tests cho analyzer.overdue — blank status + later Closed false-positive."""
from datetime import date, timedelta
from pathlib import Path

import pytest

from analyzer.dashboard_engine import DashboardEngine
from analyzer.overdue import is_phase_overdue, row_has_overdue
from parser.excel_parser import (
    FunctionListParser,
    FunctionRow,
    PhaseData,
    ParsedData,
    PhaseGroup,
)


TODAY = date(2026, 7, 30)
PHASE_ORDER = [
    "Analysis", "Dev", "Config Local", "Config UAT",
    "Document", "Config Prod", "UAT", "Golive",
]


def _pd(end_offset: int | None, status: str | None, pics=None) -> PhaseData:
    end = None if end_offset is None else TODAY + timedelta(days=end_offset)
    return PhaseData(end_date=end, status=status, pics=pics or [])


def _row_tms84_blank_uat() -> FunctionRow:
    """Mô phỏng TMS.FR.84 trước sync 13:38 — UAT blank + Golive Closed."""
    return FunctionRow(
        row_num=2,
        meta={
            "ma_cn": "TMS.FR.84",
            "ten_cn": "Dang ky nghi online",
            "module": "APP",
        },
        phases={
            "Analysis": _pd(-113, "Closed", ["SonHN6"]),
            "Dev": _pd(None, "Closed"),
            "Config Local": _pd(None, None),
            "Config UAT": _pd(None, None),
            "Document": _pd(None, None),
            "Config Prod": _pd(None, None),
            "UAT": _pd(-113, None, ["SonHN6", "Phong nhan su"]),
            "Golive": _pd(None, "Closed"),
        },
    )


def test_blank_status_still_overdue_without_later_closed():
    """Blank + End quá hạn + không phase sau Closed → vẫn overdue."""
    row = FunctionRow(
        row_num=1,
        meta={"ma_cn": "X.01"},
        phases={
            "Analysis": _pd(-10, "Closed"),
            "UAT": _pd(-5, None, ["A"]),
            "Golive": _pd(None, None),
        },
    )
    order = ["Analysis", "UAT", "Golive"]
    assert is_phase_overdue(
        row.phases["UAT"], TODAY,
        row=row, phase_name="UAT", phase_order=order,
    ) is True


def test_blank_status_not_overdue_when_later_phase_closed():
    """Blank UAT + Golive Closed → không overdue (TMS.FR.84 pattern)."""
    row = _row_tms84_blank_uat()
    assert is_phase_overdue(
        row.phases["UAT"], TODAY,
        row=row, phase_name="UAT", phase_order=PHASE_ORDER,
    ) is False
    assert row_has_overdue(row, TODAY, PHASE_ORDER) is False


def test_explicit_in_progress_still_overdue_even_if_later_closed():
    """Status In-progress không bị miễn dù Golive Closed (data lệch)."""
    row = _row_tms84_blank_uat()
    row.phases["UAT"].status = "In-progress"
    assert is_phase_overdue(
        row.phases["UAT"], TODAY,
        row=row, phase_name="UAT", phase_order=PHASE_ORDER,
    ) is True


def test_dashboard_engine_excludes_tms84_false_positive():
    """DashboardEngine.overdue_list không chứa TMS.FR.84 blank+Golive Closed."""
    row = _row_tms84_blank_uat()
    # Thêm 1 overdue thật để chắc engine vẫn đếm đúng
    real = FunctionRow(
        row_num=3,
        meta={"ma_cn": "TMS.FR.99", "module": "TMS"},
        phases={
            "Analysis": _pd(-20, "In-progress", ["A"]),
            "UAT": _pd(None, None),
            "Golive": _pd(None, None),
        },
    )
    data = ParsedData(
        headers={},
        meta_columns={},
        phase_groups=[PhaseGroup(name=n) for n in PHASE_ORDER],
        rows=[row, real],
        all_modules=["APP", "TMS"],
        all_phases=PHASE_ORDER,
    )
    metrics = DashboardEngine(today=TODAY).compute_all(data)
    ma_list = [i["ma_cn"] for i in metrics["overdue_list"]]
    assert "TMS.FR.84" not in ma_list
    assert "TMS.FR.99" in ma_list
    assert metrics["summary"]["total_overdue"] == 1


def test_parse_sync_1311_tms84_not_overdue_after_fix():
    """Reproduce: synced_20260730_1311.xlsx — UAT status blank, Golive Closed."""
    path = Path("uploads/projects/mphg/synced_20260730_1311.xlsx")
    if not path.exists():
        pytest.skip("MPHG sync fixture không có trong workspace")
    data = FunctionListParser().parse(str(path))
    row = next(r for r in data.rows if r.meta.get("ma_cn") == "TMS.FR.84")
    uat = row.phases["UAT"]
    assert uat.status is None
    assert uat.end_date == date(2026, 4, 8)
    assert row.phases["Golive"].status == "Closed"
    assert row.meta.get("module") == "APP"

    eng = DashboardEngine(today=TODAY)
    assert eng._is_overdue(uat, row, "UAT", data.all_phases) is False
    ov = [i for i in eng._overdue_list(data) if i["ma_cn"] == "TMS.FR.84"]
    assert ov == []


def test_normalize_in_progress_alias():
    """API/Excel 'In Progress' (space) map về 'In-progress'."""
    p = FunctionListParser()
    assert p._normalize_status("In Progress") == "In-progress"
    assert p._normalize_status("in_progress") == "In-progress"
    assert p._normalize_status("closed") == "Closed"
