"""
Regression: gear ⚙️ (chart config Phase A) phải chèn INLINE vào action row của
section thay vì absolute top-right — nếu không thì tooltip «Cấu hình title /
caption / ẩn chart này» đè lên nút Xuất (báo user 06/08/2026).

Kiểm tra ở tầng static JS/CSS (không tải browser) — đủ để phát hiện:
- Helper ``_findSectionHeaderActionsHost`` tồn tại + xét cả pattern hub
  (.section-hub-head + .section-tabs-tools) lẫn pattern section thường
  (flex justify-between).
- ``injectChartConfigGears`` gọi helper trên và:
    * Nếu tìm được host → thêm class ``chart-config-gear-inline`` rồi append
      vào host (không dùng absolute).
    * Nếu không tìm được → fallback absolute cũ (giữ nguyên hành vi cho
      section đặc thù).
- Marker ``dataset.gearInjected`` để tránh nhân đôi gear khi re-render
  (không dùng ``:scope .chart-config-gear`` — sẽ match nhầm gear của
  tab-pane con lồng trong hub).
- CSS có variant ``.chart-config-gear-inline`` với ``position: static`` (bỏ
  absolute) để nút thực sự nằm cạnh nút Xuất.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DASHBOARD_JS = (ROOT / "static" / "js" / "dashboard.js").read_text(encoding="utf-8")
STYLE_CSS = (ROOT / "static" / "css" / "style.css").read_text(encoding="utf-8")


def test_helper_finds_actions_host_for_hub_and_regular_sections():
    assert "function _findSectionHeaderActionsHost(" in DASHBOARD_JS
    body = DASHBOARD_JS.split("function _findSectionHeaderActionsHost(")[1].split(
        "function injectChartConfigGears("
    )[0]
    # Hub: bám vào .section-hub-head + .section-tabs-tools
    assert ".section-hub-head .section-tabs-tools" in body
    # Section thường: dò header row bằng flex justify-between hoặc flex items-center
    assert 'flex[class*="justify-between"]' in body
    assert "flex.items-center" in body
    # Chọn container cuối cùng có button/select/col-picker → tránh chọn nhầm div title
    assert "button, select, [data-col-picker]" in body


def test_inject_uses_inline_variant_when_actions_host_found():
    assert "function injectChartConfigGears(" in DASHBOARD_JS
    body = DASHBOARD_JS.split("function injectChartConfigGears(")[1].split(
        "// Phase B: mapping section id"
    )[0]
    # Gọi helper
    assert "_findSectionHeaderActionsHost(sec)" in body
    # Có host → thêm class inline rồi append vào host
    assert '"chart-config-gear-inline"' in body
    assert "actionsHost.appendChild(btn)" in body
    # Không có host → fallback absolute cũ (position + appendChild vào sec)
    assert "sec.style.position = \"relative\"" in body
    assert "sec.appendChild(btn)" in body


def test_inject_uses_marker_not_query_selector_for_idempotency():
    """Tab-pane con trong hub có gear riêng — dùng dataset marker để hub không
    nhầm gear con là gear của mình khi kiểm tra idempotent."""
    body = DASHBOARD_JS.split("function injectChartConfigGears(")[1].split(
        "// Phase B: mapping section id"
    )[0]
    assert 'sec.dataset.gearInjected === "1"' in body
    assert 'sec.dataset.gearInjected = "1"' in body
    # Không được rơi lại vào pattern cũ `:scope .chart-config-gear` (match
    # descendant → sai với hub chứa tab-pane).
    assert ':scope .chart-config-gear"' not in body
    assert ':scope .chart-config-gear\')' not in body


def test_css_defines_inline_variant_without_absolute():
    # CSS variant inline bỏ absolute
    assert ".chart-config-gear-inline" in STYLE_CSS
    css_chunk = STYLE_CSS.split(".chart-config-gear-inline")[1].split("}")[0]
    assert "position: static" in css_chunk
    # Không được vẫn giữ absolute + top/right cứng
    assert "position: absolute" not in css_chunk
