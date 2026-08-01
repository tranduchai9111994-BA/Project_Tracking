"""
UAT / Customer feedback quality (Phase E — backlog #5).

Đo chất lượng giao hàng qua khiếm khuyết & vòng UAT — không chỉ Open/Closed.

Detection (ưu tiên cột Excel auto-detect):
  - Defect / Bug / Số lỗi
  - Feedback / Phản hồi
  - Reopen / Số lần reopen
  - UAT cycle / Số vòng UAT

Khi không có cột: empty state (không bịa số lỗi) + optional tag «UAT issue»
(chỉ đếm qualitative, không suy ra defect count).
"""
from __future__ import annotations

import re
from collections import defaultdict
from typing import Any, Optional

from parser.excel_parser import ParsedData, FunctionRow

# Tag thủ công khi thiếu cột (không invent defect numbers)
UAT_ISSUE_TAG = "UAT issue"

_EMPTY_COUNT_TOKENS = {
    "", "-", "n/a", "na", "null", "none", "×", "✗",
}


def parse_count(val: Any) -> Optional[int]:
    """Parse ô số đếm (defect/reopen/cycle). Trống / không hợp lệ → None."""
    if val is None:
        return None
    if isinstance(val, bool):
        return int(val)
    if isinstance(val, int):
        return val if val >= 0 else None
    if isinstance(val, float):
        if val < 0 or val != val:  # NaN
            return None
        return int(val)
    s = str(val).strip().lower().replace(",", ".")
    if s in _EMPTY_COUNT_TOKENS:
        return None
    try:
        f = float(s)
        if f < 0:
            return None
        return int(f)
    except (TypeError, ValueError):
        return None


def _ma_cn(row: FunctionRow) -> str:
    return str(row.meta.get("ma_cn") or "").strip()


def _header_for_meta(data: ParsedData, meta_key: str) -> Optional[str]:
    col = (data.meta_columns or {}).get(meta_key)
    if col is None:
        return None
    for h, idx in (data.headers or {}).items():
        if idx == col:
            return h
    return meta_key


def find_uat_phase_name(data: ParsedData) -> Optional[str]:
    """
    Chọn phase UAT khách (ưu tiên tên gần đúng «UAT», tránh «Config UAT» nếu có UAT riêng).
    """
    names = list(data.all_phases or [])
    if not names and data.phase_groups:
        names = [pg.name for pg in data.phase_groups]
    if not names:
        return None

    # Exact / gần exact UAT
    for n in names:
        if re.fullmatch(r"(?i)\s*uat\s*", n or ""):
            return n
    # Có chữ UAT nhưng không phải Config/Cấu hình
    soft: list[str] = []
    for n in names:
        low = (n or "").lower()
        if "uat" not in low:
            continue
        if "config" in low or "cấu hình" in low or "cau hinh" in low:
            soft.append(n)
            continue
        return n
    return soft[0] if soft else None


def _uat_status(row: FunctionRow, uat_phase: Optional[str]) -> Optional[str]:
    if not uat_phase:
        return None
    pd = row.phases.get(uat_phase)
    if not pd:
        return None
    return (pd.status or "").strip() or None


