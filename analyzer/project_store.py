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
# T26 — Digest scheduler:
#   day_of_week: 0=Monday .. 6=Sunday (theo datetime.weekday())
#   hour: giờ (0-23) — server check thời điểm start-up; nếu >= hour này
#         và chưa gen digest hôm nay → gen.
DEFAULT_DIGEST = {
    "enabled": False,
    "day_of_week": 0,   # Thứ Hai
    "hour": 9,
    "last_generated_date": "",   # YYYY-MM-DD của digest gần nhất
}
# T29 — Threshold cho progress bar + WIP aging.
#   in_progress: % ngưỡng vàng (< in_progress → đỏ nhạt)
#   closed_soon: % ngưỡng xanh (>= closed_soon → xanh đậm)
DEFAULT_PROGRESS_THRESHOLDS = {"in_progress": 30, "closed_soon": 70}
DEFAULT_AGING_WIP_THRESHOLD = 14  # ngày


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
# T24: Bookmarks + Notes per-function
# ------------------------------------------------------------------
# Cấu trúc:
#   bookmarks.json: {"functions": ["MA_CN_1", "MA_CN_2", ...]}
#   function_notes.json: {"MA_CN_1": {"note": "text", "updated_at": iso}, ...}
# Key dùng Mã CN (stable qua các lần upload — row_num thay đổi khi user
# insert/delete row Excel; Mã CN là identifier ổn định nhất).

def load_bookmarks(project_dir: str) -> list[str]:
    data = _read_json(_path(project_dir, "bookmarks.json"), {"functions": []})
    if not isinstance(data, dict):
        return []
    funcs = data.get("functions") or []
    # Dedupe giữ thứ tự
    seen, out = set(), []
    for f in funcs:
        s = str(f).strip()
        if s and s not in seen:
            seen.add(s)
            out.append(s)
    return out


def save_bookmarks(project_dir: str, ma_cns: list[str]) -> list[str]:
    cleaned = []
    seen = set()
    for m in (ma_cns or []):
        s = str(m).strip()
        if s and s not in seen:
            seen.add(s)
            cleaned.append(s)
    _write_json(_path(project_dir, "bookmarks.json"), {"functions": cleaned})
    return cleaned


def toggle_bookmark(project_dir: str, ma_cn: str) -> tuple[bool, list[str]]:
    """Toggle bookmark 1 function. Return (is_bookmarked_now, all_bookmarks)."""
    ma_cn = str(ma_cn).strip()
    if not ma_cn:
        return (False, load_bookmarks(project_dir))
    bookmarks = load_bookmarks(project_dir)
    if ma_cn in bookmarks:
        bookmarks.remove(ma_cn)
        is_now = False
    else:
        bookmarks.append(ma_cn)
        is_now = True
    save_bookmarks(project_dir, bookmarks)
    return (is_now, bookmarks)


def load_function_notes(project_dir: str) -> dict[str, dict]:
    data = _read_json(_path(project_dir, "function_notes.json"), {})
    if not isinstance(data, dict):
        return {}
    out = {}
    for k, v in data.items():
        if isinstance(v, dict) and v.get("note"):
            out[str(k)] = {
                "note": str(v.get("note") or ""),
                "updated_at": str(v.get("updated_at") or ""),
            }
    return out


def save_function_note(project_dir: str, ma_cn: str, note: str) -> dict[str, dict]:
    """Lưu note (rỗng = xoá). Return full notes map."""
    ma_cn = str(ma_cn).strip()
    if not ma_cn:
        return load_function_notes(project_dir)
    notes = load_function_notes(project_dir)
    note_txt = (note or "").strip()
    if note_txt:
        notes[ma_cn] = {"note": note_txt, "updated_at": datetime.now().isoformat(timespec="seconds")}
    elif ma_cn in notes:
        del notes[ma_cn]
    _write_json(_path(project_dir, "function_notes.json"), notes)
    return notes


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
            "project_codes": list(v.get("project_codes") or []),
        }
        # Task 4b: optional per-view section_order (nếu view chỉ định layout riêng)
        so = v.get("section_order")
        if isinstance(so, list):
            entry["section_order"] = [str(x) for x in so if x]
        # Task 6: optional per-view chart_configs (title/caption/hidden override)
        cc = v.get("chart_configs")
        if isinstance(cc, dict):
            per_view: dict[str, dict] = {}
            for k, val in cc.items():
                if isinstance(val, dict):
                    s = _sanitize_chart_config(val)
                    if s:
                        per_view[str(k)] = s
            if per_view:
                entry["chart_configs"] = per_view
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
        "project_codes": list(view.get("project_codes") or []),
    }
    so = view.get("section_order")
    if isinstance(so, list):
        entry["section_order"] = [str(x) for x in so if x]
    cc = view.get("chart_configs")
    if isinstance(cc, dict):
        entry["chart_configs"] = cc  # sanitize xử lý trong save_saved_views
    views.append(entry)
    return save_saved_views(project_dir, views)


