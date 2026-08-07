"""
Regression: dashboard chủ động thông báo khi có bản mới trên GitHub, tránh
2 case user phản hồi (06/08/2026):

  1. "Có bản mới mà tui không biết" — chưa có auto-check remote, chỉ show
     badge khi disk newer than running process. Cần auto-fetch + reflect
     behind commit vào verdict/badge.
  2. "Không có mà tui cứ bấm hoài" — không có feedback rõ ràng khi manual
     check ra kết quả «đã là bản mới nhất». Cần toast + text «Đã kiểm tra N
     phút trước».
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DASHBOARD_JS = (ROOT / "static" / "js" / "dashboard.js").read_text(encoding="utf-8")
INDEX_HTML = (ROOT / "templates" / "index.html").read_text(encoding="utf-8")


def _iife_source() -> str:
    """Cắt lấy đúng module build-status IIFE (~26200–26800) để test focus vào
    đó, tránh false positive từ code khác có cùng từ khoá."""
    # Marker cố định trên đầu IIFE
    start = DASHBOARD_JS.index("PAGE_LOADED_AT = Math.floor(Date.now() / 1000)")
    end = DASHBOARD_JS.index("window.openBuildStatus = openModal", start)
    return DASHBOARD_JS[start:end]


def test_verdict_covers_git_behind_as_update_level():
    body = _iife_source()
    # verdict() có nhánh cho behind > 0
    assert "function verdict(" in body
    verdict = body.split("function verdict(")[1].split("function paintBadge(")[0]
    assert "_git.behind" in verdict
    assert 'level: "update"' in verdict
    assert "commit mới" in verdict
    # Body có gợi ý pull + restart (không tự pull vì lý do dirty tree đã doc)
    assert "git pull" in verdict


def test_badge_has_dedicated_icon_for_update():
    body = _iife_source()
    paint = body.split("function paintBadge(")[1].split("function _maybeToastRemoteUpdate(")[0]
    # Emoji riêng cho «có update»
    assert '"update"' in paint
    assert "🆕" in paint


def test_ok_verdict_includes_remote_status_when_known():
    """Khi remote đã fetched behind=0 → verdict OK phải nói rõ «Không có
    commit mới» để user không phải mở modal chỉ để xác nhận."""
    body = _iife_source()
    verdict = body.split("function verdict(")[1].split("function paintBadge(")[0]
    assert "Không có commit mới trên GitHub" in verdict


def test_auto_check_git_wired_to_boot_and_focus():
    body = _iife_source()
    assert "function _autoCheckGit(" in body
    assert "AUTO_GIT_CHECK_COOLDOWN_MS" in body
    assert "AUTO_GIT_CHECK_KEY" in body
    # Cooldown share qua localStorage
    assert "_readLastGitCheck(" in body
    assert "_writeLastGitCheck(" in body
    # DOMContentLoaded gọi auto-check sau delay + focus listener
    domready = body.split('addEventListener("DOMContentLoaded"')[1]
    assert '_autoCheckGit("boot")' in domready
    assert '_autoCheckGit("focus")' in domready
    assert "AUTO_GIT_CHECK_BOOT_DELAY_MS" in domready


def test_manual_check_shows_toast_for_both_states():
    """Manual bấm «Kiểm tra» → toast rõ:
      - có update: toast «GitHub có N commit mới»
      - không có: toast «Đã là bản mới nhất»
    Cả 2 case xử lý case «no update», khắc phục việc user bấm không thấy feedback.
    """
    body = _iife_source()
    check = body.split("async function checkGithub(")[1].split(
        "// ------------------------------------------------------------------\n    // Restart"
    )[0]
    assert "_maybeToastRemoteUpdate" in check
    assert "Đã là bản mới nhất trên GitHub" in check
    # Manual bấm cũng phải update timestamp để cooldown lần sau tính từ đây
    assert "_writeLastGitCheck(" in check
    # Không cần chờ mở modal — repaint badge sau khi có kết quả
    assert "paintBadge()" in check


def test_toast_dedupes_by_behind_count():
    body = _iife_source()
    fn = body.split("function _maybeToastRemoteUpdate(")[1].split(
        "/** Auto-check remote"
    )[0]
    # Chỉ toast khi số commit đổi — tránh spam
    assert "_lastToastBehind" in fn
    # Reset khi behind về 0 để commit mới lần sau vẫn toast được
    assert "_lastToastBehind = 0" in fn


def test_render_git_shows_last_checked_stamp():
    body = _iife_source()
    render = body.split("function renderGit(")[1].split(
        "async function checkGithub("
    )[0]
    assert "_readLastGitCheck(" in render
    assert "Đã kiểm tra" in render
    assert "_formatRelativeMinutes(" in render


def test_html_placeholder_reflects_auto_check():
    """Text mặc định trong ô git phải nói rõ đang auto-check, không phải
    «Chưa kiểm tra» (gợi ý user phải bấm)."""
    assert "Chưa kiểm tra. Việc này gọi" not in INDEX_HTML
    assert "Đang tự động kiểm tra sau khi mở trang" in INDEX_HTML
