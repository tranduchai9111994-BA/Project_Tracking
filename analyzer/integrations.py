"""
Registry API + Đồng bộ dữ liệu — quản lý danh sách API/endpoint từ nhiều
ứng dụng nguồn (VD: iHRP production/UAT, workload report, GAP tracker…) và
cho phép sync 1-click:

  1. User cấu hình 1 integration = base_url + auth config + 1 hoặc nhiều endpoint.
  2. Credential được nạp qua `.env` (KHÔNG lưu JSON) theo các prefix env đã
     cấu hình — hệ thống đọc biến tương ứng khi cần.
  3. Bấm "Sync" → mở session HTTP → auth (form/basic/bearer/api_key) → tải
     Excel HOẶC JSON (auto convert sang xlsx qua field_mapping) → parse →
     append snapshot vào project bằng logic có sẵn (SnapshotManager).

Auth method được hỗ trợ (all first-class):
  - "form_login"  — POST form username/password (đọc PREFIX_USERNAME/PASSWORD),
                    tự parse CSRF nếu có.
  - "basic_auth"  — HTTP Basic Auth (đọc PREFIX_USERNAME/PASSWORD giống form).
  - "bearer_token"— Gửi header ``Authorization: Bearer <token>``
                    (đọc PREFIX_TOKEN từ .env).
  - "api_key"     — Gửi API key qua header hoặc query param
                    (đọc PREFIX_KEY từ .env; header name + location cấu hình được).

Response type:
  - "excel" — tải trực tiếp file .xlsx / .xls, parse bằng excel_parser.
  - "json"  — response là JSON, dùng ``data_path`` (dot-notation) để trích ra
              list-of-records, rồi ``field_mapping`` (dict {col_iHRP: json_path})
              để chuyển thành xlsx trong bộ nhớ. Snapshot vẫn lưu .xlsx để nhất
              quán với compare/pickle flow cũ.
  - "csv"   — reserve (chưa implement).

Storage: `<project_dir>/integrations.json`
"""
from __future__ import annotations

import base64
import io
import json
import os
import re
import sys
import time
import uuid
from datetime import datetime
from typing import Any, Optional

import openpyxl
import requests

from analyzer.dashboard_engine import DashboardEngine
from parser.excel_parser import FunctionListParser


INTEGRATIONS_FILE = "integrations.json"
DEFAULT_TIMEOUT_SECONDS = 30
DEFAULT_AUTH_METHOD = "form_login"

# Whitelist các auth method / response type / target action — ALL first-class.
# FE dropdown hiển thị tất cả không disable, backend cũng chấp nhận + xử lý.
# `csv` được để trong PLANNED (chưa implement) — nếu user cấu hình sẽ bị reject
# tại thời điểm sync với message rõ ràng.
#
# T31 (v4.1): "database" là auth method + response type mới để tích hợp trực
# tiếp với SQL view do khách trả. Flow: mở connection (pyodbc/psycopg2/pymysql
# lazy-import) → execute SELECT với param binding an toàn → fetchall → convert
# sang list[dict] → apply field_mapping giống JSON API → build_xlsx → parse.
SUPPORTED_AUTH_METHODS = {"form_login", "basic_auth", "bearer_token", "api_key", "database"}
_PLANNED_AUTH_METHODS: set[str] = set()  # tất cả method đều đã ready
SUPPORTED_RESPONSE_TYPES = {"excel", "json", "database"}
_PLANNED_RESPONSE_TYPES = {"csv"}
SUPPORTED_TARGET_ACTIONS = {"snapshot", "append", "replace"}
SUPPORTED_APIKEY_LOCATIONS = {"header", "query"}
SUPPORTED_DB_DRIVERS = {"sqlserver", "postgres", "mysql"}
DEFAULT_DB_PORTS = {"sqlserver": 1433, "postgres": 5432, "mysql": 3306}

# Detect file Excel qua content-type / extension (mỗi web app trả kiểu khác nhau)
_EXCEL_MIME_HINTS = {
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/vnd.ms-excel",
    "application/octet-stream",   # nhiều framework trả generic → phải fallback theo extension
    "application/x-msdownload",
}

# JSON content-type — response có ct trong list này (hoặc bắt đầu bằng
# `application/json`) sẽ đi qua flow parse JSON.
_JSON_MIME_HINTS = {"application/json", "application/vnd.api+json",
                    "text/json", "application/hal+json"}

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
    """
    Chuẩn hoá 1 endpoint entry. Trả None nếu invalid.

    - HTTP endpoint: yêu cầu name + path.
    - Database endpoint (response_type='database'): yêu cầu name + query
      (path có thể rỗng, giữ field cho consistency).
    """
    if not isinstance(ep, dict):
        return None
    name = str(ep.get("name") or "").strip()
    path = str(ep.get("path") or "").strip()
    response_type = str(ep.get("response_type") or "excel").strip().lower()
    query = str(ep.get("query") or "").strip()

    # Với database endpoint: cho phép path rỗng nhưng phải có query.
    if response_type == "database":
        if not name or not query:
            return None
    else:
        if not name or not path:
            return None
    http_method = str(ep.get("http_method") or "GET").strip().upper()
    if http_method not in {"GET", "POST"}:
        http_method = "GET"
    target_action = str(ep.get("target_action") or "snapshot").strip().lower()
    params = ep.get("params")
    if not isinstance(params, dict):
        params = {}
    # Coerce tất cả value về string để tương thích requests
    params = {str(k): "" if v is None else str(v) for k, v in params.items()}

    # JSON/DB response mapping (dùng cho response_type = "json" HOẶC "database").
    data_path = str(ep.get("data_path") or "").strip()[:200]
    fm_raw = ep.get("field_mapping")
    field_mapping: dict[str, str] = {}
    if isinstance(fm_raw, dict):
        for k, v in fm_raw.items():
            if not k:
                continue
            key_s = str(k).strip()[:200]
            val_s = str(v or "").strip()[:300]
            if key_s and val_s:
                field_mapping[key_s] = val_s

    # Database-only fields (T31). query_params là dict {named_param: value}
    # dùng cho bind an toàn qua cursor.execute — không string concat.
    query_params_raw = ep.get("query_params")
    query_params: dict[str, Any] = {}
    if isinstance(query_params_raw, dict):
        for k, v in query_params_raw.items():
            if not k:
                continue
            key_s = str(k).strip()[:60]
            if not re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", key_s):
                # Bỏ qua tên param không hợp lệ để tránh gây SQL error khó debug.
                continue
            # Giữ nguyên type (int/float/str/None/bool) — driver tự cast.
            query_params[key_s] = v

    return {
        "id": str(ep.get("id") or f"ep_{uuid.uuid4().hex[:10]}"),
        "name": name[:120],
        "path": path[:500],
        "http_method": http_method,
        "params": params,
        "response_type": response_type[:16],
        "target_action": target_action[:16],
        # JSON/DB-only fields — thừa ở excel endpoint nhưng lưu vẫn OK để giữ
        # config nếu user chuyển response_type qua lại.
        "data_path": data_path,
        "field_mapping": field_mapping,
        # Database-only fields
        "query": query[:10000],           # SELECT SQL (giới hạn 10KB để tránh abuse)
        "query_params": query_params,
    }


