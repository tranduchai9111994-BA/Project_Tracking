"""Tests cho analyzer.drill_down — pure function level."""
import pytest
from datetime import date

from analyzer.drill_down import drill_down, build_title, SUPPORTED_CHARTS


# ==========================================================================
# Test 1: Supported charts registry
# ==========================================================================
def test_supported_charts_has_all_expected_keys():
    expected = {
        "phase_matrix", "phase_stacked", "pic_workload",
        "priority", "complexity", "fit_gap", "giai_doan",
        "module", "process",
    }
    assert expected.issubset(set(SUPPORTED_CHARTS))


def test_drill_down_raises_for_unsupported_chart(parsed_data):
    with pytest.raises(ValueError):
        drill_down(parsed_data, "unknown_chart", {})


# ==========================================================================
# Test 2: phase_matrix — module × phase
# ==========================================================================
def test_phase_matrix_returns_functions_matching_module_phase(parsed_data, today):
    # TMS × Analysis: TMS.FR.01 (Closed) + TMS.FR.02 (Closed) = 2 function
    items = drill_down(parsed_data, "phase_matrix", {"module": "TMS", "phase": "Analysis"}, today)
    assert len(items) == 2
    ma_cns = {i["ma_cn"] for i in items}
    assert ma_cns == {"TMS.FR.01", "TMS.FR.02"}
    for it in items:
        assert it["module"] == "TMS"
        assert it["phase"] == "Analysis"
        assert it["status"] == "Closed"


def test_phase_matrix_uat_overdue_flag(parsed_data, today):
    items = drill_down(parsed_data, "phase_matrix", {"module": "TMS", "phase": "UAT"}, today)
    # TMS.FR.01 UAT Closed → not overdue; TMS.FR.02 UAT In-progress end<today → overdue
    by_code = {i["ma_cn"]: i for i in items}
    assert by_code["TMS.FR.02"]["is_overdue"] is True
    assert by_code["TMS.FR.02"]["days_overdue"] > 0
    assert by_code["TMS.FR.01"]["is_overdue"] is False


def test_phase_matrix_returns_empty_for_wrong_module(parsed_data, today):
    items = drill_down(parsed_data, "phase_matrix", {"module": "XXX", "phase": "Analysis"}, today)
    assert items == []


# ==========================================================================
# Test 3: phase_stacked — phase × status
# ==========================================================================
def test_phase_stacked_filter_status_closed(parsed_data, today):
    items = drill_down(parsed_data, "phase_stacked", {"phase": "Analysis", "status": "Closed"}, today)
    # rows 1-4: Closed; row5: Assigned; row6: In-progress → 4 Closed
    assert len(items) == 4
    for it in items:
        assert it["phase"] == "Analysis"
        assert it["status"] == "Closed"


def test_phase_stacked_filter_in_progress(parsed_data, today):
    items = drill_down(parsed_data, "phase_stacked", {"phase": "Analysis", "status": "In-progress"}, today)
    assert len(items) == 1
    assert items[0]["ma_cn"] == "ESS.FR.10"


# ==========================================================================
# Test 4: pic_workload — pic ± status
# ==========================================================================
def test_pic_workload_all_of_a_pic(parsed_data, today):
    # SonHN6 xuất hiện ở Analysis của TMS.FR.01 + TMS.FR.02 + ESS.FR.10 (case-insensitive normalize)
    items = drill_down(parsed_data, "pic_workload", {"pic": "SonHN6"}, today)
    assert len(items) >= 3
    ma_cns = {i["ma_cn"] for i in items}
    assert {"TMS.FR.01", "TMS.FR.02", "ESS.FR.10"}.issubset(ma_cns)


def test_pic_workload_filter_overdue_only(parsed_data, today):
    # SonHN6 chỉ overdue ở ESS.FR.10 Analysis (end < today, status In-progress)
    items = drill_down(parsed_data, "pic_workload", {"pic": "SonHN6", "status": "overdue"}, today)
    assert len(items) == 1
    assert items[0]["ma_cn"] == "ESS.FR.10"
    assert items[0]["is_overdue"] is True


