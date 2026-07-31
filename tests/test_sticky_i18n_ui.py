"""Smoke tests — sticky hysteresis + sticky/filter i18n coverage (static)."""
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


def test_sticky_hysteresis_thresholds(dashboard_js: str):
    """Enter/leave + lock: gap phải > delta height compact (~150–220px)."""
    enter = re.search(r"STICKY_COMPACT_ENTER_Y\s*=\s*(\d+)", dashboard_js)
    leave = re.search(r"STICKY_COMPACT_LEAVE_Y\s*=\s*(\d+)", dashboard_js)
    lock = re.search(r"STICKY_COMPACT_LOCK_MS\s*=\s*(\d+)", dashboard_js)
    assert enter and leave and lock
    e, lv, lk = int(enter.group(1)), int(leave.group(1)), int(lock.group(1))
    assert e > lv
    # LEAVE gần top — scrollY tụt sau compact không được bật full lại
    assert lv <= 8
    # Gap đủ lớn hơn footprint cards+filter full→compact
    assert (e - lv) >= 100
    assert lk >= 150
    assert "_stickyCurrentMode" in dashboard_js
    assert "_stickyModeLockUntil" in dashboard_js
    assert "_stickyOnScroll" in dashboard_js
    assert "_stickyResolveAutoMode" in dashboard_js
    assert "_stickyResolveModeForY" in dashboard_js


def test_sticky_resolve_mode_hysteresis_band():
    """Pure band: trong (LEAVE, ENTER) giữ mode hiện tại — không flip."""
    # Inline mirror của constants + helper (tránh eval browser file).
    enter, leave = 140, 4

    def resolve(y: int, current: str | None) -> str:
        if current == "compact":
            return "full" if y <= leave else "compact"
        return "compact" if y >= enter else "full"

    # Oscillation giả lập sau compact (Y tụt 150→40): phải giữ compact
    assert resolve(150, "full") == "compact"
    assert resolve(40, "compact") == "compact"
    assert resolve(40, "full") == "full"  # chưa từng enter
    assert resolve(4, "compact") == "full"
    assert resolve(0, "compact") == "full"
    assert resolve(139, "full") == "full"
    assert resolve(140, "full") == "compact"


def test_sticky_css_stable_compact(style_css: str):
    assert "min-height: 88px" in style_css or "min-height:88px" in style_css
    # Không transition padding (gây nhảy khi compact)
    block = re.search(
        r"\.sticky-top-block\s*\{[^}]+\}", style_css, re.DOTALL
    )
    assert block
    assert "padding 0.25s" not in block.group(0)
    assert "overflow-anchor: none" in block.group(0) or "overflow-anchor:none" in block.group(0)


def test_sticky_block_i18n_keys(index_html: str, i18n_js: str):
    required = [
        "section.summary",
        "card.total",
        "card.progress",
        "card.overdue",
        "filter.analyze_by",
        "filter.module_order",
        "filter.clear_all",
        "section.overdue_title",
        "th.code",
        "th.name",
    ]
    for key in required:
        assert f'data-i18n="{key}"' in index_html, f"missing data-i18n={key}"
        assert f'"{key}"' in i18n_js, f"missing dict key {key}"


def test_lang_toggle_shows_current_lang(i18n_js: str, index_html: str):
    """btn.lang = ngôn ngữ đang chọn (VI/EN), không phải ngôn ngữ đích."""
    assert '"btn.lang": "VI"' in i18n_js  # pack vi
    # Pack en phải có btn.lang = EN
    en_pack = i18n_js.split("en: {", 1)[1]
    assert '"btn.lang": "EN"' in en_pack
    assert 'id="btnLangToggle"' in index_html


def test_card_anomaly_preserves_records_span(index_html: str):
    """data-i18n không được bọc cả span records (textContent sẽ xoá span)."""
    assert 'id="cardAnomalyRecords"' in index_html
    # Label riêng, records span sibling
    assert 'data-i18n="card.anomaly"' in index_html
    anomaly_idx = index_html.find('data-i18n="card.anomaly"')
    records_idx = index_html.find('id="cardAnomalyRecords"')
    assert anomaly_idx > 0 and records_idx > anomaly_idx
    # Không còn pattern cũ: data-i18n trên parent chứa span records
    assert not re.search(
        r'data-i18n="card\.anomaly">[^<]*<span id="cardAnomalyRecords"',
        index_html,
    )
