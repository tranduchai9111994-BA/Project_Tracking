"""
Chặn ReferenceError trong JS — loại bug mà toàn bộ suite Python không thấy được.

Bối cảnh: `apFetch is not defined` (Báo cáo tuần) chỉ nổ lúc chạy, trong nhánh
catch, nên hiện ra dưới dạng toast mơ hồ. Không test Python nào bắt được vì lỗi
nằm ở tầng trình duyệt. ESLint với rule `no-undef` hiểu scope thật nên bắt chính
xác, gần như không báo sai.

Cấu hình globals dùng chung nằm ở `eslint.config.mjs` (tự sinh từ AST của các
file JS, vì static/js là classic script chia sẻ global scope).

Bỏ qua khi máy không có Node — app chạy bằng Python, Node chỉ là tooling.
"""
import json
import os
import shutil
import subprocess

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
JS_DIR = os.path.join(ROOT, "static", "js")


def _npx() -> str | None:
    """Trên Windows npx là .cmd; shutil.which lo phần đuôi mở rộng."""
    return shutil.which("npx") or shutil.which("npx.cmd")


requires_node = pytest.mark.skipif(
    _npx() is None or not os.path.isdir(os.path.join(ROOT, "node_modules", "eslint")),
    reason="cần Node + `npm install` (devDependencies) để chạy ESLint",
)


def _run_eslint(*targets: str) -> list[dict]:
    """Trả về danh sách file-result của ESLint (format json)."""
    proc = subprocess.run(
        [_npx(), "--no-install", "eslint", "--format", "json", *targets],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=300,
    )
    out = (proc.stdout or "").strip()
    if not out:
        pytest.fail(f"ESLint không trả JSON.\nstdout={proc.stdout!r}\nstderr={proc.stderr!r}")
    # ESLint có thể in cảnh báo trước JSON; lấy từ dấu '[' đầu tiên.
    return json.loads(out[out.index("[") :])


@requires_node
def test_khong_co_bien_ham_chua_dinh_nghia():
    """static/js phải sạch no-undef."""
    results = _run_eslint("static/js")
    loi = [
        f"{os.path.relpath(f['filePath'], ROOT)}:{m['line']}:{m['column']} "
        f"{m['message']}"
        for f in results
        for m in f.get("messages", [])
    ]
    assert not loi, "ESLint phát hiện tham chiếu chưa định nghĩa:\n  " + "\n  ".join(loi)


@requires_node
def test_eslint_that_su_quet_file(tmp_path):
    """
    Canary: test trên sẽ pass rỗng nếu config hỏng và ESLint không quét gì.

    Nên phải chứng minh guard còn sống bằng cách chèn đúng lỗi đã từng xảy ra
    (`apFetch`) vào một file trong static/js rồi kiểm ESLint có tố giác không.
    File tạm không được index.html nạp (script được liệt kê tường minh).
    """
    canary = os.path.join(JS_DIR, "_eslint_canary_tmp.js")
    with open(canary, "w", encoding="utf-8") as f:
        f.write("function _canary() { return apFetch('/x'); }\n")
    try:
        results = _run_eslint("static/js/_eslint_canary_tmp.js")
        rules = [m.get("ruleId") for f in results for m in f.get("messages", [])]
        msgs = [m.get("message") for f in results for m in f.get("messages", [])]
        assert "no-undef" in rules, f"ESLint không bắt được lỗi cố ý: {msgs}"
        assert any("apFetch" in (m or "") for m in msgs)
    finally:
        os.unlink(canary)


@requires_node
def test_globals_dung_chung_duoc_tu_sinh():
    """
    Danh sách globals chia sẻ phải sinh từ AST, không phải liệt kê tay — liệt kê
    tay sẽ lạc hậu và người ta sẽ tắt rule cho đỡ ồn.

    Kiểm bằng hàm định nghĩa ở dashboard.js nhưng gọi từ sidebar_hubs.js: nếu cơ
    chế này chết thì no-undef sẽ báo sai hàng loạt (đã từng 81 lỗi).
    """
    cfg = os.path.join(ROOT, "eslint.config.mjs")
    with open(cfg, encoding="utf-8") as f:
        src = f.read()
    assert "espree.parse" in src, "phải dùng parser thật, không regex"
    assert "readdirSync" in src, "phải quét thư mục, không hardcode danh sách file"
