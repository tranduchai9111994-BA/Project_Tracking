"""Tests cho global filter (module + quy trình) trên /dashboard endpoint."""
import io


def _upload(client, path):
    with open(path, "rb") as f:
        return client.post(
            "/api/projects/default/upload",
            data={"file": (io.BytesIO(f.read()), "sample.xlsx")},
            content_type="multipart/form-data",
        )


# ==========================================================================
# ParsedData exposes all_processes
# ==========================================================================
def test_parsed_data_has_all_processes(parsed_data):
    assert hasattr(parsed_data, "all_processes")
    assert isinstance(parsed_data.all_processes, list)
    # 6 rows với 6 quy trình khác nhau (TMS.BP.01 xuất hiện 2 lần)
    assert "TMS.BP.01 - Chấm công" in parsed_data.all_processes
    assert "HR.BP.02 - Onboarding" in parsed_data.all_processes


def test_structure_info_includes_all_processes(metrics):
    assert "all_processes" in metrics["structure"]
    assert len(metrics["structure"]["all_processes"]) > 0


# ==========================================================================
# Cascade: structure info phải expose processes_by_module cho FE
# ==========================================================================
def test_structure_info_includes_processes_by_module(metrics):
    """FE dùng map này để cascade dropdown Quy trình theo Module."""
    assert "processes_by_module" in metrics["structure"]
    pbm = metrics["structure"]["processes_by_module"]
    assert isinstance(pbm, dict)
    # Fixture có 2 rows module TMS đều dùng "TMS.BP.01 - Chấm công"
    assert "TMS" in pbm
    assert pbm["TMS"] == ["TMS.BP.01 - Chấm công"]
    # HR có 1 row với "HR.BP.02 - Onboarding"
    assert "HR" in pbm
    assert pbm["HR"] == ["HR.BP.02 - Onboarding"]
    # Không có "None" hoặc module rỗng
    assert "" not in pbm
    assert None not in pbm


def test_processes_by_module_dedupes_processes(metrics):
    """2 row TMS cùng quy trình → chỉ xuất hiện 1 lần trong list."""
    pbm = metrics["structure"]["processes_by_module"]
    assert len(pbm["TMS"]) == 1


def test_processes_by_module_sorted(metrics):
    """Danh sách quy trình phải sort để UI dropdown ổn định."""
    pbm = metrics["structure"]["processes_by_module"]
    for module, procs in pbm.items():
        assert procs == sorted(procs), f"Module {module} chưa sort: {procs}"


# ==========================================================================
# _filter_parsed_data helper
# ==========================================================================
def test_filter_helper_by_module(parsed_data):
    from app import _filter_parsed_data
    filtered = _filter_parsed_data(parsed_data, module="TMS")
    assert len(filtered.rows) == 2  # TMS.FR.01 + TMS.FR.02
    assert all(r.meta.get("module") == "TMS" for r in filtered.rows)
    # all_modules subset
    assert filtered.all_modules == ["TMS"]


def test_filter_helper_by_process(parsed_data):
    from app import _filter_parsed_data
    filtered = _filter_parsed_data(parsed_data, process="TMS.BP.01 - Chấm công")
    assert len(filtered.rows) == 2
    assert all(r.meta.get("quy_trinh") == "TMS.BP.01 - Chấm công" for r in filtered.rows)


def test_filter_helper_both(parsed_data):
    from app import _filter_parsed_data
    filtered = _filter_parsed_data(parsed_data, module="HR", process="HR.BP.02 - Onboarding")
    assert len(filtered.rows) == 1
    assert filtered.rows[0].meta.get("ma_cn") == "HR.FR.05"


def test_filter_helper_empty_returns_same_object(parsed_data):
    from app import _filter_parsed_data
    filtered = _filter_parsed_data(parsed_data, module="", process="")
    assert filtered is parsed_data  # short-circuit


def test_filter_helper_preserves_phase_structure(parsed_data):
    from app import _filter_parsed_data
    filtered = _filter_parsed_data(parsed_data, module="TMS")
    # Phase structure phải giữ nguyên để chart phase matrix hoạt động
    assert filtered.all_phases == parsed_data.all_phases


# ==========================================================================
# /api/projects/<slug>/dashboard?module=&process=
# ==========================================================================
def test_dashboard_no_filter(flask_client, sample_xlsx_path):
    _upload(flask_client, sample_xlsx_path)
    r = flask_client.get("/api/projects/default/dashboard")
    assert r.status_code == 200
    data = r.get_json()
    assert data["applied_filter"] is None
    assert data["metrics"]["summary"]["total_functions"] == 6


