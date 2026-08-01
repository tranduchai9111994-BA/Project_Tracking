"""
Account store — session login cho iHRP Tracker (local / LAN).

Lưu user tại `.project_store/users.json` (override bằng ENV `IHRP_USERS_FILE`).
Mật khẩu chỉ lưu hash (werkzeug ``generate_password_hash`` / ``check_password_hash``).

Khi file chưa có user nào → tạo mặc định ``admin`` / ``admin`` (role admin).
Người dùng nên đổi mật khẩu ngay sau lần đăng nhập đầu.
"""
from __future__ import annotations

import json
import os
import secrets
import threading
import uuid
from datetime import datetime
from typing import Any, Optional

from werkzeug.security import check_password_hash, generate_password_hash

VALID_ROLES = ("admin", "viewer")
DEFAULT_ADMIN_USERNAME = "admin"
DEFAULT_ADMIN_PASSWORD = "admin"

_lock = threading.Lock()
_USERS_FILENAME = "users.json"
_SECRET_FILENAME = "secret_key"


class AuthError(Exception):
    """Lỗi nghiệp vụ auth (message tiếng Việt cho API)."""

    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.status_code = status_code


def default_store_path() -> str:
    """Path mặc định: ``<project_root>/.project_store/users.json``."""
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(root, ".project_store", _USERS_FILENAME)


def resolve_store_path(environ: Optional[dict] = None) -> str:
    env = environ if environ is not None else os.environ
    override = (env.get("IHRP_USERS_FILE") or "").strip()
    return override if override else default_store_path()


def ensure_secret_key(environ: Optional[dict] = None) -> str:
    """
    SECRET_KEY cho Flask session.

    Ưu tiên ENV ``IHRP_SECRET_KEY``; nếu không có thì đọc/ghi
    ``.project_store/secret_key`` (persist giữa các lần start).
    """
    env = environ if environ is not None else os.environ
    from_env = (env.get("IHRP_SECRET_KEY") or "").strip()
    if from_env:
        return from_env
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    path = os.path.join(root, ".project_store", _SECRET_FILENAME)
    try:
        if os.path.isfile(path):
            with open(path, "r", encoding="utf-8") as f:
                existing = f.read().strip()
            if existing:
                return existing
    except OSError:
        pass
    key = secrets.token_hex(32)
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(key)
    except OSError:
        pass  # session vẫn chạy trong process hiện tại
    return key


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _empty_store() -> dict[str, Any]:
    return {"users": []}


def _read_raw(path: str) -> dict[str, Any]:
    if not os.path.isfile(path):
        return _empty_store()
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return _empty_store()
    if not isinstance(data, dict):
        return _empty_store()
    users = data.get("users")
    if not isinstance(users, list):
        data["users"] = []
    return data


