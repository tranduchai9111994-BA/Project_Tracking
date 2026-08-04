"""
B1 — BA Task Store: quản lý đầu việc giai đoạn phân tích (task/họp/sản phẩm/nợ KH).

Lưu trữ: JSON file `<project_dir>/ba_tasks.json` — nhất quán với cách app lưu
bookmarks/capacity/... (analyzer/project_store.py), không dùng database.

So với `_write_json` cũ (ghi trực tiếp, không lock): file này bị CRUD ghi
thường xuyên hơn (mỗi lần tạo/sửa/xoá 1 task) nên bổ sung:
  - Ghi atomic (tmp file + os.replace) — tránh file hỏng nếu crash giữa lúc ghi.
  - Lock trong tiến trình theo path — tránh 2 request Flask cùng lúc ghi đè nhau.
"""
from __future__ import annotations

import json
import os
import threading
import uuid
from datetime import date
from typing import Any, Optional

TASK_TYPES = ("task", "meeting", "deliverable", "customer_debt")
STATUSES = ("open", "in_progress", "done", "blocked", "cancelled")
PRIORITIES = ("high", "medium", "low")
DONE_STATUSES = ("done", "cancelled")

_SUB_INFO_KEY = {
    "meeting": "meeting_info",
    "deliverable": "deliverable_info",
    "customer_debt": "debt_info",
}

DEFAULT_SETTINGS: dict[str, Any] = {
    "default_assignee": None,
    "week_start_day": "monday",
    "auto_alert_days_before": 2,
}

_locks_guard = threading.Lock()
_locks: dict[str, threading.Lock] = {}


def _lock_for(path: str) -> threading.Lock:
    with _locks_guard:
        lock = _locks.get(path)
        if lock is None:
            lock = threading.Lock()
            _locks[path] = lock
        return lock


def _store_path(project_dir: str) -> str:
    return os.path.join(project_dir, "ba_tasks.json")


def _empty_store() -> dict[str, Any]:
    return {"tasks": [], "settings": dict(DEFAULT_SETTINGS)}


def _read_store(project_dir: str) -> dict[str, Any]:
    path = _store_path(project_dir)
    if not os.path.isfile(path):
        return _empty_store()
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return _empty_store()
    if not isinstance(data, dict):
        return _empty_store()
    data.setdefault("tasks", [])
    settings = data.setdefault("settings", {})
    for k, v in DEFAULT_SETTINGS.items():
        settings.setdefault(k, v)
    return data


def _write_store(project_dir: str, data: dict[str, Any]) -> None:
    """CHỈ ghi — không tự lock. Dùng qua `_mutate` để lock trọn read-modify-write."""
    path = _store_path(project_dir)
    os.makedirs(project_dir, exist_ok=True)
    tmp_path = f"{path}.tmp-{os.getpid()}-{uuid.uuid4().hex[:8]}"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp_path, path)  # atomic trên cả Windows và POSIX


def _mutate(project_dir: str, fn):
    """Lock quanh TOÀN BỘ read → fn(store) → write — tránh 2 request Flask cùng
    lúc đọc cùng bản cũ rồi ghi đè nhau (VD 2 lần DELETE chạy song song sẽ mất
    1 lần xoá nếu chỉ lock riêng bước ghi). fn nhận `store`, trả về giá trị cần
    return cho caller; fn tự mutate `store["tasks"]`/`store["settings"]`.
    """
    path = _store_path(project_dir)
    with _lock_for(path):
        store = _read_store(project_dir)
        result = fn(store)
        _write_store(project_dir, store)
        return result


def _new_id() -> str:
    return f"task_{uuid.uuid4().hex[:12]}"


def _week_iso(d: date) -> str:
    y, w, _ = d.isocalendar()
    return f"{y:04d}-W{w:02d}"


def _parse_date(value: Any) -> Optional[date]:
    if not value:
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def compute_alert(task: dict[str, Any], today: date, auto_alert_days_before: int = 2) -> Optional[str]:
    """overdue | upcoming | blocked | None — theo rule B2 của roadmap."""
    if task.get("status") in DONE_STATUSES:
        return None
    due = _parse_date(task.get("due_date"))
    if due and due < today:
        return "overdue"
    if task.get("status") == "blocked":
        return "blocked"
    if due and (due - today).days <= auto_alert_days_before:
        return "upcoming"
    return None


def _with_alert(task: dict[str, Any], today: date, auto_alert_days_before: int) -> dict[str, Any]:
    out = dict(task)
    out["alert_level"] = compute_alert(task, today, auto_alert_days_before)
    return out