# ------------------------------------------------------------------
# Section order (Task 4b) — drag-drop layout, global cho project
# ------------------------------------------------------------------
# File: section_order.json = ["id1", "id2", ...] (thứ tự các section id trong dashboard).
# Không set / rỗng → FE dùng thứ tự HTML mặc định (cảnh báo trước, quản trị cuối).
# Đã save → giữ nguyên order cũ (không migrate phá layout user).
# Reset API xoá file → FE reload về HTML default mới.
#
# DEFAULT (HTML templates/index.html, sau sticky summary+filter):
#   A cảnh báo: overdue, unassigned, stalled, risk, aging-wip, sla, dataquality
#   B tiến độ:   module+tasktype, matrix, phase, giaidoan, process,
#                burndown, capacity, baseline, effort, duration, slow, deps
#   C chi tiết:  gantt, gantt-calendar, kanban, pic, priority, fitgap,
#                function-diff, my-bookmarks
#   D quản trị:  compare, digest, my-digests, custom-dashboards, history
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


# ------------------------------------------------------------------
# Module order — thứ tự Module dùng chung toàn dashboard
# ------------------------------------------------------------------
# File: module_order.json = {"order": ["TMS", "HR", "PR", ...]}
# Chấp nhận thêm (load): list thuần hoặc {"TMS": 1, "HR": 2}.
# Không set → alphabetical (behavior cũ của parser).
# ------------------------------------------------------------------

def load_module_order(project_dir: str) -> list[str]:
    """Trả list tên module theo thứ tự đã lưu (có thể rỗng)."""
    from analyzer.module_order import normalize_order
    data = _read_json(_path(project_dir, "module_order.json"), {"order": []})
    return normalize_order(data)


def save_module_order(project_dir: str, order: list[str]) -> list[str]:
    """Lưu thứ tự module. Schema: {"order": [...]}."""
    from analyzer.module_order import normalize_order
    cleaned = normalize_order(order)
    _write_json(_path(project_dir, "module_order.json"), {"order": cleaned})
    return cleaned


def reset_module_order(project_dir: str) -> None:
    """Xoá module_order.json → fallback alphabetical."""
    import os as _os
    p = _path(project_dir, "module_order.json")
    if _os.path.exists(p):
        try:
            _os.remove(p)
        except OSError:
            pass


# ------------------------------------------------------------------
# Chart notes (T28: comment per-chart trong PDF export)
# ------------------------------------------------------------------
# File: chart_notes.json = {
#   "summary": "Tóm tắt chung của báo cáo (max 500)",
#   "notes": {"section-id-1": "nhận xét (max 200)", ...}
# }
# Dùng chung cho mọi phiên xuất PDF của project → pre-fill textarea lần sau.
_CHART_NOTES_FILE = "chart_notes.json"
_MAX_SUMMARY_LEN = 500
_MAX_NOTE_LEN = 200


def load_chart_notes(project_dir: str) -> dict:
    """Trả về {'summary': str, 'notes': {section_id: text}}."""
    data = _read_json(_path(project_dir, _CHART_NOTES_FILE), {})
    if not isinstance(data, dict):
        data = {}
    summary = str(data.get("summary") or "")[:_MAX_SUMMARY_LEN]
    raw_notes = data.get("notes") or {}
    notes: dict[str, str] = {}
    if isinstance(raw_notes, dict):
        for k, v in raw_notes.items():
            if not v:
                continue
            key = str(k).strip()
            if not key:
                continue
            notes[key] = str(v)[:_MAX_NOTE_LEN]
    return {"summary": summary, "notes": notes}


def save_chart_notes(project_dir: str, payload: dict) -> dict:
    """
    Merge payload vào chart_notes.json.
    - payload["summary"] (optional) → replace summary hiện tại. Rỗng → xoá.
    - payload["notes"] (optional) → merge từng key vào notes hiện tại
      (value rỗng = xoá key đó).
    """
    if not isinstance(payload, dict):
        payload = {}
    current = load_chart_notes(project_dir)
    if "summary" in payload:
        current["summary"] = str(payload.get("summary") or "")[:_MAX_SUMMARY_LEN]
    incoming_notes = payload.get("notes")
    if isinstance(incoming_notes, dict):
        merged = dict(current.get("notes") or {})
        for k, v in incoming_notes.items():
            key = str(k).strip()
            if not key:
                continue
            text = str(v or "").strip()
            if not text:
                merged.pop(key, None)  # rỗng → xoá key
            else:
                merged[key] = text[:_MAX_NOTE_LEN]
        current["notes"] = merged
    _write_json(_path(project_dir, _CHART_NOTES_FILE), current)
    return current


