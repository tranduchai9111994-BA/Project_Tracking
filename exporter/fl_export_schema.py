"""
Schema mẫu Function List cho export re-import.

Quyết định cột ghi chú (mẫu DanhSachFunction_2026-07-31.xlsx):
  - Ưu tiên meta ``Remark`` / ``Ghi chú`` (đã có trong template nguồn).
  - Không thêm cột ``Ghi chú Tracker`` — nguồn import có thể reject cột lạ.
  - Phase ``*- Note`` chỉ tô nhẹ khi phase đó dính issue; ghi chú tracker
    gom vào Remark.

File lưu per-project:
  uploads/projects/<slug>/fl_export_template.xlsx
  uploads/projects/<slug>/fl_export_schema.json
"""
from __future__ import annotations

import os
import shutil
from datetime import datetime, timezone
from typing import Any, Optional

from parser.excel_parser import (
    META_KEYWORDS,
    FunctionListParser,
    ParsedData,
    PhaseGroup,
)

SCHEMA_VERSION = 1
TEMPLATE_XLSX = "fl_export_template.xlsx"
SCHEMA_JSON = "fl_export_schema.json"

# Meta slots hiển thị trên board Review (thứ tự UX).
REVIEW_META_SLOTS: list[tuple[str, str]] = [
    ("ma_cn", "Mã CN"),
    ("ten_cn", "Tên chức năng"),
    ("module", "Module"),
    ("quy_trinh", "Quy trình"),
    ("priority", "Priority"),
    ("complexity", "Complexity"),
    ("fit_gap", "FIT/GAP"),
    ("giai_doan", "Giai đoạn"),
    ("system", "System"),
    ("remark", "Remark / Ghi chú"),
    ("stt", "STT"),
    ("mo_ta", "Mô tả"),
    ("risk_blocker", "Risk/Blocker"),
    ("ma_du_an", "Mã dự án"),
]

# Attr phase dùng cho highlight / date-chain (không hardcode tên phase).
_START_ATTRS = ("Start", "From", "Planned")
_END_ATTRS = ("End", "To", "Actual")
_CORE_PHASE_ATTRS = ("Start", "From", "End", "To", "Planned", "Actual", "Status", "PIC", "Note")


def next_business_day(d) -> Any:
    """Ngày làm việc kế tiếp (bỏ T7=5, CN=6)."""
    from datetime import date, timedelta
    if d is None:
        return None
    if not isinstance(d, date):
        return None
    nxt = d + timedelta(days=1)
    while nxt.weekday() >= 5:
        nxt += timedelta(days=1)
    return nxt


def _header_order(headers: dict[str, int]) -> list[str]:
    """Header exact theo thứ tự cột 1-based."""
    by_col = sorted(((idx, h) for h, idx in headers.items()), key=lambda x: x[0])
    return [h for _, h in by_col]


def _col_to_header(headers: dict[str, int]) -> dict[int, str]:
    return {idx: h for h, idx in headers.items()}


def _find_note_column(
    meta_columns: dict[str, Optional[int]],
    headers: dict[str, int],
) -> dict[str, Any]:
    """
    Chọn cột note tracker — ưu tiên Remark/Ghi chú meta có sẵn.
    Không tạo cột mới.
    """
    remark_col = meta_columns.get("remark")
    if remark_col:
        inv = _col_to_header(headers)
        return {
            "kind": "meta_remark",
            "meta_key": "remark",
            "header": inv.get(remark_col, "Remark"),
            "col": remark_col,
            "added_column": False,
        }
    # Fallback: header chứa Note/Ghi chú nhưng không phải phase (không có " - ")
    for h, idx in headers.items():
        hl = h.lower()
        if " - " in h:
            continue
        if any(k in hl for k in ("remark", "ghi chú", "ghi chu", "note")):
            return {
                "kind": "meta_note",
                "meta_key": None,
                "header": h,
                "col": idx,
                "added_column": False,
            }
    return {
        "kind": "none",
        "meta_key": None,
        "header": None,
        "col": None,
        "added_column": False,
        "hint": "Không có cột Remark/Ghi chú — chỉ highlight ô cần sửa, không thêm cột lạ.",
    }