def _write_raw(path: str, data: dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")
    os.replace(tmp, path)


def _public_user(u: dict[str, Any]) -> dict[str, Any]:
    """Trả user dict không kèm password_hash."""
    return {
        "id": u.get("id"),
        "username": u.get("username"),
        "role": u.get("role") or "viewer",
        "created_at": u.get("created_at"),
    }


def ensure_default_admin(path: Optional[str] = None) -> bool:
    """
    Nếu chưa có user nào → tạo admin/admin.

    Returns:
        True nếu vừa tạo default admin, False nếu đã có user.
    """
    store_path = path or resolve_store_path()
    with _lock:
        data = _read_raw(store_path)
        if data["users"]:
            return False
        data["users"].append({
            "id": uuid.uuid4().hex,
            "username": DEFAULT_ADMIN_USERNAME,
            "password_hash": generate_password_hash(DEFAULT_ADMIN_PASSWORD),
            "role": "admin",
            "created_at": _now(),
        })
        _write_raw(store_path, data)
        return True


def authenticate(
    username: str,
    password: str,
    path: Optional[str] = None,
) -> Optional[dict[str, Any]]:
    """
    Verify username/password. Trả public user dict nếu đúng, else None.
    """
    store_path = path or resolve_store_path()
    uname = (username or "").strip()
    if not uname or password is None:
        return None
    with _lock:
        data = _read_raw(store_path)
        for u in data["users"]:
            if (u.get("username") or "").lower() != uname.lower():
                continue
            if check_password_hash(u.get("password_hash") or "", password):
                return _public_user(u)
            return None
    return None


def get_user_by_id(user_id: str, path: Optional[str] = None) -> Optional[dict[str, Any]]:
    store_path = path or resolve_store_path()
    with _lock:
        data = _read_raw(store_path)
        for u in data["users"]:
            if u.get("id") == user_id:
                return _public_user(u)
    return None


def list_users(path: Optional[str] = None) -> list[dict[str, Any]]:
    store_path = path or resolve_store_path()
    with _lock:
        data = _read_raw(store_path)
        return [_public_user(u) for u in data["users"]]


def create_user(
    username: str,
    password: str,
    role: str = "viewer",
    path: Optional[str] = None,
) -> dict[str, Any]:
    """Tạo user mới. Raise AuthError nếu invalid / trùng username."""
    store_path = path or resolve_store_path()
    uname = (username or "").strip()
    if not uname:
        raise AuthError("Tên đăng nhập không được để trống.")
    if len(uname) > 64:
        raise AuthError("Tên đăng nhập tối đa 64 ký tự.")
    if any(c.isspace() for c in uname):
        raise AuthError("Tên đăng nhập không được chứa khoảng trắng.")
    if not password or len(password) < 1:
        raise AuthError("Mật khẩu không được để trống.")
    role_n = (role or "viewer").strip().lower()
    if role_n not in VALID_ROLES:
        raise AuthError(f"Role không hợp lệ (chỉ: {', '.join(VALID_ROLES)}).")

    with _lock:
        data = _read_raw(store_path)
        for u in data["users"]:
            if (u.get("username") or "").lower() == uname.lower():
                raise AuthError("Tên đăng nhập đã tồn tại.", status_code=409)
        entry = {
            "id": uuid.uuid4().hex,
            "username": uname,
            "password_hash": generate_password_hash(password),
            "role": role_n,
            "created_at": _now(),
        }
        data["users"].append(entry)
        _write_raw(store_path, data)
        return _public_user(entry)


def change_password(
    user_id: str,
    new_password: str,
    path: Optional[str] = None,
    *,
    current_password: Optional[str] = None,
    require_current: bool = False,
) -> None:
    """
    Đổi mật khẩu theo user_id.

    Nếu ``require_current=True`` (user tự đổi) → phải cung cấp current_password đúng.
    """
    store_path = path or resolve_store_path()
    if not new_password:
        raise AuthError("Mật khẩu mới không được để trống.")
    if len(new_password) < 1:
        raise AuthError("Mật khẩu mới không được để trống.")

    with _lock:
        data = _read_raw(store_path)
        target = None
        for u in data["users"]:
            if u.get("id") == user_id:
                target = u
                break
        if not target:
            raise AuthError("Không tìm thấy tài khoản.", status_code=404)
        if require_current:
            if not check_password_hash(
                target.get("password_hash") or "", current_password or ""
            ):
                raise AuthError("Mật khẩu hiện tại không đúng.", status_code=403)
        target["password_hash"] = generate_password_hash(new_password)
        _write_raw(store_path, data)


def password_hash_for_username(
    username: str,
    path: Optional[str] = None,
) -> Optional[str]:
    """Helper test — lấy hash đã lưu (không dùng cho API)."""
    store_path = path or resolve_store_path()
    uname = (username or "").strip().lower()
    with _lock:
        data = _read_raw(store_path)
        for u in data["users"]:
            if (u.get("username") or "").lower() == uname:
                return u.get("password_hash")
    return None
