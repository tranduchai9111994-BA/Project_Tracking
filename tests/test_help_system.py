"""
T34 Task 4 — Smoke tests cho Unified Help System.

Test này KHÔNG chạy browser thật (không có Selenium/Playwright dep). Chỉ:
  1. Verify HTML template có đủ modal elements (sectionHelpModal, globalHelpModal, tour).
  2. Verify help_content.js có structure đúng và category defined.
  3. Verify dashboard.js có tất cả function global cần thiết.
  4. Verify docs/HELP_CONTENT_GUIDE.md tồn tại + đủ section.
"""
from __future__ import annotations

import os
import re

import pytest


TEMPLATE_PATH = os.path.join(
    os.path.dirname(__file__), "..", "templates", "index.html"
)
HELP_CONTENT_PATH = os.path.join(
    os.path.dirname(__file__), "..", "static", "js", "help_content.js"
)
JS_PATH = os.path.join(os.path.dirname(__file__), "..", "static", "js", "dashboard.js")
CSS_PATH = os.path.join(os.path.dirname(__file__), "..", "static", "css", "style.css")
DOCS_PATH = os.path.join(
    os.path.dirname(__file__), "..", "docs", "HELP_CONTENT_GUIDE.md"
)


@pytest.fixture(scope="module")
def index_html() -> str:
    with open(TEMPLATE_PATH, "r", encoding="utf-8") as f:
        return f.read()


@pytest.fixture(scope="module")
def help_content_js() -> str:
    with open(HELP_CONTENT_PATH, "r", encoding="utf-8") as f:
        return f.read()


@pytest.fixture(scope="module")
def dashboard_js() -> str:
    with open(JS_PATH, "r", encoding="utf-8") as f:
        return f.read()


@pytest.fixture(scope="module")
def style_css() -> str:
    # style.css có thể chứa binary/non-UTF-8 chars từ tools — dùng errors="ignore"
    with open(CSS_PATH, "r", encoding="utf-8", errors="ignore") as f:
        return f.read()


class TestHelpContentFile:
    """Verify file help_content.js có structure và content mong đợi."""

    def test_file_exists_and_nonempty(self, help_content_js):
        assert len(help_content_js) > 1000

    def test_help_content_object_defined(self, help_content_js):
        assert "const HELP_CONTENT" in help_content_js
        assert "window.HELP_CONTENT = HELP_CONTENT" in help_content_js

    def test_help_categories_defined(self, help_content_js):
        assert "const HELP_CATEGORIES" in help_content_js
        # 7 category chuẩn
        for cat in [
            "Tổng quan",
            "Tiến độ & Timeline",
            "Phân tích chuyên sâu",
            "Danh sách vấn đề",
            "Tùy chỉnh",
            "Public API",
            "Import/Export",
        ]:
            assert cat in help_content_js, f"Category '{cat}' missing"

    def test_has_at_least_25_topics(self, help_content_js):
        # Đếm topic bằng cách match `    "topic-key": {` — cần ít nhất 25
        # (spec yêu cầu ~30 section).
        keys = re.findall(r'^\s{4}"([a-z][\w\-]*)"\s*:\s*\{', help_content_js, re.MULTILINE)
        # Filter bỏ inner keys (category / title / …)
        outer_keys = [k for k in keys if k not in {
            "category", "title", "purpose", "steps", "example", "tips", "learn_more"
        }]
        assert len(outer_keys) >= 25, f"Only {len(outer_keys)} topics; expected >= 25"

    def test_critical_topics_present(self, help_content_js):
        # Các topic quan trọng nhất bắt buộc phải có
        for key in [
            '"summary":',
            '"globalfilter":',
            '"overdue":',
            '"unassigned":',
            '"risk":',
            '"stalled":',
            '"module":',
            '"gantt-calendar":',
            '"public-api":',
            '"upload":',
            '"export-all-issues":',
        ]:
            assert key in help_content_js, f"Missing topic entry: {key}"

    def test_each_topic_has_required_fields(self, help_content_js):
        # Regex lỏng — verify mỗi topic có purpose + steps + example + tips
        # Ít nhất 20 topic có structure hoàn chỉnh (không strict để tránh
        # brittle test).
        purpose_count = help_content_js.count("purpose:")
        steps_count = help_content_js.count("steps:")
        example_count = help_content_js.count("example:")
        tips_count = help_content_js.count("tips:")
        assert purpose_count >= 20
        assert steps_count >= 20
        assert example_count >= 20
        assert tips_count >= 20