def test_pic_workload_filter_status_closed(parsed_data, today):
    items = drill_down(parsed_data, "pic_workload", {"pic": "SonHN6", "status": "Closed"}, today)
    ma_cns = {i["ma_cn"] for i in items}
    # SonHN6 Closed ở Analysis của TMS.FR.01 + TMS.FR.02, không có ESS.FR.10
    assert "ESS.FR.10" not in ma_cns


# ==========================================================================
# Test 5: priority / complexity / fit_gap
# ==========================================================================
def test_priority_filter(parsed_data, today):
    items = drill_down(parsed_data, "priority", {"priority": "Must-have"}, today)
    # 3 Must-have: TMS.FR.01, TMS.FR.02, ESS.FR.10
    assert len(items) == 3
    assert all(i["priority"] == "Must-have" for i in items)


def test_complexity_filter(parsed_data, today):
    items = drill_down(parsed_data, "complexity", {"complexity": "High"}, today)
    assert len(items) == 3  # TMS.FR.02, PR.FR.03, SYS.FR.01
    assert all(i["complexity"] == "High" for i in items)


def test_fit_gap_filter_gap(parsed_data, today):
    items = drill_down(parsed_data, "fit_gap", {"fit_gap": "GAP"}, today)
    assert len(items) == 1
    assert items[0]["ma_cn"] == "TMS.FR.02"


def test_fit_gap_filter_with_module(parsed_data, today):
    items = drill_down(parsed_data, "fit_gap", {"module": "TMS", "fit_gap": "FIT"}, today)
    assert len(items) == 1
    assert items[0]["ma_cn"] == "TMS.FR.01"


# ==========================================================================
# Test 6: giai_doan / module / process
# ==========================================================================
def test_giai_doan_filter(parsed_data, today):
    items = drill_down(parsed_data, "giai_doan", {"giai_doan": "1"}, today)
    ma_cns = {i["ma_cn"] for i in items}
    # Giai đoạn 1: TMS.FR.01, TMS.FR.02, SYS.FR.01
    assert ma_cns == {"TMS.FR.01", "TMS.FR.02", "SYS.FR.01"}


def test_giai_doan_with_phase(parsed_data, today):
    items = drill_down(parsed_data, "giai_doan", {"giai_doan": "1", "phase": "Dev"}, today)
    assert len(items) == 3
    for it in items:
        assert it["phase"] == "Dev"


def test_module_filter(parsed_data, today):
    items = drill_down(parsed_data, "module", {"module": "TMS"}, today)
    assert len(items) == 2


def test_process_filter(parsed_data, today):
    items = drill_down(parsed_data, "process", {"process": "TMS.BP.01 - Chấm công"}, today)
    assert len(items) == 2


# ==========================================================================
# Test 7: Build title
# ==========================================================================
def test_build_title_variants():
    assert "TMS" in build_title("phase_matrix", {"module": "TMS", "phase": "Dev"})
    assert "Analysis" in build_title("phase_stacked", {"phase": "Analysis", "status": "Closed"})
    assert "SonHN6" in build_title("pic_workload", {"pic": "SonHN6", "status": "overdue"})
    assert "Overdue" in build_title("pic_workload", {"pic": "SonHN6", "status": "overdue"})
    assert "Must-have" in build_title("priority", {"priority": "Must-have"})
    assert "GAP" in build_title("fit_gap", {"fit_gap": "GAP"})
    assert "Giai đoạn" in build_title("giai_doan", {"giai_doan": "1"})


# ==========================================================================
# Test 8: Output shape đúng
# ==========================================================================
def test_output_shape_has_all_fields(parsed_data, today):
    items = drill_down(parsed_data, "priority", {"priority": "Must-have"}, today)
    assert len(items) > 0
    required_fields = {
        "ma_cn", "ten_cn", "module", "quy_trinh", "priority", "complexity",
        "fit_gap", "giai_doan", "phase", "status", "pics",
        "start_date", "end_date", "days_overdue", "is_overdue", "estimate_mh",
    }
    assert required_fields.issubset(set(items[0].keys()))


