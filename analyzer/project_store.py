"""
Project-scoped JSON stores — capacity, saved views, upload history, aliases, settings.

Mỗi file nằm trong uploads/projects/<slug>/:
  capacity.json, saved_views.json, upload_history.json,
  phase_aliases.json, project_settings.json
"""
from __future__ import annotations

import json
import os
from datetime import datetime
from typing import Any, Optional


DEFAULT_PIC_MD_PER_WEEK = 5.0  # 5 MD = 40 MH
DEFAULT_UPLOAD_REMINDER_DAYS = 7
DEFAULT_SLA = {"must_have_days": 3, "should_have_days": 7}


def _path(project_dir: str, filename: str) -> str:
    return os.path.join(project_dir, filename)


def _read_json(path: str, default: Any) -> Any:
    if not os.path.isfile(path):
        return default
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return default


def _write_json(path: str, data: Any) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


# ------------------------------------------------------------------
# Capacity PIC
# ------------------------------------------------------------------

def load_capacity(project_dir: str) -> dict[str, Any]:
    """{default_md_per_week, pics: {pic_name: md_per_week}}."""
    data = _read_json(_path(project_dir, "capacity.json"), {})
    if not isinstance(data, dict):
        data = {}
    return {
        "default_md_per_week": float(data.get("default_md_per_week", DEFAULT_PIC_MD_PER_WEEK)),
        "pics": dict(data.get("pics") or {}),
    }


def save_capacity(project_dir: str, payload: dict[str, Any]) -> dict[str, Any]:
    out = {
        "default_md_per_week": float(payload.get("default_md_per_week", DEFAULT_PIC_MD_PER_WEEK)),
        "pics": {str(k): float(v) for k, v in (payload.get("pics") or {}).items()},
    }
    _write_json(_path(project_dir, "capacity.json"), out)
    return out


def capacity_mh_for_pic(capacity: dict[str, Any], pic: str) -> float:
    """Trả capacity MH/tuần cho 1 PIC."""
    pics = capacity.get("pics") or {}
    md = pics.get(pic)
    if md is None:
        md = capacity.get("default_md_per_week", DEFAULT_PIC_MD_PER_WEEK)
    return float(md) * 8.0


# ------------------------------------------------------------------
# Saved views
# ------------------------------------------------------------------

def load_saved_views(project_dir: str) -> list[dict]:
    data = _read_json(_path(project_dir, "saved_views.json"), [])
    return data if isinstance(data, list) else []


def save_saved_views(project_dir: str, views: list[dict]) -> list[dict]:
    cleaned = []
    for v in views:
        if not isinstance(v, dict) or not v.get("name"):
            continue
        entry = {
            "id": str(v.get("id") or v["name"]),
            "name": str(v["name"]),
            "modules": list(v.get("modules") or []),
            "processes": list(v.get("processes") or []),
            "pics": list(v.get("pics") or []),
        }
        # Task 4b: optional per-view section_order (nếu view chỉ định layout riêng)
        so = v.get("section_order")
        if isinstance(so, list):
            entry["section_order"] = [str(x) for x in so if x]
        cleaned.append(entry)
    _write_json(_path(project_dir, "saved_views.json"), cleaned)
    return cleaned


def upsert_saved_view(project_dir: str, view: dict) -> list[dict]:
    views = load_saved_views(project_dir)
    vid = str(view.get("id") or view.get("name") or "")
    views = [v for v in views if v.get("id") != vid and v.get("name") != view.get("name")]
    entry = {
        "id": vid or str(view.get("name")),
        "name": str(view.get("name")),
        "modules": list(view.get("modules") or []),
        "processes": list(view.get("processes") or []),
        "pics": list(view.get("pics") or []),
    }
    so = view.get("section_order")
    if isinstance(so, list):
        entry["section_order"] = [str(x) for x in so if x]
    views.append(entry)
    return save_saved_views(project_dir, views)