def test_dashboard_filter_by_module(flask_client, sample_xlsx_path):
    _upload(flask_client, sample_xlsx_path)
    r = flask_client.get("/api/projects/default/dashboard?module=TMS")
    assert r.status_code == 200
    data = r.get_json()
    assert data["applied_filter"] is not None
    # Wave 2: applied_filter dùng list (modules/processes/pics)
    assert data["applied_filter"]["modules"] == ["TMS"]
    assert data["applied_filter"]["processes"] == []
    assert data["applied_filter"]["pics"] == []
    assert data["applied_filter"]["row_count"] == 2
    # Summary + metrics phải reflect subset
    assert data["metrics"]["summary"]["total_functions"] == 2
    # Module overview chỉ có TMS
    modules_in_overview = [m["module"] for m in data["metrics"]["module_overview"]]
    assert modules_in_overview == ["TMS"]


def test_dashboard_filter_by_process(flask_client, sample_xlsx_path):
    _upload(flask_client, sample_xlsx_path)
    r = flask_client.get(
        "/api/projects/default/dashboard?process=TMS.BP.01 - Chấm công"
    )
    assert r.status_code == 200
    data = r.get_json()
    assert data["applied_filter"]["processes"] == ["TMS.BP.01 - Chấm công"]
    assert data["applied_filter"]["row_count"] == 2
    assert data["metrics"]["summary"]["total_functions"] == 2


def test_dashboard_filter_module_and_process(flask_client, sample_xlsx_path):
    _upload(flask_client, sample_xlsx_path)
    r = flask_client.get(
        "/api/projects/default/dashboard?module=HR&process=HR.BP.02 - Onboarding"
    )
    assert r.status_code == 200
    data = r.get_json()
    assert data["applied_filter"]["modules"] == ["HR"]
    assert data["applied_filter"]["processes"] == ["HR.BP.02 - Onboarding"]
    assert data["applied_filter"]["row_count"] == 1
    assert data["metrics"]["summary"]["total_functions"] == 1


def test_dashboard_filter_no_match_returns_zero(flask_client, sample_xlsx_path):
    _upload(flask_client, sample_xlsx_path)
    r = flask_client.get("/api/projects/default/dashboard?module=NON_EXIST")
    assert r.status_code == 200
    data = r.get_json()
    assert data["applied_filter"]["row_count"] == 0
    assert data["metrics"]["summary"]["total_functions"] == 0


def test_dashboard_all_processes_in_structure(flask_client, sample_xlsx_path):
    _upload(flask_client, sample_xlsx_path)
    r = flask_client.get("/api/projects/default/dashboard")
    data = r.get_json()
    procs = data["metrics"]["structure"]["all_processes"]
    assert len(procs) >= 5  # 6 rows với 6 quy trình gần như unique


# ==========================================================================
# Regression tests cho bug "charts trống trắng" khi filter incompatible
# ==========================================================================
def test_dashboard_incompatible_filter_returns_empty_but_no_error(
    flask_client, sample_xlsx_path
):
    """
    Bug root cause: user chọn Module=TMS + Quy trình=HR.BP.02 (không thuộc TMS)
    → backend trả row_count=0 → mọi chart empty. Trước fix cascade, user có
    thể tự tạo ra combination này. Test đảm bảo endpoint xử lý gracefully.
    """
    _upload(flask_client, sample_xlsx_path)
    r = flask_client.get(
        "/api/projects/default/dashboard?module=TMS&process=HR.BP.02 - Onboarding"
    )
    assert r.status_code == 200
    data = r.get_json()
    assert data["applied_filter"]["row_count"] == 0
    m = data["metrics"]
    # Các block phải tồn tại (không crash) — kể cả khi rỗng
    assert m["summary"]["total_functions"] == 0
    assert m["pic_workload"] == []
    assert m["priority_breakdown"] == {}
    assert m["complexity_breakdown"] == {}
    assert m["fit_gap_analysis"] == {}
    # phase_progress_stacked vẫn có structure phases (từ data gốc)
    assert m["phase_progress_stacked"]["phases"]
    # module_overview có thể rỗng
    assert m["module_overview"] == []