def _confidence_for_meta(meta_key: str, header: str) -> str:
    """high = exact keyword; medium = partial; low = thiếu."""
    if not header:
        return "low"
    hl = header.lower().strip()
    for kw in META_KEYWORDS.get(meta_key, []):
        if hl == kw.lower():
            return "high"
    for kw in META_KEYWORDS.get(meta_key, []):
        if kw.lower() in hl:
            return "medium"
    return "medium"


def _confidence_for_phase_attr(attr: str, header: str) -> str:
    if not header or " - " not in header:
        return "low"
    _, a = header.rsplit(" - ", 1)
    a = a.strip().lower()
    attr_l = attr.lower()
    if a == attr_l:
        return "high"
    # PIC FPT / PIC MPHG → slot PIC
    if "pic" in attr_l and "pic" in a:
        return "high"
    # From/To ↔ Start/End aliases
    aliases = {
        "start": {"start", "from", "planned"},
        "from": {"start", "from", "planned"},
        "end": {"end", "to", "actual"},
        "to": {"end", "to", "actual"},
        "planned": {"start", "from", "planned"},
        "actual": {"end", "to", "actual"},
    }
    if a in aliases.get(attr_l, set()):
        return "high"
    return "medium"


def build_schema_from_parsed(
    data: ParsedData,
    *,
    source_filename: str = "",
    slot_overrides: Optional[dict[str, str]] = None,
) -> dict[str, Any]:
    """
    Xây schema export từ ParsedData (auto-detect).

    ``slot_overrides``: map slot_id → headerExact (từ Review board).
      slot_id dạng ``meta:ma_cn`` hoặc ``phase:Analysis:Start``.
    """
    headers = dict(data.headers)
    header_list = _header_order(headers)
    inv = _col_to_header(headers)
    overrides = slot_overrides or {}

    meta_map: dict[str, Optional[str]] = {}
    meta_cols: dict[str, Optional[int]] = {}
    for key, col in (data.meta_columns or {}).items():
        hdr = inv.get(col) if col else None
        ov = overrides.get(f"meta:{key}")
        if ov:
            hdr = ov
            col = headers.get(ov)
        meta_map[key] = hdr
        meta_cols[key] = col

    phase_groups: list[dict[str, Any]] = []
    for pg in data.phase_groups:
        attrs: dict[str, str] = {}
        attr_cols: dict[str, int] = {}
        for attr, col in pg.attributes.items():
            hdr = inv.get(col, f"{pg.name} - {attr}")
            ov = overrides.get(f"phase:{pg.name}:{attr}")
            # Cho phép override slot chuẩn Start/End/Status/PIC bằng header PIC FPT…
            if not ov and attr.upper().startswith("PIC"):
                ov = overrides.get(f"phase:{pg.name}:PIC")
            if ov:
                hdr = ov
                col = headers.get(ov, col)
            attrs[attr] = hdr
            attr_cols[attr] = col
        phase_groups.append({
            "name": pg.name,
            "attributes": attrs,
            "attribute_cols": attr_cols,
        })

    note = _find_note_column(meta_cols, headers)
    # Override note qua slot meta:remark nếu user kéo
    if overrides.get("meta:remark"):
        h = overrides["meta:remark"]
        note = {
            "kind": "meta_remark",
            "meta_key": "remark",
            "header": h,
            "col": headers.get(h),
            "added_column": False,
        }

    slots = _build_review_slots(data, meta_map, phase_groups, overrides)

    return {
        "version": SCHEMA_VERSION,
        "headers": header_list,
        "header_cols": {h: headers[h] for h in header_list if h in headers},
        "meta_map": meta_map,
        "meta_cols": {k: v for k, v in meta_cols.items() if v},
        "phase_groups": phase_groups,
        "note_column": note,
        "slots": slots,
        "source_filename": source_filename or "",
        "saved_at": datetime.now(timezone.utc).isoformat(),
        "slot_assignments": {
            s["id"]: s["header"] for s in slots if s.get("header")
        },
    }


