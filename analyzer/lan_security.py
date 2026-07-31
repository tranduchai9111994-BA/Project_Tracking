"""
T34 Task 2 — LAN secure self-host mode.

Mục đích: cho phép user share dashboard qua LAN (đồng nghiệp cùng công ty)
nhưng vẫn giữ được bảo mật:

  * PUBLIC READ (view dashboard) → mọi máy trong LAN đều xem được.
  * ADMIN MUTATIONS (upload, delete, config) → chỉ máy CHỦ (localhost)
    mới được gọi.

Cách hoạt động:
  1. `@localhost_only` decorator — check `request.remote_addr`:
     - 127.0.0.1 / ::1 / localhost → cho qua.
     - IP khác → 403 với message rõ ràng.
  2. `is_localhost_request(request)` — helper thuần để test.
  3. `install_access_log(app, path)` — cài before/after middleware ghi log
     mọi request. Rotate khi > 10MB.
  4. `read_access_log_tail(path, limit)` — đọc N dòng cuối cho UI Settings.

Ghi chú:
  - App chạy local single-user, KHÔNG dùng authentication phức tạp
    (session/JWT/OAuth). Bảo vệ dựa vào network topology + firewall +
    Public API token (đã có cho embed chart).
  - Có thể override bằng ENV `IHRP_LAN_ADMIN_ALLOW` (comma-separated IP)
    khi user muốn cho phép admin từ 1 máy khác đáng tin (VD máy của PM).
"""
from __future__ import annotations

import json
import os
import socket
import threading
import time
from datetime import datetime
from functools import wraps
from typing import Any, Callable, Optional

from flask import Flask, g, jsonify, request


# ==========================================================================
# LOCALHOST GUARD
# ==========================================================================

_LOCALHOST_IPS = {"127.0.0.1", "::1", "localhost"}

_ENV_TRUTHY = {"1", "true", "yes", "on"}
_ENV_FALSY = {"0", "false", "no", "off"}


def resolve_bind_host(environ: Optional[dict] = None) -> str:
    """
    Quyết định host bind cho Flask (solo-safe by default).

    Convention:
      - Mặc định → ``127.0.0.1`` (chỉ máy local).
      - Mở LAN ``0.0.0.0`` khi ``IHRP_BIND_LOCAL_ONLY=0`` hoặc ``IHRP_LAN=1``.
      - ``IHRP_BIND_LOCAL_ONLY=1`` luôn thắng (localhost), kể cả khi ``IHRP_LAN=1``.

    Không đọc từ file — chỉ ENV (để test dễ monkeypatch / truyền dict).
    """
    env = environ if environ is not None else os.environ
    bind_local = (env.get("IHRP_BIND_LOCAL_ONLY") or "").strip().lower()
    lan = (env.get("IHRP_LAN") or "").strip().lower()

    if bind_local in _ENV_TRUTHY:
        return "127.0.0.1"
    if bind_local in _ENV_FALSY:
        return "0.0.0.0"
    if lan in _ENV_TRUTHY:
        return "0.0.0.0"
    return "127.0.0.1"


def _extra_allow_list() -> set[str]:
    """
    ENV `IHRP_LAN_ADMIN_ALLOW="192.168.1.10,192.168.1.20"` — cho phép
    admin từ IP cụ thể ngoài localhost. Rỗng → không mở rộng.

    Cảnh báo: KHÔNG dùng ``*`` / subnet / ``0.0.0.0`` — chỉ IP cụ thể.
    Mặc định rỗng (không mở rộng admin).
    """
    raw = os.environ.get("IHRP_LAN_ADMIN_ALLOW", "").strip()
    if not raw:
        return set()
    return {ip.strip() for ip in raw.split(",") if ip.strip()}


def is_localhost_request(req) -> bool:
    """
    True nếu request đến từ localhost (127.0.0.1/::1) hoặc IP nằm trong
    whitelist `IHRP_LAN_ADMIN_ALLOW`.

    Chú ý: `req.remote_addr` là IP client sau khi Werkzeug xử lý
    X-Forwarded-For (nếu có ProxyFix). App chạy trực tiếp không qua reverse
    proxy → `remote_addr` là IP thật.
    """
    ip = (getattr(req, "remote_addr", None) or "").strip()
    if not ip:
        return False
    if ip in _LOCALHOST_IPS:
        return True
    if ip in _extra_allow_list():
        return True
    return False