def test_dashboard_filter_module_pic_workload_not_empty(
    flask_client, sample_xlsx_path
):
    """Khi filter đúng module → pic_workload phải có data (không empty)."""
    _upload(flask_client, sample_xlsx_path)
    r = flask_client.get("/api/projects/default/dashboard?module=TMS")
    data = r.get_json()
    m = data["metrics"]
    # TMS có 2 row với nhiều PIC → pic_workload phải có ≥ 1 pic
    assert len(m["pic_workload"]) > 0
    # priority + complexity không được empty
    assert m["priority_breakdown"]  # dict non-empty
    assert m["complexity_breakdown"]
    # fit_gap_analysis phải có key module TMS
    assert "TMS" in m["fit_gap_analysis"]


def test_dashboard_filter_processes_by_module_subset(
    flask_client, sample_xlsx_path
):
    """
    Sau khi filter module=TMS, processes_by_module trong structure
    subset chỉ còn TMS (dùng để FE re-cascade nếu cần).
    """
    _upload(flask_client, sample_xlsx_path)
    r = flask_client.get("/api/projects/default/dashboard?module=TMS")
    data = r.get_json()
    pbm = data["metrics"]["structure"]["processes_by_module"]
    # Filter subset chỉ chứa module TMS
    assert list(pbm.keys()) == ["TMS"]
    assert pbm["TMS"] == ["TMS.BP.01 - Chấm công"]


# ==========================================================================
# Wave 2: Multi-select filter (module / process / pic)
# ==========================================================================

def test_filter_helper_multi_modules(parsed_data):
    """OR trong 1 chiều: modules=[TMS,HR] → row của cả TMS và HR."""
    from app import _filter_parsed_data
    filtered = _filter_parsed_data(parsed_data, modules=["TMS", "HR"])
    # TMS có 2 row + HR có 1 row = 3
    assert len(filtered.rows) == 3
    mods = {r.meta.get("module") for r in filtered.rows}
    assert mods == {"TMS", "HR"}


def test_filter_helper_multi_modules_and_processes_intersect(parsed_data):
    """
    AND giữa các chiều: modules=[TMS,HR] AND processes=[HR.BP.02 - Onboarding]
    → chỉ còn row HR.BP.02 (thuộc HR + đúng quy trình).
    """
    from app import _filter_parsed_data
    filtered = _filter_parsed_data(
        parsed_data,
        modules=["TMS", "HR"],
        processes=["HR.BP.02 - Onboarding"],
    )
    assert len(filtered.rows) == 1
    assert filtered.rows[0].meta.get("module") == "HR"


def test_filter_helper_by_pic_single(parsed_data):
    """PIC filter: match nếu bất kỳ phase nào chứa PIC.
    Parser normalize case → 'SONHN6' và 'SonHN6' được coi cùng 1 người.
    """
    from app import _filter_parsed_data
    # SonHN6 xuất hiện ở TMS.FR.01, TMS.FR.02, và ESS.FR.10 (case đã normalize)
    filtered = _filter_parsed_data(parsed_data, pics=["SonHN6"])
    codes = {r.meta.get("ma_cn") for r in filtered.rows}
    assert "TMS.FR.01" in codes
    assert "TMS.FR.02" in codes
    assert "ESS.FR.10" in codes
    # Row không có SonHN6 → không match
    assert "HR.FR.05" not in codes


def test_filter_helper_by_pic_multi_or(parsed_data):
    """OR trong PIC filter: pics=[SonHN6, CuongNM129] → union."""
    from app import _filter_parsed_data
    filtered = _filter_parsed_data(parsed_data, pics=["SonHN6", "CuongNM129"])
    codes = {r.meta.get("ma_cn") for r in filtered.rows}
    # SonHN6 (case-normalized) → TMS.FR.01, TMS.FR.02, ESS.FR.10
    # CuongNM129 → HR.FR.05
    assert codes == {"TMS.FR.01", "TMS.FR.02", "ESS.FR.10", "HR.FR.05"}


def test_filter_helper_module_and_pic_intersect(parsed_data):
    """AND: module=TMS AND pic=SonHN6 → chỉ row TMS có SonHN6."""
    from app import _filter_parsed_data
    filtered = _filter_parsed_data(
        parsed_data,
        modules=["TMS"],
        pics=["SonHN6"],
    )
    codes = {r.meta.get("ma_cn") for r in filtered.rows}
    assert codes == {"TMS.FR.01", "TMS.FR.02"}


def test_filter_helper_pic_not_exist(parsed_data):
    """PIC không tồn tại → row_count = 0."""
    from app import _filter_parsed_data
    filtered = _filter_parsed_data(parsed_data, pics=["KHONG_TON_TAI_XYZ"])
    assert len(filtered.rows) == 0


