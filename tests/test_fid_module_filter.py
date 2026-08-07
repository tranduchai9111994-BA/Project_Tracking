"""
Filter Module/Loại (multi-select) cho section «Thiếu / Trùng FID».

Quy ước đã chốt:
  - Module "không dùng FID" = không có row nào điền FID → UI bỏ check mặc định.
    Suy từ dữ liệu (`modules_without_fid`), KHÔNG hardcode tên module như "APP",
    vì mã module đổi theo dự án.
  - 4 card tổng hợp chạy theo filter (card nằm trong section, để lệch bảng thì
    PM đọc 47 mà đếm được 30 dòng), kèm ghi chú số toàn bộ.
  - Badge sidebar cố ý vẫn là số toàn bộ.
  - Export FL tôn trọng filter đang chọn.
"""
from __future__ import annotations

from pathlib import Path

from analyzer.fid_check import compute_fid_issues
from parser.excel_parser import FunctionRow, PhaseData, PhaseGroup, ParsedData


JS = Path(__file__).resolve().parents[1] / "static" / "js" / "dashboard.js"
HTML = Path(__file__).resolve().parents[1] / "templates" / "index.html"


def _row(ma: str, module: str, fid: str, dev_closed: bool = True) -> FunctionRow:
    return FunctionRow(
        row_num=2,
        meta={"ma_cn": ma, "ten_cn": f"Func {ma}", "module": module, "fid": fid},
        phases={"Dev": PhaseData(status="Closed" if dev_closed else "Open")},
    )


def _data(rows: list[FunctionRow], fid_col: bool = True) -> ParsedData:
    return ParsedData(
        headers={},
        meta_columns={"fid": 5} if fid_col else {},
        phase_groups=[PhaseGroup(name="Dev")],
        rows=rows,
        all_phases=["Dev"],
        all_modules=sorted({str(r.meta.get("module") or "") for r in rows}),
    )


# ── Backend: module_stats / modules_without_fid ─────────────────────────────

def test_module_khong_row_nao_co_fid_bi_danh_dau():
    """APP không có FID nào → vào modules_without_fid; HR có FID → không vào."""
    data = _data([
        _row("APP.01", "APP", ""),
        _row("APP.02", "APP", ""),
        _row("HR.01", "HR", "F001"),
        _row("HR.02", "HR", ""),
    ])
    r = compute_fid_issues(data)
    assert r["modules_without_fid"] == ["APP"]


def test_modules_without_fid_bat_moi_module_khong_dung_fid():
    """Không chỉ APP — ESS cũng phải bị bắt, đó là lý do không hardcode."""
    data = _data([
        _row("APP.01", "APP", ""),
        _row("ESS.01", "ESS", ""),
        _row("HR.01", "HR", "F001"),
    ])
    assert compute_fid_issues(data)["modules_without_fid"] == ["APP", "ESS"]


def test_module_stats_dem_rows_with_fid_dev_closed():
    data = _data([
        _row("HR.01", "HR", "F001", dev_closed=True),
        _row("HR.02", "HR", "", dev_closed=True),
        _row("HR.03", "HR", "", dev_closed=False),
    ])
    st = compute_fid_issues(data)["module_stats"]["HR"]
    assert st == {"rows": 3, "with_fid": 1, "dev_closed": 2}


def test_row_chua_dien_fid_nhung_module_co_dung_thi_van_bao_issue():
    """Bỏ check module không dùng FID không được che issue của module có dùng."""
    data = _data([
        _row("APP.01", "APP", ""),
        _row("HR.01", "HR", "F001"),
        _row("HR.02", "HR", ""),
    ])
    r = compute_fid_issues(data)
    skip = set(r["modules_without_fid"])
    kept = [i for i in r["issues"] if i["module"] not in skip]
    assert [i["ma_cn"] for i in kept] == ["HR.02"]


def test_module_rong_van_xuat_hien_trong_module_stats():
    """Module rỗng phải lọc được, nếu không filter mặc định ẩn nó âm thầm."""
    data = _data([_row("X.01", "", ""), _row("HR.01", "HR", "F001")])
    r = compute_fid_issues(data)
    assert "" in r["module_stats"]
    assert "" in r["modules_without_fid"]


def test_dev_closed_theo_module_cong_lai_bang_tong():
    """Card «Dev đã Closed» khi lọc = tổng dev_closed các module còn lại."""
    data = _data([
        _row("APP.01", "APP", ""),
        _row("HR.01", "HR", "F001"),
        _row("HR.02", "HR", "F002"),
    ])
    r = compute_fid_issues(data)
    total = sum(st["dev_closed"] for st in r["module_stats"].values())
    assert total == r["summary"]["total_dev_closed_rows"]


def test_khong_co_cot_fid_thi_moi_module_deu_khong_dung_fid():
    """File thiếu cột FID → UI phải fallback check hết chứ không để bảng trống."""
    data = _data([_row("HR.01", "HR", ""), _row("PR.01", "PR", "")], fid_col=False)
    r = compute_fid_issues(data)
    assert r["fid_column_present"] is False
    assert r["modules_without_fid"] == ["HR", "PR"]


