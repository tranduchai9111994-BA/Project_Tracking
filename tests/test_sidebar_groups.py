"""Smoke tests — sidebar hub redesign (12 hubs + groups + search)."""
from __future__ import annotations

import os
import re

import pytest

ROOT = os.path.join(os.path.dirname(__file__), "..")
DASHBOARD_JS = os.path.join(ROOT, "static", "js", "dashboard.js")
SIDEBAR_HUBS_JS = os.path.join(ROOT, "static", "js", "sidebar_hubs.js")
I18N_JS = os.path.join(ROOT, "static", "js", "i18n.js")
INDEX_HTML = os.path.join(ROOT, "templates", "index.html")
STYLE_CSS = os.path.join(ROOT, "static", "css", "style.css")


@pytest.fixture(scope="module")
def dashboard_js() -> str:
    with open(DASHBOARD_JS, encoding="utf-8") as f:
        return f.read()


@pytest.fixture(scope="module")
def sidebar_hubs_js() -> str:
    with open(SIDEBAR_HUBS_JS, encoding="utf-8") as f:
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


_DEFAULT_MEMBERSHIP = {
    "overview": {"section-summary", "section-module-progress"},
    "issues": {"section-issues", "section-risk-hub"},
    "progress": {"section-timeline", "section-weekly"},
    "forecast": {"section-plan", "section-manpower"},
    "analysis": {"section-analysis"},
    "admin": {"section-admin"},
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
    assert 'name_vi: "Phân tích"' in block
    assert 'name_en: "Analysis"' in block
    assert 'name_vi: "Quản trị"' in block
    assert 'name_en: "Administration"' in block


def test_default_membership_map(dashboard_js: str):
    block = _extract_default_group_block(dashboard_js)
    seen = {}
    for gid, sections in _DEFAULT_MEMBERSHIP.items():
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


def test_hub_defs_in_sidebar_hubs_js(sidebar_hubs_js: str):
    for hid in (
        "section-module-progress", "section-issues", "section-risk-hub",
        "section-timeline", "section-weekly", "section-plan",
        "section-manpower", "section-analysis", "section-admin",
    ):
        assert hid in sidebar_hubs_js
    assert "ihrp.tab." in sidebar_hubs_js
    assert "ihrp.sidebar.collapsed." in sidebar_hubs_js
    assert "function migrateSectionOrder" in sidebar_hubs_js
    assert "function scrollToSection" in sidebar_hubs_js


def test_filter_all_vs_one_group_api(dashboard_js: str):
    assert 'SIDEBAR_GROUP_ALL = "__all__"' in dashboard_js
    assert "function applySidebarGroupFilter()" in dashboard_js
    assert "group-filtered-out" in dashboard_js
    assert "ihrp_sidebar_groups_v2" in dashboard_js


def test_sidebar_html_search_and_hubs(index_html: str):
    assert 'id="sidebarSearchInput"' in index_html
    assert 'id="sidebarNavLinks"' in index_html
    assert "sidebar-nav--v2" in index_html
    assert 'href="#section-summary"' in index_html
    assert 'href="#section-module-progress"' in index_html
    assert 'href="#section-issues"' in index_html
    assert "sidebar_hubs.js" in index_html
    # Dropdown Tất cả đã thay bằng search
    assert 'id="sidebarGroupSelect"' in index_html  # hidden compat
    assert "sidebar-search" in index_html


def test_sidebar_group_i18n_keys(i18n_js: str):
    # Legacy sg.* keys vẫn giữ (modal editor)
    for key in ("sg.all", "sg.modal_title", "sg.save", "sg.cancel"):
        assert f'"{key}"' in i18n_js, f"missing i18n key {key}"


def test_group_filtered_css(style_css: str):
    assert ".group-filtered-out" in style_css
    assert ".sidebar-nav-item" in style_css
    assert ".section-tabs" in style_css
    assert ".sidebar-badge" in style_css


def test_all_sidebar_links_in_default_membership(index_html: str, dashboard_js: str):
    nav_m = re.search(r'id="sidebarNav".*?</nav>', index_html, re.DOTALL)
    assert nav_m
    nav_links = set(re.findall(r'href="#(section-[^"]+)"', nav_m.group(0)))
    covered = set()
    for secs in _DEFAULT_MEMBERSHIP.values():
        covered |= secs
    missing = nav_links - covered
    assert not missing, f"sidebar links missing from default groups: {sorted(missing)}"
    assert "section-summary" in nav_links