def localhost_only(fn: Callable) -> Callable:
    """
    Decorator: chỉ cho phép localhost gọi endpoint.

    Non-localhost → 403 JSON với message giải thích + hint cách unlock.
    """
    @wraps(fn)
    def _wrapped(*args, **kwargs):
        if not is_localhost_request(request):
            return jsonify({
                "error": "Admin endpoint chỉ truy cập từ máy chủ (localhost).",
                "detail": (
                    f"Request từ {request.remote_addr!r} bị từ chối. "
                    f"Endpoint này thay đổi dữ liệu server, không mở cho LAN. "
                    f"Nếu bạn là chủ máy → mở app trực tiếp bằng "
                    f"http://localhost:5000 thay vì IP LAN."
                ),
                "hint": (
                    "Muốn cho phép 1 máy khác dùng admin? Set ENV "
                    "IHRP_LAN_ADMIN_ALLOW=192.168.1.X trước khi khởi động."
                ),
                "code": "LOCALHOST_ONLY",
            }), 403
        return fn(*args, **kwargs)
    return _wrapped


# ==========================================================================
# ADMIN GUARD MIDDLEWARE — chặn admin endpoint từ non-localhost
# ==========================================================================

# Path pattern nhận dạng admin endpoint. Dùng suffix match sau /api/ (hoặc
# sau /api/projects/<slug>/) để tương thích cả 2 dạng URL cũ và mới.
#
# Nguyên tắc: TẤT CẢ mutation (POST/PUT/DELETE) đều mặc định là admin.
# NGOẠI TRỪ các endpoint read-only "trá hình POST" — dùng POST body chỉ để
# truyền filter phức tạp, không mutate state → whitelist tường minh.

READONLY_POST_MARKERS = (
    "/drill-down/export",       # POST body chứa filter — return Excel
    "/chart-aggregate",         # POST body chứa filter — return JSON
    "/portfolio/compare",       # POST body chứa list slug — return JSON
    "/portfolio/compare/export",# POST body chứa list slug — return Excel
    "/audit-report",            # POST body chứa filter — return Excel
    "/pic-blacklist/export",    # POST body chứa filter — return Excel
)

# Export routes rất nhiều (export-overdue, export-chart, export-all-issues,
# export-sla, …) — tất cả read-only cho dù dùng POST. Nhận dạng qua marker
# `/export-` trong path.
_EXPORT_MARKER = "/export-"


def is_admin_mutation_request(req) -> bool:
    """
    True nếu request là mutation cần bảo vệ (admin only).

    Logic:
      1. GET / HEAD / OPTIONS → không phải admin (read-only).
      2. Path `/public/*` (public API) → không phải admin (token đã guard).
      3. Path chứa `/export-` hoặc match `READONLY_POST_MARKERS`
         → read-only "POST-in-disguise".
      4. Còn lại (POST/PUT/DELETE trên /api/*) → admin mutation.
    """
    method = (getattr(req, "method", "") or "").upper()
    if method in ("GET", "HEAD", "OPTIONS"):
        return False

    path = getattr(req, "path", "") or ""
    if not path.startswith("/api/"):
        # `/embed/*` etc. — không phải admin
        return False

    if path.startswith("/public/"):
        return False

    if _EXPORT_MARKER in path:
        return False

    for marker in READONLY_POST_MARKERS:
        if path.endswith(marker) or marker in path:
            return False

    return True


def install_admin_guard(app: Flask) -> None:
    """
    Cài `before_request` guard chặn mutation từ non-localhost.

    Áp dụng logic của `is_admin_mutation_request(request)` — nếu request
    thuộc nhóm admin và IP không phải localhost → trả 403.

    User có thể whitelist thêm IP qua ENV `IHRP_LAN_ADMIN_ALLOW`.
    """

    @app.before_request
    def _admin_guard():
        if not is_admin_mutation_request(request):
            return None
        if is_localhost_request(request):
            return None
        # Chặn với message rõ ràng
        return jsonify({
            "error": "Admin endpoint chỉ truy cập từ máy chủ (localhost).",
            "detail": (
                f"Request {request.method} {request.path} từ "
                f"{request.remote_addr!r} bị từ chối. Endpoint này thay đổi "
                f"dữ liệu server, không mở cho LAN."
            ),
            "hint": (
                "Muốn cho phép 1 máy khác dùng admin? Set ENV "
                "IHRP_LAN_ADMIN_ALLOW=192.168.1.X trước khi khởi động app."
            ),
            "code": "LOCALHOST_ONLY",
        }), 403


# ==========================================================================
# ACCESS LOG — ghi log mọi request để user audit truy cập LAN
# ==========================================================================

_MAX_LOG_SIZE = 10 * 1024 * 1024   # 10 MB
_MAX_LOG_LINES_READ = 500          # UI đọc tối đa 500 dòng cuối
_log_lock = threading.Lock()       # tránh race khi rotate


def _rotate_if_large(path: str) -> None:
    """
    Rotate `access.log` → `access.log.1` khi vượt _MAX_LOG_SIZE.
    Chỉ giữ 1 file backup (best-effort — nếu rotate fail thì im lặng).
    """
    try:
        if os.path.exists(path) and os.path.getsize(path) > _MAX_LOG_SIZE:
            backup = path + ".1"
            if os.path.exists(backup):
                os.remove(backup)
            os.rename(path, backup)
    except OSError:
        pass


