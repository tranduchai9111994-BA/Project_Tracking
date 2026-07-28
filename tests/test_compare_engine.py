"""Tests cho analyzer.compare_engine."""
import copy
from datetime import date

import pytest

from analyzer.compare_engine import CompareEngine
from parser.excel_parser import PhaseData


def test_self_compare_has_zero_delta(parsed_data):
    """So sánh file với chính nó → không có change."""
    result = CompareEngine().compare(
        parsed_data, parsed_data,
        old_date="2026-07-01", new_date="2026-07-28",
    )
    assert result["delta_total"] == 0
    assert result["delta_pct"] == 0.0
    assert len(result["new_functions"]) == 0
    assert len(result["removed_functions"]) == 0
    assert len(result["status_changes"]) == 0


def test_detect_new_function(parsed_data):
    """Function bổ sung phải detect được."""
    from parser.excel_parser import FunctionRow

    new_data = copy.deepcopy(parsed_data)
    new_row = FunctionRow(
        row_num=100,
        meta={"stt": 100, "ma_cn": "NEW.FR.01", "ten_cn": "Function mới", "module": "APP"},
        phases={},
    )
    new_data.rows.append(new_row)

    result = CompareEngine().compare(
        parsed_data, new_data,
        old_date="2026-07-01", new_date="2026-07-28",
    )
    assert len(result["new_functions"]) == 1
    assert result["new_functions"][0]["ma_cn"] == "NEW.FR.01"
    assert result["delta_total"] == 1


def test_detect_removed_function(parsed_data):
    """Function bị xóa phải detect được."""
    old_data = copy.deepcopy(parsed_data)
    new_data = copy.deepcopy(parsed_data)
    removed = new_data.rows.pop(0)  # remove first row

    result = CompareEngine().compare(
        old_data, new_data,
        old_date="2026-07-01", new_date="2026-07-28",
    )
    assert len(result["removed_functions"]) == 1
    assert result["removed_functions"][0]["ma_cn"] == removed.meta.get("ma_cn")


def test_detect_status_change_forward(parsed_data):
    """Chuyển từ In-progress → Closed = forward."""
    old_data = copy.deepcopy(parsed_data)
    new_data = copy.deepcopy(parsed_data)

    # Row TMS.FR.02 UAT: In-progress → Closed
    for r in new_data.rows:
        if r.meta.get("ma_cn") == "TMS.FR.02":
            r.phases["UAT"] = PhaseData(
                start_date=r.phases["UAT"].start_date,
                end_date=r.phases["UAT"].end_date,
                status="Closed",
                pics=r.phases["UAT"].pics,
                estimate_mh=r.phases["UAT"].estimate_mh,
            )
            break

    result = CompareEngine().compare(
        old_data, new_data,
        old_date="2026-07-01", new_date="2026-07-28",
    )
    forwards = [sc for sc in result["status_changes"] if sc["direction"] == "forward"]
    assert len(forwards) >= 1
    tms02_uat = [sc for sc in forwards
                 if sc["ma_cn"] == "TMS.FR.02" and sc["phase"] == "UAT"]
    assert len(tms02_uat) == 1
    assert tms02_uat[0]["old_status"] == "In-progress"
    assert tms02_uat[0]["new_status"] == "Closed"


def test_detect_status_change_backward(parsed_data):
    """Chuyển Closed → In-progress = backward."""
    old_data = copy.deepcopy(parsed_data)
    new_data = copy.deepcopy(parsed_data)

    for r in new_data.rows:
        if r.meta.get("ma_cn") == "TMS.FR.01":
            r.phases["Analysis"] = PhaseData(
                start_date=r.phases["Analysis"].start_date,
                end_date=r.phases["Analysis"].end_date,
                status="In-progress",
                pics=r.phases["Analysis"].pics,
            )
            break

    result = CompareEngine().compare(
        old_data, new_data,
        old_date="2026-07-01", new_date="2026-07-28",
    )
    backwards = [sc for sc in result["status_changes"] if sc["direction"] == "backward"]
    assert len(backwards) >= 1


def test_velocity_calculated(parsed_data):
    """Velocity metrics được tính khi 2 date hợp lệ."""
    old_data = copy.deepcopy(parsed_data)
    new_data = copy.deepcopy(parsed_data)

    for r in new_data.rows:
        if r.meta.get("ma_cn") == "TMS.FR.02":
            r.phases["UAT"] = PhaseData(
                start_date=r.phases["UAT"].start_date,
                end_date=r.phases["UAT"].end_date,
                status="Closed",
                pics=r.phases["UAT"].pics,
            )

    result = CompareEngine().compare(
        old_data, new_data,
        old_date="2026-07-01", new_date="2026-07-28",
    )
    vel = result["velocity"]
    assert vel["days_between"] == 27
    assert vel["functions_closed"] >= 1
    assert vel["close_rate_per_day"] is not None


def test_module_deltas_include_all_modules(parsed_data):
    """module_deltas cover tất cả module."""
    result = CompareEngine().compare(
        parsed_data, parsed_data,
        old_date="2026-07-01", new_date="2026-07-28",
    )
    modules_in_data = set(parsed_data.all_modules)
    modules_in_deltas = set(result["module_deltas"].keys())
    assert modules_in_data <= modules_in_deltas


def test_fallback_matching_by_ten_module(parsed_data):
    """
    Nếu Mã CN đổi nhưng Tên + Module giống → match qua fallback.
    Không được count vào new_functions/removed_functions.
    """
    old_data = copy.deepcopy(parsed_data)
    new_data = copy.deepcopy(parsed_data)

    # Đổi Mã CN của 1 row
    new_data.rows[0].meta["ma_cn"] = "CHANGED.FR.01"

    result = CompareEngine().compare(
        old_data, new_data,
        old_date="2026-07-01", new_date="2026-07-28",
    )
    # Không nên là "removed" hay "new"
    assert not any(f["ma_cn"] == "CHANGED.FR.01" for f in result["new_functions"])
    original_ma = parsed_data.rows[0].meta["ma_cn"]
    assert not any(f["ma_cn"] == original_ma for f in result["removed_functions"])