# ------------------------------------------------------------------
# Section order (Task 4b) — drag-drop layout, global cho project
# ------------------------------------------------------------------
# File: section_order.json = ["id1", "id2", ...] (thứ tự các section id trong dashboard).
# Không set → FE dùng thứ tự HTML mặc định.
# ------------------------------------------------------------------

def load_section_order(project_dir: str) -> list[str]:
    data = _read_json(_path(project_dir, "section_order.json"), [])
    if not isinstance(data, list):
        return []
    return [str(x) for x in data if x]


def save_section_order(project_dir: str, order: list[str]) -> list[str]:
    cleaned = [str(x).strip() for x in (order or []) if str(x).strip()]
    _write_json(_path(project_dir, "section_order.json"), cleaned)
    return cleaned


def reset_section_order(project_dir: str) -> None:
    """Xoá file section_order.json → FE fallback về HTML default."""
    import os as _os
    p = _path(project_dir, "section_order.json")
    if _os.path.exists(p):
        try:
            _os.remove(p)
        except OSError:
            pass


def delete_saved_view(project_dir: str, view_id: str) -> list[dict]:
    views = [v for v in load_saved_views(project_dir)
             if v.get("id") != view_id and v.get("name") != view_id]
    return save_saved_views(project_dir, views)


# ------------------------------------------------------------------
# Upload history (meta only — không copy file)
# ------------------------------------------------------------------

def load_upload_history(project_dir: str) -> list[dict]:
    data = _read_json(_path(project_dir, "upload_history.json"), [])
    return data if isinstance(data, list) else []


def append_upload_history(
    project_dir: str,
    *,
    filename: str,
    row_count: int,
    checksum: str = "",
    extra: Optional[dict] = None,
    max_entries: int = 50,
) -> list[dict]:
    hist = load_upload_history(project_dir)
    entry = {
        "time": datetime.now().isoformat(timespec="seconds"),
        "filename": filename,
        "row_count": row_count,
        "checksum": checksum,
    }
    if extra:
        entry.update(extra)
    hist.insert(0, entry)
    hist = hist[:max_entries]
    _write_json(_path(project_dir, "upload_history.json"), hist)
    return hist


# ------------------------------------------------------------------
# Phase aliases (cross-project template)
# ------------------------------------------------------------------

def load_phase_aliases(project_dir: str) -> dict[str, str]:
    """Map phase_name_local → phase_name_canonical."""
    data = _read_json(_path(project_dir, "phase_aliases.json"), {})
    return {str(k): str(v) for k, v in data.items()} if isinstance(data, dict) else {}


def save_phase_aliases(project_dir: str, aliases: dict[str, str]) -> dict[str, str]:
    out = {str(k): str(v) for k, v in (aliases or {}).items()}
    _write_json(_path(project_dir, "phase_aliases.json"), out)
    return out


# ------------------------------------------------------------------
# Project settings (reminder days, SLA thresholds)
# ------------------------------------------------------------------

def load_project_settings(project_dir: str) -> dict[str, Any]:
    data = _read_json(_path(project_dir, "project_settings.json"), {})
    if not isinstance(data, dict):
        data = {}
    sla = dict(DEFAULT_SLA)
    sla.update(data.get("sla") or {})
    return {
        "upload_reminder_days": int(data.get("upload_reminder_days", DEFAULT_UPLOAD_REMINDER_DAYS)),
        "sla": {
            "must_have_days": int(sla.get("must_have_days", 3)),
            "should_have_days": int(sla.get("should_have_days", 7)),
        },
    }


def save_project_settings(project_dir: str, payload: dict[str, Any]) -> dict[str, Any]:
    current = load_project_settings(project_dir)
    if "upload_reminder_days" in payload:
        current["upload_reminder_days"] = int(payload["upload_reminder_days"])
    if "sla" in payload and isinstance(payload["sla"], dict):
        current["sla"].update({
            k: int(v) for k, v in payload["sla"].items()
            if k in ("must_have_days", "should_have_days")
        })
    _write_json(_path(project_dir, "project_settings.json"), current)
    return current