def test_pics_is_list(parsed_data, today):
    items = drill_down(parsed_data, "pic_workload", {"pic": "BaoLQ31"}, today)
    assert len(items) > 0
    for it in items:
        assert isinstance(it["pics"], list)


# ==========================================================================
# Test 9: Overdue/Unassigned dedupe theo ma_cn (fix mismatch card vs drill)
# ==========================================================================
def _make_multi_overdue_data(today):
    """3 function, mỗi function có 2-3 phase overdue → dedupe drill = 3 rows."""
    from datetime import timedelta
    from parser.excel_parser import (
        ParsedData, FunctionRow, PhaseData, PhaseGroup,
    )

    def _pd(start_off=None, end_off=None, status=None, pics=None):
        return PhaseData(
            start_date=(today + timedelta(days=start_off)) if start_off is not None else None,
            end_date=(today + timedelta(days=end_off)) if end_off is not None else None,
            status=status,
            pics=pics or [],
        )

    rows = [
        # F1: 3 phase đều overdue
        FunctionRow(row_num=2, meta={
            "ma_cn": "F1", "ten_cn": "F1", "module": "M1", "quy_trinh": "P1",
            "priority": "Must-have", "complexity": "High", "fit_gap": "FIT", "giai_doan": "1",
        }, phases={
            "Analysis": _pd(-30, -25, "In-progress", ["A"]),
            "Dev": _pd(-20, -10, "Open", ["B"]),
            "UAT": _pd(-5, -2, "Assigned", ["A", "C"]),
        }),
        # F2: 2 phase overdue + 1 phase Closed (không tính)
        FunctionRow(row_num=3, meta={
            "ma_cn": "F2", "ten_cn": "F2", "module": "M1", "quy_trinh": "P1",
            "priority": "Should-have", "complexity": "Medium", "fit_gap": "GAP", "giai_doan": "1",
        }, phases={
            "Analysis": _pd(-40, -35, "Closed", ["A"]),  # Closed → không overdue
            "Dev": _pd(-25, -20, "In-progress", ["B"]),
            "UAT": _pd(-10, -3, "Open", ["C"]),
        }),
        # F3: 2 phase overdue
        FunctionRow(row_num=4, meta={
            "ma_cn": "F3", "ten_cn": "F3", "module": "M2", "quy_trinh": "P2",
            "priority": "Could-have", "complexity": "Low", "fit_gap": "FIT", "giai_doan": "2",
        }, phases={
            "Analysis": _pd(-15, -12, "In-progress", ["D"]),
            "Dev": _pd(-8, -1, "Open", []),  # unassigned + overdue
        }),
    ]
    return ParsedData(
        headers={}, meta_columns={},
        phase_groups=[
            # PhaseGroup.task_type là computed @property, không phải field
            PhaseGroup(name="Analysis", attributes={}),
            PhaseGroup(name="Dev", attributes={}),
            PhaseGroup(name="UAT", attributes={}),
        ],
        rows=rows,
        all_modules=["M1", "M2"],
        all_phases=["Analysis", "Dev", "UAT"],
        all_pics=["A", "B", "C", "D"],
        all_statuses=["Open", "In-progress", "Assigned", "Closed"],
        all_priorities=["Must-have", "Should-have", "Could-have"],
        all_complexities=["High", "Medium", "Low"],
        all_giai_doan=["1", "2"],
    )


def test_overdue_drill_dedupes_by_function(today):
    """
    Card summary đếm distinct function; drill phải khớp count.
    3 function × 7 phase-record overdue → drill trả về 3 rows (không phải 7).
    """
    data = _make_multi_overdue_data(today)
    items = drill_down(data, "overdue", {}, today)
    # Đúng 3 function (dedupe theo ma_cn)
    assert len(items) == 3
    ma_cns = {i["ma_cn"] for i in items}
    assert ma_cns == {"F1", "F2", "F3"}