def test_dashboard_multi_module_comma_separated(flask_client, sample_xlsx_path):
    """Query pattern comma-separated: ?module=TMS,HR"""
    _upload(flask_client, sample_xlsx_path)
    r = flask_client.get("/api/projects/default/dashboard?module=TMS,HR")
    assert r.status_code == 200
    data = r.get_json()
    assert data["applied_filter"]["modules"] == ["TMS", "HR"]
    assert data["applied_filter"]["row_count"] == 3


def test_dashboard_multi_module_repeated_param(flask_client, sample_xlsx_path):
    """Query pattern repeated: ?module=TMS&module=HR — cũng phải work."""
    _upload(flask_client, sample_xlsx_path)
    r = flask_client.get("/api/projects/default/dashboard?module=TMS&module=HR")
    assert r.status_code == 200
    data = r.get_json()
    assert set(data["applied_filter"]["modules"]) == {"TMS", "HR"}
    assert data["applied_filter"]["row_count"] == 3


def test_dashboard_module_and_pic_intersection(flask_client, sample_xlsx_path):
    """Filter kết hợp module + pic qua HTTP."""
    _upload(flask_client, sample_xlsx_path)
    r = flask_client.get("/api/projects/default/dashboard?module=TMS&pic=SonHN6")
    assert r.status_code == 200
    data = r.get_json()
    assert data["applied_filter"]["modules"] == ["TMS"]
    assert data["applied_filter"]["pics"] == ["SonHN6"]
    assert data["applied_filter"]["row_count"] == 2


def test_dashboard_pic_not_exist_returns_zero(flask_client, sample_xlsx_path):
    """PIC không tồn tại → row_count = 0, không crash."""
    _upload(flask_client, sample_xlsx_path)
    r = flask_client.get("/api/projects/default/dashboard?pic=KHONG_TON_TAI_XYZ")
    assert r.status_code == 200
    data = r.get_json()
    assert data["applied_filter"]["row_count"] == 0
    assert data["metrics"]["summary"]["total_functions"] == 0


def test_dashboard_multi_pic_or(flask_client, sample_xlsx_path):
    """?pic=SonHN6,CuongNM129 → union (SonHN6 normalize → 3 rows, CuongNM129 → 1 row)."""
    _upload(flask_client, sample_xlsx_path)
    r = flask_client.get("/api/projects/default/dashboard?pic=SonHN6,CuongNM129")
    data = r.get_json()
    assert set(data["applied_filter"]["pics"]) == {"SonHN6", "CuongNM129"}
    assert data["applied_filter"]["row_count"] == 4


# ==========================================================================
# Wave 2: PIC workload — by_phase breakdown
# ==========================================================================

def test_pic_workload_has_by_phase_key(metrics):
    """Mỗi PIC entry phải có key 'by_phase' là dict."""
    pics = metrics["pic_workload"]
    assert len(pics) > 0
    for p in pics:
        assert "by_phase" in p, f"PIC {p['pic']} thiếu by_phase"
        assert isinstance(p["by_phase"], dict)


def test_pic_workload_by_phase_structure(metrics):
    """
    by_phase[phase] phải có đủ 5 field: total, closed, in_progress,
    assigned, overdue. Chỉ chứa phase mà PIC có tham gia (total > 0).
    """
    pics = metrics["pic_workload"]
    required_fields = {"total", "closed", "in_progress", "assigned", "overdue"}
    for p in pics:
        for phase, stats in p["by_phase"].items():
            assert isinstance(stats, dict)
            assert required_fields.issubset(stats.keys()), \
                f"PIC {p['pic']} phase {phase} thiếu field: {required_fields - stats.keys()}"
            assert stats["total"] > 0, \
                f"by_phase chỉ nên chứa phase có total > 0 (PIC {p['pic']}, phase {phase})"


def test_pic_workload_by_phase_aggregate_matches_total(metrics):
    """
    Tổng các by_phase[*].total của 1 PIC = total_tasks aggregate.
    (invariant: aggregate = sum của breakdown per-phase)
    """
    for p in metrics["pic_workload"]:
        sum_by_phase = sum(v["total"] for v in p["by_phase"].values())
        assert sum_by_phase == p["total_tasks"], \
            f"PIC {p['pic']}: sum by_phase ({sum_by_phase}) != total_tasks ({p['total_tasks']})"

        sum_closed = sum(v["closed"] for v in p["by_phase"].values())
        assert sum_closed == p["closed"]
        sum_ip = sum(v["in_progress"] for v in p["by_phase"].values())
        assert sum_ip == p["in_progress"]
        sum_as = sum(v["assigned"] for v in p["by_phase"].values())
        assert sum_as == p["assigned"]