def _build_review_slots(
    data: ParsedData,
    meta_map: dict[str, Optional[str]],
    phase_groups: list[dict],
    overrides: dict[str, str],
) -> list[dict[str, Any]]:
    """Danh sách slot cho UI Review board + confidence."""
    slots: list[dict[str, Any]] = []
    for key, label in REVIEW_META_SLOTS:
        hdr = overrides.get(f"meta:{key}") or meta_map.get(key)
        slots.append({
            "id": f"meta:{key}",
            "kind": "meta",
            "meta_key": key,
            "label": label,
            "header": hdr,
            "confidence": _confidence_for_meta(key, hdr or ""),
            "group": "Meta",
        })

    for pg in phase_groups:
        name = pg["name"]
        attrs = pg.get("attributes") or {}
        # Slot chuẩn + mọi attr detect được
        seen: set[str] = set()
        ordered_attrs: list[str] = []
        for a in ("Start", "From", "End", "To", "Status", "PIC", "Estimate MH", "Note"):
            # map alias: nếu file dùng From thay Start vẫn hiện 1 slot Start
            if a in attrs:
                ordered_attrs.append(a)
                seen.add(a)
            elif a == "Start" and "From" in attrs and "From" not in seen:
                ordered_attrs.append("From")
                seen.add("From")
            elif a == "End" and "To" in attrs and "To" not in seen:
                ordered_attrs.append("To")
                seen.add("To")
            elif a == "PIC":
                pic_attrs = [k for k in attrs if "PIC" in k.upper()]
                for pa in pic_attrs:
                    if pa not in seen:
                        ordered_attrs.append(pa)
                        seen.add(pa)
        for a in attrs:
            if a not in seen:
                ordered_attrs.append(a)
                seen.add(a)

        for attr in ordered_attrs:
            slot_id = f"phase:{name}:{attr}"
            # PIC aggregate override
            hdr = overrides.get(slot_id) or overrides.get(f"phase:{name}:PIC") if "PIC" in attr.upper() else overrides.get(slot_id)
            if not hdr:
                hdr = attrs.get(attr)
            slots.append({
                "id": slot_id,
                "kind": "phase",
                "phase": name,
                "attr": attr,
                "label": f"{name} · {attr}",
                "header": hdr,
                "confidence": _confidence_for_phase_attr(attr, hdr or ""),
                "group": name,
            })
    return slots


def build_review_payload(
    data: ParsedData,
    *,
    source_filename: str = "",
    slot_overrides: Optional[dict[str, str]] = None,
) -> dict[str, Any]:
    """Payload cho FE Review mapping (headers + slots + schema draft)."""
    schema = build_schema_from_parsed(
        data, source_filename=source_filename, slot_overrides=slot_overrides,
    )
    # Headers trái: group phase vs meta
    header_items = []
    for h in schema["headers"]:
        if " - " in h:
            phase, attr = h.rsplit(" - ", 1)
            group = phase
            kind = "phase"
        else:
            group = "Meta"
            kind = "meta"
        header_items.append({
            "header": h,
            "group": group,
            "kind": kind,
            "col": schema["header_cols"].get(h),
        })
    return {
        "headers": header_items,
        "slots": schema["slots"],
        "schema": schema,
        "note_column": schema["note_column"],
        "source_filename": source_filename,
        "tip": (
            "Hệ thống đã tự map theo auto-detect. Ô xanh = khớp chắc; "
            "vàng = nên review. Kéo header → slot để sửa. "
            "Ghi chú tracker ghi vào cột Remark/Ghi chú có sẵn — không thêm cột lạ."
        ),
    }


def schema_from_xlsx(filepath: str, source_filename: str = "") -> dict[str, Any]:
    """Parse file mẫu → schema."""
    data = FunctionListParser().parse(filepath)
    return build_schema_from_parsed(
        data, source_filename=source_filename or os.path.basename(filepath),
    )


