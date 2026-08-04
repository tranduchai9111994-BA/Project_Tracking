"""Tests Forecast Manpower."""
from __future__ import annotations

from datetime import date

from parser.excel_parser import ParsedData, PhaseData, PhaseGroup, FunctionRow
from analyzer.forecast_manpower import (
    DEFAULT_MH,
    compute_forecast_manpower,
    months_until,
    suggest_target_months,
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


def test_months_until_golive_dec_2026():
    """Aug 1 → Dec 1 2026 ≈ 4 tháng (không phải 1)."""
    today = date(2026, 8, 1)
    assert months_until(today, date(2026, 12, 1)) == 4.0
    # Đã qua hạn → tối thiểu 0.25
    assert months_until(today, date(2026, 7, 1)) == 0.25


def test_suggest_target_months_from_golive():
    """Phase tên map → Cấu hình Golive, End 12/2026 → ~4.5 tháng."""
    today = date(2026, 8, 1)
    # Tên phase khớp TASK_TYPE_RULES → "Cấu hình Golive"
    rows = [
        _row("G1", {
            "Config Golive": PhaseData(
                status="Open",
                end_date=date(2026, 12, 15),
                estimate_mh=8,
            ),
            "Dev": PhaseData(
                status="Open",
                end_date=date(2026, 9, 1),
                estimate_mh=16,
            ),
        }),
    ]
    groups = [
        PhaseGroup(name="Config Golive", attributes={}),
        PhaseGroup(name="Dev", attributes={}),
    ]
    data = ParsedData(
        headers={},
        meta_columns={},
        rows=rows,
        phase_groups=groups,
        all_phases=["Config Golive", "Dev"],
        all_modules=["PR"],
    )
    assert groups[0].task_type == "Cấu hình Golive"
    sug = suggest_target_months(data, today=today)
    assert sug["source"] == "golive"
    assert sug["months"] == 4.5  # 4 + (15-1)/30 → 4.47 → 4.5
    assert "Golive" in sug["source_label"]

    # auto_target: hire giảm mạnh vs target=1 (31 MM / 4 tháng ≈ 8)
    rem_mh = 31 * 160
    rows3 = [
        _row("X1", {
            "Config Golive": PhaseData(
                status="Open", estimate_mh=8, end_date=date(2026, 12, 1)
            ),
            "Dev": PhaseData(status="Open", estimate_mh=rem_mh),
        }),
    ]
    groups3 = [
        PhaseGroup(name="Config Golive", attributes={}),
        PhaseGroup(name="Dev", attributes={}),
    ]
    data3 = ParsedData(
        headers={},
        meta_columns={},
        rows=rows3,
        phase_groups=groups3,
        all_phases=["Config Golive", "Dev"],
        all_modules=["PR"],
    )
    auto = compute_forecast_manpower(
        data3, target_months=None, auto_target=True, today=today, display_unit="manmonth"
    )
    forced1 = compute_forecast_manpower(
        data3, target_months=1.0, today=today, display_unit="manmonth"
    )
    assert auto["target_months"] == 4.0
    assert auto["target_months_meta"]["overridden"] is False
    assert "Golive" in auto["target_months_meta"]["source_label"]
    # Dev pool: 31 MM remaining → hire
    pools_auto = {p["stage_id"]: p for p in auto["pools"]}
    pools_1 = {p["stage_id"]: p for p in forced1["pools"]}
    hire_auto = pools_auto["dev"]["hire_needed"]
    hire_1 = pools_1["dev"]["hire_needed"]
    assert hire_auto == 8
    assert hire_1 == 31
    assert hire_auto < hire_1


def test_suggest_fallback_max_open_end():
    today = date(2026, 8, 1)
    rows = [
        _row("A1", {
            "Analysis": PhaseData(status="Open", end_date=date(2026, 11, 1), estimate_mh=8),
        }),
    ]
    data = _data(rows, [("Analysis", "Phân tích")])
    sug = suggest_target_months(data, today=today)
    assert sug["source"] in ("max_open_end", "golive")
    assert sug["months"] == 3.0