def test_pic_workload_by_phase_specific_pic(metrics):
    """
    SonHN6 (sau normalize) làm Analysis ở 3 row:
    - TMS.FR.01 (Closed)
    - TMS.FR.02 (Closed)
    - ESS.FR.10 (In-progress, đã normalize từ 'SONHN6')
    → SonHN6.by_phase[Analysis] = {total:3, closed:2, in_progress:1}
    """
    sonhn6 = next((p for p in metrics["pic_workload"] if p["pic"] == "SonHN6"), None)
    assert sonhn6 is not None, "PIC SonHN6 phải có trong workload"
    assert "Analysis" in sonhn6["by_phase"]
    analysis = sonhn6["by_phase"]["Analysis"]
    assert analysis["total"] == 3
    assert analysis["closed"] == 2
    assert analysis["in_progress"] == 1
    assert analysis["assigned"] == 0


# ==========================================================================
# Wave 2.1 (regression) — Verify MỌI section/metric cascade ĐÚNG sau filter.
#
# Mục tiêu: fix cứng contract "sau khi filter Module=X, không được leak module
# khác vào bất kỳ chart/section nào". Nếu tương lai ai đó thêm metric mới mà
# quên filter → test sẽ fail ngay.
#
# Sample fixture có duy nhất 1 row PR (PR.FR.03) — dễ verify chính xác.
# ==========================================================================

def _filtered_metrics(parsed_data, today, **filters):
    """Helper: apply _filter_parsed_data rồi compute metrics."""
    from app import _filter_parsed_data
    from analyzer.dashboard_engine import DashboardEngine
    filtered = _filter_parsed_data(parsed_data, **filters)
    return DashboardEngine(today=today, long_duration_threshold=3).compute_all(filtered)


def test_cascade_structure_all_modules(parsed_data, today):
    """Filter Module=PR → structure.all_modules chỉ còn ['PR']."""
    m = _filtered_metrics(parsed_data, today, modules=["PR"])
    assert m["structure"]["all_modules"] == ["PR"]


def test_cascade_structure_processes_by_module(parsed_data, today):
    """Filter Module=PR → processes_by_module chỉ có key 'PR'."""
    m = _filtered_metrics(parsed_data, today, modules=["PR"])
    pbm = m["structure"]["processes_by_module"]
    assert list(pbm.keys()) == ["PR"]
    assert pbm["PR"] == ["PR.BP.01 - Performance"]


def test_cascade_structure_all_pics_subset(parsed_data, today):
    """
    Filter Module=PR → all_pics chỉ chứa PIC làm việc trên row PR.
    Row PR.FR.03: Analysis=TungTT83, Dev=NhuNHT3+HaiTD16.
    Các PIC khác (SonHN6, PhatTPT3, BaoLQ31, ...) KHÔNG được có mặt.
    """
    m = _filtered_metrics(parsed_data, today, modules=["PR"])
    pics = set(m["structure"]["all_pics"])
    assert pics == {"TungTT83", "NhuNHT3", "HaiTD16"}
    # Guard chống regression: PIC của module khác tuyệt đối không được leak
    for leaked in ("SonHN6", "PhatTPT3", "BaoLQ31", "CuongNM129", "NhiVN"):
        assert leaked not in pics, f"PIC {leaked} bị leak vào scope PR"


def test_cascade_structure_all_processes(parsed_data, today):
    """Filter Module=PR → all_processes subset chỉ còn quy trình của PR."""
    m = _filtered_metrics(parsed_data, today, modules=["PR"])
    assert m["structure"]["all_processes"] == ["PR.BP.01 - Performance"]


def test_cascade_structure_all_priorities(parsed_data, today):
    """Filter Module=PR → all_priorities chỉ còn priority của row PR (Could-have)."""
    m = _filtered_metrics(parsed_data, today, modules=["PR"])
    assert m["structure"]["all_priorities"] == ["Could-have"]


def test_cascade_structure_all_complexities(parsed_data, today):
    """Filter Module=PR → all_complexities chỉ còn complexity của row PR (High)."""
    m = _filtered_metrics(parsed_data, today, modules=["PR"])
    assert m["structure"]["all_complexities"] == ["High"]


