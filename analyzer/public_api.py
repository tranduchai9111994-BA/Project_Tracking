"""
T33 — Public API (REST + iframe + PNG snapshot).

Module này quản lý token public read-only cho phép bên thứ 3 (đối tác, khách,
Confluence/Word/email) truy cập subset metrics của 1 project qua API/iframe/PNG.

Kiến trúc:
- Token lưu trong `.project_store/<slug>/public_tokens.json`:
    {"tokens": [{
        "id":            uuid4 hex,
        "name":          human-readable label,
        "token_prefix":  "pub_" + 8 ký tự đầu (dùng cho UI hint, không nhạy cảm),
        "token_hash":    SHA-256 của FULL token (verify bằng cách hash input,
                         so sánh — không bao giờ lưu plaintext về sau),
        "scope":         list[str] — chart_id / "summary" / "functions" / "*"
                         (`*` = full access),
        "created_at":    ISO 8601,
        "last_used_at":  ISO 8601 hoặc None,
        "revoked":       bool,
    }, ...]}

- Verify: hash header X-API-Key → tìm token match hash + chưa revoke + scope
  cover required scope. Update last_used_at (không throw nếu write fail).

- Rate limit: in-memory dict {token_id: deque[float]} — window 60s, max 60
  request. Vượt → raise RateLimitError → HTTP 429 + Retry-After.

- Thread-safety: dùng lock đơn giản cho rate-limiter dict. File write dùng
  atomic rename (đủ cho single-process dev; production đa worker cần Redis).

Không dùng dependency mới — stdlib (hashlib, secrets, uuid, threading, time).
"""
from __future__ import annotations

import hashlib
import json
import os
import secrets
import threading
import time
import uuid
from collections import deque
from datetime import datetime
from typing import Any, Optional


# ---------- File / const ----------

_TOKENS_FILE = "public_tokens.json"
_MAX_TOKENS_PER_PROJECT = 50
_MAX_NAME_LEN = 100
_MAX_SCOPE_ITEMS = 100          # phòng abuse — user không cần > 100 chart_id
_TOKEN_BYTES = 20               # 20 bytes → 40 hex chars
_TOKEN_PREFIX = "pub_"

# Rate limit
_RL_WINDOW_SEC = 60
_RL_MAX_REQUESTS = 60
_rl_lock = threading.Lock()
_rl_buckets: dict[str, deque[float]] = {}


# ---------- Errors ----------

class PublicApiError(Exception):
    """Base exception cho public API."""
    status_code = 400


class InvalidTokenError(PublicApiError):
    status_code = 401


class TokenScopeError(PublicApiError):
    status_code = 403


class RateLimitError(PublicApiError):
    status_code = 429

    def __init__(self, retry_after: int = _RL_WINDOW_SEC):
        super().__init__(f"Vượt rate limit {_RL_MAX_REQUESTS} req / {_RL_WINDOW_SEC}s")
        self.retry_after = retry_after


# ---------- I/O helpers ----------

def _tokens_path(project_dir: str) -> str:
    return os.path.join(project_dir, _TOKENS_FILE)


def _read_tokens_raw(project_dir: str) -> dict:
    path = _tokens_path(project_dir)
    if not os.path.isfile(path):
        return {"tokens": []}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict) or not isinstance(data.get("tokens"), list):
            return {"tokens": []}
        return data
    except (OSError, json.JSONDecodeError):
        return {"tokens": []}


def _write_tokens_raw(project_dir: str, payload: dict) -> None:
    os.makedirs(project_dir, exist_ok=True)
    path = _tokens_path(project_dir)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


# ---------- Token helpers ----------

