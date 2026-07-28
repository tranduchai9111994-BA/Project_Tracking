"""
Function Diff — So sánh file hiện tại với snapshot upload trước (Task 3).

BA muốn biết "tuần này có gì đổi": function mới thêm / bị xoá / đổi PIC /
Priority / Complexity / FIT-GAP / Status phase.

Snapshot đã có sẵn: SnapshotManager pickle ParsedData mỗi lần upload
(theo ngày, ghi đè cùng ngày). Task này chỉ load 2 snapshot và so sánh.

Match: bằng Mã CN. Fallback theo (Tên + Module) nếu Mã CN blank cả 2 phía.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Any, Iterable, Optional

from parser.excel_parser import ParsedData, FunctionRow, PhaseData


# Field meta so sánh, tương ứng key trong FunctionRow.meta
_PRI_COMPLEX_FIELDS = [
    ("priority", "Priority"),
    ("complexity", "Complexity"),
]


def _row_key(row: FunctionRow) -> str:
    """
    Key match giữa 2 snapshot:
    - Ưu tiên Mã CN (case-insensitive, strip)
    - Fallback: 'FALLBACK|<ten>|<module>' nếu ma_cn blank

    Lưu ý: return string đã lower + strip để so sánh nhất quán.
    """
    ma = (row.meta.get("ma_cn") or "").strip().lower()
    if ma:
        return ma
    ten = (row.meta.get("ten_cn") or "").strip().lower()
    module = (row.meta.get("module") or "").strip().lower()
    return f"__fb__|{ten}|{module}"


def _row_pics(row: FunctionRow) -> set[str]:
    """Gộp toàn bộ PIC của row (unique across all phases)."""
    out: set[str] = set()
    for pd in row.phases.values():
        for p in (pd.pics or []):
            if p:
                out.add(p)
    return out


def _row_pics_by_phase(row: FunctionRow) -> dict[str, list[str]]:
    """PIC theo từng phase (giữ thứ tự phase key gốc)."""
    return {name: list(pd.pics or []) for name, pd in row.phases.items()}


def _row_status_by_phase(row: FunctionRow) -> dict[str, str]:
    return {name: (pd.status or "") for name, pd in row.phases.items()}


def _row_display(row: FunctionRow) -> dict[str, Any]:
    """Serialize row → dict FE có thể hiển thị (không kèm phase detail)."""
    return {
        "row_num": row.row_num,
        "ma_cn": row.meta.get("ma_cn") or "",
        "ten_cn": row.meta.get("ten_cn") or "",
        "module": row.meta.get("module") or "",
        "quy_trinh": row.meta.get("quy_trinh") or "",
        "priority": row.meta.get("priority") or "",
        "complexity": row.meta.get("complexity") or "",
        "fit_gap": row.meta.get("fit_gap") or "",
    }


def _fmt_pic_list(pics: Iterable[str]) -> str:
    """PIC list → chuỗi hiển thị (sorted để so sánh ổn định)."""
    return ", ".join(sorted(set(p for p in pics if p)))


def compute_function_diff(
    current: ParsedData,
    previous: ParsedData,
    current_meta: Optional[dict] = None,
    previous_meta: Optional[dict] = None,
) -> dict[str, Any]:
    """
    So sánh 2 snapshot. Trả cấu trúc chuẩn cho FE + Excel export.

    Args:
        current: ParsedData hiện tại
        previous: ParsedData trước đó
        current_meta / previous_meta: meta của snapshot (date, filename, ...)

    Returns:
        {
          "current_snapshot":  {...},
          "previous_snapshot": {...},
          "counts": {added, deleted, pic_changed, prio_complex_changed,
                     fitgap_changed, status_changed, total_changed},
          "added":  [row_display, ...],
          "deleted": [row_display, ...],
          "pic_changed":  [{row_display, old, new}],
          "priority_complexity_changed": [{row_display, field, old, new}],
          "fitgap_changed": [{row_display, old, new}],
          "phase_status_changed": [{row_display, phase, old, new}],
        }
    """
    cur_map: dict[str, FunctionRow] = {}
    for r in current.rows:
        k = _row_key(r)
        # Nếu trùng key (rare — cùng mã CN 2 dòng) thì giữ dòng đầu để deterministic
        cur_map.setdefault(k, r)

    prev_map: dict[str, FunctionRow] = {}
    for r in previous.rows:
        k = _row_key(r)
        prev_map.setdefault(k, r)

    added_keys = set(cur_map) - set(prev_map)
    deleted_keys = set(prev_map) - set(cur_map)
    common_keys = set(cur_map) & set(prev_map)

    added = [_row_display(cur_map[k]) for k in added_keys]
    deleted = [_row_display(prev_map[k]) for k in deleted_keys]

    pic_changed: list[dict] = []
    prio_complex_changed: list[dict] = []
    fitgap_changed: list[dict] = []
    status_changed: list[dict] = []

    # Set để đếm distinct function bị đổi (không đếm lặp)
    changed_row_keys: set[str] = set()

    for k in common_keys:
        cur = cur_map[k]
        prv = prev_map[k]
        disp = _row_display(cur)

        # 1) Priority / Complexity
        for field_key, label in _PRI_COMPLEX_FIELDS:
            a = (prv.meta.get(field_key) or "").strip()
            b = (cur.meta.get(field_key) or "").strip()
            if a != b:
                prio_complex_changed.append({
                    **disp,
                    "field": label,
                    "old": a or "(trống)",
                    "new": b or "(trống)",
                })
                changed_row_keys.add(k)

        # 2) FIT/GAP
        fg_a = (prv.meta.get("fit_gap") or "").strip()
        fg_b = (cur.meta.get("fit_gap") or "").strip()
        if fg_a != fg_b:
            fitgap_changed.append({
                **disp,
                "old": fg_a or "(trống)",
                "new": fg_b or "(trống)",
            })
            changed_row_keys.add(k)

        # 3) PIC — so sánh set overall + per-phase (chi tiết per phase để BA nhìn được)
        pics_a = _row_pics(prv)
        pics_b = _row_pics(cur)
        if pics_a != pics_b:
            # Break down theo phase để hiển thị chi tiết. Nếu không đổi ở phase nào cụ thể
            # (nhưng set overall khác — VD dòng thêm 1 phase mới có PIC) → gom vào "Tổng thể"
            per_phase_a = _row_pics_by_phase(prv)
            per_phase_b = _row_pics_by_phase(cur)
            all_phases = list({**per_phase_a, **per_phase_b}.keys())
            phase_level_captured = False
            for phase_name in all_phases:
                a_pics = set(per_phase_a.get(phase_name, []))
                b_pics = set(per_phase_b.get(phase_name, []))
                if a_pics != b_pics:
                    pic_changed.append({
                        **disp,
                        "phase": phase_name,
                        "old": _fmt_pic_list(a_pics) or "(trống)",
                        "new": _fmt_pic_list(b_pics) or "(trống)",
                    })
                    phase_level_captured = True
            if not phase_level_captured:
                # Bản backup, hiếm gặp
                pic_changed.append({
                    **disp,
                    "phase": "(Tổng thể)",
                    "old": _fmt_pic_list(pics_a) or "(trống)",
                    "new": _fmt_pic_list(pics_b) or "(trống)",
                })
            changed_row_keys.add(k)

        # 4) Status phase
        status_a = _row_status_by_phase(prv)
        status_b = _row_status_by_phase(cur)
        all_phases = list({**status_a, **status_b}.keys())
        for phase_name in all_phases:
            sa = (status_a.get(phase_name) or "").strip()
            sb = (status_b.get(phase_name) or "").strip()
            if sa != sb:
                status_changed.append({
                    **disp,
                    "phase": phase_name,
                    "old": sa or "(trống)",
                    "new": sb or "(trống)",
                })
                changed_row_keys.add(k)

    # Sort output: theo ma_cn để user dễ theo dõi. Fallback ma_cn empty đẩy cuối.
    def _sort_by_ma(rows):
        rows.sort(key=lambda r: (r.get("ma_cn", "") == "", r.get("ma_cn", ""), r.get("ten_cn", "")))

    _sort_by_ma(added)
    _sort_by_ma(deleted)
    _sort_by_ma(pic_changed)
    _sort_by_ma(prio_complex_changed)
    _sort_by_ma(fitgap_changed)
    _sort_by_ma(status_changed)

    return {
        "current_snapshot": current_meta or {},
        "previous_snapshot": previous_meta or {},
        "counts": {
            "added": len(added),
            "deleted": len(deleted),
            "pic_changed": len(pic_changed),
            "prio_complex_changed": len(prio_complex_changed),
            "fitgap_changed": len(fitgap_changed),
            "status_changed": len(status_changed),
            "total_changed": len(changed_row_keys),
            "current_total": len(current.rows),
            "previous_total": len(previous.rows),
        },
        "added": added,
        "deleted": deleted,
        "pic_changed": pic_changed,
        "priority_complexity_changed": prio_complex_changed,
        "fitgap_changed": fitgap_changed,
        "phase_status_changed": status_changed,
    }