def test_cascade_structure_all_giai_doan(parsed_data, today):
    """Filter Module=PR → all_giai_doan chỉ còn giai đoạn của row PR ('2')."""
    m = _filtered_metrics(parsed_data, today, modules=["PR"])
    assert m["structure"]["all_giai_doan"] == ["2"]


def test_cascade_structure_all_phases_KEEP_FULL(parsed_data, today):
    """
    KHÔNG cascade phase — đây là cấu trúc file, giữ nguyên cho mọi chart
    có trục "phase" (matrix, stacked, timeline, effort heatmap).
    Test này lock design để tránh ai đó vô tình lọc phase cũng.
    """
    m = _filtered_metrics(parsed_data, today, modules=["PR"])
    assert m["structure"]["all_phases"] == ["Analysis", "Dev", "UAT"]


def test_cascade_module_overview_only_pr(parsed_data, today):
    """Filter Module=PR → module_overview chỉ có 1 row PR."""
    m = _filtered_metrics(parsed_data, today, modules=["PR"])
    mods = [r["module"] for r in m["module_overview"]]
    assert mods == ["PR"]


def test_cascade_progress_by_task_type_only_pr(parsed_data, today):
    """Filter Module=PR → progress_by_task_type.by_module chỉ có key 'PR'."""
    m = _filtered_metrics(parsed_data, today, modules=["PR"])
    assert set(m["progress_by_task_type"]["by_module"].keys()) == {"PR"}


def test_cascade_phase_status_matrix_only_pr(parsed_data, today):
    """Filter Module=PR → matrix.modules = ['PR'], data chỉ có key 'PR'."""
    m = _filtered_metrics(parsed_data, today, modules=["PR"])
    matrix = m["phase_status_matrix"]
    assert matrix["modules"] == ["PR"]
    assert list(matrix["data"].keys()) == ["PR"]


def test_cascade_fit_gap_analysis_only_pr(parsed_data, today):
    """Filter Module=PR → fit_gap_analysis chỉ có key 'PR'."""
    m = _filtered_metrics(parsed_data, today, modules=["PR"])
    assert list(m["fit_gap_analysis"].keys()) == ["PR"]


def test_cascade_effort_analysis_modules_only_pr(parsed_data, today):
    """
    Filter Module=PR → effort_analysis.modules = ['PR'] (dùng cho heatmap X-axis)
    và heatmap dict cũng chỉ có key 'PR'.
    """
    m = _filtered_metrics(parsed_data, today, modules=["PR"])
    e = m["effort_analysis"]
    assert e["modules"] == ["PR"]
    assert list(e["heatmap"].keys()) == ["PR"]
    # PIC breakdown cũng phải chỉ chứa PIC làm việc trên PR
    pic_names = {p["pic"] for p in e["by_pic"]}
    assert pic_names.issubset({"TungTT83", "NhuNHT3", "HaiTD16"})


def test_cascade_process_analysis_modules_only_pr(parsed_data, today):
    """Filter Module=PR → mỗi item process_analysis chỉ có 'PR' trong modules."""
    m = _filtered_metrics(parsed_data, today, modules=["PR"])
    for item in m["process_analysis"]:
        assert item["modules"] == ["PR"], \
            f"Quy trình '{item['process']}' bị leak module khác: {item['modules']}"


def test_cascade_pic_workload_only_pr_pics(parsed_data, today):
    """Filter Module=PR → pic_workload chỉ có PIC làm việc trên row PR."""
    m = _filtered_metrics(parsed_data, today, modules=["PR"])
    pic_names = {p["pic"] for p in m["pic_workload"]}
    assert pic_names == {"TungTT83", "NhuNHT3", "HaiTD16"}


def test_cascade_timeline_data_modules_only_pr(parsed_data, today):
    """Filter Module=PR → timeline_data.modules và functions_by_module chỉ có 'PR'."""
    m = _filtered_metrics(parsed_data, today, modules=["PR"])
    t = m["timeline_data"]
    assert t["modules"] == ["PR"]
    assert list(t["functions_by_module"].keys()) == ["PR"]


def test_cascade_priority_breakdown_only_pr(parsed_data, today):
    """Filter Module=PR → priority_breakdown chỉ có priority của PR."""
    m = _filtered_metrics(parsed_data, today, modules=["PR"])
    # PR.FR.03 có Could-have → dict chỉ có key này (không leak Must-have/Should-have)
    keys = set(m["priority_breakdown"].keys())
    assert keys == {"Could-have"}