# ------------------------------------------------------------------
# Chart configs (Task 6 — Phase A: title/caption/hide per chart section)
# ------------------------------------------------------------------
# File: chart_configs.json = {target_id: {"title"?, "caption"?, "hidden"?}}
# target_id có thể là section id (VD "section-pic") hoặc canvas id (VD "chartPIC").
# FE tự map + apply override.
# ------------------------------------------------------------------

_CHART_CFG_FILE = "chart_configs.json"


def _sanitize_chart_config(entry: dict) -> dict:
    """Chỉ giữ các key hợp lệ; loại các key rỗng để file không phình."""
    out: dict = {}
    # --- Phase A: title / caption / hidden ---
    if isinstance(entry.get("title"), str) and entry["title"].strip():
        out["title"] = entry["title"].strip()[:200]
    if isinstance(entry.get("caption"), str) and entry["caption"].strip():
        out["caption"] = entry["caption"].strip()[:1000]
    if entry.get("hidden") is True:
        out["hidden"] = True
    # --- Phase B: type / axes / colors / filter_override ---
    ctype = entry.get("type") or entry.get("chart_type")
    if isinstance(ctype, str) and ctype.strip():
        out["type"] = ctype.strip()[:32]
    x_field = entry.get("x_field")
    y_measure = entry.get("y_measure")
    series_field = entry.get("series_field") or None
    if isinstance(x_field, str) and x_field.strip():
        out["x_field"] = x_field.strip()[:32]
    if isinstance(y_measure, str) and y_measure.strip():
        out["y_measure"] = y_measure.strip()[:32]
    if isinstance(series_field, str) and series_field.strip():
        out["series_field"] = series_field.strip()[:32]
    palette = entry.get("palette") or entry.get("colors")
    if isinstance(palette, str) and palette.strip():
        out["palette"] = palette.strip()[:32]
    elif isinstance(palette, list) and palette:
        out["palette"] = [str(c).strip()[:16] for c in palette if c][:16]
    fo = entry.get("filter_override")
    if isinstance(fo, dict) and fo:
        cleaned_fo: dict = {}
        for k in ("modules", "processes", "pics", "priorities", "complexities",
                  "fitgaps", "statuses"):
            v = fo.get(k)
            if isinstance(v, list) and v:
                cleaned_fo[k] = [str(x)[:80] for x in v if x][:100]
        for k in ("overdue_only", "closed_only", "open_only"):
            if fo.get(k) is True:
                cleaned_fo[k] = True
        if cleaned_fo:
            out["filter_override"] = cleaned_fo
    return out


def load_chart_configs(project_dir: str) -> dict[str, dict]:
    data = _read_json(_path(project_dir, _CHART_CFG_FILE), {})
    if not isinstance(data, dict):
        return {}
    cleaned: dict[str, dict] = {}
    for k, v in data.items():
        if isinstance(v, dict):
            s = _sanitize_chart_config(v)
            if s:
                cleaned[str(k)] = s
    return cleaned


def save_chart_configs(project_dir: str, configs: dict[str, dict]) -> dict[str, dict]:
    """Overwrite full map — dùng khi FE gửi bulk."""
    cleaned: dict[str, dict] = {}
    if isinstance(configs, dict):
        for k, v in configs.items():
            if isinstance(v, dict):
                s = _sanitize_chart_config(v)
                if s:
                    cleaned[str(k)] = s
    _write_json(_path(project_dir, _CHART_CFG_FILE), cleaned)
    return cleaned


def upsert_chart_config(project_dir: str, target_id: str, entry: dict) -> dict[str, dict]:
    """
    Update 1 chart config. Nếu entry sanitize xong RỖNG → xoá key.
    Trả về full map sau khi update.
    """
    all_cfg = load_chart_configs(project_dir)
    tid = str(target_id).strip()
    if not tid:
        return all_cfg
    s = _sanitize_chart_config(entry or {})
    if s:
        all_cfg[tid] = s
    else:
        all_cfg.pop(tid, None)
    _write_json(_path(project_dir, _CHART_CFG_FILE), all_cfg)
    return all_cfg


def delete_chart_config(project_dir: str, target_id: str) -> dict[str, dict]:
    all_cfg = load_chart_configs(project_dir)
    all_cfg.pop(str(target_id).strip(), None)
    _write_json(_path(project_dir, _CHART_CFG_FILE), all_cfg)
    return all_cfg


def reset_chart_configs(project_dir: str) -> None:
    """Xoá toàn bộ chart config → về default."""
    import os as _os
    p = _path(project_dir, _CHART_CFG_FILE)
    if _os.path.exists(p):
        try:
            _os.remove(p)
        except OSError:
            pass


