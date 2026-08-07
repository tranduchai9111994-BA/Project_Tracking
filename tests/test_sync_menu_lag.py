"""
Regression: nút Đồng bộ mở menu ngay, không chờ API vài giây.

Bug trước (06/08/2026):
  1. Prefetch dùng timeout 1200ms với slug còn «default» → cache rỗng +
     capabilities đã set → lần sau không refetch → hiện «Chưa có integration»
     dù MPHG đã có.
  2. toggleSyncQuickMenu gọi refresh (await fetch) trước khi user thấy list
     → cảm giác lag vài giây.

Fix:
  - Cache theo loadedSlug; invalidate khi switchProject.
  - Prefetch sau loadProjectList().then (đúng slug).
  - Mở menu ngay: cache hit → list; miss → «Đang tải…» rồi fill nền.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
JS = (ROOT / "static" / "js" / "dashboard.js").read_text(encoding="utf-8")
APP = (ROOT / "app.py").read_text(encoding="utf-8")


def test_integ_state_tracks_loaded_slug():
    assert "loadedSlug:" in JS or "loadedSlug =" in JS
    assert "_integFetchForSlug" in JS


def test_toggle_opens_menu_before_await():
    """toggleSyncQuickMenu phải unhide menu trước khi phụ thuộc fetch xong."""
    body = JS.split("function toggleSyncQuickMenu(")[1].split(
        "window.toggleSyncQuickMenu"
    )[0]
    # Mở menu ngay
    assert 'menu.classList.remove("hidden")' in body
    # Có skeleton khi miss cache
    assert "Đang tải danh sách API" in body
    # Refresh chạy nền, không block unhide
    assert "_integRefreshSyncQuickMenu({ background: true })" in body
    # unhide phải xuất hiện trước lời gọi refresh trong source (thứ tự đọc)
    # — thực tế: skeleton/render trước, rồi unhide, rồi background refresh.
    idx_unhide = body.index('menu.classList.remove("hidden")')
    idx_bg = body.index("_integRefreshSyncQuickMenu({ background: true })")
    assert idx_unhide < idx_bg


def test_prefetch_after_load_project_list():
    assert "_integPrefetchAfterProjectReady" in JS
    assert "loadProjectList().then" in JS
    # Gắn trong then của loadProjectList
    then_body = JS.split("loadProjectList().then(() => {")[1].split("});")[0]
    assert "_integPrefetchAfterProjectReady" in then_body


def test_switch_project_invalidates_cache():
    body = JS.split("async function switchProject(")[1].split(
        "async function tryLoadDashboardForCurrent"
    )[0]
    assert "_integState.loadedSlug = null" in body
    assert "_integPrefetchAfterProjectReady" in body


def test_no_legacy_blind_1200ms_refresh():
    """Không còn setTimeout 1200ms gọi _integRefreshSyncQuickMenu với slug mù."""
    assert "}, 1200);\n});\n\n\n// ==========================================================================\n// GANTT CALENDAR" not in JS
    # Marker cũ trong comment/code
    legacy = 'setTimeout(() => {\n        if (typeof currentProjectSlug === "string" && currentProjectSlug) {\n            _integRefreshSyncQuickMenu();\n        }\n    }, 1200);'
    assert legacy not in JS


def test_app_eager_imports_integrations():
    assert "_integ_warm" in APP
    assert "from analyzer import integrations as _integ_warm" in APP