def test_cascade_complexity_breakdown_only_pr(parsed_data, today):
    """Filter Module=PR → complexity_breakdown chỉ có complexity của PR (High)."""
    m = _filtered_metrics(parsed_data, today, modules=["PR"])
    keys = set(m["complexity_breakdown"].keys())
    assert keys == {"High"}


def test_cascade_overdue_list_module_only_pr(parsed_data, today):
    """Filter Module=PR → overdue_list nếu có item, module đều là 'PR'."""
    m = _filtered_metrics(parsed_data, today, modules=["PR"])
    for item in m["overdue_list"]:
        assert item["module"] == "PR"


def test_cascade_unassigned_tasks_module_only_pr(parsed_data, today):
    """Filter Module=PR → unassigned_tasks đều thuộc PR."""
    m = _filtered_metrics(parsed_data, today, modules=["PR"])
    for item in m["unassigned_tasks"]:
        assert item["module"] == "PR"


def test_cascade_stalled_tasks_module_only_pr(parsed_data, today):
    """Filter Module=PR → stalled_tasks.items đều thuộc PR."""
    m = _filtered_metrics(parsed_data, today, modules=["PR"])
    for item in m["stalled_tasks"]["items"]:
        assert item["module"] == "PR"


def test_cascade_duration_analysis_module_only_pr(parsed_data, today):
    """Filter Module=PR → duration_analysis.items đều thuộc PR."""
    m = _filtered_metrics(parsed_data, today, modules=["PR"])
    for item in m["duration_analysis"]["items"]:
        assert item["module"] == "PR"


def test_cascade_risk_scores_module_only_pr(parsed_data, today):
    """Filter Module=PR → risk_scores đều thuộc PR."""
    m = _filtered_metrics(parsed_data, today, modules=["PR"])
    for item in m["risk_scores"]:
        assert item["module"] == "PR"


def test_cascade_summary_modules_count_only_pr(parsed_data, today):
    """Filter Module=PR → summary.modules_count = 1."""
    m = _filtered_metrics(parsed_data, today, modules=["PR"])
    assert m["summary"]["modules_count"] == 1
    assert m["summary"]["total_functions"] == 1


# --------------------------------------------------------------------------
# End-to-end: qua HTTP endpoint (không chỉ helper)
# --------------------------------------------------------------------------

def test_cascade_dashboard_endpoint_full_no_leak(flask_client, sample_xlsx_path):
    """
    Combo end-to-end: filter Module=PR qua HTTP → mọi section trong response
    KHÔNG được có module khác. Đây là contract lock cho FE.
    """
    _upload(flask_client, sample_xlsx_path)
    r = flask_client.get("/api/projects/default/dashboard?module=PR")
    assert r.status_code == 200
    m = r.get_json()["metrics"]

    # Structure
    assert m["structure"]["all_modules"] == ["PR"]
    assert list(m["structure"]["processes_by_module"].keys()) == ["PR"]

    # Module-scoped sections
    assert [r["module"] for r in m["module_overview"]] == ["PR"]
    assert list(m["fit_gap_analysis"].keys()) == ["PR"]
    assert m["phase_status_matrix"]["modules"] == ["PR"]
    assert m["effort_analysis"]["modules"] == ["PR"]
    assert m["timeline_data"]["modules"] == ["PR"]
    assert set(m["progress_by_task_type"]["by_module"].keys()) == {"PR"}

    # Row-scoped list: mọi item đều thuộc PR
    for src_key in ("overdue_list", "unassigned_tasks", "risk_scores"):
        for item in m[src_key]:
            assert item.get("module") == "PR", \
                f"{src_key} leak module {item.get('module')}"


def test_cascade_dashboard_endpoint_filter_pic(flask_client, sample_xlsx_path):
    """
    Filter PIC=TungTT83 (chỉ làm việc trên PR.FR.03) → mọi section
    scope module đều chỉ có 'PR'.
    """
    _upload(flask_client, sample_xlsx_path)
    r = flask_client.get("/api/projects/default/dashboard?pic=TungTT83")
    assert r.status_code == 200
    m = r.get_json()["metrics"]
    assert m["structure"]["all_modules"] == ["PR"]
    assert m["summary"]["total_functions"] == 1
    assert [r["module"] for r in m["module_overview"]] == ["PR"]


# ==========================================================================
# Wave 3 — Cascade dropdown PIC theo Module: structure.pics_by_module
# ==========================================================================