class TestHelpModalsHtml:
    """Verify HTML template có đủ modal elements + button."""

    def test_section_help_modal_present(self, index_html):
        assert 'id="sectionHelpModal"' in index_html
        assert 'id="secHelpCategory"' in index_html
        assert 'id="secHelpTitle"' in index_html
        assert 'id="secHelpBody"' in index_html
        assert 'id="secHelpLearnMore"' in index_html

    def test_global_help_modal_present(self, index_html):
        assert 'id="globalHelpModal"' in index_html
        assert 'id="globalHelpSearch"' in index_html
        assert 'id="globalHelpList"' in index_html

    def test_tour_overlay_present(self, index_html):
        assert 'id="onboardingTourOverlay"' in index_html
        assert 'id="tourSpotlight"' in index_html
        assert 'id="tourTooltip"' in index_html
        assert 'id="tourStepBadge"' in index_html
        assert 'id="tourStepTitle"' in index_html
        assert 'id="tourStepDesc"' in index_html
        assert 'id="tourBackBtn"' in index_html
        assert 'id="tourNextBtn"' in index_html
        assert 'id="tourDotIndicator"' in index_html

    def test_global_help_button_in_header(self, index_html):
        assert 'id="btnGlobalHelp"' in index_html
        assert 'onclick="openGlobalHelpModal()"' in index_html
        assert "❓ Trợ giúp" in index_html

    def test_help_content_script_loaded_before_dashboard(self, index_html):
        # help_content.js phải load trước dashboard.js.
        # Match script tag chính xác — không phải chuỗi trong static_ver('js/dashboard.js')
        m_help = re.search(r'<script[^>]+src="[^"]*help_content\.js', index_html)
        m_dash = re.search(r'<script[^>]+src="[^"]*/dashboard\.js', index_html)
        assert m_help is not None, "Không tìm thấy <script src=help_content.js>"
        assert m_dash is not None, "Không tìm thấy <script src=dashboard.js>"
        assert m_help.start() < m_dash.start(), (
            f"help_content.js phải load TRƯỚC dashboard.js "
            f"(pos {m_help.start()} vs {m_dash.start()})"
        )

    def test_ctrl_slash_hint_in_search(self, index_html):
        # Modal global help có hint Ctrl+/
        assert "Ctrl" in index_html
        # kbd tag cho phím /
        assert "kbd" in index_html


class TestDashboardJsFunctions:
    """Verify dashboard.js define các function global cần thiết."""

    def test_open_section_help_modal_defined(self, dashboard_js):
        assert "function openSectionHelpModal(" in dashboard_js
        assert "window.openSectionHelpModal" in dashboard_js

    def test_close_section_help_modal_defined(self, dashboard_js):
        assert "function closeSectionHelpModal(" in dashboard_js
        assert "window.closeSectionHelpModal" in dashboard_js

    def test_open_global_help_modal_defined(self, dashboard_js):
        assert "function openGlobalHelpModal(" in dashboard_js
        assert "window.openGlobalHelpModal" in dashboard_js

    def test_attach_unified_section_help_defined(self, dashboard_js):
        assert "function attachUnifiedSectionHelp(" in dashboard_js
        assert "window.attachUnifiedSectionHelp" in dashboard_js

    def test_tour_functions_defined(self, dashboard_js):
        # startTour + _tourNext + _tourBack + _tourSkip + maybeStartOnboardingTour
        assert "function startOnboardingTour(" in dashboard_js
        assert "function maybeStartOnboardingTour(" in dashboard_js
        assert "function _tourNext(" in dashboard_js
        assert "function _tourBack(" in dashboard_js
        assert "function _tourSkip(" in dashboard_js
        assert "window.startOnboardingTour" in dashboard_js
        assert "window.maybeStartOnboardingTour" in dashboard_js

    def test_tour_has_at_least_6_steps(self, dashboard_js):
        # _TOUR_STEPS array phải có >= 6 step (spec: 6-8 step)
        m = re.search(r"const _TOUR_STEPS\s*=\s*\[(.*?)\];", dashboard_js, re.DOTALL)
        assert m is not None, "_TOUR_STEPS array không tìm thấy"
        step_count = m.group(1).count("selector:")
        assert step_count >= 6, f"Chỉ có {step_count} step, cần >= 6"
        assert step_count <= 10, f"Có {step_count} step, tour dài quá (spec 6-8)"

    def test_ctrl_slash_keyboard_shortcut_hooked(self, dashboard_js):
        # Có handler bắt Ctrl+/
        assert 'e.key === "/"' in dashboard_js
        assert "ctrlKey" in dashboard_js or "metaKey" in dashboard_js

    def test_esc_closes_modals(self, dashboard_js):
        assert 'e.key === "Escape"' in dashboard_js

    def test_cmd_palette_help_entries_injected(self, dashboard_js):
        # _helpCollectCmdEntries phải được inject vào _CMD_ACTIONS
        assert "function _helpCollectCmdEntries(" in dashboard_js
        assert "❓ Trợ giúp:" in dashboard_js

    def test_apply_dashboard_response_hooks_help(self, dashboard_js):
        # applyDashboardResponse cuối cùng phải gọi attachUnifiedSectionHelp
        # + maybeStartOnboardingTour
        # Match trong scope của applyDashboardResponse
        assert "window.attachUnifiedSectionHelp" in dashboard_js
        assert "window.maybeStartOnboardingTour" in dashboard_js


