"""Smoke: sau sync FE phải reload stalled (metrics) + section lazy với cache-bust.

Root cause regression (324f11b thiếu):
- `_refreshAfterSync` chỉ reset `_presentState.loaded` (presentation) +
  `/dashboard?_=` — không hủy filter-fetch đang bay, không reset pageState
  stalled, không bust cache lazy DQ/aging/…
- Response /dashboard cũ có thể đè `metricsData.stalled_tasks` sau sync.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DASHBOARD_JS = (ROOT / "static" / "js" / "dashboard.js").read_text(encoding="utf-8")


def test_refresh_after_sync_resets_stalled_pages_and_lazy_caches():
    assert "async function _refreshAfterSync(" in DASHBOARD_JS
    assert "function _resetListPagesAfterSync(" in DASHBOARD_JS
    assert "function _clearLazySectionCaches(" in DASHBOARD_JS
    # Stalled nằm trong list page reset
    chunk = DASHBOARD_JS.split("function _resetListPagesAfterSync(")[1].split(
        "function _clearLazySectionCaches("
    )[0]
    assert '"stalled"' in chunk or "'stalled'" in chunk


def test_refresh_after_sync_cancels_filter_fetch_and_sets_cache_bust():
    chunk = DASHBOARD_JS.split("async function _refreshAfterSync(")[1].split(
        "window._refreshAfterSync"
    )[0]
    assert "_filterFetchTimer" in chunk
    assert "_cacheBustToken" in chunk
    assert "_resetListPagesAfterSync()" in chunk
    assert "_clearLazySectionCaches()" in chunk
    assert "tryLoadDashboardForCurrent(true, { cacheBust: true })" in chunk


def test_dashboard_load_gen_ignores_stale_response():
    assert "let _dashboardLoadGen = 0" in DASHBOARD_JS
    assert "gen !== _dashboardLoadGen" in DASHBOARD_JS
    # Cả tryLoadDashboardForCurrent và _doGlobalFilterFetch phải guard
    assert DASHBOARD_JS.count("gen !== _dashboardLoadGen") >= 2


def test_build_filter_query_and_lazy_urls_support_cache_bust():
    assert "function _appendCacheBust(" in DASHBOARD_JS
    bfq = DASHBOARD_JS.split("function _buildFilterQuery(")[1].split(
        "function _appendCacheBust("
    )[0]
    assert "_cacheBustToken" in bfq
    # Lazy endpoints gắn bust
    assert "_appendCacheBust(url)" in DASHBOARD_JS


def test_render_dashboard_still_renders_stalled_from_metrics():
    """Stalled không lazy-fetch riêng — phải re-render từ metrics payload."""
    rd = DASHBOARD_JS.split("function renderDashboard(")[1].split(
        "function renderSummaryCards("
    )[0]
    assert 'renderStalledSection' in rd
    assert "function renderStalledSection(" in DASHBOARD_JS
