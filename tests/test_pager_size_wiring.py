"""
Regression: select «Hiển thị 10/20/50» phải thực sự đổi số dòng của MỌI bảng.

Root cause đã sửa (2026-08-05): 3 bảng (Thiếu/Trùng FID, Thời gian dài, Báo cáo
tuần GAP) tự giữ `pageSize` riêng trong state cục bộ và dùng nó để slice, trong
khi `renderPager` ghi lựa chọn của user vào `pageState[key].size`. Callback chỉ
đồng bộ `page` chứ không đồng bộ `size` → chọn 10 vẫn ra 50 dòng, và pager tính
totalPages theo size mới nên bấm sang trang 2 ra bảng rỗng.

Cách chống lặp lại: `pageState[key]` là nguồn duy nhất, mọi bảng slice qua
`_pageSlice(key, items)`.
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DASHBOARD_JS = (ROOT / "static" / "js" / "dashboard.js").read_text(encoding="utf-8")

# Bảng dùng renderPager nhưng render bằng hàm riêng (không qua _pageSlice
# trong renderXxxTable chung) — 3 cái từng bị bug.
_FIXED_TABLES = {
    "fid": "_fidRenderTable",
    "dur": "_durRenderTable",
    "weeklyGap": "_weeklyGapRenderTable",
}


def _pagestate_block() -> str:
    return DASHBOARD_JS.split("const pageState = {")[1].split("};")[0]


def _fn_body(name: str) -> str:
    """Cắt thân hàm theo dấu function tiếp theo (đủ dùng cho assert chuỗi)."""
    body = DASHBOARD_JS.split(f"function {name}(")[1]
    nxt = re.search(r"\nfunction \w+\(|\nasync function \w+\(", body)
    return body[: nxt.start()] if nxt else body


def test_every_render_pager_key_is_declared_in_pagestate():
    """pageState khai báo thiếu key → size mặc định rơi về nhánh lazy-init."""
    keys = set(re.findall(r'renderPager\(\s*"[^"]+",\s*"(\w+)"', DASHBOARD_JS))
    assert keys, "không tìm thấy call renderPager nào"
    block = _pagestate_block()
    missing = sorted(k for k in keys if f"{k}:" not in block)
    assert missing == [], f"pageState thiếu key: {missing}"


def test_default_page_size_is_ten_for_all_tables():
    """Yêu cầu nghiệp vụ: mặc định 10 dòng/trang cho mọi bảng."""
    assert "const PAGE_DEFAULT_SIZE = 10;" in DASHBOARD_JS
    block = _pagestate_block()
    sizes = re.findall(r"\w+:\s*\{\s*page:\s*1,\s*size:\s*([^\s},]+)", block)
    assert sizes, "không parse được size trong pageState"
    assert set(sizes) == {"PAGE_DEFAULT_SIZE"}, (
        f"có bảng hardcode size khác PAGE_DEFAULT_SIZE: {set(sizes)}"
    )


def test_fixed_tables_registered_with_default_size():
    block = _pagestate_block()
    for key in _FIXED_TABLES:
        assert f"{key}:" in block, f"pageState thiếu {key}"


def test_fixed_tables_slice_via_pageslice_not_local_pagesize():
    """Bảng phải slice qua _pageSlice để size + clamp page dùng chung 1 nguồn."""
    for key, fn in _FIXED_TABLES.items():
        body = _fn_body(fn)
        assert f'_pageSlice("{key}"' in body, f"{fn} không dùng _pageSlice"
        assert "pageSize" not in body, f"{fn} vẫn còn pageSize cục bộ"
        # Không tự tính start bằng size riêng
        assert ".slice(start, start +" not in body, f"{fn} vẫn tự slice tay"


def test_no_local_pagesize_left_in_the_three_states():
    for state in ("_fidState", "_durState", "_weeklyGapState"):
        decl = DASHBOARD_JS.split(f"const {state} = {{")[1].split("}")[0]
        assert "pageSize" not in decl, f"{state} vẫn giữ pageSize riêng"
        assert "page:" not in decl, f"{state} vẫn giữ page riêng"


def test_fixed_tables_reset_page_on_reload():
    """Load data mới phải về trang 1 qua pageState, không qua state cục bộ."""
    for key in _FIXED_TABLES:
        assert f"pageState.{key}.page = 1" in DASHBOARD_JS, (
            f"không reset trang 1 cho {key} khi load lại"
        )


def test_sync_reset_covers_fixed_tables():
    chunk = DASHBOARD_JS.split("function _resetListPagesAfterSync(")[1].split("}")[0]
    for key in _FIXED_TABLES:
        assert f'"{key}"' in chunk, f"sync không reset page cho {key}"


def test_pager_set_size_writes_state_and_recalls_callback():
    """Hợp đồng của renderPager: đổi size → ghi pageState + gọi lại onChange."""
    body = _fn_body("pagerSetSize")
    assert "st.size = parseInt(sizeVal, 10) || 0;" in body
    assert "st.page = 1;" in body
    assert "st._onChange()" in body


def test_pageslice_handles_show_all_and_clamps_page():
    body = _fn_body("_pageSlice")
    # size=0 → "Tất cả"
    assert "if (!st.size || st.size <= 0)" in body
    assert "if (st.page > totalPages) st.page = totalPages;" in body