def test_structure_info_includes_pics_by_module(metrics):
    """FE dùng map này để cascade dropdown PIC khi user chọn Module."""
    assert "pics_by_module" in metrics["structure"]
    pbm = metrics["structure"]["pics_by_module"]
    assert isinstance(pbm, dict)


def test_pics_by_module_no_empty_keys(metrics):
    """Không có key rỗng/None — row không có Module bị loại."""
    pbm = metrics["structure"]["pics_by_module"]
    assert "" not in pbm
    assert None not in pbm


def test_pics_by_module_lists_sorted_and_unique(metrics):
    """Mỗi list PIC phải sort + unique để UI dropdown ổn định."""
    pbm = metrics["structure"]["pics_by_module"]
    for module, pics in pbm.items():
        assert pics == sorted(pics), f"Module {module} chưa sort: {pics}"
        assert len(pics) == len(set(pics)), f"Module {module} có duplicate PIC"


def test_pics_by_module_pr_contains_known_pics(metrics):
    """Row PR.FR.03: Analysis=TungTT83, Dev=NhuNHT3+HaiTD16 → 3 PIC unique."""
    pbm = metrics["structure"]["pics_by_module"]
    assert "PR" in pbm
    pr_pics = set(pbm["PR"])
    assert {"TungTT83", "NhuNHT3", "HaiTD16"}.issubset(pr_pics), \
        f"PR thiếu PIC: {pr_pics}"


def test_pics_by_module_pic_case_normalized(metrics):
    """
    Row ESS.FR.10 có SONHN6 (all caps) trong Excel → parser đã normalize
    thành SonHN6. pics_by_module['ESS'] phải chứa dạng đã normalize.
    """
    pbm = metrics["structure"]["pics_by_module"]
    assert "ESS" in pbm
    assert "SonHN6" in pbm["ESS"]
    # KHÔNG được có dạng chưa normalize
    assert "SONHN6" not in pbm["ESS"]


def test_pics_by_module_hr_only_own_pic(metrics):
    """
    Row HR.FR.05 chỉ có CuongNM129 ở Analysis; các phase khác không PIC.
    → HR.pics_by_module chỉ có ['CuongNM129'].
    """
    pbm = metrics["structure"]["pics_by_module"]
    assert "HR" in pbm
    assert pbm["HR"] == ["CuongNM129"]


def test_pics_by_module_no_cross_module_leak(metrics):
    """
    Guard chống regression: PIC của module này không leak sang module khác.
    HR.pics_by_module KHÔNG được chứa PIC của PR (TungTT83, NhuNHT3).
    """
    pbm = metrics["structure"]["pics_by_module"]
    hr_pics = set(pbm.get("HR", []))
    for leaked in ("TungTT83", "NhuNHT3", "PhatTPT3", "BaoLQ31"):
        assert leaked not in hr_pics, f"PIC {leaked} bị leak vào HR"


# --------------------------------------------------------------------------
# Cascade: sau khi filter, pics_by_module cũng subset đúng
# --------------------------------------------------------------------------

def test_cascade_pics_by_module_filter_pr(parsed_data, today):
    """Filter Module=PR → pics_by_module chỉ có key 'PR'."""
    m = _filtered_metrics(parsed_data, today, modules=["PR"])
    pbm = m["structure"]["pics_by_module"]
    assert list(pbm.keys()) == ["PR"]
    assert set(pbm["PR"]) == {"TungTT83", "NhuNHT3", "HaiTD16"}


def test_cascade_pics_by_module_filter_multi_module(parsed_data, today):
    """Filter Module=[PR, HR] → pics_by_module có cả 2 key, mỗi key subset đúng."""
    m = _filtered_metrics(parsed_data, today, modules=["PR", "HR"])
    pbm = m["structure"]["pics_by_module"]
    assert set(pbm.keys()) == {"PR", "HR"}
    assert set(pbm["PR"]) == {"TungTT83", "NhuNHT3", "HaiTD16"}
    assert pbm["HR"] == ["CuongNM129"]


def test_cascade_pics_by_module_via_endpoint(flask_client, sample_xlsx_path):
    """End-to-end qua HTTP: filter Module=PR → pics_by_module chỉ chứa PIC PR."""
    _upload(flask_client, sample_xlsx_path)
    r = flask_client.get("/api/projects/default/dashboard?module=PR")
    assert r.status_code == 200
    pbm = r.get_json()["metrics"]["structure"]["pics_by_module"]
    assert list(pbm.keys()) == ["PR"]
    assert set(pbm["PR"]) == {"TungTT83", "NhuNHT3", "HaiTD16"}
