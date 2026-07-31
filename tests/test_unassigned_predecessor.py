"""Tests cho rule Unassigned: chỉ bắt PIC khi phase trước Closed."""
from datetime import date, timedelta

import pytest

from analyzer.dashboard_engine import DashboardEngine
from analyzer.unassigned import (
    is_predecessor_closed,
    is_unassigned_phase,
)
from parser.excel_parser import FunctionRow, PhaseData, PhaseGroup, ParsedData


TODAY = date(2026, 7, 31)
ORDER = ["Analysis", "Dev", "Config Local", "Config UAT", "Document", "Config Prod"]


def _pd(status=None, pics=None, *, start_off=None, end_off=None) -> PhaseData:
    return PhaseData(
        start_date=(TODAY + timedelta(days=start_off)) if start_off is not None else None,
        end_date=(TODAY + timedelta(days=end_off)) if end_off is not None else None,
        status=status,
        pics=list(pics or []),
    )


def _row(phases: dict[str, PhaseData], ma_cn: str = "X.01") -> FunctionRow:
    return FunctionRow(
        row_num=2,
        meta={"ma_cn": ma_cn, "ten_cn": ma_cn, "module": "M", "priority": "Must-have"},
        phases=phases,
    )


def _parsed(rows: list[FunctionRow], order: list[str] | None = None) -> ParsedData:
    order = order or ORDER
    return ParsedData(
        headers={},
        meta_columns={},
        phase_groups=[PhaseGroup(name=n, attributes={}) for n in order],
        rows=rows,
        all_modules=["M"],
        all_phases=order,
        all_pics=[],
        all_statuses=["Open", "In-progress", "Closed"],
    )


def test_analysis_closed_dev_no_pic_flags():
    """Analysis Closed + Dev no PIC → flag."""
    row = _row({
        "Analysis": _pd("Closed", ["A"], end_off=-10),
        "Dev": _pd("Open", []),
    })
    assert is_unassigned_phase(row, "Dev", row.phases["Dev"], ORDER) is True


def test_analysis_not_closed_dev_no_pic_no_flag():
    """Analysis chưa Closed + Dev no PIC → không flag."""
    row = _row({
        "Analysis": _pd("In-progress", ["A"], end_off=5),
        "Dev": _pd("Open", []),
    })
    assert is_unassigned_phase(row, "Dev", row.phases["Dev"], ORDER) is False

    row2 = _row({
        "Analysis": _pd("In-progress", ["A"]),
        "Dev": _pd(None, [], end_off=3),  # có End nhưng Analysis chưa xong
    })
    assert is_unassigned_phase(row2, "Dev", row2.phases["Dev"], ORDER) is False


def test_dev_closed_config_no_pic_flags():
    """Dev Closed + Config Local no PIC → flag."""
    row = _row({
        "Analysis": _pd("Closed", ["A"]),
        "Dev": _pd("Closed", ["B"]),
        "Config Local": _pd("Open", []),
    })
    assert is_unassigned_phase(
        row, "Config Local", row.phases["Config Local"], ORDER,
    ) is True


def test_dev_not_closed_config_no_pic_no_flag():
    """Dev chưa Closed + Config no PIC → không flag."""
    row = _row({
        "Analysis": _pd("Closed", ["A"]),
        "Dev": _pd("In-progress", ["B"]),
        "Config Local": _pd(None, [], end_off=10),
    })
    assert is_unassigned_phase(
        row, "Config Local", row.phases["Config Local"], ORDER,
    ) is False


def test_first_phase_in_scope_no_pic_flags():
    """Phase đầu (Analysis) in-scope thiếu PIC → flag."""
    row = _row({
        "Analysis": _pd("Open", []),
        "Dev": _pd(None, []),
    })
    assert is_unassigned_phase(row, "Analysis", row.phases["Analysis"], ORDER) is True


def test_first_phase_blank_no_flag():
    """Phase đầu hoàn toàn blank → không flag."""
    row = _row({
        "Analysis": _pd(None, []),
        "Dev": _pd(None, []),
    })
    assert is_unassigned_phase(row, "Analysis", row.phases["Analysis"], ORDER) is False


def test_predecessor_cancelled_does_not_unlock():
    """Cancelled ≠ Closed → không unlock phase sau."""
    row = _row({
        "Analysis": _pd("Cancelled", ["A"]),
        "Dev": _pd("Open", []),
    })
    assert is_predecessor_closed(row, "Dev", ORDER) is False
    assert is_unassigned_phase(row, "Dev", row.phases["Dev"], ORDER) is False


def test_engine_summary_and_list_match_gate():
    """DashboardEngine summary/list chỉ giữ case Analysis Closed + Dev no PIC."""
    data = _parsed([
        _row({
            "Analysis": _pd("Closed", ["A"]),
            "Dev": _pd("Open", []),
        }, ma_cn="OK.01"),
        _row({
            "Analysis": _pd("In-progress", ["A"]),
            "Dev": _pd("Open", []),
        }, ma_cn="SKIP.01"),
        _row({
            "Analysis": _pd("Closed", ["A"]),
            "Dev": _pd("Closed", ["B"]),
            "Config Local": _pd("Assigned", []),
        }, ma_cn="CFG.01"),
        _row({
            "Analysis": _pd("Closed", ["A"]),
            "Dev": _pd("In-progress", ["B"]),
            "Config Local": _pd(None, [], end_off=2),
        }, ma_cn="CFG.SKIP"),
    ])
    m = DashboardEngine(today=TODAY).compute_all(data)
    phases = {(i["ma_cn"], i["phase"]) for i in m["unassigned_tasks"]}
    assert ("OK.01", "Dev") in phases
    assert ("CFG.01", "Config Local") in phases
    assert ("SKIP.01", "Dev") not in phases
    assert ("CFG.SKIP", "Config Local") not in phases
    assert m["summary"]["unassigned_count"] == 2
    assert m["summary"]["unassigned_records"] == 2