def _normalize(payload: dict[str, Any], *, base: Optional[dict[str, Any]] = None, today: Optional[date] = None) -> dict[str, Any]:
    """Chuẩn hoá 1 task: set default field, validate type/status/priority, gán week_iso khi tạo mới."""
    today = today or date.today()
    task = dict(base) if base else {}

    def _pick(key: str, choices: tuple[str, ...], default: str) -> str:
        v = payload.get(key, task.get(key, default))
        return v if v in choices else default

    task["title"] = str(payload.get("title", task.get("title", ""))).strip()
    task["module"] = payload.get("module", task.get("module", "")) or ""
    task["type"] = _pick("type", TASK_TYPES, "task")
    task["status"] = _pick("status", STATUSES, "open")
    task["priority"] = _pick("priority", PRIORITIES, "medium")
    task["assignee"] = payload.get("assignee", task.get("assignee")) or ""
    task["due_date"] = payload.get("due_date", task.get("due_date"))
    task["done_date"] = payload.get("done_date", task.get("done_date"))
    if task["status"] == "done" and not task.get("done_date"):
        task["done_date"] = today.isoformat()
    task["tags"] = list(payload.get("tags", task.get("tags") or []))
    task["notes"] = payload.get("notes", task.get("notes", "")) or ""
    task["linked_functions"] = list(payload.get("linked_functions", task.get("linked_functions") or []))

    sub_key = _SUB_INFO_KEY.get(task["type"])
    for k in _SUB_INFO_KEY.values():
        task.setdefault(k, None)
    if sub_key:
        if sub_key in payload:
            task[sub_key] = payload[sub_key]
    else:
        task["meeting_info"] = None
        task["deliverable_info"] = None
        task["debt_info"] = None

    if "id" not in task:
        task["id"] = _new_id()
        task["created_at"] = today.isoformat()
        task["week_iso"] = _week_iso(today)

    return task


def list_tasks(project_dir: str, *, today: Optional[date] = None) -> list[dict[str, Any]]:
    """Toàn bộ task, đã gắn alert_level. Filter/sort để B2 xử lý ở tầng route."""
    today = today or date.today()
    store = _read_store(project_dir)
    days = store["settings"].get("auto_alert_days_before", 2)
    return [_with_alert(t, today, days) for t in store["tasks"]]


def get_task(project_dir: str, task_id: str, *, today: Optional[date] = None) -> Optional[dict[str, Any]]:
    today = today or date.today()
    store = _read_store(project_dir)
    for t in store["tasks"]:
        if t.get("id") == task_id:
            days = store["settings"].get("auto_alert_days_before", 2)
            return _with_alert(t, today, days)
    return None


def create_task(project_dir: str, payload: dict[str, Any], *, today: Optional[date] = None) -> dict[str, Any]:
    today = today or date.today()

    def _do(store: dict[str, Any]) -> dict[str, Any]:
        task = _normalize(payload, today=today)
        store["tasks"].append(task)
        days = store["settings"].get("auto_alert_days_before", 2)
        return _with_alert(task, today, days)

    return _mutate(project_dir, _do)


def bulk_create_tasks(project_dir: str, payloads: list[dict[str, Any]], *, today: Optional[date] = None) -> list[dict[str, Any]]:
    today = today or date.today()

    def _do(store: dict[str, Any]) -> list[dict[str, Any]]:
        created = []
        for payload in payloads:
            task = _normalize(payload, today=today)
            store["tasks"].append(task)
            created.append(task)
        days = store["settings"].get("auto_alert_days_before", 2)
        return [_with_alert(t, today, days) for t in created]

    return _mutate(project_dir, _do)


def update_task(project_dir: str, task_id: str, payload: dict[str, Any], *, today: Optional[date] = None) -> Optional[dict[str, Any]]:
    today = today or date.today()

    def _do(store: dict[str, Any]) -> Optional[dict[str, Any]]:
        for idx, t in enumerate(store["tasks"]):
            if t.get("id") == task_id:
                updated = _normalize(payload, base=t, today=today)
                store["tasks"][idx] = updated
                days = store["settings"].get("auto_alert_days_before", 2)
                return _with_alert(updated, today, days)
        return None

    return _mutate(project_dir, _do)


def delete_task(project_dir: str, task_id: str) -> bool:
    def _do(store: dict[str, Any]) -> bool:
        before = len(store["tasks"])
        store["tasks"] = [t for t in store["tasks"] if t.get("id") != task_id]
        return len(store["tasks"]) != before

    return _mutate(project_dir, _do)


def week_date_range(week_iso: str) -> Optional[tuple[date, date]]:
    """'2026-W31' → (Monday, Sunday) của tuần đó. None nếu parse lỗi."""
    try:
        year_s, week_s = week_iso.split("-W")
        monday = date.fromisocalendar(int(year_s), int(week_s), 1)
        return monday, date.fromisocalendar(int(year_s), int(week_s), 7)
    except (ValueError, IndexError):
        return None


def tasks_in_week(tasks: list[dict[str, Any]], week_iso: str, date_field: str = "due_date") -> list[dict[str, Any]]:
    """Task có week_iso khớp HOẶC `date_field` rơi trong tuần đó."""
    rng = week_date_range(week_iso)
    out = []
    for t in tasks:
        if t.get("week_iso") == week_iso:
            out.append(t)
            continue
        if rng:
            d = _parse_date(t.get(date_field))
            if d and rng[0] <= d <= rng[1]:
                out.append(t)
    return out