def review_from_xlsx(filepath: str, source_filename: str = "") -> dict[str, Any]:
    data = FunctionListParser().parse(filepath)
    return build_review_payload(
        data, source_filename=source_filename or os.path.basename(filepath),
    )


def apply_slot_overrides_to_schema(
    base_schema: dict[str, Any],
    slot_assignments: dict[str, str],
    headers_list: Optional[list[str]] = None,
) -> dict[str, Any]:
    """Áp assignment từ FE lên schema đã có (không re-parse nếu đủ info)."""
    headers = headers_list or list(base_schema.get("headers") or [])
    header_cols = {h: i + 1 for i, h in enumerate(headers)}
    # Rebuild ParsedData-like via re-detect from headers dict
    fake_headers = dict(header_cols)
    parser = FunctionListParser()
    meta = parser._detect_meta_columns(fake_headers)
    phases = parser._detect_phase_groups(fake_headers)
    # Build minimal ParsedData
    data = ParsedData(
        headers=fake_headers,
        meta_columns=meta,
        phase_groups=phases,
        rows=[],
    )
    return build_schema_from_parsed(
        data,
        source_filename=base_schema.get("source_filename", ""),
        slot_overrides=slot_assignments,
    )


# ------------------------------------------------------------------
# Persist helpers (project_dir)
# ------------------------------------------------------------------

def template_xlsx_path(project_dir: str) -> str:
    return os.path.join(project_dir, TEMPLATE_XLSX)


def schema_json_path(project_dir: str) -> str:
    return os.path.join(project_dir, SCHEMA_JSON)


def load_fl_export_schema(project_dir: str) -> Optional[dict[str, Any]]:
    path = schema_json_path(project_dir)
    if not os.path.isfile(path):
        return None
    try:
        import json
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else None
    except (OSError, ValueError):
        return None


def save_fl_export_template(
    project_dir: str,
    source_xlsx: str,
    schema: dict[str, Any],
) -> dict[str, Any]:
    """Copy file mẫu + ghi schema JSON. Return schema đã lưu."""
    os.makedirs(project_dir, exist_ok=True)
    dest = template_xlsx_path(project_dir)
    # Tránh SameFileError khi confirm mapping trên file đã lưu
    if os.path.abspath(source_xlsx) != os.path.abspath(dest):
        shutil.copy2(source_xlsx, dest)
    schema = dict(schema)
    schema["saved_at"] = datetime.now(timezone.utc).isoformat()
    schema["template_file"] = TEMPLATE_XLSX
    import json
    with open(schema_json_path(project_dir), "w", encoding="utf-8") as f:
        json.dump(schema, f, ensure_ascii=False, indent=2)
    return schema


def delete_fl_export_template(project_dir: str) -> None:
    for p in (template_xlsx_path(project_dir), schema_json_path(project_dir)):
        try:
            if os.path.isfile(p):
                os.remove(p)
        except OSError:
            pass


def resolve_export_schema(
    project_dir: str,
    fallback_data: Optional[ParsedData] = None,
    fallback_xlsx: Optional[str] = None,
) -> dict[str, Any]:
    """
    Schema dùng khi export:
      1) schema đã lưu per-project
      2) fallback parse current.xlsx / fallback_data
    """
    saved = load_fl_export_schema(project_dir)
    if saved and saved.get("headers"):
        return saved
    if fallback_xlsx and os.path.isfile(fallback_xlsx):
        return schema_from_xlsx(fallback_xlsx, os.path.basename(fallback_xlsx))
    if fallback_data is not None:
        return build_schema_from_parsed(fallback_data, source_filename="(current FL)")
    raise ValueError("Chưa có mẫu FL và không có dữ liệu fallback để suy schema.")


def phase_start_attr(attrs: dict) -> Optional[str]:
    for a in _START_ATTRS:
        if a in attrs:
            return a
    return None


def phase_end_attr(attrs: dict) -> Optional[str]:
    for a in _END_ATTRS:
        if a in attrs:
            return a
    return None