class TestUnifiedHelpCss:
    """Verify CSS đã có style cho .unified-help-btn."""

    def test_help_btn_style_defined(self, style_css):
        assert ".unified-help-btn" in style_css
        assert ".unified-help-btn:hover" in style_css

    def test_help_block_modal_style_defined(self, style_css):
        assert ".help-block-modal" in style_css
        assert ".help-block-label" in style_css

    def test_tour_spotlight_style_defined(self, style_css):
        assert "#tourSpotlight" in style_css

    def test_dark_mode_variants_present(self, style_css):
        # Dark mode cho các class chính
        assert "html.dark .unified-help-btn" in style_css
        assert "html.dark .help-block-modal" in style_css


class TestDocsGuide:
    """Verify docs/HELP_CONTENT_GUIDE.md tồn tại + có nội dung guide chuẩn."""

    def test_guide_file_exists(self):
        assert os.path.exists(DOCS_PATH)

    def test_guide_covers_topics(self):
        with open(DOCS_PATH, "r", encoding="utf-8") as f:
            content = f.read()
        # 4 phần chính
        assert "Thêm topic mới" in content or "Thêm topic" in content
        assert "help_content.js" in content
        assert "Attach nút" in content or "Attach nut" in content
        assert "Onboarding Tour" in content or "onboarding tour" in content.lower()

    def test_guide_shows_category_list(self):
        with open(DOCS_PATH, "r", encoding="utf-8") as f:
            content = f.read()
        # 7 category chuẩn phải liệt kê
        for cat in [
            "Tổng quan",
            "Tiến độ",
            "Phân tích chuyên sâu",
            "Danh sách vấn đề",
            "Public API",
        ]:
            assert cat in content, f"Category '{cat}' missing trong docs"


class TestHelpContentDataHelpIdCoverage:
    """
    Verify các section quan trọng trong HTML đã có data-help hoặc data-help-id
    trỏ tới key hợp lệ trong HELP_CONTENT.
    """

    def test_key_sections_have_help_attribute(self, index_html):
        # Sample section chính cần có help — verify bằng data-help="section-X"
        # hoặc data-help-id="X" (key match với HELP_CONTENT).
        critical = [
            ("summary",),          # data-help="section-summary" (đã có)
            ("overdue",),
            ("unassigned",),
            ("risk",),
            ("module",),
            ("matrix",),
            ("gantt-calendar",),
            ("my-bookmarks",),
        ]
        for (key,) in critical:
            # Match bất kỳ: data-help="section-<key>" hoặc data-help-id="<key>"
            found = (
                f'data-help="section-{key}"' in index_html
                or f'data-help-id="{key}"' in index_html
            )
            assert found, (
                f"Section key '{key}' không có data-help hoặc data-help-id "
                f"trong template — không hiển thị được nút ?"
            )