def _hash_token(token: str) -> str:
    """SHA-256 hex — one-way, dùng để so sánh."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _generate_token() -> str:
    """Sinh token dạng 'pub_<40 hex>' bằng secrets.token_hex (cryptographic RNG)."""
    return _TOKEN_PREFIX + secrets.token_hex(_TOKEN_BYTES)


def _sanitize_scope(scope: Any) -> list[str]:
    """
    Normalize scope: nhận list[str] hoặc str. Trả về list[str] duy nhất, sorted.
    Value "*" = wildcard access (all charts + summary + functions).
    """
    if scope is None:
        return []
    if isinstance(scope, str):
        scope = [s.strip() for s in scope.split(",")]
    if not isinstance(scope, list):
        raise PublicApiError("scope phải là list[str] hoặc comma-separated string")
    out: set[str] = set()
    for item in scope:
        s = str(item or "").strip()
        if not s:
            continue
        # Cho phép cả '_' và '-' — normalize về '-'
        s = s.replace("_", "-")
        out.add(s)
    if len(out) > _MAX_SCOPE_ITEMS:
        raise PublicApiError(f"Scope quá dài (>{_MAX_SCOPE_ITEMS} entries)")
    return sorted(out)


def _mask_token_view(entry: dict) -> dict:
    """
    Trả về dict để hiển thị FE — không expose token_hash / full token.
    Chỉ token_prefix (8 char đầu) đủ để user nhận dạng token nào.
    """
    return {
        "id": entry.get("id"),
        "name": entry.get("name"),
        "token_prefix": entry.get("token_prefix"),
        "scope": entry.get("scope") or [],
        "created_at": entry.get("created_at"),
        "last_used_at": entry.get("last_used_at"),
        "revoked": bool(entry.get("revoked")),
    }


# ---------- Public CRUD ----------

def list_tokens(project_dir: str, include_revoked: bool = True) -> list[dict]:
    """
    Trả list token đã mask (không expose hash). Sort desc created_at.
    include_revoked=False → chỉ token còn active.
    """
    raw = _read_tokens_raw(project_dir)
    out: list[dict] = []
    for t in raw.get("tokens", []):
        if not isinstance(t, dict):
            continue
        if not include_revoked and t.get("revoked"):
            continue
        out.append(_mask_token_view(t))
    out.sort(key=lambda x: x.get("created_at") or "", reverse=True)
    return out


def create_token(
    project_dir: str,
    name: str,
    scope: Any,
) -> tuple[str, dict]:
    """
    Tạo token mới. Trả (plaintext_token, masked_entry).

    plaintext_token CHỈ trả 1 lần này — sau đó chỉ còn hash. FE cần show
    modal "Copy ngay, sẽ không hiện lại" cho user.

    Raises:
        PublicApiError nếu name rỗng / scope không hợp lệ / vượt cap.
    """
    name = str(name or "").strip()
    if not name:
        raise PublicApiError("Thiếu tên token")
    if len(name) > _MAX_NAME_LEN:
        name = name[:_MAX_NAME_LEN]
    clean_scope = _sanitize_scope(scope)
    # Cho phép scope rỗng nếu user muốn generic — nhưng khi verify sẽ deny
    # tất cả trừ khi có "*". → nudge user chọn ít nhất 1 scope hoặc "*".
    if not clean_scope:
        raise PublicApiError("Chọn ít nhất 1 scope (hoặc '*' cho full access)")

    raw = _read_tokens_raw(project_dir)
    tokens = list(raw.get("tokens", []))
    # Đếm active (chưa revoke) để enforce cap
    active_count = sum(1 for t in tokens if not t.get("revoked"))
    if active_count >= _MAX_TOKENS_PER_PROJECT:
        raise PublicApiError(
            f"Vượt giới hạn {_MAX_TOKENS_PER_PROJECT} token active — hãy revoke bớt"
        )

    plaintext = _generate_token()
    entry = {
        "id": uuid.uuid4().hex,
        "name": name,
        "token_prefix": plaintext[:12],   # 'pub_' + 8 hex chars
        "token_hash": _hash_token(plaintext),
        "scope": clean_scope,
        "created_at": datetime.utcnow().isoformat(timespec="seconds") + "Z",
        "last_used_at": None,
        "revoked": False,
    }
    tokens.append(entry)
    _write_tokens_raw(project_dir, {"tokens": tokens})
    return plaintext, _mask_token_view(entry)


def revoke_token(project_dir: str, token_id: str) -> bool:
    """
    Đánh dấu revoked=True. Trả True nếu tìm thấy + đã đổi state.
    Nếu token đã revoke rồi → vẫn trả True (idempotent).
    """
    token_id = str(token_id or "").strip()
    if not token_id:
        return False
    raw = _read_tokens_raw(project_dir)
    tokens = raw.get("tokens", [])
    hit = False
    for t in tokens:
        if t.get("id") == token_id:
            t["revoked"] = True
            hit = True
            break
    if hit:
        _write_tokens_raw(project_dir, {"tokens": tokens})
    return hit


def verify_token(
    project_dir: str,
    token_string: str,
    required_scope: Optional[str] = None,
) -> dict:
    """
    Verify token — return raw entry (có token_hash) nếu valid.

    Args:
        token_string: giá trị từ header `X-API-Key` hoặc query `?token=`.
        required_scope: nếu set → token.scope phải chứa scope này (hoặc "*").

    Raises:
        InvalidTokenError: token không tồn tại / đã revoke.
        TokenScopeError: scope không match.
    """
    token_string = str(token_string or "").strip()
    if not token_string or not token_string.startswith(_TOKEN_PREFIX):
        raise InvalidTokenError("Thiếu / sai format token (thiếu 'pub_')")

    token_hash = _hash_token(token_string)
    raw = _read_tokens_raw(project_dir)
    match = None
    for t in raw.get("tokens", []):
        # constant-time compare để chống timing-attack (dù rare trong context này)
        if secrets.compare_digest(str(t.get("token_hash") or ""), token_hash):
            match = t
            break
    if not match:
        raise InvalidTokenError("Token không tồn tại")
    if match.get("revoked"):
        raise InvalidTokenError("Token đã bị revoke")

    if required_scope:
        scope_list = match.get("scope") or []
        norm_scope = str(required_scope).replace("_", "-").strip()
        if "*" not in scope_list and norm_scope not in scope_list:
            raise TokenScopeError(
                f"Token không có quyền '{norm_scope}' — scope: {scope_list}"
            )

    return match


def touch_last_used(project_dir: str, token_id: str) -> None:
    """Update last_used_at cho token. Silent-fail để không block request."""
    try:
        raw = _read_tokens_raw(project_dir)
        tokens = raw.get("tokens", [])
        changed = False
        now = datetime.utcnow().isoformat(timespec="seconds") + "Z"
        for t in tokens:
            if t.get("id") == token_id:
                t["last_used_at"] = now
                changed = True
                break
        if changed:
            _write_tokens_raw(project_dir, {"tokens": tokens})
    except Exception:
        pass


# ---------- Rate limit ----------

def check_rate_limit(token_id: str, now: Optional[float] = None) -> None:
    """
    Sliding window: prune events > 60s cũ, nếu deque >= 60 → raise 429.
    Không raise → record thêm 1 event.
    """
    if not token_id:
        return
    if now is None:
        now = time.time()
    with _rl_lock:
        bucket = _rl_buckets.setdefault(token_id, deque())
        cutoff = now - _RL_WINDOW_SEC
        # Prune head
        while bucket and bucket[0] < cutoff:
            bucket.popleft()
        if len(bucket) >= _RL_MAX_REQUESTS:
            # Retry-After = giây còn lại đến khi entry đầu tiên rơi khỏi window
            retry_after = max(1, int(bucket[0] + _RL_WINDOW_SEC - now) + 1)
            raise RateLimitError(retry_after=retry_after)
        bucket.append(now)


def reset_rate_limit(token_id: Optional[str] = None) -> None:
    """Reset bucket — dùng cho test hoặc admin. token_id=None → clear all."""
    with _rl_lock:
        if token_id is None:
            _rl_buckets.clear()
        else:
            _rl_buckets.pop(token_id, None)


# ---------- Metadata ----------

# Danh sách scope hợp lệ (chart_id + special) — FE hiển thị multi-select.
# Sync với SUPPORTED_EXPORT_CHARTS + các "logical" scope cho public API endpoint.
# Value ở đây là scope key — không nhất thiết trùng chart_id trong FE (một
# chart_id có thể expose qua nhiều endpoint public khác nhau).
PUBLIC_SCOPES: list[dict] = [
    {"key": "*", "label": "Tất cả (full access)"},
    {"key": "summary", "label": "Summary metrics (tổng quan)"},
    {"key": "functions", "label": "Danh sách function (list)"},
    {"key": "module-overview", "label": "Overview theo Module"},
    {"key": "phase-matrix", "label": "Phase × Status matrix"},
    {"key": "phase-stacked", "label": "Progress theo Phase (stacked bar)"},
    {"key": "progress-task-type", "label": "Progress theo Task type"},
    {"key": "pic-workload", "label": "PIC workload"},
    {"key": "priority", "label": "Priority breakdown"},
    {"key": "complexity", "label": "Complexity breakdown"},
    {"key": "fit-gap", "label": "FIT/GAP analysis"},
    {"key": "giai-doan", "label": "Progress theo Giai đoạn"},
    {"key": "overdue", "label": "Danh sách trễ deadline"},
    {"key": "unassigned", "label": "Task chưa có PIC"},
    {"key": "stalled", "label": "Task đình trệ"},
    {"key": "risk", "label": "Risk scores"},
    {"key": "effort-heatmap", "label": "Effort heatmap"},
    {"key": "process", "label": "Process analysis"},
]

PUBLIC_SCOPE_KEYS: set[str] = {s["key"] for s in PUBLIC_SCOPES}