def compute_uat_quality(
    data: ParsedData,
    *,
    function_tags: Optional[dict[str, list[str]]] = None,
    detail_limit: Optional[int] = 200,
) -> dict[str, Any]:
    """
    Tính metrics chất lượng UAT / feedback.

    Formulas:
      - total_defects / total_feedback = Σ count (ô trống bỏ qua, không đếm 0 giả)
      - functions_with_defects = số function có defect_count > 0
      - reopen_rate_pct = (# function reopen_count > 0)
            ÷ (# function UAT Closed|Resolved HOẶC reopen_count > 0) × 100
      - avg_uat_cycles = trung bình uat_cycle trên function có giá trị
      - multi_cycle_count = số function có uat_cycle ≥ 2

    detail_limit: cắt danh sách function (None/0 = tất cả — dùng khi xuất Excel).
    """
    tags_map = function_tags or {}
    defect_header = _header_for_meta(data, "defect_count")
    feedback_header = _header_for_meta(data, "feedback_count")
    reopen_header = _header_for_meta(data, "reopen_count")
    cycle_header = _header_for_meta(data, "uat_cycle")

    defect_col = (data.meta_columns or {}).get("defect_count")
    feedback_col = (data.meta_columns or {}).get("feedback_count")
    same_defect_feedback = (
        defect_col is not None
        and feedback_col is not None
        and defect_col == feedback_col
    )
    # Nếu cùng cột → chỉ báo defect (tránh double-count)
    if same_defect_feedback:
        feedback_header = None

    has_columns = any([
        defect_header, feedback_header, reopen_header, cycle_header,
    ])
    uat_phase = find_uat_phase_name(data)

    tagged_uat_issue = 0
    total_fns = 0
    total_defects = 0
    total_feedback = 0
    total_reopens = 0
    fns_with_defects = 0
    fns_with_feedback = 0
    fns_with_reopen = 0
    fns_defect_data = 0
    fns_feedback_data = 0
    fns_reopen_data = 0
    fns_cycle_data = 0
    cycle_sum = 0
    cycle_max = 0
    multi_cycle = 0
    uat_closedish = 0  # Closed | Resolved
    reopen_denom_set = 0

    by_mod: dict[str, dict[str, Any]] = defaultdict(lambda: {
        "total": 0,
        "defects": 0,
        "feedback": 0,
        "reopens": 0,
        "fns_with_defects": 0,
        "fns_with_reopen": 0,
        "fns_reopen_denom": 0,
        "cycle_sum": 0,
        "cycle_n": 0,
        "multi_cycle": 0,
        "tagged_uat_issue": 0,
    })

    per_function: list[dict[str, Any]] = []

    for row in data.rows:
        total_fns += 1
        ma = _ma_cn(row)
        mod = (row.meta.get("module") or "").strip() or "(trống)"
        ten = row.meta.get("ten_cn") or ""
        acc = by_mod[mod]
        acc["total"] += 1

        tags = tags_map.get(ma) or []
        is_tagged = UAT_ISSUE_TAG in tags
        if is_tagged:
            tagged_uat_issue += 1
            acc["tagged_uat_issue"] += 1

        d = parse_count(row.meta.get("defect_count")) if defect_header else None
        f = (
            None if same_defect_feedback or not feedback_header
            else parse_count(row.meta.get("feedback_count"))
        )
        r = parse_count(row.meta.get("reopen_count")) if reopen_header else None
        c = parse_count(row.meta.get("uat_cycle")) if cycle_header else None

        if d is not None:
            fns_defect_data += 1
            total_defects += d
            acc["defects"] += d
            if d > 0:
                fns_with_defects += 1
                acc["fns_with_defects"] += 1
        if f is not None:
            fns_feedback_data += 1
            total_feedback += f
            acc["feedback"] += f
            if f > 0:
                fns_with_feedback += 1
        if r is not None:
            fns_reopen_data += 1
            total_reopens += r
            acc["reopens"] += r
            if r > 0:
                fns_with_reopen += 1
                acc["fns_with_reopen"] += 1
        if c is not None:
            fns_cycle_data += 1
            cycle_sum += c
            cycle_max = max(cycle_max, c)
            acc["cycle_sum"] += c
            acc["cycle_n"] += 1
            if c >= 2:
                multi_cycle += 1
                acc["multi_cycle"] += 1

        uat_st = _uat_status(row, uat_phase)
        closedish = uat_st in ("Closed", "Resolved")
        if closedish:
            uat_closedish += 1

        in_reopen_denom = False
        if reopen_header:
            if closedish or (r is not None and r > 0):
                in_reopen_denom = True
        if in_reopen_denom:
            reopen_denom_set += 1
            acc["fns_reopen_denom"] += 1

        issues = (d or 0) + (f or 0)
        has_signal = (
            (d is not None and d > 0)
            or (f is not None and f > 0)
            or (r is not None and r > 0)
            or (c is not None and c >= 2)
            or is_tagged
        )
        if has_signal or (d is not None) or (f is not None) or (r is not None) or (c is not None):
            per_function.append({
                "ma_cn": ma,
                "ten_cn": ten,
                "module": mod,
                "quy_trinh": row.meta.get("quy_trinh") or row.meta.get("process") or "",
                "defect_count": d,
                "feedback_count": f,
                "reopen_count": r,
                "uat_cycle": c,
                "issues": issues,
                "uat_status": uat_st,
                "tagged_uat_issue": is_tagged,
            })

    # Sắp function: nhiều issue / reopen trước
    per_function.sort(
        key=lambda x: (
            -(x["issues"] or 0),
            -(x["reopen_count"] or 0),
            -(x["uat_cycle"] or 0),
            x["ma_cn"] or "",
        )
    )

    reopen_rate = None
    if reopen_header and reopen_denom_set > 0:
        reopen_rate = round(fns_with_reopen / reopen_denom_set * 100, 1)

    avg_cycles = (
        round(cycle_sum / fns_cycle_data, 2) if fns_cycle_data > 0 else None
    )
    avg_defects = (
        round(total_defects / fns_defect_data, 2) if fns_defect_data > 0 else None
    )
    avg_reopens = (
        round(total_reopens / fns_reopen_data, 2) if fns_reopen_data > 0 else None
    )

    modules: list[dict[str, Any]] = []
    for mod, a in by_mod.items():
        denom = int(a["fns_reopen_denom"])
        mod_reopen_rate = (
            round(int(a["fns_with_reopen"]) / denom * 100, 1) if denom > 0 else None
        )
        cn = int(a["cycle_n"])
        modules.append({
            "module": mod,
            "total": int(a["total"]),
            "defects": int(a["defects"]),
            "feedback": int(a["feedback"]),
            "reopens": int(a["reopens"]),
            "fns_with_defects": int(a["fns_with_defects"]),
            "fns_with_reopen": int(a["fns_with_reopen"]),
            "reopen_rate_pct": mod_reopen_rate,
            "avg_uat_cycles": round(a["cycle_sum"] / cn, 2) if cn > 0 else None,
            "multi_cycle": int(a["multi_cycle"]),
            "tagged_uat_issue": int(a["tagged_uat_issue"]),
        })
    modules.sort(
        key=lambda m: (
            -(m["defects"] + m["feedback"]),
            -(m["reopen_rate_pct"] or 0),
            m["module"],
        )
    )

    if has_columns:
        detection_mode = "column"
    elif tagged_uat_issue > 0:
        detection_mode = "tag"
    else:
        detection_mode = "none"

    messages: list[str] = []
    if has_columns:
        parts = []
        if defect_header:
            parts.append(f"defect «{defect_header}»")
        if feedback_header:
            parts.append(f"feedback «{feedback_header}»")
        if reopen_header:
            parts.append(f"reopen «{reopen_header}»")
        if cycle_header:
            parts.append(f"UAT cycle «{cycle_header}»")
        messages.append("Phát hiện cột chất lượng: " + ", ".join(parts) + ".")
        if same_defect_feedback and defect_header:
            messages.append(
                f"Cột «{defect_header}» khớp cả defect & feedback — chỉ đếm một lần (defect)."
            )
    else:
        messages.append(
            "Không có cột Defect/Bug/Feedback/Reopen/UAT cycle trên Excel. "
            "Không bịa số lỗi — metrics đếm = trống."
        )
        messages.append(
            "Gợi ý: thêm cột «Số lỗi» / «Reopen» / «Số vòng UAT» trên Function List, "
            f"hoặc gắn tag «{UAT_ISSUE_TAG}» / ghi chú function để theo dõi qualitative."
        )
        if tagged_uat_issue:
            messages.append(
                f"{tagged_uat_issue} function đang gắn tag «{UAT_ISSUE_TAG}» "
                "(chỉ đếm tag — không suy ra số defect)."
            )

    if uat_phase:
        messages.append(f"Phase UAT dùng cho reopen rate: «{uat_phase}».")
    elif reopen_header:
        messages.append(
            "Không tìm thấy phase UAT — reopen rate chỉ dựa function có reopen_count > 0."
        )

    if reopen_rate is not None and reopen_rate >= 20:
        messages.append(
            f"Reopen rate {reopen_rate}% — chất lượng UAT cần review (ngưỡng gợi ý ≥20%)."
        )
    if multi_cycle >= 3:
        messages.append(
            f"{multi_cycle} function ≥ 2 vòng UAT — có thể thiếu sẵn sàng trước khi vào UAT."
        )

    return {
        "definition": (
            "Chất lượng UAT: số defect/feedback theo function, "
            "reopen rate = % function từng reopen trong nhóm đã Closed/Resolved UAT "
            "(hoặc có reopen > 0), "
            "UAT cycle = số vòng UAT ghi trên Excel."
        ),
        "detection": {
            "mode": detection_mode,
            "primary": "column" if has_columns else (
                "tag" if tagged_uat_issue else "none"
            ),
            "defect_header": defect_header,
            "feedback_header": feedback_header,
            "reopen_header": reopen_header,
            "uat_cycle_header": cycle_header,
            "same_defect_feedback_column": same_defect_feedback,
            "uat_phase": uat_phase,
            "uat_issue_tag": UAT_ISSUE_TAG,
            "has_quality_columns": has_columns,
            "rules": [
                "Auto-detect header chứa Defect/Bug/Số lỗi, Feedback/Phản hồi, "
                "Reopen, UAT cycle/Số vòng UAT (bỏ qua cột phase « - »).",
                "Không có cột → không invent số lỗi; optional tag «UAT issue».",
                "Reopen rate = (# reopen>0) ÷ (# UAT Closed|Resolved ∪ reopen>0).",
                "Exact header Bug/Defect/Bugs/Defects được nhận; tránh dính «Debug».",
            ],
        },
        "summary": {
            "total_functions": total_fns,
            "total_defects": total_defects if defect_header else None,
            "total_feedback": total_feedback if feedback_header else None,
            "total_issues": (
                (total_defects if defect_header else 0)
                + (total_feedback if feedback_header else 0)
            ) if has_columns and (defect_header or feedback_header) else None,
            "fns_with_defects": fns_with_defects if defect_header else None,
            "fns_with_feedback": fns_with_feedback if feedback_header else None,
            "fns_with_quality_data": max(
                fns_defect_data, fns_feedback_data, fns_reopen_data, fns_cycle_data
            ),
            "avg_defects_per_fn": avg_defects,
            "total_reopens": total_reopens if reopen_header else None,
            "fns_with_reopen": fns_with_reopen if reopen_header else None,
            "reopen_denom": reopen_denom_set if reopen_header else None,
            "reopen_rate_pct": reopen_rate,
            "avg_reopens": avg_reopens,
            "avg_uat_cycles": avg_cycles,
            "max_uat_cycles": cycle_max if fns_cycle_data else None,
            "multi_cycle_count": multi_cycle if cycle_header else None,
            "fns_with_cycle_data": fns_cycle_data if cycle_header else None,
            "uat_closed_or_resolved": uat_closedish,
            "tagged_uat_issue": tagged_uat_issue,
        },
        "modules": modules,
        "functions": (
            per_function if not detail_limit or detail_limit <= 0
            else per_function[:detail_limit]
        ),
        "functions_truncated": (
            0 if not detail_limit or detail_limit <= 0
            else max(0, len(per_function) - detail_limit)
        ),
        "messages": messages,
        "assumptions": [
            "Ô trống / «-» / N/A không đếm là 0 trong avg (loại khỏi mẫu).",
            "Reopen rate chỉ tính khi có cột Reopen.",
            "Phase UAT: ưu tiên tên khớp UAT (không Config UAT nếu đã có UAT riêng).",
            f"Tag «{UAT_ISSUE_TAG}» chỉ là tín hiệu qualitative — không tạo defect giả.",
        ],
    }