def test_overdue_drill_dedupe_aggregates_phase_list(today):
    """Row aggregate phải chứa danh sách phase trong cột `phase`."""
    data = _make_multi_overdue_data(today)
    items = {i["ma_cn"]: i for i in drill_down(data, "overdue", {}, today)}
    # F1: 3 phase overdue Analysis, Dev, UAT
    assert items["F1"]["phase_count"] == 3
    for ph in ("Analysis", "Dev", "UAT"):
        assert ph in items["F1"]["phase"]
    # F2: chỉ 2 phase overdue (Analysis Closed bị loại)
    assert items["F2"]["phase_count"] == 2
    assert "Analysis" not in items["F2"]["phase"]
    assert "Dev" in items["F2"]["phase"] and "UAT" in items["F2"]["phase"]


def test_overdue_drill_dedupe_days_overdue_is_max(today):
    """`days_overdue` = max của các phase, `end_date` = sớm nhất."""
    data = _make_multi_overdue_data(today)
    items = {i["ma_cn"]: i for i in drill_down(data, "overdue", {}, today)}
    # F1: end_off của Analysis=-25 → days=25 (max), UAT=-2 → days=2
    assert items["F1"]["days_overdue"] == 25
    # end_date sớm nhất là -30... không, đó là start; end sớm nhất là -25.
    # Datetime iso format so sánh string ổn.
    assert items["F1"]["end_date"] < items["F1"]["start_date"] or items["F1"]["end_date"]


def test_overdue_drill_dedupe_pics_are_union(today):
    """`pics` = union unique của tất cả phase."""
    data = _make_multi_overdue_data(today)
    items = {i["ma_cn"]: i for i in drill_down(data, "overdue", {}, today)}
    # F1: PIC ở Analysis=[A], Dev=[B], UAT=[A,C] → union = {A,B,C}
    assert set(items["F1"]["pics"]) == {"A", "B", "C"}


def test_overdue_drill_dedupe_sorted_by_days_overdue_desc(today):
    """Sau dedupe vẫn sort theo days_overdue giảm dần."""
    data = _make_multi_overdue_data(today)
    items = drill_down(data, "overdue", {}, today)
    days = [i["days_overdue"] for i in items]
    assert days == sorted(days, reverse=True)


def test_overdue_drill_count_matches_row_has_overdue(today):
    """
    Nhất quán với dashboard_engine._row_has_overdue: card summary = count
    distinct function có bất kỳ phase overdue nào = drill count.
    """
    from analyzer.dashboard_engine import DashboardEngine

    data = _make_multi_overdue_data(today)
    engine = DashboardEngine(today=today)
    summary = engine._summary(data)
    drill_items = drill_down(data, "overdue", {}, today)
    assert summary["total_overdue"] == len(drill_items)


def test_unassigned_drill_dedupes_by_function(today):
    """Same dedupe logic cho drill 'unassigned'."""
    data = _make_multi_overdue_data(today)
    # F3.Dev: status="Open" + no PIC → unassigned
    items = drill_down(data, "unassigned", {}, today)
    ma_cns = {i["ma_cn"] for i in items}
    # F3 phải xuất hiện, mỗi function chỉ 1 lần
    assert "F3" in ma_cns
    # Không có duplicate ma_cn
    assert len(items) == len(ma_cns)


def test_unassigned_drill_count_matches_summary(today):
    """Card unassigned = drill unassigned (distinct function)."""
    from analyzer.dashboard_engine import DashboardEngine

    data = _make_multi_overdue_data(today)
    engine = DashboardEngine(today=today)
    summary = engine._summary(data)
    drill_items = drill_down(data, "unassigned", {}, today)
    assert summary["unassigned_count"] == len(drill_items)
