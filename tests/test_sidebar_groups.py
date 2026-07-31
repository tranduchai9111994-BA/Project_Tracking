"""Smoke tests — sidebar dashboard groups (default membership + All vs one group)."""
from __future__ import annotations

import os
import re

import pytest

ROOT = os.path.join(os.path.dirname(__file__), "..")
DASHBOARD_JS = os.path.join(ROOT, "static", "js", "dashboard.js")
I18N_JS = os.path.join(ROOT, "static", "js", "i18n.js")
INDEX_HTML = os.path.join(ROOT, "templates", "index.html")
STYLE_CSS = os.path.join(ROOT, "static", "css", "style.css")


@pytest.fixture(scope="module")
def dashboard_js() -> str:
    with open(DASHBOARD_JS, encoding="utf-8") as f:
        return f.read()


@pytest.fixture(scope="module")
def i18n_js() -> str:
    with open(I18N_JS, encoding="utf-8") as f:
        return f.read()


@pytest.fixture(scope="module")
def index_html() -> str:
    with open(INDEX_HTML, encoding="utf-8") as f:
        return f.read()


@pytest.fixture(scope="module")
def style_css() -> str:
    raw = open(STYLE_CSS, "rb").read()
    for enc in ("utf-8", "utf-8-sig", "cp1258", "latin-1"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


# Default membership expected (mirrors DEFAULT_SIDEBAR_GROUP_DEFS)
_DEFAULT_MEMBERSHIP = {
    "tracking": {
        "section-summary", "section-rlog", "section-overdue",
        "section-unassigned", "section-stalled", "section-aging-wip",
        "section-sla", "section-module", "section-tasktype",
        "section-matrix", "section-phase", "section-giaidoan",
    },
    "forecast": {
        "section-gantt", "section-forecast-gantt", "section-gantt-calendar", "section-burndown",
        "section-capacity", "section-pic-overload", "section-baseline",
        "section-duration",
    },
    "quality": {
        "section-dataquality", "section-anomaly", "section-risk",
    },
    "analysis": {
        "section-process", "section-pic", "section-priority",
        "section-fitgap-dashboard", "section-effort", "section-slow",
        "section-deps", "section-function-diff", "section-kanban",
        "section-my-bookmarks",
    },
    "pm": {
        "section-pm", "section-digest", "section-my-digests",
    },
    "admin": {
        "section-compare", "section-custom-dashboards", "section-history",
    },
}


def _extract_default_group_block(dashboard_js: str) -> str:
    m = re.search(
        r"const DEFAULT_SIDEBAR_GROUP_DEFS\s*=\s*\[(.*?)\];",
        dashboard_js,
        re.DOTALL,
    )
    assert m, "DEFAULT_SIDEBAR_GROUP_DEFS missing"
    return m.group(1)


def test_default_groups_present(dashboard_js: str):
    block = _extract_default_group_block(dashboard_js)
    for gid in _DEFAULT_MEMBERSHIP:
        assert f'id: "{gid}"' in block, f"missing group {gid}"
    # Bilingual names
    assert 'name_vi: "Chất lượng"' in block
    assert 'name_en: "Quality"' in block
    assert 'name_vi: "Phân tích"' in block
    assert 'name_en: "Analysis"' in block
    assert 'name_vi: "Chiều PM"' in block
    assert 'name_en: "PM dimension"' in block
    assert 'name_vi: "Quản trị"' in block
    assert 'name_en: "Administration"' in block


def test_default_membership_map(dashboard_js: str):
    """Mỗi section thuộc đúng 1 nhóm default; không trùng membership."""
    block = _extract_default_group_block(dashboard_js)
    seen = {}
    for gid, sections in _DEFAULT_MEMBERSHIP.items():
        # Tìm object group theo id
        gm = re.search(
            rf'id:\s*"{gid}"\s*,\s*name_vi:.*?sections:\s*\[(.*?)\]',
            block,
            re.DOTALL,
        )
        assert gm, f"cannot parse sections for {gid}"
        found = set(re.findall(r'"(section-[^"]+)"', gm.group(1)))
        assert found == sections, (
            f"membership mismatch for {gid}:\n"
            f"  expected={sorted(sections)}\n"
            f"  found   ={sorted(found)}"
        )
        for sid in found:
            assert sid not in seen, f"{sid} in both {seen[sid]} and {gid}"
            seen[sid] = gid


def test_filter_all_vs_one_group_api(dashboard_js: str):
    """API filter: All + set group + compose class group-filtered-out."""
    assert 'SIDEBAR_GROUP_ALL = "__all__"' in dashboard_js
    assert "function applySidebarGroupFilter()" in dashboard_js
    assert "function setSidebarActiveGroup(" in dashboard_js
    assert "function resetSidebarGroupsToDefault(" in dashboard_js
    assert "group-filtered-out" in dashboard_js
    assert "buildSidebarSectionMembership" in dashboard_js
    # Compose: không đè .hidden visibility
    assert "data-user-hidden" in dashboard_js or "userHidden" in dashboard_js
    assert "ihrp_sidebar_groups_v1" in dashboard_js


def test_sidebar_html_toolbar_and_modal(index_html: str):
    assert 'id="sidebarGroupSelect"' in index_html
    assert 'id="btnEditSidebarGroups"' in index_html
    assert 'id="sidebarGroupsModal"' in index_html
    assert 'id="sidebarNavLinks"' in index_html
    assert 'data-i18n="sg.modal_title"' in index_html
    assert 'data-i18n="sg.reset"' in index_html
    # Sidebar links vẫn trỏ section-*
    assert 'href="#section-summary"' in index_html
    assert 'href="#section-gantt"' in index_html


def test_sidebar_group_i18n_keys(i18n_js: str):
    keys = [
        "sg.all", "sg.select_title", "sg.edit_title", "sg.modal_title",
        "sg.reset", "sg.add", "sg.delete", "sg.save", "sg.cancel",
        "sg.name_vi", "sg.name_en", "sg.move", "sg.toast_saved",
        "sg.toast_reset", "sg.confirm_delete", "sg.confirm_reset",
    ]
    for key in keys:
        assert f'"{key}"' in i18n_js, f"missing i18n key {key}"
    # VI + EN packs cả hai
    vi = i18n_js.split("vi: {", 1)[1].split("en: {", 1)[0]
    en = i18n_js.split("en: {", 1)[1]
    assert '"sg.all": "Tất cả"' in vi
    assert '"sg.all": "All"' in en


def test_group_filtered_css(style_css: str):
    assert ".group-filtered-out" in style_css
    assert ".sidebar-group-toolbar" in style_css
    assert ".sidebar-group-select" in style_css


def test_all_sidebar_links_in_default_membership(index_html: str, dashboard_js: str):
    """Mọi link sidebar #section-* phải nằm trong default membership (không orphan)."""
    links = set(re.findall(r'href="#(section-[^"]+)"', index_html))
    # Chỉ lấy trong #sidebarNav
    nav_m = re.search(r'id="sidebarNav".*?</nav>', index_html, re.DOTALL)
    assert nav_m
    nav_links = set(re.findall(r'href="#(section-[^"]+)"', nav_m.group(0)))
    covered = set()
    for secs in _DEFAULT_MEMBERSHIP.values():
        covered |= secs
    missing = nav_links - covered
    assert not missing, f"sidebar links missing from default groups: {sorted(missing)}"
    # Extra in defaults but not in nav is OK (future-proof) — chỉ cảnh báo soft
    assert "section-summary" in nav_links
