"""
Registry API + Đồng bộ dữ liệu — quản lý danh sách API/endpoint từ nhiều
ứng dụng nguồn (VD: iHRP production/UAT) và cho phép sync 1-click:

  1. User cấu hình 1 integration = base_url + auth config + 1 hoặc nhiều endpoint.
  2. Credential được nạp qua `.env` (KHÔNG lưu JSON) theo prefix `credential_env`,
     hệ thống đọc `<PREFIX>_USERNAME` + `<PREFIX>_PASSWORD` khi cần.
  3. Bấm "Sync" → mở session HTTP → tự login form → tải file Excel → parse →
     append snapshot vào project bằng logic có sẵn (SnapshotManager).

MVP hỗ trợ:
  - auth.method = "form_login"  (POST form username/password, tự parse CSRF nếu có)
  - endpoint.response_type = "excel" + target_action = "snapshot"

Các method khác (basic_auth / bearer_token / api_key) và response type khác
(json / csv) được reserve để mở rộng — hiện raise NotImplementedError để FE
biết mà disable.

Storage: `<project_dir>/integrations.json`
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
import uuid
from datetime import datetime
from typing import Any, Optional

import requests

from analyzer.dashboard_engine import DashboardEngine
from parser.excel_parser import FunctionListParser


INTEGRATIONS_FILE = "integrations.json"
DEFAULT_TIMEOUT_SECONDS = 30
DEFAULT_AUTH_METHOD = "form_login"

# Whitelist các auth method / response type / target action đang support.
# FE sẽ hiển thị dropdown nhưng disable option chưa support (tooltip
# "Đang phát triển") — logic thực thi được canh gác ở sync/test để an toàn.
SUPPORTED_AUTH_METHODS = {"form_login"}
_PLANNED_AUTH_METHODS = {"basic_auth", "bearer_token", "api_key"}
SUPPORTED_RESPONSE_TYPES = {"excel"}
_PLANNED_RESPONSE_TYPES = {"json", "csv"}
SUPPORTED_TARGET_ACTIONS = {"snapshot", "append", "replace"}

# Detect file Excel qua content-type / extension (mỗi web app trả kiểu khác nhau)
_EXCEL_MIME_HINTS = {
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/vnd.ms-excel",
    "application/octet-stream",   # nhiều framework trả generic → phải fallback theo extension
    "application/x-msdownload",
}


# ============================================================================
# CRUD
# ============================================================================

def _path(project_dir: str) -> str:
    return os.path.join(project_dir, INTEGRATIONS_FILE)


def _read(project_dir: str) -> dict[str, Any]:
    p = _path(project_dir)
    if not os.path.isfile(p):
        return {"integrations": []}
    try:
        with open(p, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return {"integrations": []}
    if not isinstance(data, dict):
        return {"integrations": []}
    if not isinstance(data.get("integrations"), list):
        data["integrations"] = []
    return data


def _write(project_dir: str, data: dict[str, Any]) -> None:
    os.makedirs(project_dir, exist_ok=True)
    with open(_path(project_dir), "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _sanitize_endpoint(ep: dict) -> Optional[dict]:
    """Chuẩn hoá 1 endpoint entry. Trả None nếu invalid (thiếu name/path)."""
    if not isinstance(ep, dict):
        return None
    name = str(ep.get("name") or "").strip()
    path = str(ep.get("path") or "").strip()
    if not name or not path:
        return None
    http_method = str(ep.get("http_method") or "GET").strip().upper()
    if http_method not in {"GET", "POST"}:
        http_method = "GET"
    response_type = str(ep.get("response_type") or "excel").strip().lower()
    target_action = str(ep.get("target_action") or "snapshot").strip().lower()
    params = ep.get("params")
    if not isinstance(params, dict):
        params = {}
    # Coerce tất cả value về string để tương thích requests
    params = {str(k): "" if v is None else str(v) for k, v in params.items()}
    return {
        "id": str(ep.get("id") or f"ep_{uuid.uuid4().hex[:10]}"),
        "name": name[:120],
        "path": path[:500],
        "http_method": http_method,
        "params": params,
        "response_type": response_type[:16],
        "target_action": target_action[:16],
    }


def _sanitize_auth(auth: Any) -> dict:
    """
    Chuẩn hoá config auth. Không chứa credential (username/password NẰM Ở `.env`,
    resolve tại thời điểm sync qua `credential_env` prefix).
    """
    if not isinstance(auth, dict):
        auth = {}
    method = str(auth.get("method") or DEFAULT_AUTH_METHOD).strip().lower()
    login_path = str(auth.get("login_path") or "/login").strip()[:300]
    username_field = str(auth.get("username_field") or "username").strip()[:60] or "username"
    password_field = str(auth.get("password_field") or "password").strip()[:60] or "password"
    credential_env = str(auth.get("credential_env") or "").strip().upper()
    # Chỉ giữ ký tự ASCII an toàn cho tên biến môi trường
    credential_env = re.sub(r"[^A-Z0-9_]+", "_", credential_env)[:60]
    extra_fields = auth.get("extra_fields")
    if not isinstance(extra_fields, dict):
        extra_fields = {}
    extra_fields = {
        str(k)[:60]: ("" if v is None else str(v)[:500])
        for k, v in extra_fields.items()
    }
    return {
        "method": method[:32],
        "login_path": login_path,
        "username_field": username_field,
        "password_field": password_field,
        "credential_env": credential_env,
        "extra_fields": extra_fields,
    }


def _sanitize_integration(data: dict, existing: Optional[dict] = None) -> dict:
    """
    Chuẩn hoá 1 integration cho persist. Merge với existing (nếu update) để
    không mất id/created_at/last_synced_at khi FE chỉ gửi 1 phần.
    """
    if not isinstance(data, dict):
        raise ValueError("Payload phải là JSON object")

    name = str(data.get("name") or "").strip()
    base_url = str(data.get("base_url") or "").strip().rstrip("/")
    if not name:
        raise ValueError("Thiếu 'name'")
    if not base_url:
        raise ValueError("Thiếu 'base_url'")
    if not re.match(r"^https?://", base_url, re.IGNORECASE):
        raise ValueError("base_url phải bắt đầu bằng http:// hoặc https://")

    endpoints_raw = data.get("endpoints") or []
    if not isinstance(endpoints_raw, list):
        raise ValueError("'endpoints' phải là list")
    endpoints: list[dict] = []
    for ep in endpoints_raw:
        s = _sanitize_endpoint(ep)
        if s:
            endpoints.append(s)

    now_iso = datetime.now().isoformat(timespec="seconds")
    return {
        "id": str((existing or {}).get("id") or data.get("id") or f"int_{uuid.uuid4().hex[:12]}"),
        "name": name[:120],
        "base_url": base_url[:500],
        "auth": _sanitize_auth(data.get("auth")),
        "endpoints": endpoints,
        "created_at": str((existing or {}).get("created_at") or now_iso),
        "last_synced_at": (existing or {}).get("last_synced_at") if existing else None,
        "last_sync_status": (existing or {}).get("last_sync_status") if existing else None,
        "last_sync_message": (existing or {}).get("last_sync_message") if existing else None,
    }


def list_integrations(project_dir: str) -> list[dict]:
    return list(_read(project_dir).get("integrations") or [])


def get_integration(project_dir: str, integration_id: str) -> Optional[dict]:
    for it in list_integrations(project_dir):
        if it.get("id") == integration_id:
            return it
    return None


def create_integration(project_dir: str, data: dict) -> dict:
    sanitized = _sanitize_integration(data)
    all_data = _read(project_dir)
    all_data["integrations"].append(sanitized)
    _write(project_dir, all_data)
    return sanitized


def update_integration(project_dir: str, integration_id: str, data: dict) -> Optional[dict]:
    all_data = _read(project_dir)
    for idx, existing in enumerate(all_data["integrations"]):
        if existing.get("id") == integration_id:
            merged_input = dict(existing)
            # Cho phép PUT với chỉ 1 số field — merge shallow rồi sanitize lại
            for k in ("name", "base_url"):
                if k in data:
                    merged_input[k] = data[k]
            if "auth" in data and isinstance(data["auth"], dict):
                merged_input["auth"] = {**existing.get("auth", {}), **data["auth"]}
            if "endpoints" in data:
                merged_input["endpoints"] = data["endpoints"]
            sanitized = _sanitize_integration(merged_input, existing=existing)
            all_data["integrations"][idx] = sanitized
            _write(project_dir, all_data)
            return sanitized
    return None


def delete_integration(project_dir: str, integration_id: str) -> bool:
    all_data = _read(project_dir)
    before = len(all_data["integrations"])
    all_data["integrations"] = [
        i for i in all_data["integrations"] if i.get("id") != integration_id
    ]
    if len(all_data["integrations"]) == before:
        return False
    _write(project_dir, all_data)
    return True


# ============================================================================
# Credential resolution
# ============================================================================

def _load_dotenv_if_present() -> None:
    """
    Nạp `.env` ở workspace root vào `os.environ` (không ghi đè biến đã có).
    Không dùng python-dotenv để tránh thêm dependency; parser tối giản đủ dùng.

    Được gọi mỗi lần resolve_credentials để pick-up thay đổi khi user sửa `.env`
    mà không cần restart Flask (dev nhẹ nhàng).
    """
    # workspace root = parent của folder analyzer
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    env_path = os.path.join(root, ".env")
    if not os.path.isfile(env_path):
        return
    try:
        with open(env_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" not in line:
                    continue
                key, _, val = line.partition("=")
                key = key.strip()
                val = val.strip()
                # Strip quote đơn/kép nếu user quote value
                if len(val) >= 2 and val[0] == val[-1] and val[0] in ("'", '"'):
                    val = val[1:-1]
                # KHÔNG ghi đè biến môi trường thật (env process có ưu tiên)
                if key and key not in os.environ:
                    os.environ[key] = val
    except OSError:
        pass


def resolve_credentials(credential_env: str) -> tuple[str, str]:
    """
    Đọc `<PREFIX>_USERNAME` và `<PREFIX>_PASSWORD` từ `os.environ`.

    Raises:
        ValueError khi thiếu prefix hoặc chưa set biến — thông báo tên biến
        chính xác để user chỉnh `.env`, KHÔNG bao giờ log giá trị password.
    """
    prefix = (credential_env or "").strip().upper()
    if not prefix:
        raise ValueError("Chưa cấu hình 'credential_env' — không xác định được biến .env")
    _load_dotenv_if_present()
    user_key = f"{prefix}_USERNAME"
    pass_key = f"{prefix}_PASSWORD"
    username = os.environ.get(user_key, "")
    password = os.environ.get(pass_key, "")
    if not username or not password:
        missing = []
        if not username:
            missing.append(user_key)
        if not password:
            missing.append(pass_key)
        raise ValueError(
            "Thiếu biến môi trường: " + ", ".join(missing)
            + ". Thêm vào file .env ở gốc project rồi thử lại."
        )
    return username, password


# ============================================================================
# HTTP sync
# ============================================================================

_CSRF_INPUT_NAMES = {
    "csrf_token", "csrfmiddlewaretoken", "_csrf", "authenticity_token",
    "__requestverificationtoken", "csrf", "_token",
}


def _extract_csrf_tokens(html: str) -> dict[str, str]:
    """
    Parse HTML tìm CSRF token trong <input hidden> — bs4 optional dep.
    Trả về dict {input_name: value}. Không có bs4 → fallback regex đơn giản.
    """
    tokens: dict[str, str] = {}
    if not html:
        return tokens
    try:
        from bs4 import BeautifulSoup  # optional dep
        soup = BeautifulSoup(html, "html.parser")
        for inp in soup.find_all("input"):
            n = (inp.get("name") or "").strip()
            if not n:
                continue
            if n.lower() in _CSRF_INPUT_NAMES:
                tokens[n] = inp.get("value") or ""
    except Exception:
        # Fallback regex — không hoàn hảo nhưng cover 95% form login đơn giản
        for m in re.finditer(
            r'<input[^>]+name=["\']([^"\']+)["\'][^>]*value=["\']([^"\']*)["\']',
            html, re.IGNORECASE,
        ):
            n = m.group(1).strip()
            if n.lower() in _CSRF_INPUT_NAMES:
                tokens[n] = m.group(2)
    return tokens


def _do_form_login(
    session: requests.Session,
    base_url: str,
    auth: dict,
    username: str,
    password: str,
    timeout: int = DEFAULT_TIMEOUT_SECONDS,
) -> dict:
    """
    Thực hiện form login. Return dict thông tin (status_code, verified, msg)
    KHÔNG bao giờ chứa password. Raise requests exceptions nếu network fail.
    """
    login_path = auth.get("login_path") or "/login"
    login_url = base_url.rstrip("/") + (login_path if login_path.startswith("/") else "/" + login_path)

    # Step 1: GET login page → lấy CSRF nếu có
    csrf_tokens: dict[str, str] = {}
    try:
        r_get = session.get(login_url, timeout=timeout, allow_redirects=True)
        if r_get.status_code < 500:
            csrf_tokens = _extract_csrf_tokens(r_get.text or "")
    except requests.RequestException:
        # Không fatal — nếu server không cho GET login (rare), vẫn thử POST
        pass

    # Step 2: POST form
    payload: dict[str, str] = {
        auth.get("username_field") or "username": username,
        auth.get("password_field") or "password": password,
    }
    extra = auth.get("extra_fields") or {}
    if isinstance(extra, dict):
        payload.update({str(k): str(v) for k, v in extra.items()})
    payload.update(csrf_tokens)

    r_post = session.post(
        login_url,
        data=payload,
        timeout=timeout,
        allow_redirects=True,
    )

    # Heuristic verify: nhiều app trả 200 nhưng redirect về login khi fail;
    # 1 số app trả 302 → follow → landing page có user info; số ít trả 401/403.
    verified = True
    reason = ""
    if r_post.status_code in (401, 403):
        verified = False
        reason = f"HTTP {r_post.status_code} — sai username hoặc password"
    elif r_post.status_code >= 500:
        verified = False
        reason = f"Server lỗi HTTP {r_post.status_code}"
    else:
        # Check redirect chain — nếu final URL vẫn nằm ở login_path thì fail
        final_url = r_post.url or ""
        try:
            from urllib.parse import urlparse
            final_path = urlparse(final_url).path or ""
        except Exception:
            final_path = ""
        # So sánh path chuẩn hoá (bỏ trailing slash)
        if final_path.rstrip("/") == (login_path or "").rstrip("/"):
            # Có thể vẫn ở login — nhưng cũng có thể server render lại login sau khi POST ok?
            # → thêm điều kiện phụ: body chứa keyword lỗi thường gặp
            body_low = (r_post.text or "")[:5000].lower()
            fail_hints = ["invalid", "incorrect", "sai mật khẩu", "sai tài khoản",
                          "không đúng", "authentication failed", "login failed"]
            if any(h in body_low for h in fail_hints):
                verified = False
                reason = "Server trả về trang login sau khi POST — nghi ngờ sai credential"

    return {
        "status_code": r_post.status_code,
        "final_url": r_post.url,
        "verified": verified,
        "message": reason or ("Login OK" if verified else "Login không xác minh được"),
    }


def _looks_like_excel(response: requests.Response) -> bool:
    """Heuristic: content-type + extension trong URL. KHÔNG đọc content."""
    ctype = (response.headers.get("Content-Type") or "").split(";")[0].strip().lower()
    if ctype in _EXCEL_MIME_HINTS:
        # octet-stream vẫn cần check thêm bằng URL
        if ctype == "application/octet-stream":
            return response.url.lower().endswith((".xlsx", ".xls"))
        return True
    # Fallback URL check
    return response.url.lower().endswith((".xlsx", ".xls"))


def test_integration(
    project_dir: str,
    integration_id: str,
    timeout: int = DEFAULT_TIMEOUT_SECONDS,
) -> dict:
    """
    Test login only — không tải Excel. Update `last_sync_status` để user thấy
    trong danh sách. Trả dict {status, message}.
    """
    integ = get_integration(project_dir, integration_id)
    if not integ:
        return {"status": "error", "message": "Không tìm thấy integration"}

    method = (integ.get("auth") or {}).get("method") or DEFAULT_AUTH_METHOD
    if method not in SUPPORTED_AUTH_METHODS:
        return {
            "status": "error",
            "message": f"Auth method '{method}' chưa được hỗ trợ (MVP chỉ form_login).",
        }

    try:
        username, password = resolve_credentials((integ.get("auth") or {}).get("credential_env", ""))
    except ValueError as e:
        _update_last_status(project_dir, integration_id, "error", str(e))
        return {"status": "error", "message": str(e)}

    session = requests.Session()
    try:
        info = _do_form_login(
            session=session,
            base_url=integ["base_url"],
            auth=integ["auth"],
            username=username,
            password=password,
            timeout=timeout,
        )
    except requests.RequestException as e:
        msg = f"Không kết nối được: {type(e).__name__}: {str(e)[:200]}"
        _update_last_status(project_dir, integration_id, "error", msg)
        return {"status": "error", "message": msg}
    finally:
        # Không cache session — an toàn hơn, tránh giữ cookie đăng nhập trong process
        session.close()

    if info["verified"]:
        _update_last_status(project_dir, integration_id, "ok", "Test login thành công")
        return {"status": "ok", "message": "Đăng nhập thành công", **_safe_info(info)}
    _update_last_status(project_dir, integration_id, "error", info["message"])
    return {"status": "error", "message": info["message"], **_safe_info(info)}


def sync_integration(
    project_dir: str,
    integration_id: str,
    endpoint_id: str,
    *,
    project_manager,
    project_slug: str,
    long_duration_threshold: int = 3,
    timeout: int = DEFAULT_TIMEOUT_SECONDS,
) -> dict:
    """
    Đồng bộ 1 endpoint: login → GET file Excel → parse → save snapshot vào project.

    Args:
        project_dir: absolute path đến folder project (uploads/projects/<slug>/)
        integration_id: id của integration đã cấu hình
        endpoint_id: id endpoint cần chạy
        project_manager: instance ProjectManager (từ app.py)
        project_slug: slug của project để lưu snapshot
        long_duration_threshold: forward cho DashboardEngine
        timeout: giây timeout mỗi request HTTP

    Trả về:
        {
          "status": "ok" | "error",
          "message": "...",
          "snapshot_id": "YYYY-MM-DD" | None,   # date của snapshot vừa lưu
          "rows_imported": int,
          "filename": str | None,
        }
    """
    integ = get_integration(project_dir, integration_id)
    if not integ:
        return {"status": "error", "message": "Không tìm thấy integration",
                "snapshot_id": None, "rows_imported": 0, "filename": None}

    # Tìm endpoint
    endpoint = None
    for ep in integ.get("endpoints") or []:
        if ep.get("id") == endpoint_id:
            endpoint = ep
            break
    if not endpoint:
        return {"status": "error", "message": "Không tìm thấy endpoint trong integration",
                "snapshot_id": None, "rows_imported": 0, "filename": None}

    method = (integ.get("auth") or {}).get("method") or DEFAULT_AUTH_METHOD
    if method not in SUPPORTED_AUTH_METHODS:
        return {"status": "error",
                "message": f"Auth method '{method}' chưa hỗ trợ (MVP form_login).",
                "snapshot_id": None, "rows_imported": 0, "filename": None}

    response_type = (endpoint.get("response_type") or "excel").lower()
    if response_type not in SUPPORTED_RESPONSE_TYPES:
        return {"status": "error",
                "message": f"Response type '{response_type}' chưa hỗ trợ (MVP excel).",
                "snapshot_id": None, "rows_imported": 0, "filename": None}

    # Resolve creds
    try:
        username, password = resolve_credentials((integ.get("auth") or {}).get("credential_env", ""))
    except ValueError as e:
        _update_last_status(project_dir, integration_id, "error", str(e))
        return {"status": "error", "message": str(e),
                "snapshot_id": None, "rows_imported": 0, "filename": None}

    session = requests.Session()
    try:
        # 1) Login
        try:
            login_info = _do_form_login(
                session=session,
                base_url=integ["base_url"],
                auth=integ["auth"],
                username=username,
                password=password,
                timeout=timeout,
            )
        except requests.RequestException as e:
            msg = f"Login network fail: {type(e).__name__}: {str(e)[:200]}"
            _update_last_status(project_dir, integration_id, "error", msg)
            return {"status": "error", "message": msg,
                    "snapshot_id": None, "rows_imported": 0, "filename": None}

        if not login_info["verified"]:
            _update_last_status(project_dir, integration_id, "error", login_info["message"])
            return {"status": "error", "message": login_info["message"],
                    "snapshot_id": None, "rows_imported": 0, "filename": None}

        # 2) GET/POST endpoint để lấy file Excel
        ep_path = endpoint.get("path") or ""
        endpoint_url = integ["base_url"].rstrip("/") + (ep_path if ep_path.startswith("/") else "/" + ep_path)
        http_method = (endpoint.get("http_method") or "GET").upper()
        params = endpoint.get("params") or {}

        try:
            if http_method == "POST":
                r_data = session.post(endpoint_url, data=params, timeout=timeout, allow_redirects=True)
            else:
                r_data = session.get(endpoint_url, params=params, timeout=timeout, allow_redirects=True)
        except requests.RequestException as e:
            msg = f"Không tải được file: {type(e).__name__}: {str(e)[:200]}"
            _update_last_status(project_dir, integration_id, "error", msg)
            return {"status": "error", "message": msg,
                    "snapshot_id": None, "rows_imported": 0, "filename": None}

        if r_data.status_code >= 400:
            msg = f"Endpoint trả HTTP {r_data.status_code}"
            _update_last_status(project_dir, integration_id, "error", msg)
            return {"status": "error", "message": msg,
                    "snapshot_id": None, "rows_imported": 0, "filename": None}

        if not _looks_like_excel(r_data):
            ctype = r_data.headers.get("Content-Type", "unknown")
            msg = (f"Response không phải Excel (Content-Type: {ctype}). "
                   f"Kiểm tra lại 'path'/'params' hoặc quyền tài khoản.")
            _update_last_status(project_dir, integration_id, "error", msg)
            return {"status": "error", "message": msg,
                    "snapshot_id": None, "rows_imported": 0, "filename": None}

        # 3) Lưu tạm file → dùng lại flow SnapshotManager có sẵn
        ts = datetime.now().strftime("%Y%m%d_%H%M")
        # File tạm lưu ngay trong project_dir để dễ debug/rollback
        filename = f"synced_{ts}.xlsx"
        target_path = os.path.join(project_dir, filename)
        try:
            with open(target_path, "wb") as fout:
                fout.write(r_data.content)
        except OSError as e:
            msg = f"Không lưu được file tạm: {e}"
            _update_last_status(project_dir, integration_id, "error", msg)
            return {"status": "error", "message": msg,
                    "snapshot_id": None, "rows_imported": 0, "filename": None}

        # 4) Parse Excel
        try:
            parsed = FunctionListParser().parse(target_path)
            metrics = DashboardEngine(long_duration_threshold=long_duration_threshold).compute_all(parsed)
        except Exception as e:
            msg = f"Parse file lỗi: {type(e).__name__}: {str(e)[:300]}"
            _update_last_status(project_dir, integration_id, "error", msg)
            return {"status": "error", "message": msg,
                    "snapshot_id": None, "rows_imported": 0, "filename": filename}

        rows_count = len(parsed.rows)

        # 5) Save snapshot (append vào project) — tận dụng SnapshotManager
        target_action = (endpoint.get("target_action") or "snapshot").lower()
        snapshot_entry = None
        try:
            smgr = project_manager.get_snapshot_manager(project_slug)
            snapshot_entry = smgr.save_snapshot(target_path, parsed, metrics)
            # target_action = replace → copy target_path đè current.xlsx (để dashboard
            # dùng file mới sync ngay lập tức). target_action = append (mặc định
            # cho spec) chỉ lưu snapshot, không đổi current.xlsx.
            if target_action == "replace":
                import shutil as _sh
                _sh.copy2(target_path, project_manager.get_current_file_path(project_slug))
                project_manager.touch_last_upload(project_slug)
        except Exception as e:
            msg = f"Lưu snapshot lỗi: {type(e).__name__}: {str(e)[:200]}"
            _update_last_status(project_dir, integration_id, "error", msg)
            return {"status": "error", "message": msg,
                    "snapshot_id": None, "rows_imported": rows_count, "filename": filename}

        # 6) Cập nhật status
        ok_msg = (f"Đã tải {rows_count} dòng · snapshot {snapshot_entry.get('date') if snapshot_entry else '?'} · "
                  f"endpoint '{endpoint.get('name')}'")
        _update_last_status(project_dir, integration_id, "ok", ok_msg, sync_time=True)

        return {
            "status": "ok",
            "message": ok_msg,
            "snapshot_id": snapshot_entry.get("date") if snapshot_entry else None,
            "snapshot_entry": snapshot_entry,
            "rows_imported": rows_count,
            "filename": filename,
            "target_action": target_action,
        }
    finally:
        session.close()


# ============================================================================
# Helpers
# ============================================================================

def _safe_info(info: dict) -> dict:
    """Trim login response info để không leak thông tin nhạy cảm ra FE."""
    return {
        "http_status": info.get("status_code"),
        "final_url": info.get("final_url"),
    }


def _update_last_status(
    project_dir: str,
    integration_id: str,
    status: str,
    message: str,
    *,
    sync_time: bool = False,
) -> None:
    """
    Update last_sync_status + last_sync_message (+ optionally last_synced_at)
    cho integration. KHÔNG raise nếu file chưa tồn tại — chỉ log stderr.
    """
    try:
        all_data = _read(project_dir)
        for it in all_data.get("integrations") or []:
            if it.get("id") == integration_id:
                it["last_sync_status"] = status
                it["last_sync_message"] = message[:500]
                if sync_time:
                    it["last_synced_at"] = datetime.now().isoformat(timespec="seconds")
                break
        _write(project_dir, all_data)
    except Exception as e:
        # Không critical — chỉ log để dev debug
        print(f"[integrations] Không update được last_sync_status: {e}", file=sys.stderr)


def integration_capabilities() -> dict:
    """
    Metadata FE dùng để populate dropdown auth method / response type / target action.
    Tách flag `supported` để FE có thể disable option chưa implement.
    """
    return {
        "auth_methods": [
            {"value": m, "supported": True}
            for m in sorted(SUPPORTED_AUTH_METHODS)
        ] + [
            {"value": m, "supported": False, "hint": "Đang phát triển"}
            for m in sorted(_PLANNED_AUTH_METHODS)
        ],
        "response_types": [
            {"value": r, "supported": True}
            for r in sorted(SUPPORTED_RESPONSE_TYPES)
        ] + [
            {"value": r, "supported": False, "hint": "Đang phát triển"}
            for r in sorted(_PLANNED_RESPONSE_TYPES)
        ],
        "target_actions": sorted(SUPPORTED_TARGET_ACTIONS),
        "default_timeout_seconds": DEFAULT_TIMEOUT_SECONDS,
    }
