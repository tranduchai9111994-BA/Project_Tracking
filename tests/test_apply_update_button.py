"""
Regression: 1 nút gộp «Áp dụng bản mới» thay cho 2 nút Restart / Tải lại giao diện.

Yêu cầu user 06/08/2026: "gom chung hết vào 1 nút giúp tôi làm cả 2 việc".
Trước đây user phải quyết định bấm nút nào; giờ JS tự chọn theo verdict.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DASHBOARD_JS = (ROOT / "static" / "js" / "dashboard.js").read_text(encoding="utf-8")
INDEX_HTML = (ROOT / "templates" / "index.html").read_text(encoding="utf-8")


def _iife_source() -> str:
    start = DASHBOARD_JS.index("PAGE_LOADED_AT = Math.floor(Date.now() / 1000)")
    end = DASHBOARD_JS.index("window.openBuildStatus = openModal", start)
    return DASHBOARD_JS[start:end]


class TestHtml:
    def test_single_button_replaces_two(self):
        """Không còn 2 nút riêng — chỉ 1 nút gộp."""
        # Nút mới có
        assert 'id="btnApplyUpdate"' in INDEX_HTML
        assert 'onclick="applyUpdate()"' in INDEX_HTML
        assert 'id="btnApplyUpdateIcon"' in INDEX_HTML
        assert 'id="btnApplyUpdateLabel"' in INDEX_HTML
        # 2 nút cũ đã bị gỡ
        assert 'id="btnRestartServer"' not in INDEX_HTML
        assert 'onclick="restartServer()"' not in INDEX_HTML
        assert 'onclick="location.reload()"' not in INDEX_HTML

    def test_button_default_label(self):
        """Trước khi JS chạy, nút phải có nhãn/icon mặc định — không rỗng."""
        idx = INDEX_HTML.index('id="btnApplyUpdate"')
        snippet = INDEX_HTML[idx: idx + 800]
        assert "Áp dụng bản mới" in snippet
        assert "🔄" in snippet


class TestJs:
    def test_apply_update_is_exported_globally(self):
        assert "window.applyUpdate = applyUpdate" in DASHBOARD_JS
        # Backward compat — restart cũ vẫn được export
        assert "window.restartServer = restart" in DASHBOARD_JS

    def test_apply_update_chooses_restart_when_needed(self):
        """`applyUpdate` phải phân nhánh theo verdict:
          - restart/update + restart_available → gọi restart()
          - else → location.reload()
        """
        body = _iife_source()
        fn_start = body.index("async function applyUpdate(")
        fn = body[fn_start:]
        fn = fn[: fn.index("window.applyUpdate")] if "window.applyUpdate" in fn else fn[:2000]
        assert 'v.level === "restart"' in fn
        assert 'v.level === "update"' in fn
        assert "_info.restart_available" in fn
        assert "await restart()" in fn
        assert "location.reload()" in fn

    def test_apply_update_refreshes_when_info_missing(self):
        """Bấm nút khi chưa poll xong → phải refresh() để có verdict đúng,
        tránh vô tình chỉ reload khi thực sự cần restart."""
        body = _iife_source()
        idx = body.index("async function applyUpdate(")
        fn = body[idx: idx + 1200]
        assert "if (!_info) await refresh()" in fn

    def test_paint_apply_btn_covers_all_states(self):
        """`_paintApplyBtn` phải xử lý cả 4 nhánh: restart, update, reload, ok +
        fallback khi restart_available=false."""
        body = _iife_source()
        idx = body.index("function _paintApplyBtn(")
        fn = body[idx: idx + 2500]
        # Data attr giúp test/CSS biết state hiện tại
        assert 'btn.dataset.action' in fn
        # Nhãn hai chế độ
        assert "Restart & tải lại" in fn
        assert "Tải lại giao diện" in fn
        # Fallback khi không restart được — vẫn cho reload, không disable cứng
        assert "restart_blocked_reason" in fn
        assert "btn.disabled = false" in fn

    def test_render_calls_paint_apply_btn(self):
        """`render()` (mở modal) phải cập nhật nút — không giữ nhãn từ lần trước."""
        body = _iife_source()
        render = body[body.index("function render("): body.index("function _formatRelativeMinutes(")]
        assert "_paintApplyBtn()" in render