def filter_and_sort(
    tasks: list[dict[str, Any]],
    *,
    type: Optional[str] = None,  # noqa: A002 - khớp tên query param roadmap
    status: Optional[str] = None,
    assignee: Optional[str] = None,
    module: Optional[str] = None,
    week: Optional[str] = None,
    priority: Optional[str] = None,
    alert: Optional[str] = None,
    tag: Optional[str] = None,
    sort: Optional[str] = None,
    order: str = "asc",
) -> list[dict[str, Any]]:
    """B2 — filter/sort theo query params. `tasks` phải đã có alert_level (list_tasks)."""
    rows = tasks
    if type:
        rows = [t for t in rows if t.get("type") == type]
    if status:
        rows = [t for t in rows if t.get("status") == status]
    if assignee:
        rows = [t for t in rows if (t.get("assignee") or "").strip().lower() == assignee.strip().lower()]
    if module:
        rows = [t for t in rows if (t.get("module") or "").strip().lower() == module.strip().lower()]
    if week:
        rows = [t for t in rows if t.get("week_iso") == week]
    if priority:
        rows = [t for t in rows if t.get("priority") == priority]
    if alert:
        rows = [t for t in rows if t.get("alert_level") == alert]
    if tag:
        rows = [t for t in rows if tag in (t.get("tags") or [])]

    sort_key = sort if sort in ("due_date", "created_at", "priority") else "created_at"
    reverse = (order or "asc").lower() == "desc"
    rows = sorted(rows, key=lambda t: (t.get(sort_key) is None, t.get(sort_key) or ""), reverse=reverse)
    return rows


# ------------------------------------------------------------------
# B2 — Import từ Excel (title/module/assignee/due_date/type/notes)
# ------------------------------------------------------------------

IMPORT_FIELDS = ("title", "module", "assignee", "due_date", "type", "notes")

_IMPORT_FIELD_ALIASES: dict[str, tuple[str, ...]] = {
    "title": ("title", "tiêu đề", "tieu de", "đầu việc", "dau viec", "task", "tên", "ten", "ten cong viec"),
    "module": ("module", "phân hệ", "phan he"),
    "assignee": ("assignee", "pic", "người phụ trách", "nguoi phu trach", "phụ trách", "phu trach"),
    "due_date": ("due_date", "due date", "hạn", "han", "deadline", "ngày hết hạn", "ngay het han"),
    "type": ("type", "loại", "loai"),
    "notes": ("notes", "note", "ghi chú", "ghi chu", "mô tả", "mo ta"),
}


def _norm_header(s: Any) -> str:
    return str(s or "").strip().lower()


def suggest_import_mapping(headers: list[str]) -> dict[str, str]:
    """Đề xuất mapping field → header thực tế, theo alias — dùng cho preview trước confirm."""
    mapping: dict[str, str] = {}
    normed = [(_norm_header(h), h) for h in headers if h]
    for field, aliases in _IMPORT_FIELD_ALIASES.items():
        for norm_h, orig_h in normed:
            if norm_h in aliases or any(a in norm_h for a in aliases):
                mapping[field] = orig_h
                break
    return mapping


def build_import_payloads(
    headers: list[str], rows: list[list[Any]], mapping: dict[str, str],
) -> list[dict[str, Any]]:
    """Map raw Excel rows → list payload cho bulk_create_tasks. Bỏ row không có title."""
    col_idx: dict[str, int] = {}
    for field, header_name in mapping.items():
        if field in IMPORT_FIELDS and header_name in headers:
            col_idx[field] = headers.index(header_name)

    def _cell(row: list[Any], field: str) -> str:
        i = col_idx.get(field)
        if i is None or i >= len(row) or row[i] is None:
            return ""
        return str(row[i]).strip()

    payloads: list[dict[str, Any]] = []
    for row in rows:
        if not row or all(v is None or str(v).strip() == "" for v in row):
            continue
        title = _cell(row, "title")
        if not title:
            continue
        payload: dict[str, Any] = {"title": title, "status": "open"}
        if "module" in col_idx:
            payload["module"] = _cell(row, "module")
        if "assignee" in col_idx:
            payload["assignee"] = _cell(row, "assignee")
        if "due_date" in col_idx:
            due = _cell(row, "due_date")
            payload["due_date"] = due[:10] if due else None
        if "type" in col_idx:
            t = _cell(row, "type").lower()
            payload["type"] = t if t in TASK_TYPES else "task"
        if "notes" in col_idx:
            payload["notes"] = _cell(row, "notes")
        payloads.append(payload)
    return payloads


def get_settings(project_dir: str) -> dict[str, Any]:
    return dict(_read_store(project_dir)["settings"])


def update_settings(project_dir: str, payload: dict[str, Any]) -> dict[str, Any]:
    def _do(store: dict[str, Any]) -> dict[str, Any]:
        for k in DEFAULT_SETTINGS:
            if k in payload:
                store["settings"][k] = payload[k]
        return dict(store["settings"])

    return _mutate(project_dir, _do)