def _append_log_line(path: str, entry: dict[str, Any]) -> None:
    """Append 1 JSON line vào log, rotate nếu cần."""
    try:
        _rotate_if_large(path)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False, default=str) + "\n")
    except OSError:
        pass  # log fail thì không crash request


def install_access_log(app: Flask, log_path: str) -> None:
    """
    Cài middleware ghi access log vào file `log_path`.

    Format mỗi dòng (1 JSON object):
      {
        "ts": ISO8601,
        "ip": "192.168.1.5",
        "method": "GET",
        "path": "/api/projects/x/dashboard",
        "status": 200,
        "duration_ms": 12,
        "is_admin": true|false,   # request đi qua @localhost_only?
        "is_localhost": true|false
      }

    Bỏ qua log cho:
      - Path static (`/static/*`) — quá nhiều noise.
      - Path health check nếu có (chưa có).
    """

    @app.before_request
    def _log_start():
        g._log_start_ts = time.perf_counter()

    @app.after_request
    def _log_end(resp):
        # Bỏ qua static để log gọn
        path = request.path or ""
        if path.startswith("/static/"):
            return resp

        try:
            start = getattr(g, "_log_start_ts", None)
            duration_ms = int((time.perf_counter() - start) * 1000) if start else 0
        except Exception:
            duration_ms = 0

        entry = {
            "ts": datetime.now().isoformat(timespec="seconds"),
            "ip": request.remote_addr or "?",
            "method": request.method,
            "path": path,
            "status": resp.status_code,
            "duration_ms": duration_ms,
            "is_localhost": is_localhost_request(request),
        }
        with _log_lock:
            _append_log_line(log_path, entry)
        return resp


def read_access_log_tail(log_path: str, limit: int = 100) -> list[dict[str, Any]]:
    """
    Đọc N dòng cuối của access log, parse JSON. Trả list mới nhất trước.

    Nếu file không tồn tại → [].
    Dòng parse fail → bỏ qua (không crash).
    Clamp limit tối đa _MAX_LOG_LINES_READ để tránh OOM.
    """
    if not os.path.exists(log_path):
        return []
    limit = max(1, min(int(limit), _MAX_LOG_LINES_READ))

    # Đọc từ cuối file — dùng chiến thuật đơn giản: đọc toàn bộ (log
    # rotate ở 10MB nên full file cũng chỉ ~10MB, chấp nhận được cho
    # in-memory scan). Tránh dùng seek+readline reverse phức tạp.
    try:
        with open(log_path, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
    except OSError:
        return []

    tail = lines[-limit:]
    parsed: list[dict[str, Any]] = []
    for line in tail:
        line = line.strip()
        if not line:
            continue
        try:
            parsed.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    parsed.reverse()  # mới nhất trước
    return parsed


# ==========================================================================
# LAN URL DETECTION — hiển thị URL LAN cho user copy
# ==========================================================================

def detect_lan_ips(port: int = 5000) -> list[dict[str, str]]:
    """
    Phát hiện các IP LAN của máy hiện tại để hiển thị URL truy cập:
      [{"ip": "192.168.1.5", "url": "http://192.168.1.5:5000", "label": "LAN"}]

    Cách: lấy hostname → getaddrinfo → filter loopback, filter link-local
    IPv6, filter APIPA (169.254.*).

    Fallback: nếu không detect được → trả localhost.
    """
    urls: list[dict[str, str]] = []
    seen: set[str] = set()

    # 1. Method chính: kết nối UDP outbound để lấy "outbound IP"
    #    (không thực sự gửi packet — chỉ để OS chọn interface).
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(0.5)
        try:
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
            if ip and ip not in seen:
                seen.add(ip)
                urls.append({
                    "ip": ip, "url": f"http://{ip}:{port}",
                    "label": "LAN (outbound interface)",
                })
        finally:
            s.close()
    except OSError:
        pass

    # 2. Bổ sung: liệt kê tất cả IP qua getaddrinfo
    try:
        hostname = socket.gethostname()
        info = socket.getaddrinfo(hostname, None, family=socket.AF_INET)
        for entry in info:
            ip = entry[4][0]
            if not ip or ip in seen:
                continue
            # Skip loopback + APIPA
            if ip.startswith("127.") or ip.startswith("169.254."):
                continue
            seen.add(ip)
            urls.append({
                "ip": ip, "url": f"http://{ip}:{port}",
                "label": "LAN",
            })
    except (socket.gaierror, OSError):
        pass

    # Luôn thêm localhost cuối cùng cho reference
    urls.append({
        "ip": "127.0.0.1",
        "url": f"http://localhost:{port}",
        "label": "Localhost (chỉ máy chủ)",
    })
    return urls
