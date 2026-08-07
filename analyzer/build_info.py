"""
Phát hiện code trên đĩa đã mới hơn process đang chạy.

Bối cảnh: `start.bat` chạy Flask ở chế độ PRODUCTION (`debug=False`) nên **không
auto-reload**. Sửa `.py` hoặc `templates/` xong mà quên restart thì server vẫn
phục vụ bản cũ, và trước đây không có cách nào biết ngoài việc đoán. Trạng thái
lai đó đã gây ra vài lần truy bug rất tốn công (xem docs/ARCHITECTURE.md).

Nguyên tắc: **không hardcode danh sách file cần theo dõi.** Danh sách hardcode sẽ
lạc hậu ngay khi thêm module mới. Thay vào đó lấy từ `sys.modules` — đúng những
file mà process *đang thực sự nạp*. Cách này tự động bỏ qua `venv/`,
`node_modules/`, `tests/` và các script ad-hoc ở root, mà không cần liệt kê loại trừ.
"""
from __future__ import annotations

import os
import subprocess
import sys
import time
from typing import Iterable, Optional

# Template Jinja được biên dịch và giữ trong RAM khi debug=False, nên đổi file
# .html cũng đòi restart. Chúng không nằm trong sys.modules nên phải quét riêng.
TEMPLATE_EXTS = (".html",)

# Đổi JS/CSS thì chỉ cần reload trang, không cần restart: Flask phục vụ static
# kèm `Cache-Control: no-cache` + ETag nên nội dung mới về ngay sau một lần reload.
STATIC_SUBDIRS = ("js", "css")
STATIC_EXTS = (".js", ".css")

_GIT_TIMEOUT = 20


def _mtime(path: str) -> Optional[float]:
    try:
        return os.path.getmtime(path)
    except OSError:
        return None


def _is_inside(path: str, root: str) -> bool:
    """
    `path` có nằm trong `root` hay không.

    Không dùng `os.path.commonpath`: nó **raise ValueError** khi hai đường dẫn
    khác ổ đĩa, mà đó là trường hợp thường xuyên — stdlib nằm ở C: còn project ở
    D:. `normcase` là bắt buộc vì đường dẫn Windows không phân biệt hoa thường.
    """
    p = os.path.normcase(os.path.abspath(path))
    r = os.path.normcase(os.path.abspath(root)).rstrip(os.sep)
    return p == r or p.startswith(r + os.sep)


def _dependency_roots() -> list[str]:
    """
    Thư mục chứa **thư viện của người khác**, cần loại khỏi "code của mình".

    Lấy từ runtime chứ không hardcode tên `venv`: `start.bat` tạo venv **bên trong**
    project, nên nếu không loại thì toàn bộ site-packages bị tính là source của
    project — đo được 317 file thay vì 29, badge sẽ đầy path của thư viện. Cách này
    đúng cho cả `.venv`, `env` hay tên khác.

    Khi không chạy trong venv, `sys.prefix` trỏ ra ngoài project nên vô hại.
    """
    roots = [sys.prefix, getattr(sys, "base_prefix", sys.prefix)]
    try:
        import site

        roots.extend(site.getsitepackages())
        user_site = site.getusersitepackages()
        if isinstance(user_site, str):
            roots.append(user_site)
    except (ImportError, AttributeError):
        pass
    return [r for r in roots if r]


def loaded_source_files(root: str) -> list[str]:
    """
    File .py mà process đang nạp, nằm trong `root` và **là code của project**.

    Hạn chế đã biết: module **mới thêm mà chưa được import** sẽ không thấy. Trên
    thực tế không thành vấn đề vì thêm module luôn kèm sửa file đã import nó, và
    file đó thì thấy được.
    """
    deps = _dependency_roots()
    out: set[str] = set()
    # list(...) vì import ở thread khác có thể sửa dict khi đang lặp.
    for mod in list(sys.modules.values()):
        f = getattr(mod, "__file__", None)
        if not f or not f.endswith(".py"):
            continue
        f_abs = os.path.abspath(f)
        if not _is_inside(f_abs, root):
            continue
        if any(_is_inside(f_abs, d) for d in deps):
            continue
        out.add(f_abs)
    return sorted(out)


def _files_under(directory: str, exts: Iterable[str]) -> list[str]:
    out: list[str] = []
    for dirpath, dirnames, filenames in os.walk(directory):
        dirnames[:] = [d for d in dirnames if d != "__pycache__"]
        for name in filenames:
            if name.endswith(tuple(exts)):
                out.append(os.path.join(dirpath, name))
    return out


def template_files(root: str) -> list[str]:
    d = os.path.join(root, "templates")
    return _files_under(d, TEMPLATE_EXTS) if os.path.isdir(d) else []


def static_files(root: str) -> list[str]:
    out: list[str] = []
    for sub in STATIC_SUBDIRS:
        d = os.path.join(root, "static", sub)
        if os.path.isdir(d):
            out.extend(_files_under(d, STATIC_EXTS))
    return out


