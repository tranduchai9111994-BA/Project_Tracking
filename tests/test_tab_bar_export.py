"""
Nút 📥 trên tab bar của hub + option «Xuất tất cả tab».

Bug gốc (2026-08d): config `tabs` của hub Issues không khai key nào để xuất, mà
handler chỉ đọc `tab.export`, nên cả 9 tab đều rơi vào nhánh "Tab này chưa có
export riêng" — dù nút xuất trong thân section vẫn chạy. Test ở đây chốt lại:
  1. mọi tab Issues đều khai được đường xuất (`export` hoặc `exportFn`);
  2. hàm mà config trỏ tới có thật trong dashboard.js (typo là chết im lặng);
  3. option xuất gộp truyền forceFull để không bị nhóm focus bóp lại 1 sheet;
  4. 2 endpoint export mới (source checklist, duration flag) trả về xlsx.
"""
from __future__ import annotations

import io
import re
from pathlib import Path

import openpyxl
import pytest

ROOT = Path(__file__).resolve().parent.parent
HUBS = ROOT / "static" / "js" / "sidebar_hubs.js"
JS = ROOT / "static" / "js" / "dashboard.js"

# Các tab của hub Issues, khớp SIDEBAR_NAV_TREE
ISSUE_TABS = [
    "section-overdue",
    "section-unassigned",
    "section-stalled",
    "section-aging-wip",
    "section-dataquality",
    "section-fid-check",
    "section-source-checklist",
    "section-duration-flag",
    "section-weekly-gap",
]


def _hubs_src() -> str:
    return HUBS.read_text(encoding="utf-8")


def _tab_line(section: str) -> str:
    """Dòng config của 1 tab trong SIDEBAR_NAV_TREE."""
    src = _hubs_src()
    for line in src.splitlines():
        if f'section: "{section}"' in line:
            return line
    pytest.fail(f"không thấy config tab {section}")


# ── 1. Mọi tab Issues đều có đường xuất ───────────────────────────────────

@pytest.mark.parametrize("section", ISSUE_TABS)
def test_moi_tab_issues_co_badge_dem(section):
    """Mỗi tab Issues phải có badge để PM thấy số mà không cần mở từng tab."""
    line = _tab_line(section)
    assert 'badge: "' in line, f"{section} thiếu badge → tab bar không hiện số đếm"


@pytest.mark.parametrize("section", ISSUE_TABS)
def test_moi_tab_issues_khai_duong_xuat(section):
    line = _tab_line(section)
    assert ("exportFn:" in line) or ("export:" in line), (
        f"{section} không khai export → nút 📥 trên tab bar báo "
        f'"chưa có export riêng"'
    )


@pytest.mark.parametrize("section", ISSUE_TABS)
def test_ham_export_cua_tab_ton_tai_that(section):
    """Config trỏ tới tên hàm dạng string → typo không có ai báo lúc build."""
    line = _tab_line(section)
    m = re.search(r'exportFn:\s*"([^"]+)"', line)
    if not m:
        return  # tab dùng chart key, exportChartData lo
    fn = m.group(1)
    js = JS.read_text(encoding="utf-8")
    # Đủ điều kiện nếu gán tường minh vào window, hoặc khai ở top-level (script
    # thường, không module → function declaration cột 0 tự nằm trên window).
    on_window = f"window.{fn} =" in js
    top_level = re.search(rf"^(?:async )?function {re.escape(fn)}\s*\(", js, re.M)
    assert on_window or top_level, (
        f"{section} trỏ tới {fn} nhưng dashboard.js không có hàm global này"
    )


@pytest.mark.parametrize("section", ISSUE_TABS)
def test_ham_extra_params_cua_tab_ton_tai_that(section):
    line = _tab_line(section)
    m = re.search(r'extraParamsFn:\s*"([^"]+)"', line)
    if not m:
        return
    fn = m.group(1)
    js = JS.read_text(encoding="utf-8")
    assert f"window.{fn} =" in js, f"{fn} chưa được export ra window"


def test_handler_doc_ca_export_va_exportFn():
    src = _hubs_src()
    start = src.index("function _openTabExport")
    body = src[start:start + 2600]
    assert "tab.exportFn" in body
    assert "tab.export" in body
    assert "extraParamsFn" in body


# ── 2. Option xuất gộp ────────────────────────────────────────────────────

def test_hub_issues_khai_export_gop():
    src = _hubs_src()
    assert 'exportAllFn: "exportAllIssues"' in src
    assert "exportAllLabel_vi" in src


def test_option_gop_truyen_forceFull():
    """Không có forceFull thì đang focus 1 nhóm sẽ chỉ ra 1 sheet."""
    src = _hubs_src()
    start = src.index("opts.allTabs = {")
    assert "forceFull: true" in src[start:start + 400]


def test_exportAllIssues_ton_trong_forceFull():
    js = JS.read_text(encoding="utf-8")
    start = js.index("async function exportAllIssues(")
    body = js[start:js.index("window.exportAllIssues", start)]
    assert "forceFull" in body
    assert "!forceFull &&" in body, "forceFull phải bỏ qua nhánh focus"


def test_menu_co_nhom_gop_nhieu_tab():
    js = JS.read_text(encoding="utf-8")
    assert "data-all-group" in js
    assert "data-all-tabs" in js
    assert "onlyAllTabs" in js


# ── 3. Endpoint export mới ────────────────────────────────────────────────

def _upload(client, path):
    with open(path, "rb") as f:
        return client.post(
            "/api/upload",
            data={"file": (io.BytesIO(f.read()), "fl.xlsx")},
            content_type="multipart/form-data",
        )


@pytest.mark.parametrize(
    "endpoint,sheet",
    [
        ("export-source-checklist", "Lay_Source_Test"),
        ("export-duration-flag", "Thoi_Gian_Dai"),
    ],
)
def test_endpoint_moi_tra_ve_xlsx(flask_client, sample_xlsx_path, endpoint, sheet):
    _upload(flask_client, sample_xlsx_path)
    r = flask_client.get(f"/api/projects/default/{endpoint}")
    assert r.status_code == 200
    wb = openpyxl.load_workbook(io.BytesIO(r.data))
    assert wb.sheetnames == [sheet]


def test_endpoint_moi_404_khi_chua_co_data(flask_client):
    for ep in ("export-source-checklist", "export-duration-flag"):
        assert flask_client.get(f"/api/projects/default/{ep}").status_code == 404