# ── Backend: export FL tôn trọng filter ────────────────────────────────────

def test_export_fl_loc_theo_fid_module_va_fid_type():
    """
    Cả 2 chế độ xuất phải đi qua cùng 1 helper để không bao giờ lệch nhau:
    danh sách lỗi (/export-fid-issues) và FL để import (/export-fl-reimport).
    """
    import app as app_module

    src = Path(app_module.__file__).read_text(encoding="utf-8")
    assert "def _fid_issues_for_request(" in src
    assert 'FID_NO_MODULE_TOKEN = "__no_module__"' in src, (
        "module rỗng cần token riêng khi qua CSV"
    )

    helper = src[src.index("def _fid_issues_for_request("):]
    helper = helper[: helper.index("\ndef ", 1)]
    assert '_multi("fid_module")' in helper
    assert '_multi("fid_type")' in helper

    # Lọc phải xảy ra trước khi union vào hits, nếu không thì filter vô nghĩa
    idx_helper = src.index("fid_issues_list = _fid_issues_for_request(")
    idx_collect = src.index("hits = collect_issue_hits(")
    assert idx_helper < idx_collect

    # Và endpoint danh sách lỗi dùng đúng helper đó
    endpoint = src[src.index("def project_export_fid_issues("):]
    assert "_fid_issues_for_request(data)" in endpoint[:1500]


# ── Frontend wiring ────────────────────────────────────────────────────────

def test_html_dung_multi_select_thay_native_select():
    html = HTML.read_text(encoding="utf-8")
    assert 'id="fidModuleMS"' in html
    assert 'id="fidTypeMS"' in html
    assert 'id="fidModuleFilter"' not in html, "select single cũ phải bị bỏ"
    assert 'id="fidTypeFilter"' not in html
    assert "resetFidFilters()" in html
    assert 'id="fidScopeBanner"' in html


def test_js_mac_dinh_suy_tu_modules_without_fid():
    js = JS.read_text(encoding="utf-8")
    assert "function _fidDefaultModules" in js
    assert "_fidState.modulesWithoutFid" in js
    # Không hardcode tên module trong logic mặc định
    start = js.index("function _fidDefaultModules")
    body = js[start:start + 600]
    assert '"APP"' not in body and "'APP'" not in body


def test_js_fallback_check_het_khi_moi_module_khong_dung_fid():
    js = JS.read_text(encoding="utf-8")
    start = js.index("function _fidDefaultModules")
    body = js[start:js.index("}", js.index("return kept.length", start))]
    assert "kept.length ? kept : all" in body


def test_js_luu_lua_chon_theo_project():
    js = JS.read_text(encoding="utf-8")
    assert "function _fidModuleLsKey" in js
    assert "fidModuleSel:" in js
    assert "function _fidLoadModuleSel" in js
    assert "function _fidSaveModuleSel" in js


def test_js_card_chay_theo_filter():
    js = JS.read_text(encoding="utf-8")
    start = js.index("function _fidRenderSummaryCards")
    body = js[start:start + 2600]
    assert "_fidState.filtered" in body, "card phải tính từ tập đã lọc"
    assert "toàn bộ:" in body, "phải ghi chú số toàn bộ khi đang lọc"
    assert "dev_closed" in body, "card Dev đã Closed tính lại theo module"


def test_js_banner_giai_thich_module_bi_an():
    js = JS.read_text(encoding="utf-8")
    assert "function _fidUpdateScopeBanner" in js
    start = js.index("function _fidUpdateScopeBanner")
    body = js[start:start + 2000]
    assert "không dùng FID" in body
    assert "hiddenNoFid" in body and "hiddenManual" in body


def test_js_export_gui_kem_filter():
    """Filter cục bộ gom vào 1 chỗ để cả 2 chế độ xuất dùng chung."""
    js = JS.read_text(encoding="utf-8")
    start = js.index("function _fidExportParams")
    body = js[start:start + 900]
    assert 'params.set("fid_module"' in body
    assert 'params.set("fid_type"' in body
    assert "_fidModWire" in body, "module rỗng phải map sang token wire"
    # Cả 2 nhánh của menu đều truyền filter này xuống backend
    picker = js[js.index("function openFidExportPicker"):][:600]
    assert "extraParams: _fidExportParams" in picker
    assert 'flKinds: "fid"' in picker
    assert "_fidExportParams(params)" in js[js.index("async function exportFidIssueList"):][:1200]


def test_js_badge_van_dem_toan_bo():
    """Badge sidebar cố ý không theo filter — giữ nguyên summary.total_issues."""
    js = JS.read_text(encoding="utf-8")
    assert "_updateFidBadge(d.summary?.total_issues || 0)" in js


def test_js_loai_issue_la_multi_select():
    js = JS.read_text(encoding="utf-8")
    assert 'key: "fidType"' in js
    assert "function _fidSelectedTypes" in js
    assert "FID_TYPE_LABELS" in js
