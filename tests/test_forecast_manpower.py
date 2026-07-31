"""Tests Forecast Manpower."""
from __future__ import annotations

from datetime import date

from parser.excel_parser import ParsedData, PhaseData, PhaseGroup, FunctionRow
from analyzer.forecast_manpower import (
    DEFAULT_MH,
    compute_forecast_manpower,
    _phase_mh,
)


def _row(ma: str, phases: dict, row_num: int = 2) -> FunctionRow:
    return FunctionRow(
        row_num=row_num,
        meta={"ma_cn": ma, "ten_cn": ma, "module": "PR"},
        phases=phases,
    )


def _data(rows, phase_names_types: list[tuple[str, str]]) -> ParsedData:
    groups = [PhaseGroup(name=name, attributes={}) for name, _tt in phase_names_types]
    all_phases = [n for n, _ in phase_names_types]
    return ParsedData(
        headers={},
        meta_columns={},
        rows=rows,
        phase_groups=groups,
        all_phases=all_phases,
        all_modules=["PR"],
    )


def test_default_mh_when_blank():
    pd = PhaseData(status="Open")
    mh, note, used = _phase_mh(pd, "unit")
    assert mh == DEFAULT_MH
    assert used is True
    assert "mặc định" in note.lower() or "mac dinh" in note.lower() or "mặc định" in note


def test_unit_uses_estimate():
    pd = PhaseData(status="Open", estimate_mh=16)
    mh, note, used = _phase_mh(pd, "unit")
    assert mh == 16
    assert used is False


def test_duration_working_days():
    # Mon 2026-07-27 → Fri 2026-07-31 = 5 days → 40 MH
    pd = PhaseData(
        status="Open",
        start_date=date(2026, 7, 27),
        end_date=date(2026, 7, 31),
    )
    mh, note, used = _phase_mh(pd, "duration")
    assert mh == 40
    assert used is False
    assert "Duration" in note


def test_compute_pools_and_hire():
    rows = [
        _row("A1", {
            "Analysis": PhaseData(status="Open", estimate_mh=8),
            "Dev": PhaseData(status="Open", estimate_mh=16),
            "UAT": PhaseData(status="Closed", estimate_mh=8),
        }),
        _row("A2", {
            "Analysis": PhaseData(status="Open"),  # default 8
            "Dev": PhaseData(status="Open", estimate_mh=8),
        }),
    ]
    data = _data(rows, [("Analysis", "Phân tích"), ("Dev", "Lập trình"), ("UAT", "UAT")])
    result = compute_forecast_manpower(
        data,
        basis="unit",
        display_unit="manhour",
        target_months=1.0,
        headcount={"dev": 1, "impl_shared": 0},
    )
    assert result["totals"]["mh_remaining"] > 0
    pools = {p["stage_id"]: p for p in result["pools"]}
    assert pools["dev"]["mh_remaining"] == 24  # 16+8
    # Analysis open: 8+8=16 remaining in impl (UAT closed not in remaining)
    assert pools["impl_shared"]["mh_remaining"] == 16
    assert pools["dev"]["hire_needed"] >= 0
    assert any(d["used_default"] for d in result["detail"])


def test_display_manday_manmonth():
    rows = [_row("B1", {"Dev": PhaseData(status="Open", estimate_mh=160)})]
    data = _data(rows, [("Dev", "Lập trình")])
    r = compute_forecast_manpower(data, display_unit="manmonth", target_months=1)
    assert r["totals"]["display_remaining"] == 1.0
    r2 = compute_forecast_manpower(data, display_unit="manday")
    assert r2["totals"]["display_remaining"] == 20.0
