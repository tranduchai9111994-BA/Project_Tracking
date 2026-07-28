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