def _changed(paths: Iterable[str], since: float, root: str) -> list[dict]:
    """File có mtime > since, kèm thời điểm sửa để hiện trên UI."""
    out = []
    for p in paths:
        m = _mtime(p)
        if m is not None and m > since:
            out.append({
                "path": os.path.relpath(p, root).replace(os.sep, "/"),
                "mtime": int(m),
                "mtime_text": time.strftime("%H:%M:%S", time.localtime(m)),
            })
    out.sort(key=lambda d: d["mtime"], reverse=True)
    return out


def build_info(root: str, started_at: float) -> dict:
    """
    So đĩa với process đang chạy.

    Args:
        root: thư mục gốc project.
        started_at: epoch giây lúc process khởi động (`_BUILD_STAMP`).

    Returns:
        needs_restart  — có .py/template đổi ⇒ phải restart mới có hiệu lực.
        server_changed — danh sách file đó (mới nhất trước).
        static_changed — JS/CSS đổi; chỉ cần reload trang, không cần restart.
        static_mtime   — mtime lớn nhất của JS/CSS. Frontend so mốc này với thời
                         điểm **trang được nạp** để biết tab có đang giữ bundle
                         cũ hay không; so với `started_at` là sai vì trang có thể
                         được nạp muộn hơn lúc server khởi động.
    """
    srcs = loaded_source_files(root)
    tmpls = template_files(root)
    statics = static_files(root)

    server_changed = _changed(srcs + tmpls, started_at, root)
    static_changed = _changed(statics, started_at, root)
    static_mtimes = [m for m in (_mtime(p) for p in statics) if m is not None]

    return {
        "started_at": int(started_at),
        "started_at_text": time.strftime("%H:%M:%S", time.localtime(started_at)),
        "needs_restart": bool(server_changed),
        "server_changed": server_changed,
        "static_changed": static_changed,
        "static_mtime": int(max(static_mtimes)) if static_mtimes else 0,
        "watched": {
            "sources": len(srcs),
            "templates": len(tmpls),
            "static": len(statics),
        },
        # Interpreter nào đang phục vụ. Hiện lên UI vì start.bat có bước activate
        # venv, nên "đang chạy venv hay Python hệ thống" là câu hỏi thật khi truy
        # lỗi thiếu package sau restart.
        "python": {
            "executable": sys.executable,
            "in_venv": sys.prefix != getattr(sys, "base_prefix", sys.prefix),
            "version": sys.version.split()[0],
        },
    }


# --------------------------------------------------------------------------
# Git — chỉ đọc, chỉ báo. Không pull, không checkout.
# --------------------------------------------------------------------------

def _git(root: str, *args: str, timeout: int = _GIT_TIMEOUT) -> tuple[int, str]:
    """Chạy git, trả (returncode, stdout đã strip). Không bao giờ raise."""
    kwargs = {}
    if os.name == "nt":  # tránh nháy cửa sổ console
        kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        p = subprocess.run(
            ["git", *args],
            cwd=root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            **kwargs,
        )
        return p.returncode, (p.stdout or "").strip()
    except (OSError, subprocess.SubprocessError):
        return 1, ""


def git_status(root: str, fetch: bool = False) -> dict:
    """
    Trạng thái git để **báo cáo**, không tự cập nhật.

    Cố ý không có pull/checkout/reset: một endpoint làm được những việc đó là
    đường thực thi code tuỳ ý từ UI web. Ngoài ra working tree ở đây thường xuyên
    có nhiều file chưa commit, nên pull tự động sẽ hoặc conflict hoặc phải
    stash/reset — tức xoá việc chưa commit của người dùng.

    Args:
        fetch: có gọi `git fetch` không. Chậm và cần mạng, nên chỉ bật khi người
            dùng chủ động bấm kiểm tra, tuyệt đối không đặt trong vòng poll.
    """
    ok, _ = _git(root, "rev-parse", "--git-dir")
    if ok != 0:
        return {"available": False, "reason": "không phải git repo (hoặc chưa có git)"}

    info: dict = {"available": True, "fetched": False}
    _, info["branch"] = _git(root, "rev-parse", "--abbrev-ref", "HEAD")
    _, info["commit"] = _git(root, "rev-parse", "--short", "HEAD")
    _, subject = _git(root, "log", "-1", "--pretty=%s")
    info["commit_subject"] = subject
    _, porcelain = _git(root, "status", "--porcelain")
    info["dirty_files"] = len([l for l in porcelain.splitlines() if l.strip()])

    if fetch:
        rc, _ = _git(root, "fetch", "--quiet")
        info["fetched"] = rc == 0
        if rc != 0:
            info["fetch_error"] = "git fetch thất bại (mạng hoặc xác thực)"

    rc, upstream = _git(root, "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}")
    if rc != 0 or not upstream:
        info["upstream"] = None
        return info
    info["upstream"] = upstream
    rc, counts = _git(root, "rev-list", "--left-right", "--count", f"HEAD...{upstream}")
    if rc == 0 and counts:
        parts = counts.split()
        if len(parts) == 2:
            info["ahead"], info["behind"] = int(parts[0]), int(parts[1])
    return info