def set_chart_config_visibility(
    project_dir: str, mapping: dict
) -> dict[str, dict]:
    """
    Bulk update chỉ trường `hidden` của nhiều section cùng lúc.

    `mapping`: {section_id: visible_bool} — True = hiển thị, False = ẩn.
    Preserve tất cả field khác của entry (title/caption/type/x_field/…).
    Trả về full map chart_configs sau khi cập nhật.

    Dùng cho tab "Hiển thị" trong Settings modal (bulk toggle nhiều section
    trong 1 request thay vì loop POST /chart-config từng cái).
    """
    all_cfg = load_chart_configs(project_dir)
    if not isinstance(mapping, dict):
        return all_cfg
    for sid, visible in mapping.items():
        sid_s = str(sid).strip()
        if not sid_s:
            continue
        entry = dict(all_cfg.get(sid_s) or {})
        if visible:
            # User muốn hiển thị → xoá cờ hidden (nếu có)
            entry.pop("hidden", None)
        else:
            # User muốn ẩn
            entry["hidden"] = True
        s = _sanitize_chart_config(entry)
        if s:
            all_cfg[sid_s] = s
        else:
            # Entry rỗng sau sanitize (không còn field nào) → xoá key để file gọn
            all_cfg.pop(sid_s, None)
    _write_json(_path(project_dir, _CHART_CFG_FILE), all_cfg)
    return all_cfg


# ------------------------------------------------------------------
# Custom dashboards (Task 9 — Dynamic Dashboard Builder)
# ------------------------------------------------------------------
# File: custom_dashboards.json = list of {id, title, caption, chart_type,
#   x_field, y_measure, series_field, filters, palette, created_at}
# Mỗi item = 1 chart user tạo qua wizard/chat.
# ------------------------------------------------------------------

_CUSTOM_DASH_FILE = "custom_dashboards.json"


def _sanitize_custom_dashboard(entry: dict) -> Optional[dict]:
    if not isinstance(entry, dict):
        return None
    title = str(entry.get("title") or "").strip()
    x_field = str(entry.get("x_field") or "").strip()
    if not title or not x_field:
        return None
    out = {
        "id": str(entry.get("id") or "").strip()[:60],
        "title": title[:200],
        "caption": str(entry.get("caption") or "").strip()[:500],
        "chart_type": str(entry.get("chart_type") or "bar").strip()[:32],
        "x_field": x_field[:32],
        "y_measure": str(entry.get("y_measure") or "count").strip()[:32],
        "series_field": (str(entry.get("series_field") or "").strip()[:32] or None),
        "palette": str(entry.get("palette") or "default").strip()[:32],
        "created_at": str(entry.get("created_at") or "")[:32],
        "filters": {},
    }
    fo = entry.get("filters") or {}
    if isinstance(fo, dict):
        for k in ("modules", "processes", "pics", "priorities", "complexities",
                  "fitgaps", "statuses"):
            v = fo.get(k)
            if isinstance(v, list) and v:
                out["filters"][k] = [str(x)[:80] for x in v if x][:100]
        for k in ("overdue_only", "closed_only", "open_only"):
            if fo.get(k) is True:
                out["filters"][k] = True
    if not out["id"]:
        # Auto-gen id từ timestamp
        import time
        out["id"] = f"custom_{int(time.time() * 1000)}"
    if not out["created_at"]:
        out["created_at"] = datetime.now().isoformat(timespec="seconds")
    return out


def load_custom_dashboards(project_dir: str) -> list[dict]:
    data = _read_json(_path(project_dir, _CUSTOM_DASH_FILE), [])
    if not isinstance(data, list):
        return []
    cleaned: list[dict] = []
    for e in data:
        s = _sanitize_custom_dashboard(e)
        if s:
            cleaned.append(s)
    return cleaned


def _save_custom_dashboards(project_dir: str, items: list[dict]) -> list[dict]:
    _write_json(_path(project_dir, _CUSTOM_DASH_FILE), items)
    return items


def upsert_custom_dashboard(project_dir: str, entry: dict) -> Optional[dict]:
    """Thêm mới hoặc update 1 custom dashboard. Trả entry đã lưu (hoặc None nếu invalid)."""
    s = _sanitize_custom_dashboard(entry)
    if not s:
        return None
    items = load_custom_dashboards(project_dir)
    items = [i for i in items if i.get("id") != s["id"]]
    items.append(s)
    _save_custom_dashboards(project_dir, items)
    return s


def delete_custom_dashboard(project_dir: str, item_id: str) -> list[dict]:
    items = [i for i in load_custom_dashboards(project_dir) if i.get("id") != item_id]
    _save_custom_dashboards(project_dir, items)
    return items