def _sanitize_env_prefix(raw: Any) -> str:
    """Chuẩn hoá 1 prefix env: uppercase + chỉ giữ A-Z0-9_, cắt 60 ký tự."""
    s = str(raw or "").strip().upper()
    return re.sub(r"[^A-Z0-9_]+", "_", s)[:60]


def _sanitize_auth(auth: Any) -> dict:
    """
    Chuẩn hoá config auth. KHÔNG chứa credential thực (username/password/token/key
    NẰM Ở `.env`, resolve tại thời điểm sync qua các prefix env).

    Giữ tất cả field của tất cả method trong 1 dict phẳng để đơn giản: khi FE
    chuyển method, field không dùng chỉ bị bỏ qua ở runtime chứ không phải xoá
    khỏi JSON. Backward compat: entry cũ chỉ có ``credential_env`` vẫn hoạt
    động với ``form_login`` và ``basic_auth``.
    """
    if not isinstance(auth, dict):
        auth = {}
    method = str(auth.get("method") or DEFAULT_AUTH_METHOD).strip().lower()

    # --- form_login fields (cũng dùng cho basic_auth) ---
    login_path = str(auth.get("login_path") or "/login").strip()[:300]
    username_field = str(auth.get("username_field") or "username").strip()[:60] or "username"
    password_field = str(auth.get("password_field") or "password").strip()[:60] or "password"
    credential_env = _sanitize_env_prefix(auth.get("credential_env"))
    extra_fields = auth.get("extra_fields")
    if not isinstance(extra_fields, dict):
        extra_fields = {}
    extra_fields = {
        str(k)[:60]: ("" if v is None else str(v)[:500])
        for k, v in extra_fields.items()
    }

    # --- bearer_token fields ---
    bearer_env = _sanitize_env_prefix(auth.get("bearer_env"))

    # --- api_key fields ---
    apikey_env = _sanitize_env_prefix(auth.get("apikey_env"))
    apikey_header = str(auth.get("apikey_header") or "X-API-Key").strip()[:80] or "X-API-Key"
    apikey_location = str(auth.get("apikey_location") or "header").strip().lower()
    if apikey_location not in SUPPORTED_APIKEY_LOCATIONS:
        apikey_location = "header"

    # --- database fields (T31) ---
    # KHÔNG chứa username/password — 2 biến này resolve từ .env qua credential_env
    # cùng cơ chế với form_login/basic_auth. Chỉ lưu host/port/database/driver để
    # user thấy được config trong UI + backend build connection string.
    db_driver_raw = str(auth.get("db_driver") or "").strip().lower()
    db_driver = db_driver_raw if db_driver_raw in SUPPORTED_DB_DRIVERS else ""
    db_host = str(auth.get("db_host") or "").strip()[:200]
    try:
        db_port = int(auth.get("db_port") or 0)
    except (TypeError, ValueError):
        db_port = 0
    if db_port < 0 or db_port > 65535:
        db_port = 0
    # Nếu chưa set port → dùng port mặc định của driver để user khỏi phải nhớ.
    if db_port == 0 and db_driver:
        db_port = DEFAULT_DB_PORTS.get(db_driver, 0)
    db_database = str(auth.get("db_database") or "").strip()[:200]

    verify_ssl = auth.get("verify_ssl", True)
    if not isinstance(verify_ssl, bool):
        verify_ssl = bool(verify_ssl)

    return {
        "method": method[:32],
        "login_path": login_path,
        "username_field": username_field,
        "password_field": password_field,
        "credential_env": credential_env,
        "extra_fields": extra_fields,
        "bearer_env": bearer_env,
        "apikey_env": apikey_env,
        "apikey_header": apikey_header,
        "apikey_location": apikey_location,
        "verify_ssl": verify_ssl,
        # database
        "db_driver": db_driver,
        "db_host": db_host,
        "db_port": db_port,
        "db_database": db_database,
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
    # T31: database method KHÔNG có URL → base_url optional. Với các method
    # HTTP khác vẫn require + validate scheme.
    auth_method = str((data.get("auth") or {}).get("method") or DEFAULT_AUTH_METHOD).strip().lower()
    if auth_method != "database":
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


def resolve_bearer_token(bearer_env: str) -> str:
    """Đọc ``<PREFIX>_TOKEN`` từ .env / os.environ cho auth bearer_token."""
    prefix = (bearer_env or "").strip().upper()
    if not prefix:
        raise ValueError("Chưa cấu hình 'bearer_env' — không xác định được biến .env")
    _load_dotenv_if_present()
    var_name = f"{prefix}_TOKEN"
    token = (os.environ.get(var_name) or "").strip()
    if not token:
        raise ValueError(
            f"Thiếu biến môi trường: {var_name}. Thêm vào file .env ở gốc project rồi thử lại."
        )
    return token


def resolve_api_key(apikey_env: str) -> str:
    """Đọc ``<PREFIX>_KEY`` từ .env / os.environ cho auth api_key."""
    prefix = (apikey_env or "").strip().upper()
    if not prefix:
        raise ValueError("Chưa cấu hình 'apikey_env' — không xác định được biến .env")
    _load_dotenv_if_present()
    var_name = f"{prefix}_KEY"
    key = (os.environ.get(var_name) or "").strip()
    if not key:
        raise ValueError(
            f"Thiếu biến môi trường: {var_name}. Thêm vào file .env ở gốc project rồi thử lại."
        )
    return key


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


def _looks_like_json(response: requests.Response) -> bool:
    """Content-Type ``application/json`` hoặc variant (hal+json, api+json…)."""
    ctype = (response.headers.get("Content-Type") or "").split(";")[0].strip().lower()
    if ctype in _JSON_MIME_HINTS:
        return True
    return ctype.startswith("application/") and ctype.endswith("+json")


# ============================================================================
# Auth session preparation — 1 hàm chung cho 4 method
# ============================================================================

class AuthError(Exception):
    """Raise khi verify auth thất bại — dùng làm sentinel để sync/test format msg."""


def _prepare_authenticated_session(
    base_url: str,
    auth: dict,
    *,
    timeout: int = DEFAULT_TIMEOUT_SECONDS,
) -> tuple[requests.Session, dict[str, str], dict[str, Any]]:
    """
    Chuẩn bị `requests.Session` đã auth theo `auth.method`.

    Trả về:
        (session, extra_query_params, info)
        - session: đã set header/auth phù hợp (bearer/basic/api_key/form_login).
          Caller nhớ `session.close()` khi xong.
        - extra_query_params: dict param phải MERGE vào query của mỗi endpoint
          request (chỉ dùng cho api_key với apikey_location='query').
        - info: dict metadata trả về cho test/sync (VD http_status, final_url).

    Raise:
        AuthError khi verify không thành công (VD form_login trả login page).
        ValueError khi config thiếu / method không hỗ trợ / creds .env vắng.
        requests.RequestException khi network fail.
    """
    method = (auth.get("method") or DEFAULT_AUTH_METHOD).strip().lower()
    if method not in SUPPORTED_AUTH_METHODS:
        raise ValueError(f"Auth method '{method}' chưa được hỗ trợ.")

    session = requests.Session()
    verify_ssl = bool(auth.get("verify_ssl", True))
    session.verify = verify_ssl
    if not verify_ssl:
        try:
            import urllib3
            urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        except Exception:
            pass
    extra_query: dict[str, str] = {}
    info: dict[str, Any] = {"method": method, "verify_ssl": verify_ssl}

    if method == "form_login":
        username, password = resolve_credentials(auth.get("credential_env", ""))
        login_info = _do_form_login(session, base_url, auth, username, password, timeout=timeout)
        info.update(login_info)
        if not login_info.get("verified"):
            raise AuthError(login_info.get("message") or "Login form thất bại")
    elif method == "basic_auth":
        # HTTPBasicAuth từ requests tự encode base64 vào header Authorization.
        username, password = resolve_credentials(auth.get("credential_env", ""))
        # Không dùng requests.auth để tách rõ payload log (base64 vẫn có thể decode
        # ngược ra password → tự set header + KHÔNG lưu vào info)
        b64 = base64.b64encode(f"{username}:{password}".encode("utf-8")).decode("ascii")
        session.headers["Authorization"] = f"Basic {b64}"
        info["verified"] = True
        info["message"] = "Basic auth header đã sẵn sàng"
    elif method == "bearer_token":
        token = resolve_bearer_token(auth.get("bearer_env", ""))
        session.headers["Authorization"] = f"Bearer {token}"
        info["verified"] = True
        info["message"] = "Bearer token header đã sẵn sàng"
    elif method == "api_key":
        key = resolve_api_key(auth.get("apikey_env", ""))
        header_name = (auth.get("apikey_header") or "X-API-Key").strip() or "X-API-Key"
        location = (auth.get("apikey_location") or "header").strip().lower()
        if location == "query":
            # Truyền qua query param — caller merge vào params của mỗi endpoint
            extra_query[header_name] = key
        else:
            session.headers[header_name] = key
        info["verified"] = True
        info["message"] = f"API key {location} đã sẵn sàng"
    else:
        # Đề phòng: mặc dù SUPPORTED_AUTH_METHODS đã check ở đầu, giữ default
        # để nếu ai đó thêm method mới quên implement ở đây thì fail rõ ràng.
        session.close()
        raise ValueError(f"Auth method '{method}' chưa được implement.")

    return session, extra_query, info


# ============================================================================
# JSON response → xlsx (in-memory)
# ============================================================================

def _dig_json(obj: Any, path: str) -> Any:
    """
    Dot-notation traversal 1 JSON node.

    - path rỗng → trả về obj (identity)
    - path chứa số (VD "items.0.code") → dùng index cho list
    - Key không tồn tại → trả None
    """
    if path is None or path == "":
        return obj
    cur = obj
    for part in path.split("."):
        if cur is None:
            return None
        if isinstance(cur, dict):
            cur = cur.get(part)
        elif isinstance(cur, list):
            try:
                cur = cur[int(part)]
            except (ValueError, IndexError):
                return None
        else:
            return None
    return cur


def extract_records(payload: Any, data_path: str) -> list[dict]:
    """
    Trích list-of-records từ JSON payload theo `data_path` dot-notation.

    - data_path rỗng: payload phải là list ở top-level.
    - data_path != rỗng: trích node → phải là list.
    - Nếu kết quả không phải list → return [] (caller handle empty).
    """
    node = _dig_json(payload, (data_path or "").strip())
    if isinstance(node, list):
        # Filter chỉ giữ dict entries (skip primitive khi user query nhầm)
        return [x for x in node if isinstance(x, dict)]
    return []


def _stringify_json_value(v: Any) -> Any:
    """
    Convert 1 JSON value sang giá trị chấp nhận được cho Excel cell.

    - None → None (openpyxl để trống cell)
    - dict/list → JSON string (để user thấy value gốc, không mất thông tin)
    - bool → str "True"/"False"
    - str/int/float → giữ nguyên (openpyxl hỗ trợ)
    """
    if v is None:
        return None
    if isinstance(v, (dict, list)):
        # Nén nhẹ để cell không quá dài
        try:
            return json.dumps(v, ensure_ascii=False)[:2000]
        except (TypeError, ValueError):
            return str(v)[:2000]
    if isinstance(v, bool):
        return "True" if v else "False"
    return v


def build_xlsx_from_json_records(
    records: list[dict],
    field_mapping: dict[str, str],
) -> bytes:
    """
    Chuyển JSON records → bytes .xlsx theo `field_mapping`.

    Args:
        records: list of dict (mỗi dict = 1 record function).
        field_mapping: dict {tên_cột_iHRP: json_path}. VD:
            {"Mã CN": "code", "Analysis - Start": "phases.analysis.start"}
            → tạo file có 2 cột "Mã CN" (từ record["code"]) và "Analysis - Start"
            (từ record["phases"]["analysis"]["start"]).
        Empty value ở field_mapping → skip cột đó.
        Nếu field_mapping RỖNG hoàn toàn → dùng union tất cả keys của records
        làm header (dùng cho database endpoint không cấu hình mapping — SQL
        query có thể alias cột thành tên iHRP chuẩn sẵn).

    Trả bytes của file .xlsx (workbook 1 sheet "Function List").
    """
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Function List"

    # Chỉ giữ mapping có json_path không rỗng — cột rỗng gây confusion cho parser
    valid_pairs = [(k, v) for k, v in field_mapping.items() if k and v]
    if valid_pairs:
        headers = [k for k, _ in valid_pairs]
        paths = [p for _, p in valid_pairs]
        ws.append(headers)
        for rec in records:
            if not isinstance(rec, dict):
                continue
            ws.append([_stringify_json_value(_dig_json(rec, p)) for p in paths])
    else:
        # Fallback: không có mapping → dump raw. Header = union keys giữ thứ tự
        # xuất hiện đầu tiên (đảm bảo ổn định qua các lần chạy — quan trọng
        # cho parser auto-detect cột).
        seen: dict[str, None] = {}
        for rec in records:
            if isinstance(rec, dict):
                for k in rec.keys():
                    if k not in seen:
                        seen[str(k)] = None
        headers = list(seen.keys())
        ws.append(headers)
        for rec in records:
            if not isinstance(rec, dict):
                continue
            ws.append([_stringify_json_value(rec.get(h)) for h in headers])

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


# ============================================================================
# Database connection + query (T31)
# ============================================================================
#
# Design notes:
# - Lazy-import driver bên trong `_open_db_connection` để user không cài driver
#   vẫn dùng được các auth method HTTP khác (không crash khi import module).
# - Chỉ chấp nhận SELECT / WITH — reject UPDATE/DELETE/DROP/INSERT ở tầng
#   `_run_database_query` (guard cứng, không phụ thuộc DB permission).
# - Bind param NAMED (`:name`) → convert sang placeholder driver-specific
#   (`?` cho pyodbc, `%(name)s` cho psycopg2/pymysql) — CHỈ dùng cursor bind,
#   KHÔNG string concat → an toàn SQL injection.
# - Connection close chắc chắn qua try/finally.


def _convert_named_to_qmark(sql: str, params: dict) -> tuple[str, list]:
    """
    Convert `:name` → `?` cho pyodbc. Trả (sql_mới, ordered_values).

    Regex `(?<!:):([A-Za-z_][A-Za-z0-9_]*)` không match `::` (cast operator
    trong Postgres/SQL Server) — vẫn hoạt động đúng nếu user viết
    `col::text`.
    """
    ordered: list = []
    def _rep(m):
        name = m.group(1)
        ordered.append(params.get(name))
        return "?"
    new_sql = re.sub(r"(?<!:):([A-Za-z_][A-Za-z0-9_]*)", _rep, sql)
    return new_sql, ordered


def _convert_named_to_pyformat(sql: str, params: dict) -> tuple[str, dict]:
    """
    Convert `:name` → `%(name)s` cho psycopg2 / pymysql. Trả (sql_mới,
    dict_params) — chỉ giữ những key thực sự có trong SQL để tránh driver
    error khi truyền param dư.
    """
    used: set[str] = set()
    def _rep(m):
        name = m.group(1)
        used.add(name)
        return f"%({name})s"
    new_sql = re.sub(r"(?<!:):([A-Za-z_][A-Za-z0-9_]*)", _rep, sql)
    return new_sql, {k: params.get(k) for k in used}


def _open_db_connection(auth: dict, username: str, password: str, timeout: int = 10):
    """
    Mở connection tới DB theo `auth.db_driver`. Lazy-import driver.

    Raises:
        ValueError: config thiếu / driver không hỗ trợ / library chưa cài
            (message có gợi ý `pip install ...`).
        Exception subclass tuỳ driver khi connect fail (VD pyodbc.OperationalError,
            psycopg2.OperationalError, pymysql.err.OperationalError).

    Caller có trách nhiệm close connection.
    """
    driver = str(auth.get("db_driver") or "").strip().lower()
    host = str(auth.get("db_host") or "").strip()
    port = int(auth.get("db_port") or 0) or DEFAULT_DB_PORTS.get(driver, 0)
    database = str(auth.get("db_database") or "").strip()

    if driver not in SUPPORTED_DB_DRIVERS:
        raise ValueError(
            f"db_driver không hỗ trợ. Chấp nhận: {', '.join(sorted(SUPPORTED_DB_DRIVERS))}"
        )
    if not host:
        raise ValueError("Thiếu db_host")
    if not database:
        raise ValueError("Thiếu db_database")

    if driver == "sqlserver":
        try:
            import pyodbc  # type: ignore  # noqa: WPS433 (lazy import intentional)
        except ImportError as e:
            raise ValueError(
                "Chưa cài driver 'pyodbc'. Chạy: pip install pyodbc "
                "(Windows: cần cài sẵn ODBC Driver 17 hoặc 18 for SQL Server). "
                f"[import err: {e}]"
            )
        # Ưu tiên ODBC Driver 18 (phổ biến nhất 2024+), fallback về 17 rồi
        # driver mặc định "SQL Server". Nếu tất cả fail → raise từ lần cuối.
        candidates = (
            "ODBC Driver 18 for SQL Server",
            "ODBC Driver 17 for SQL Server",
            "SQL Server",
        )
        last_err: Optional[Exception] = None
        for odbc in candidates:
            conn_str = (
                f"DRIVER={{{odbc}}};SERVER={host},{port};DATABASE={database};"
                f"UID={username};PWD={password};"
                # TrustServerCertificate=yes cần cho ODBC 18 (mặc định
                # Encrypt=yes) nếu server dùng self-signed cert (đa số
                # internal DB đều rơi vào case này).
                "TrustServerCertificate=yes;"
            )
            try:
                return pyodbc.connect(conn_str, timeout=timeout)
            except Exception as e:  # pyodbc.Error subclass
                last_err = e
                continue
        raise ValueError(
            f"Không kết nối được SQL Server (đã thử {len(candidates)} ODBC driver). "
            f"Lỗi cuối: {type(last_err).__name__}: {str(last_err)[:200]}"
        )

    if driver == "postgres":
        try:
            import psycopg2  # type: ignore
        except ImportError as e:
            raise ValueError(
                "Chưa cài driver 'psycopg2'. Chạy: pip install psycopg2-binary. "
                f"[import err: {e}]"
            )
        return psycopg2.connect(
            host=host, port=port, dbname=database,
            user=username, password=password,
            connect_timeout=timeout,
        )

    if driver == "mysql":
        try:
            import pymysql  # type: ignore
        except ImportError as e:
            raise ValueError(
                "Chưa cài driver 'pymysql'. Chạy: pip install pymysql. "
                f"[import err: {e}]"
            )
        return pymysql.connect(
            host=host, port=port, database=database,
            user=username, password=password,
            connect_timeout=timeout,
        )

    raise ValueError(f"Chưa implement db_driver='{driver}'")


# SELECT-only guard: chỉ cho phép statement bắt đầu bằng SELECT / WITH.
# Chặn UPDATE/DELETE/DROP/INSERT/CALL/EXEC v.v. ở tầng backend (không phụ
# thuộc user setup DB permission — defense in depth).
_ALLOWED_QUERY_KEYWORDS = {"SELECT", "WITH"}


def _run_database_query(auth: dict, username: str, password: str, endpoint: dict,
                        *, timeout: int = 10) -> list[dict]:
    """
    Execute SELECT query trên DB → list[dict] (key = column name).

    Bind param an toàn qua cursor.execute(sql, params) — KHÔNG string concat.

    Raises ValueError với message rõ ràng cho các case:
        - query rỗng / không phải SELECT.
        - driver chưa cài / config thiếu (từ `_open_db_connection`).
        - query fail (bắt exception cụ thể của driver, format lại).
    """
    query = str(endpoint.get("query") or "").strip()
    if not query:
        raise ValueError("Endpoint chưa có SQL 'query'")

    # Strip trailing semicolons + comment đơn giản để lấy keyword đầu.
    query_stripped = re.sub(r"^\s*(--[^\n]*\n)+", "", query).lstrip()
    first_word = (query_stripped.split(None, 1)[0] if query_stripped else "").upper()
    if first_word not in _ALLOWED_QUERY_KEYWORDS:
        raise ValueError(
            f"Query phải bắt đầu bằng SELECT hoặc WITH (read-only). "
            f"Nhận: '{first_word or query_stripped[:20]}'"
        )

    params = endpoint.get("query_params") or {}
    if not isinstance(params, dict):
        params = {}

    driver = str(auth.get("db_driver") or "").strip().lower()
    conn = _open_db_connection(auth, username, password, timeout=timeout)
    try:
        cursor = conn.cursor()
        try:
            if driver == "sqlserver":
                sql, ordered = _convert_named_to_qmark(query, params)
                cursor.execute(sql, ordered)
            else:
                # psycopg2 + pymysql đều support pyformat named param.
                sql, pyparams = _convert_named_to_pyformat(query, params)
                cursor.execute(sql, pyparams)
            columns: list[str] = (
                [str(d[0]) for d in cursor.description] if cursor.description else []
            )
            rows = cursor.fetchall() if columns else []
        finally:
            try:
                cursor.close()
            except Exception:
                pass
        # Convert rows → list[dict] cho consistency với JSON flow.
        # pyodbc.Row / tuple / list đều iterable → zip an toàn.
        out: list[dict] = []
        for row in rows:
            try:
                out.append({columns[i]: row[i] for i in range(len(columns))})
            except (IndexError, TypeError):
                # Row có kích thước khác columns → skip để không crash toàn bộ.
                continue
        return out
    finally:
        try:
            conn.close()
        except Exception:
            pass


def test_database_connection(auth: dict) -> dict:
    """
    Verify config DB: resolve creds từ .env → mở connection → ping bằng
    query đơn giản `SELECT 1` (an toàn với mọi driver) → close.

    Trả dict {status, message} tương tự `test_integration`.
    """
    try:
        username, password = resolve_credentials(auth.get("credential_env", ""))
    except ValueError as e:
        return {"status": "error", "message": str(e)}
    try:
        conn = _open_db_connection(auth, username, password)
    except ValueError as e:
        return {"status": "error", "message": str(e)}
    except Exception as e:
        return {"status": "error",
                "message": f"Kết nối DB fail: {type(e).__name__}: {str(e)[:250]}"}
    try:
        cur = conn.cursor()
        cur.execute("SELECT 1")
        try:
            cur.fetchone()
        except Exception:
            pass  # 1 số driver không có fetchone trên SELECT 1 → OK
        cur.close()
        driver = str(auth.get("db_driver") or "").strip().lower()
        return {
            "status": "ok",
            "message": f"Kết nối {driver} tới {auth.get('db_host')}/{auth.get('db_database')} OK",
        }
    except Exception as e:
        return {"status": "error",
                "message": f"Ping SELECT 1 fail: {type(e).__name__}: {str(e)[:200]}"}
    finally:
        try:
            conn.close()
        except Exception:
            pass


# ============================================================================
# Endpoint fetch helpers
# ============================================================================

def _resolve_endpoint_url(base_url: str, path: str) -> str:
    """Nếu path là absolute URL → dùng nguyên. Ngược lại prefix base_url."""
    if re.match(r"^https?://", path, re.IGNORECASE):
        return path
    if path.startswith("/"):
        return base_url.rstrip("/") + path
    return base_url.rstrip("/") + "/" + path


def _flatten_json_keys(obj: Any, prefix: str = "", out: Optional[dict] = None) -> dict[str, Any]:
    """
    Duyệt 1 JSON record → dict {dot.path: sample_value}. Dùng cho auto-suggest
    mapping ở FE: user thấy các key khả dụng + giá trị mẫu để chọn.

    Giới hạn depth 5 + tối đa 100 keys để tránh explode với record khổng lồ.
    """
    if out is None:
        out = {}
    if len(out) >= 100:
        return out
    if isinstance(obj, dict):
        for k, v in obj.items():
            new_prefix = f"{prefix}.{k}" if prefix else str(k)
            if isinstance(v, (dict, list)) and prefix.count(".") < 5:
                _flatten_json_keys(v, new_prefix, out)
            else:
                sample = _stringify_json_value(v)
                out[new_prefix] = sample if not isinstance(sample, str) else sample[:120]
            if len(out) >= 100:
                return out
    elif isinstance(obj, list) and obj:
        # Chỉ recurse vào phần tử đầu để giữ tên path ngắn gọn — user thấy
        # `items.code` thay vì `items.0.code`, `items.1.code`… (đủ để suy ra).
        _flatten_json_keys(obj[0], prefix, out)
    return out


def _err(msg: str, **extra) -> dict:
    """Shortcut trả về error dict với payload chuẩn cho FE."""
    base = {"status": "error", "message": msg,
            "snapshot_id": None, "rows_imported": 0, "filename": None}
    base.update(extra)
    return base


def test_integration(
    project_dir: str,
    integration_id: str,
    timeout: int = DEFAULT_TIMEOUT_SECONDS,
) -> dict:
    """
    Test auth. Update `last_sync_status`. Trả dict {status, message, ...}.

    Với `form_login`: thử login → verify.
    Với `basic_auth` / `bearer_token` / `api_key`: chỉ verify credential nạp
    được từ .env (không hit server) vì các method này không có "login" tách biệt.
    Muốn verify server thực sự chấp nhận creds → user bấm Sync 1 endpoint.
    """
    integ = get_integration(project_dir, integration_id)
    if not integ:
        return {"status": "error", "message": "Không tìm thấy integration"}

    method = (integ.get("auth") or {}).get("method") or DEFAULT_AUTH_METHOD
    if method not in SUPPORTED_AUTH_METHODS:
        return {"status": "error",
                "message": f"Auth method '{method}' chưa được hỗ trợ."}

    # T31: database method → verify connection thay vì auth HTTP.
    if method == "database":
        result = test_database_connection(integ.get("auth") or {})
        _update_last_status(project_dir, integration_id, result.get("status", "error"),
                            result.get("message", ""))
        return result

    try:
        session, _extra_query, info = _prepare_authenticated_session(
            base_url=integ["base_url"],
            auth=integ["auth"],
            timeout=timeout,
        )
    except AuthError as e:
        _update_last_status(project_dir, integration_id, "error", str(e))
        return {"status": "error", "message": str(e)}
    except ValueError as e:
        _update_last_status(project_dir, integration_id, "error", str(e))
        return {"status": "error", "message": str(e)}
    except requests.RequestException as e:
        msg = f"Không kết nối được: {type(e).__name__}: {str(e)[:200]}"
        _update_last_status(project_dir, integration_id, "error", msg)
        return {"status": "error", "message": msg}
    finally:
        # session sẽ được close ở đây nếu tồn tại — với try trên nếu raise
        # trước khi tạo session thì cũng không sao vì Python vẫn chạy finally.
        try:
            session.close()  # type: ignore[has-type]
        except Exception:
            pass

    ok_msg = {
        "form_login": "Đăng nhập form thành công",
        "basic_auth": "Basic auth header đã nạp — thử Sync 1 endpoint để verify server chấp nhận",
        "bearer_token": "Bearer token đã nạp — thử Sync 1 endpoint để verify server chấp nhận",
        "api_key": "API key đã nạp — thử Sync 1 endpoint để verify server chấp nhận",
    }.get(method, "OK")
    _update_last_status(project_dir, integration_id, "ok", ok_msg)
    return {"status": "ok", "message": ok_msg, **_safe_info(info)}


def _fetch_endpoint(
    session: requests.Session,
    integ: dict,
    endpoint: dict,
    extra_query: dict[str, str],
    timeout: int,
) -> requests.Response:
    """Gọi GET/POST endpoint. Raise requests.RequestException khi network fail."""
    endpoint_url = _resolve_endpoint_url(integ["base_url"], endpoint.get("path") or "")
    http_method = (endpoint.get("http_method") or "GET").upper()
    params: dict[str, str] = dict(endpoint.get("params") or {})
    # api_key ở query location — merge vào params (chỉ khi key chưa có trong params)
    for k, v in (extra_query or {}).items():
        params.setdefault(k, v)

    if http_method == "POST":
        # Với POST + JSON API thường body là JSON — nhưng để không mở rộng UI
        # quá phức tạp, MVP dùng params làm form-data cho POST giống spec cũ.
        # Nếu user cần JSON body → header Content-Type sẽ được set trong integration
        # extra_fields (bổ sung sau nếu cần).
        return session.post(endpoint_url, data=params, timeout=timeout, allow_redirects=True)
    return session.get(endpoint_url, params=params, timeout=timeout, allow_redirects=True)


def _run_database_sync(
    integ: dict,
    endpoint: dict,
    *,
    project_dir: str,
    project_manager,
    project_slug: str,
    long_duration_threshold: int,
    timeout: int,
) -> dict:
    """
    Sync 1 endpoint database: resolve creds → execute query → build xlsx →
    parse → save snapshot. Cấu trúc trả về giống `sync_integration` để FE
    không phải phân biệt.
    """
    integration_id = integ.get("id") or ""
    auth = integ.get("auth") or {}
    # 1) Resolve creds
    try:
        username, password = resolve_credentials(auth.get("credential_env", ""))
    except ValueError as e:
        _update_last_status(project_dir, integration_id, "error", str(e))
        return _err(str(e))

    # 2) Execute query → list[dict]
    try:
        records = _run_database_query(auth, username, password, endpoint, timeout=timeout)
    except ValueError as e:
        _update_last_status(project_dir, integration_id, "error", str(e))
        return _err(str(e))
    except Exception as e:
        msg = f"Query fail: {type(e).__name__}: {str(e)[:250]}"
        _update_last_status(project_dir, integration_id, "error", msg)
        return _err(msg)

    if not records:
        msg = ("Query trả 0 row. Kiểm tra lại WHERE clause hoặc query_params.")
        _update_last_status(project_dir, integration_id, "error", msg)
        return _err(msg)

    # 3) Convert list[dict] → xlsx (dùng chung logic với JSON API).
    #    field_mapping rỗng → dùng union keys làm header (SQL alias =
    #    tên cột iHRP chuẩn nếu user viết `SELECT col AS [Mã CN] ...`).
    field_mapping = endpoint.get("field_mapping") or {}
    try:
        xlsx_bytes = build_xlsx_from_json_records(records, field_mapping if isinstance(field_mapping, dict) else {})
    except Exception as e:
        msg = f"Build xlsx từ DB records lỗi: {type(e).__name__}: {str(e)[:200]}"
        _update_last_status(project_dir, integration_id, "error", msg)
        return _err(msg)

    ts = datetime.now().strftime("%Y%m%d_%H%M")
    filename = f"synced_db_{ts}.xlsx"
    target_path = os.path.join(project_dir, filename)
    try:
        with open(target_path, "wb") as fout:
            fout.write(xlsx_bytes)
    except OSError as e:
        msg = f"Không lưu được file tạm: {e}"
        _update_last_status(project_dir, integration_id, "error", msg)
        return _err(msg)

    # 4) Parse (chung với excel/json flow)
    try:
        parsed = FunctionListParser().parse(target_path)
        metrics = DashboardEngine(long_duration_threshold=long_duration_threshold).compute_all(parsed)
    except Exception as e:
        msg = f"Parse file lỗi: {type(e).__name__}: {str(e)[:300]}"
        _update_last_status(project_dir, integration_id, "error", msg)
        return _err(msg, filename=filename)

    rows_count = len(parsed.rows)

    # 5) Save snapshot
    target_action = (endpoint.get("target_action") or "snapshot").lower()
    snapshot_entry = None
    try:
        smgr = project_manager.get_snapshot_manager(project_slug)
        snapshot_entry = smgr.save_snapshot(
            target_path, parsed, metrics,
            source=f"sync:{integration_id}:{endpoint.get('id') or 'db'}",
        )
        if target_action == "replace":
            import shutil as _sh
            _sh.copy2(target_path, project_manager.get_current_file_path(project_slug))
            project_manager.touch_last_upload(project_slug)
        # Ghi lịch sử upload với source=sync:...
        try:
            from analyzer import project_store as _ps
            ep_id = endpoint.get("id") or "db"
            _ps.append_upload_history(
                project_dir,
                filename=filename or os.path.basename(target_path),
                row_count=rows_count,
                source=f"sync:{integration_id}:{ep_id}",
                extra={
                    "modules": len(getattr(parsed, "all_modules", []) or []),
                    "phases": len(getattr(parsed, "all_phases", []) or []),
                    "integration_id": integration_id,
                    "endpoint_id": ep_id,
                },
            )
        except Exception:
            pass
    except Exception as e:
        msg = f"Lưu snapshot lỗi: {type(e).__name__}: {str(e)[:200]}"
        _update_last_status(project_dir, integration_id, "error", msg)
        return _err(msg, rows_imported=rows_count, filename=filename)

    ok_msg = (f"Đã query {rows_count} dòng · snapshot "
              f"{snapshot_entry.get('date') if snapshot_entry else '?'} · "
              f"endpoint '{endpoint.get('name')}' [database]")
    _update_last_status(project_dir, integration_id, "ok", ok_msg, sync_time=True)
    return {
        "status": "ok",
        "message": ok_msg,
        "snapshot_id": snapshot_entry.get("date") if snapshot_entry else None,
        "snapshot_entry": snapshot_entry,
        "rows_imported": rows_count,
        "filename": filename,
        "target_action": target_action,
        "response_type": "database",
    }


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
    Đồng bộ 1 endpoint: auth → tải Excel HOẶC JSON → (json thì convert xlsx qua
    field_mapping) → parse → save snapshot vào project.

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
          "snapshot_id": "YYYY-MM-DD" | None,
          "rows_imported": int,
          "filename": str | None,
        }
    """
    integ = get_integration(project_dir, integration_id)
    if not integ:
        return _err("Không tìm thấy integration")

    # Tìm endpoint
    endpoint = next(
        (ep for ep in (integ.get("endpoints") or []) if ep.get("id") == endpoint_id),
        None,
    )
    if not endpoint:
        return _err("Không tìm thấy endpoint trong integration")

    method = (integ.get("auth") or {}).get("method") or DEFAULT_AUTH_METHOD
    if method not in SUPPORTED_AUTH_METHODS:
        return _err(f"Auth method '{method}' chưa hỗ trợ.")

    response_type = (endpoint.get("response_type") or "excel").lower()
    if response_type not in SUPPORTED_RESPONSE_TYPES:
        return _err(
            f"Response type '{response_type}' chưa hỗ trợ "
            f"(supported: {', '.join(sorted(SUPPORTED_RESPONSE_TYPES))})."
        )

    # ---- T31: DATABASE branch — bypass HTTP session hoàn toàn ----
    # Database method KHÔNG có URL / session; đọc trực tiếp qua SQL query.
    # Response type 'database' bắt buộc pair với auth.method='database'
    # (khách trả view → chỉ có 1 flow duy nhất).
    if method == "database" or response_type == "database":
        if method != "database":
            return _err(
                "response_type='database' chỉ dùng khi auth.method='database'"
            )
        if response_type != "database":
            return _err(
                "auth.method='database' chỉ dùng khi response_type='database'"
            )
        return _run_database_sync(
            integ, endpoint,
            project_dir=project_dir,
            project_manager=project_manager,
            project_slug=project_slug,
            long_duration_threshold=long_duration_threshold,
            timeout=timeout,
        )

    # 1) Prepare session (auth)
    try:
        session, extra_query, _auth_info = _prepare_authenticated_session(
            base_url=integ["base_url"],
            auth=integ["auth"],
            timeout=timeout,
        )
    except AuthError as e:
        _update_last_status(project_dir, integration_id, "error", str(e))
        return _err(str(e))
    except ValueError as e:
        _update_last_status(project_dir, integration_id, "error", str(e))
        return _err(str(e))
    except requests.RequestException as e:
        msg = f"Auth network fail: {type(e).__name__}: {str(e)[:200]}"
        _update_last_status(project_dir, integration_id, "error", msg)
        return _err(msg)

    try:
        # 2) Fetch endpoint
        try:
            r_data = _fetch_endpoint(session, integ, endpoint, extra_query, timeout)
        except requests.RequestException as e:
            msg = f"Không tải được: {type(e).__name__}: {str(e)[:200]}"
            _update_last_status(project_dir, integration_id, "error", msg)
            return _err(msg)

        if r_data.status_code >= 400:
            msg = f"Endpoint trả HTTP {r_data.status_code}"
            _update_last_status(project_dir, integration_id, "error", msg)
            return _err(msg)

        # 3) Lưu bytes → file tạm .xlsx (JSON convert trong memory trước)
        ts = datetime.now().strftime("%Y%m%d_%H%M")
        filename = f"synced_{ts}.xlsx"
        target_path = os.path.join(project_dir, filename)

        if response_type == "excel":
            if not _looks_like_excel(r_data):
                ctype = r_data.headers.get("Content-Type", "unknown")
                msg = (f"Response không phải Excel (Content-Type: {ctype}). "
                       f"Kiểm tra lại 'path'/'params' hoặc quyền tài khoản.")
                _update_last_status(project_dir, integration_id, "error", msg)
                return _err(msg)
            xlsx_bytes = r_data.content
        elif response_type == "json":
            try:
                payload = r_data.json()
            except ValueError as e:
                # Content-Type có thể vẫn json/text, nhưng body không parse được
                msg = f"Response không phải JSON hợp lệ: {str(e)[:200]}"
                _update_last_status(project_dir, integration_id, "error", msg)
                return _err(msg)

            data_path = (endpoint.get("data_path") or "").strip()
            field_mapping = endpoint.get("field_mapping") or {}
            if not isinstance(field_mapping, dict) or not field_mapping:
                msg = ("Response JSON nhưng chưa cấu hình 'field_mapping'. "
                       "Vào Editor endpoint → panel Field Mapping để thêm map JSON key → cột.")
                _update_last_status(project_dir, integration_id, "error", msg)
                return _err(msg)

            records = extract_records(payload, data_path)
            if not records:
                msg = (f"Không trích được record nào từ JSON (data_path='{data_path or '<root>'}'"
                       f", type={type(payload).__name__}). Kiểm tra lại data_path.")
                _update_last_status(project_dir, integration_id, "error", msg)
                return _err(msg)
            try:
                xlsx_bytes = build_xlsx_from_json_records(records, field_mapping)
            except Exception as e:
                msg = f"Convert JSON → xlsx lỗi: {type(e).__name__}: {str(e)[:200]}"
                _update_last_status(project_dir, integration_id, "error", msg)
                return _err(msg)
        else:  # pragma: no cover — đã guard ở đầu, giữ để phòng ngừa
            return _err(f"Response type '{response_type}' chưa implement.")

        try:
            with open(target_path, "wb") as fout:
                fout.write(xlsx_bytes)
        except OSError as e:
            msg = f"Không lưu được file tạm: {e}"
            _update_last_status(project_dir, integration_id, "error", msg)
            return _err(msg)

        # 4) Parse Excel (chung cho cả excel + json converted)
        try:
            parsed = FunctionListParser().parse(target_path)
            metrics = DashboardEngine(long_duration_threshold=long_duration_threshold).compute_all(parsed)
        except Exception as e:
            msg = f"Parse file lỗi: {type(e).__name__}: {str(e)[:300]}"
            _update_last_status(project_dir, integration_id, "error", msg)
            return _err(msg, filename=filename)

        rows_count = len(parsed.rows)

        # 5) Save snapshot (append vào project) — tận dụng SnapshotManager
        target_action = (endpoint.get("target_action") or "snapshot").lower()
        snapshot_entry = None
        try:
            smgr = project_manager.get_snapshot_manager(project_slug)
            snapshot_entry = smgr.save_snapshot(
                target_path, parsed, metrics,
                source=f"sync:{integration_id}:{endpoint_id}",
            )
            # replace → copy đè current.xlsx để dashboard load ngay dữ liệu mới.
            # append/snapshot chỉ append, không đổi current.xlsx.
            if target_action == "replace":
                import shutil as _sh
                _sh.copy2(target_path, project_manager.get_current_file_path(project_slug))
                project_manager.touch_last_upload(project_slug)
            # T35 Task 4 — ghi lịch sử với source sync
            try:
                from analyzer import project_store as _ps
                _ps.append_upload_history(
                    project_dir,
                    filename=filename or os.path.basename(target_path),
                    row_count=rows_count,
                    source=f"sync:{integration_id}:{endpoint_id}",
                    extra={
                        "modules": len(getattr(parsed, "all_modules", []) or []),
                        "phases": len(getattr(parsed, "all_phases", []) or []),
                        "integration_id": integration_id,
                        "endpoint_id": endpoint_id,
                    },
                )
            except Exception:
                pass
        except Exception as e:
            msg = f"Lưu snapshot lỗi: {type(e).__name__}: {str(e)[:200]}"
            _update_last_status(project_dir, integration_id, "error", msg)
            return _err(msg, rows_imported=rows_count, filename=filename)

        # 6) Cập nhật status
        ok_msg = (f"Đã tải {rows_count} dòng · snapshot "
                  f"{snapshot_entry.get('date') if snapshot_entry else '?'} · "
                  f"endpoint '{endpoint.get('name')}' [{response_type}]")
        _update_last_status(project_dir, integration_id, "ok", ok_msg, sync_time=True)

        return {
            "status": "ok",
            "message": ok_msg,
            "snapshot_id": snapshot_entry.get("date") if snapshot_entry else None,
            "snapshot_entry": snapshot_entry,
            "rows_imported": rows_count,
            "filename": filename,
            "target_action": target_action,
            "response_type": response_type,
        }
    finally:
        session.close()


def preview_json_endpoint(
    project_dir: str,
    integration_id: str,
    endpoint_id: str,
    *,
    timeout: int = DEFAULT_TIMEOUT_SECONDS,
    max_records: int = 3,
) -> dict:
    """
    Gọi endpoint (auth + fetch) và trả về sample records + flat keys để FE
    auto-suggest field_mapping. KHÔNG tạo snapshot.

    Trả:
        {
          "status": "ok"|"error",
          "message": "...",
          "sample_records": [<max_records records đầu>],
          "flat_keys": {"dot.path": "sample_value_or_first_element"},
          "record_count": int,
        }
    """
    integ = get_integration(project_dir, integration_id)
    if not integ:
        return {"status": "error", "message": "Không tìm thấy integration"}
    endpoint = next(
        (ep for ep in (integ.get("endpoints") or []) if ep.get("id") == endpoint_id),
        None,
    )
    if not endpoint:
        return {"status": "error", "message": "Không tìm thấy endpoint"}

    try:
        session, extra_query, _info = _prepare_authenticated_session(
            base_url=integ["base_url"],
            auth=integ["auth"],
            timeout=timeout,
        )
    except (AuthError, ValueError) as e:
        return {"status": "error", "message": str(e)}
    except requests.RequestException as e:
        return {"status": "error",
                "message": f"Auth network fail: {type(e).__name__}: {str(e)[:200]}"}

    try:
        try:
            r_data = _fetch_endpoint(session, integ, endpoint, extra_query, timeout)
        except requests.RequestException as e:
            return {"status": "error",
                    "message": f"Fetch fail: {type(e).__name__}: {str(e)[:200]}"}

        if r_data.status_code >= 400:
            return {"status": "error", "message": f"Endpoint trả HTTP {r_data.status_code}"}

        try:
            payload = r_data.json()
        except ValueError as e:
            return {"status": "error",
                    "message": f"Response không phải JSON hợp lệ: {str(e)[:200]}"}

        data_path = (endpoint.get("data_path") or "").strip()
        records = extract_records(payload, data_path)
        if not records:
            # Trả về flat keys của payload chính để user vẫn thấy structure và
            # sửa data_path cho đúng.
            return {
                "status": "ok",
                "message": (f"Không trích được record với data_path='{data_path or '<root>'}'. "
                            f"Payload là {type(payload).__name__} — điều chỉnh data_path để trỏ tới array."),
                "sample_records": [],
                "flat_keys": _flatten_json_keys(payload),
                "record_count": 0,
            }
        first = records[0]
        return {
            "status": "ok",
            "message": f"Preview {min(max_records, len(records))}/{len(records)} record",
            "sample_records": records[:max_records],
            "flat_keys": _flatten_json_keys(first),
            "record_count": len(records),
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
    Metadata FE dùng để populate dropdown auth method / response type / target
    action. Tất cả 4 auth method + 2 response type (excel/json) đều đã ready
    (first-class). Chỉ `csv` reserve chưa implement.

    Thêm `auth_method_fields` để FE biết mỗi method cần hiện field nào (dynamic
    show/hide trong Editor).
    """
    return {
        "auth_methods": [
            {"value": m, "supported": True}
            for m in sorted(SUPPORTED_AUTH_METHODS)
        ] + [
            {"value": m, "supported": False, "hint": "Đang phát triển"}
            for m in sorted(_PLANNED_AUTH_METHODS)
        ],
        "auth_method_fields": {
            # Fields user cần điền cho mỗi method. FE dùng để show/hide trong
            # editor + hint text mô tả env variable cần set.
            "form_login": {
                "required": ["credential_env", "login_path"],
                "optional": ["username_field", "password_field", "extra_fields"],
                "env_vars": ["<PREFIX>_USERNAME", "<PREFIX>_PASSWORD"],
                "description": "Đăng nhập form HTML — POST username/password + tự parse CSRF nếu có.",
            },
            "basic_auth": {
                "required": ["credential_env"],
                "optional": [],
                "env_vars": ["<PREFIX>_USERNAME", "<PREFIX>_PASSWORD"],
                "description": "HTTP Basic Auth — gửi header Authorization: Basic <base64(user:pass)>.",
            },
            "bearer_token": {
                "required": ["bearer_env"],
                "optional": [],
                "env_vars": ["<PREFIX>_TOKEN"],
                "description": "Bearer token — gửi header Authorization: Bearer <token>. Dùng cho REST API JWT / OAuth token cố định.",
            },
            "api_key": {
                "required": ["apikey_env", "apikey_header", "apikey_location"],
                "optional": [],
                "env_vars": ["<PREFIX>_KEY"],
                "description": "API Key — gửi qua header (VD X-API-Key) hoặc query param.",
            },
            "database": {
                "required": ["db_driver", "db_host", "db_database", "credential_env"],
                "optional": ["db_port"],
                "env_vars": ["<PREFIX>_USERNAME", "<PREFIX>_PASSWORD"],
                "description": (
                    "Database (SQL view) — kết nối trực tiếp SQL Server / Postgres / MySQL "
                    "và execute SELECT view/query do khách trả. "
                    "Endpoint dùng 'query' + 'query_params' (bind :name an toàn)."
                ),
            },
        },
        "response_types": [
            {"value": r, "supported": True}
            for r in sorted(SUPPORTED_RESPONSE_TYPES)
        ] + [
            {"value": r, "supported": False, "hint": "Đang phát triển"}
            for r in sorted(_PLANNED_RESPONSE_TYPES)
        ],
        "target_actions": sorted(SUPPORTED_TARGET_ACTIONS),
        "apikey_locations": sorted(SUPPORTED_APIKEY_LOCATIONS),
        "db_drivers": [
            {"value": "sqlserver", "label": "SQL Server (pyodbc)",
             "default_port": DEFAULT_DB_PORTS["sqlserver"],
             "hint": "Windows cần cài sẵn ODBC Driver 17 hoặc 18 for SQL Server"},
            {"value": "postgres", "label": "PostgreSQL (psycopg2)",
             "default_port": DEFAULT_DB_PORTS["postgres"],
             "hint": "pip install psycopg2-binary"},
            {"value": "mysql", "label": "MySQL (pymysql)",
             "default_port": DEFAULT_DB_PORTS["mysql"],
             "hint": "pip install pymysql"},
        ],
        "default_timeout_seconds": DEFAULT_TIMEOUT_SECONDS,
        # Gợi ý cột chuẩn để FE prefill Field Mapping panel (JSON response_type).
        # Không bắt buộc — user có thể thêm cột riêng.
        "default_field_columns": [
            "Mã CN", "Tên chức năng", "Module", "Quy trình", "Priority",
            "Complexity", "FIT/GAP", "Giai đoạn",
            "Analysis - Start", "Analysis - End", "Analysis - Status", "Analysis - PIC",
            "Dev - Start", "Dev - End", "Dev - Status", "Dev - PIC",
            "UAT - From", "UAT - To", "UAT - Status", "UAT - PIC",
        ],
    }