# ------------------------------------------------------------------
# PIC → Role map (Task 10 — Kanban filter theo tổ chức)
# ------------------------------------------------------------------
# File: pic_role_map.json = {pic_name: role_string}
# Role không hạn chế enum — user tự đặt (BA, Dev, Tester, PM, Lead, ...).
# ------------------------------------------------------------------

_PIC_ROLE_FILE = "pic_role_map.json"


def load_pic_role_map(project_dir: str) -> dict[str, str]:
    data = _read_json(_path(project_dir, _PIC_ROLE_FILE), {})
    if not isinstance(data, dict):
        return {}
    return {str(k): str(v)[:32] for k, v in data.items() if k and v}


def save_pic_role_map(project_dir: str, mapping: dict[str, str]) -> dict[str, str]:
    if not isinstance(mapping, dict):
        return {}
    cleaned = {str(k).strip()[:80]: str(v).strip()[:32]
               for k, v in mapping.items()
               if str(k).strip() and str(v).strip()}
    _write_json(_path(project_dir, _PIC_ROLE_FILE), cleaned)
    return cleaned


def delete_saved_view(project_dir: str, view_id: str) -> list[dict]:
    views = [v for v in load_saved_views(project_dir)
             if v.get("id") != view_id and v.get("name") != view_id]
    return save_saved_views(project_dir, views)


# ------------------------------------------------------------------
# Upload history (meta only — không copy file)
# ------------------------------------------------------------------

# Giới hạn lịch sử UI/meta — đồng bộ với MAX_SNAPSHOTS (snapshot_manager).
# Có thể đưa vào Settings sau này; hardcode 10 OK.
MAX_UPLOAD_HISTORY = 10


def append_upload_history(
    project_dir: str,
    *,
    filename: str,
    row_count: int,
    checksum: str = "",
    source: str = "upload",
    extra: Optional[dict] = None,
    max_entries: int = MAX_UPLOAD_HISTORY,
) -> list[dict]:
    """
    Ghi 1 entry lịch sử upload/sync (upload thủ công hoặc sync).

    Chỉ giữ ``max_entries`` bản ghi mới nhất (mặc định MAX_UPLOAD_HISTORY).
    source: \"upload\" (thủ công) hoặc \"sync:<integ_id>:<endpoint_id>\".
    """
    hist = load_upload_history(project_dir)
    entry = {
        "time": datetime.now().isoformat(timespec="seconds"),
        "filename": filename,
        "row_count": row_count,
        "checksum": checksum,
        "source": (source or "upload").strip() or "upload",
    }
    if extra:
        entry.update(extra)
    hist.insert(0, entry)
    # U27 — nếu caller không truyền max_entries custom, đọc từ settings
    if max_entries == MAX_UPLOAD_HISTORY:
        try:
            max_entries = int(
                load_project_settings(project_dir).get("max_upload_history") or MAX_UPLOAD_HISTORY
            )
        except Exception:
            max_entries = MAX_UPLOAD_HISTORY
    hist = hist[: max(1, int(max_entries))]
    _write_json(_path(project_dir, "upload_history.json"), hist)
    return hist


def load_upload_history(project_dir: str) -> list[dict]:
    """
    Load lịch sử. Entry cũ không có source → default \"upload\".

    Migration: nếu file đang > cap (U27 settings hoặc MAX_UPLOAD_HISTORY)
    → prune về N mới nhất và ghi lại.
    """
    data = _read_json(_path(project_dir, "upload_history.json"), [])
    if not isinstance(data, list):
        return []
    out = []
    for e in data:
        if not isinstance(e, dict):
            continue
        if not e.get("source"):
            e = {**e, "source": "upload"}
        out.append(e)
    try:
        cap = int(load_project_settings(project_dir).get("max_upload_history") or MAX_UPLOAD_HISTORY)
        cap = max(3, min(50, cap))
    except Exception:
        cap = MAX_UPLOAD_HISTORY
    if len(out) > cap:
        out = out[:cap]
        _write_json(_path(project_dir, "upload_history.json"), out)
    return out


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
    """Trả về tất cả settings với default hợp lý — reminder / SLA /
    digest schedule (T26) / thresholds (T29)."""
    data = _read_json(_path(project_dir, "project_settings.json"), {})
    if not isinstance(data, dict):
        data = {}
    sla = dict(DEFAULT_SLA)
    sla.update(data.get("sla") or {})
    digest = dict(DEFAULT_DIGEST)
    digest.update(data.get("digest") or {})
    thresholds = dict(DEFAULT_PROGRESS_THRESHOLDS)
    thresholds.update(data.get("progress_thresholds") or {})
    return {
        "upload_reminder_days": int(data.get("upload_reminder_days", DEFAULT_UPLOAD_REMINDER_DAYS)),
        "sla": {
            "must_have_days": int(sla.get("must_have_days", 3)),
            "should_have_days": int(sla.get("should_have_days", 7)),
        },
        "digest": {
            "enabled": bool(digest.get("enabled", False)),
            "day_of_week": max(0, min(6, int(digest.get("day_of_week", 0)))),
            "hour": max(0, min(23, int(digest.get("hour", 9)))),
            "last_generated_date": str(digest.get("last_generated_date") or ""),
        },
        "progress_thresholds": {
            "in_progress": max(0, min(100, int(thresholds.get("in_progress", 30)))),
            "closed_soon": max(0, min(100, int(thresholds.get("closed_soon", 70)))),
        },
        "aging_wip_threshold": max(1, int(data.get("aging_wip_threshold", DEFAULT_AGING_WIP_THRESHOLD))),
        # U27 — số snapshot / upload history giữ (thay hardcode 10)
        "max_snapshots": max(3, min(50, int(data.get("max_snapshots", MAX_UPLOAD_HISTORY)))),
        "max_upload_history": max(3, min(50, int(data.get(
            "max_upload_history",
            data.get("max_snapshots", MAX_UPLOAD_HISTORY),
        )))),
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
    # T26: digest schedule
    if "digest" in payload and isinstance(payload["digest"], dict):
        d = payload["digest"]
        if "enabled" in d:
            current["digest"]["enabled"] = bool(d["enabled"])
        if "day_of_week" in d:
            current["digest"]["day_of_week"] = max(0, min(6, int(d["day_of_week"])))
        if "hour" in d:
            current["digest"]["hour"] = max(0, min(23, int(d["hour"])))
        if "last_generated_date" in d:
            current["digest"]["last_generated_date"] = str(d["last_generated_date"] or "")
    # T29: thresholds
    if "progress_thresholds" in payload and isinstance(payload["progress_thresholds"], dict):
        pt = payload["progress_thresholds"]
        if "in_progress" in pt:
            current["progress_thresholds"]["in_progress"] = max(0, min(100, int(pt["in_progress"])))
        if "closed_soon" in pt:
            current["progress_thresholds"]["closed_soon"] = max(0, min(100, int(pt["closed_soon"])))
        # Enforce in_progress < closed_soon để không bị đảo ngược
        if current["progress_thresholds"]["in_progress"] >= current["progress_thresholds"]["closed_soon"]:
            current["progress_thresholds"]["in_progress"] = max(
                0, current["progress_thresholds"]["closed_soon"] - 10
            )
    if "aging_wip_threshold" in payload:
        current["aging_wip_threshold"] = max(1, int(payload["aging_wip_threshold"]))
    # U27 — retention
    if "max_snapshots" in payload:
        current["max_snapshots"] = max(3, min(50, int(payload["max_snapshots"])))
    if "max_upload_history" in payload:
        current["max_upload_history"] = max(3, min(50, int(payload["max_upload_history"])))
    # Nếu chỉ gửi 1 trong 2 → đồng bộ cả hai (UI dùng 1 ô)
    if "max_snapshots" in payload and "max_upload_history" not in payload:
        current["max_upload_history"] = current["max_snapshots"]
    if "max_upload_history" in payload and "max_snapshots" not in payload:
        current["max_snapshots"] = current["max_upload_history"]
    _write_json(_path(project_dir, "project_settings.json"), current)
    return current


# ------------------------------------------------------------------
# T32: Excel Column Mapping presets
# ------------------------------------------------------------------
# File: excel_mapping_presets.json = {"presets": [{"name": str, "mapping":
#       {ihrp_col: actual_header}, "updated_at": iso}, ...]}
# Presets là "template" cho phép user nhanh chóng apply lại mapping cho file
# cùng vendor / cùng cấu trúc mà không phải map lại từ đầu.

_MAPPING_PRESETS_FILE = "excel_mapping_presets.json"
_MAX_PRESETS = 30           # đủ cho user quản lý nhiều source khác nhau
_MAX_PRESET_NAME = 80


def list_mapping_presets(project_dir: str) -> list[dict]:
    """
    Trả về list preset đã lưu (sorted theo updated_at desc). Mỗi entry:
    {"name": str, "mapping": {...}, "updated_at": iso_string}.

    File không tồn tại / lỗi format → [] (không raise).
    """
    data = _read_json(_path(project_dir, _MAPPING_PRESETS_FILE), {"presets": []})
    if not isinstance(data, dict):
        return []
    presets = data.get("presets") or []
    if not isinstance(presets, list):
        return []
    out: list[dict] = []
    for p in presets:
        if not isinstance(p, dict):
            continue
        name = str(p.get("name") or "").strip()
        mapping = p.get("mapping")
        if not name or not isinstance(mapping, dict):
            continue
        clean_mapping = {str(k).strip(): str(v).strip()
                         for k, v in mapping.items()
                         if str(k).strip() and str(v).strip()}
        out.append({
            "name": name[:_MAX_PRESET_NAME],
            "mapping": clean_mapping,
            "updated_at": str(p.get("updated_at") or ""),
        })
    # Sort desc updated_at (chuỗi ISO đủ để so sánh lexicographic)
    out.sort(key=lambda x: x.get("updated_at", ""), reverse=True)
    return out


def save_mapping_preset(
    project_dir: str,
    name: str,
    mapping: dict[str, str],
) -> list[dict]:
    """
    Upsert 1 preset theo `name` (case-sensitive). Trả list preset mới nhất.

    Args:
        name: tên preset (bắt buộc, sẽ trim + truncate 80 ký tự).
        mapping: dict {ihrp_col: actual_header}. Entry rỗng bị drop.

    Behavior:
        - Nếu tên đã tồn tại → OVERWRITE mapping + updated_at.
        - Nếu chưa → append.
        - Enforce cap _MAX_PRESETS: nếu vượt → xoá preset cũ nhất
          (updated_at nhỏ nhất) để nhường chỗ.

    Raises:
        ValueError khi name rỗng.
    """
    from datetime import datetime
    clean_name = str(name or "").strip()[:_MAX_PRESET_NAME]
    if not clean_name:
        raise ValueError("Preset name không được rỗng")
    clean_mapping = {str(k).strip(): str(v).strip()
                     for k, v in (mapping or {}).items()
                     if str(k).strip() and str(v).strip()}

    presets = list_mapping_presets(project_dir)
    # Remove existing với cùng name
    presets = [p for p in presets if p.get("name") != clean_name]
    presets.insert(0, {
        "name": clean_name,
        "mapping": clean_mapping,
        "updated_at": datetime.now().isoformat(timespec="seconds"),
    })
    # Cap
    if len(presets) > _MAX_PRESETS:
        presets = presets[:_MAX_PRESETS]
    _write_json(_path(project_dir, _MAPPING_PRESETS_FILE), {"presets": presets})
    return presets


def delete_mapping_preset(project_dir: str, name: str) -> tuple[bool, list[dict]]:
    """
    Xoá preset theo name. Trả (deleted, remaining_list).

    - `deleted = True` nếu tìm thấy + xoá thành công.
    - `deleted = False` nếu không có preset với name đó.
    """
    presets = list_mapping_presets(project_dir)
    before = len(presets)
    presets = [p for p in presets if p.get("name") != name]
    deleted = len(presets) < before
    if deleted:
        _write_json(_path(project_dir, _MAPPING_PRESETS_FILE), {"presets": presets})
    return deleted, presets


# ------------------------------------------------------------------
# T34 Task 3C — JSON API integration mapping presets
# ------------------------------------------------------------------
# File: integrations_mapping_presets.json = {
#   "presets": {
#     "<integration_id>": [
#       {"name": str, "mapping": {ihrp_col: json_path}, "updated_at": iso},
#       ...
#     ]
#   }
# }
# Scope preset PER integration (mỗi integration có nhiều endpoint với
# response shape khác nhau; user thường muốn giữ mapping riêng cho từng
# vendor). Reuse cùng cap _MAX_PRESETS cho consistency.

_INTEG_MAPPING_PRESETS_FILE = "integrations_mapping_presets.json"


def list_integration_mapping_presets(project_dir: str, integration_id: str) -> list[dict]:
    """
    List preset của 1 integration cụ thể.

    Sort desc theo updated_at. File / integration không tồn tại → [].
    """
    integration_id = str(integration_id or "").strip()
    if not integration_id:
        return []
    data = _read_json(_path(project_dir, _INTEG_MAPPING_PRESETS_FILE), {"presets": {}})
    if not isinstance(data, dict):
        return []
    all_presets = data.get("presets") or {}
    if not isinstance(all_presets, dict):
        return []
    presets = all_presets.get(integration_id) or []
    if not isinstance(presets, list):
        return []
    out: list[dict] = []
    for p in presets:
        if not isinstance(p, dict):
            continue
        name = str(p.get("name") or "").strip()
        mapping = p.get("mapping")
        if not name or not isinstance(mapping, dict):
            continue
        clean = {str(k).strip(): str(v).strip()
                 for k, v in mapping.items()
                 if str(k).strip() and str(v).strip()}
        out.append({
            "name": name[:_MAX_PRESET_NAME],
            "mapping": clean,
            "updated_at": str(p.get("updated_at") or ""),
        })
    out.sort(key=lambda x: x.get("updated_at", ""), reverse=True)
    return out


def save_integration_mapping_preset(
    project_dir: str,
    integration_id: str,
    name: str,
    mapping: dict[str, str],
) -> list[dict]:
    """Upsert 1 preset cho integration cụ thể. Trả list mới nhất."""
    integration_id = str(integration_id or "").strip()
    if not integration_id:
        raise ValueError("integration_id không được rỗng")
    clean_name = str(name or "").strip()[:_MAX_PRESET_NAME]
    if not clean_name:
        raise ValueError("Preset name không được rỗng")
    clean_mapping = {str(k).strip(): str(v).strip()
                     for k, v in (mapping or {}).items()
                     if str(k).strip() and str(v).strip()}

    data = _read_json(_path(project_dir, _INTEG_MAPPING_PRESETS_FILE),
                     {"presets": {}})
    if not isinstance(data, dict):
        data = {"presets": {}}
    all_presets = data.get("presets") if isinstance(data.get("presets"), dict) else {}

    presets = list_integration_mapping_presets(project_dir, integration_id)
    presets = [p for p in presets if p.get("name") != clean_name]
    presets.insert(0, {
        "name": clean_name,
        "mapping": clean_mapping,
        "updated_at": datetime.now().isoformat(timespec="seconds"),
    })
    if len(presets) > _MAX_PRESETS:
        presets = presets[:_MAX_PRESETS]

    all_presets[integration_id] = presets
    _write_json(_path(project_dir, _INTEG_MAPPING_PRESETS_FILE),
                {"presets": all_presets})
    return presets


def delete_integration_mapping_preset(
    project_dir: str, integration_id: str, name: str,
) -> tuple[bool, list[dict]]:
    """Xoá preset của integration. Trả (deleted, remaining_list)."""
    integration_id = str(integration_id or "").strip()
    if not integration_id:
        return False, []
    data = _read_json(_path(project_dir, _INTEG_MAPPING_PRESETS_FILE),
                     {"presets": {}})
    if not isinstance(data, dict):
        return False, []
    all_presets = data.get("presets") if isinstance(data.get("presets"), dict) else {}
    presets = list_integration_mapping_presets(project_dir, integration_id)
    before = len(presets)
    presets = [p for p in presets if p.get("name") != name]
    deleted = len(presets) < before
    if deleted:
        all_presets[integration_id] = presets
        _write_json(_path(project_dir, _INTEG_MAPPING_PRESETS_FILE),
                    {"presets": all_presets})
    return deleted, presets

# ------------------------------------------------------------------
# T-AA — Archive settings (per-project)
# File: archive_settings.json
# ------------------------------------------------------------------

DEFAULT_ARCHIVE_SETTINGS = {
    "enabled": True,
    "archive_after_days": 90,      # 0 = never auto-archive
    "auto_run_on_startup": True,
    "purge_after_days": 365,       # 0 = never purge
}

_ARCHIVE_SETTINGS_FILE = "archive_settings.json"


def load_archive_settings(project_dir: str) -> dict[str, Any]:
    """Load archive settings với default hợp lý."""
    data = _read_json(_path(project_dir, _ARCHIVE_SETTINGS_FILE), {})
    if not isinstance(data, dict):
        data = {}
    out = dict(DEFAULT_ARCHIVE_SETTINGS)
    out.update(data)
    out["enabled"] = bool(out.get("enabled", True))
    out["auto_run_on_startup"] = bool(out.get("auto_run_on_startup", True))
    try:
        out["archive_after_days"] = max(0, min(3650, int(out.get("archive_after_days", 90))))
    except (TypeError, ValueError):
        out["archive_after_days"] = 90
    try:
        out["purge_after_days"] = max(0, min(3650, int(out.get("purge_after_days", 365))))
    except (TypeError, ValueError):
        out["purge_after_days"] = 365
    return out


def save_archive_settings(project_dir: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Merge + lưu archive settings. Return settings sau khi lưu."""
    current = load_archive_settings(project_dir)
    if not isinstance(payload, dict):
        payload = {}
    if "enabled" in payload:
        current["enabled"] = bool(payload["enabled"])
    if "auto_run_on_startup" in payload:
        current["auto_run_on_startup"] = bool(payload["auto_run_on_startup"])
    if "archive_after_days" in payload:
        try:
            current["archive_after_days"] = max(0, min(3650, int(payload["archive_after_days"])))
        except (TypeError, ValueError):
            pass
    if "purge_after_days" in payload:
        try:
            current["purge_after_days"] = max(0, min(3650, int(payload["purge_after_days"])))
        except (TypeError, ValueError):
            pass
    _write_json(_path(project_dir, _ARCHIVE_SETTINGS_FILE), current)
    return current
