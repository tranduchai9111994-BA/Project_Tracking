"""
Data Quality Analyzer — phát hiện các vấn đề chất lượng dữ liệu trong Function List.

Mục đích: giúp PM/BA nhận ra các ô data bị lỗi/thiếu (invalid status, blank
PIC/Priority, End < Start, Closed thiếu End, WIP thiếu End/deadline, duplicate Mã CN...)
để clean data trước khi báo cáo cấp trên.

Không có dependency ngoài Python stdlib + parser.excel_parser.
"""
from __future__ import annotations
from collections import Counter
from datetime import date
from typing import Any

from parser.excel_parser import ParsedData, FunctionRow, VALID_STATUSES
from analyzer.unassigned import (
    is_missing_deadline_phase,
    is_unassigned_phase,
)


# === Các loại issue ===
# Mỗi issue có: `code`, `severity` (high/medium/low), `label` (VN), `suggestion` (VN).
ISSUE_META: dict[str, dict[str, str]] = {
    "invalid_status": {
        "severity": "high",
        "label": "Status không hợp lệ",
        "suggestion": "Đổi về 1 trong: Open, Assigned, In-progress, Resolved, Closed, Pending, Cancelled.",
    },
    "end_before_start": {
        "severity": "high",
        "label": "End date < Start date",
        "suggestion": "Kiểm tra lại ngày Start/End — có thể user nhập ngược 2 ô.",
    },
    "closed_no_end": {
        "severity": "medium",
        "label": "Status Closed nhưng thiếu End date",
        "suggestion": "Bổ sung End date thực tế để tính overdue/aging chính xác.",
    },
    "missing_deadline": {
        "severity": "medium",
        "label": "Thiếu End khi đang làm",
        "suggestion": "Bổ sung End/Deadline cho phase đang Open/Assigned/In-progress/Resolved/Pending.",
    },
    "blank_pic": {
        "severity": "medium",
        "label": "Phase active nhưng thiếu PIC",
        "suggestion": "Gán PIC phụ trách để track công việc.",
    },
    "blank_priority": {
        "severity": "low",
        "label": "Thiếu Priority",
        "suggestion": "Chọn Must-have / Should-have / Could-have / Won't-have.",
    },
    "blank_complexity": {
        "severity": "low",
        "label": "Thiếu Complexity",
        "suggestion": "Chọn Low / Medium / High.",
    },
    "blank_fitgap": {
        "severity": "low",
        "label": "Thiếu FIT/GAP",
        "suggestion": "Chọn FIT hoặc GAP.",
    },
    "duplicate_ma_cn": {
        "severity": "high",
        "label": "Trùng Mã CN",
        "suggestion": "Đổi lại Mã CN để duy nhất — mỗi function 1 mã.",
    },
    # U10 — phase overlap (Start/End chồng nhau giữa 2 phase cùng function)
    "phase_overlap": {
        "severity": "medium",
        "label": "Phase overlap ngày",
        "suggestion": "Điều chỉnh Start/End để 2 phase không chồng lịch.",
    },
    # U11 — Estimate MH lệch so với duration (ngày làm việc ≈ duration*8h)
    "estimate_vs_duration": {
        "severity": "low",
        "label": "Estimate MH lệch duration",
        "suggestion": "Đối chiếu Estimate MH với (End−Start) — lệch > 3× thường do nhập sai hoặc lệch cột.",
    },
}

# Cặp phase được phép chạy song song trùng ngày — không flag phase_overlap.
# Key = frozenset 2 tên đã normalize (lowercase, collapse whitespace).
PARALLEL_PHASE_PAIRS: frozenset[frozenset[str]] = frozenset({
    frozenset({"config local", "config uat"}),
})

# Codes được gộp vào card «Bất thường» (đo được, dedupe ma_cn).
ANOMALY_CODES = frozenset({
    "phase_overlap",
    "estimate_vs_duration",
    "end_before_start",
    "duplicate_ma_cn",
})


def _norm_phase_name(name: str) -> str:
    """Chuẩn hóa tên phase để so khớp linh hoạt (case/whitespace)."""
    return " ".join(str(name).strip().lower().split())


def _is_allowed_parallel(phase_a: str, phase_b: str) -> bool:
    """True nếu cặp phase nằm trong whitelist song song hợp lệ."""
    pair = frozenset({_norm_phase_name(phase_a), _norm_phase_name(phase_b)})
    return pair in PARALLEL_PHASE_PAIRS


def _norm_status(s: Any) -> str:
    """Chuẩn hóa status về string strip. Nếu là số (Excel Estimate MH lệch cột)
    thì coi như invalid — nhưng đã được parser lọc, ở đây chỉ nhận string."""
    if s is None:
        return ""
    return str(s).strip()


def _is_closed_status(status: str) -> bool:
    return status.lower() in ("closed", "cancelled")


def _is_active_status(status: str) -> bool:
    """Phase 'active' = có kế hoạch làm nhưng chưa xong (không phải Closed/Cancelled)."""
    if not status:
        return False
    return status.lower() in ("open", "assigned", "in-progress", "resolved", "pending")


def _row_ma_cn(row: FunctionRow) -> str:
    return str(row.meta.get("ma_cn") or "").strip()


def _row_ten_cn(row: FunctionRow) -> str:
    return str(row.meta.get("ten_cn") or "").strip()


def _row_module(row: FunctionRow) -> str:
    return str(row.meta.get("module") or "").strip()


def _row_process(row: FunctionRow) -> str:
    # meta key chuẩn là "quy_trinh" (giữ backward-compat với "process")
    return str(row.meta.get("quy_trinh") or row.meta.get("process") or "").strip()


def _has_planned_dates(pd) -> bool:
    """Phase 'có kế hoạch' = có ít nhất 1 trong start/end date."""
    return bool(pd.start_date or pd.end_date)


def compute_data_quality(
    data: ParsedData,
    today: date | None = None,
) -> dict[str, Any]:
    """
    Quét toàn bộ ParsedData → trả về:
      {
        "issues": [ {row_num, ma_cn, ten_cn, module, phase, code, severity,
                     label, detail, suggestion}, ... ],
        "summary": {
            "total_issues": N,
            "by_severity": {"high": x, "medium": y, "low": z},
            "by_code": {code: count, ...},
            "affected_rows": N (số function có ít nhất 1 issue),
            "clean_rows": N (số function không có issue),
            "total_rows": N (tổng function),
            "clean_pct": float,
        }
      }
    """
    today = today or date.today()
    issues: list[dict[str, Any]] = []

    # === 1. Detect trùng Mã CN (làm 1 pass để nhóm) ===
    ma_cn_counter: Counter = Counter()
    ma_cn_first_row: dict[str, int] = {}
    for row in data.rows:
        mc = _row_ma_cn(row)
        if mc:
            ma_cn_counter[mc] += 1
            ma_cn_first_row.setdefault(mc, row.row_num)

    duplicated_codes = {k for k, v in ma_cn_counter.items() if v > 1}

    # === 2. Duyệt từng row → detect các issue ===
    for row in data.rows:
        ma_cn = _row_ma_cn(row)
        ten_cn = _row_ten_cn(row)
        module = _row_module(row)
        quy_trinh = _row_process(row)

        # ---- Row-level issues (không phụ thuộc phase) ----
        # Duplicate Mã CN
        if ma_cn and ma_cn in duplicated_codes:
            issues.append({
                "row_num": row.row_num,
                "ma_cn": ma_cn,
                "ten_cn": ten_cn,
                "module": module,
                "quy_trinh": quy_trinh,
                "phase": "",
                "code": "duplicate_ma_cn",
                "severity": ISSUE_META["duplicate_ma_cn"]["severity"],
                "label": ISSUE_META["duplicate_ma_cn"]["label"],
                "detail": f"Mã CN '{ma_cn}' xuất hiện {ma_cn_counter[ma_cn]} lần trong file",
                "suggestion": ISSUE_META["duplicate_ma_cn"]["suggestion"],
            })

        # Meta-level blanks — chỉ cảnh báo nếu row có Mã CN (row rỗng bỏ qua)
        if ma_cn:
            if not str(row.meta.get("priority") or "").strip():
                issues.append({
                    "row_num": row.row_num, "ma_cn": ma_cn, "ten_cn": ten_cn,
                    "module": module, "quy_trinh": quy_trinh, "phase": "",
                    "code": "blank_priority",
                    "severity": ISSUE_META["blank_priority"]["severity"],
                    "label": ISSUE_META["blank_priority"]["label"],
                    "detail": "Cột Priority trống",
                    "suggestion": ISSUE_META["blank_priority"]["suggestion"],
                })
            if not str(row.meta.get("complexity") or "").strip():
                issues.append({
                    "row_num": row.row_num, "ma_cn": ma_cn, "ten_cn": ten_cn,
                    "module": module, "quy_trinh": quy_trinh, "phase": "",
                    "code": "blank_complexity",
                    "severity": ISSUE_META["blank_complexity"]["severity"],
                    "label": ISSUE_META["blank_complexity"]["label"],
                    "detail": "Cột Complexity trống",
                    "suggestion": ISSUE_META["blank_complexity"]["suggestion"],
                })
            if not str(row.meta.get("fit_gap") or "").strip():
                issues.append({
                    "row_num": row.row_num, "ma_cn": ma_cn, "ten_cn": ten_cn,
                    "module": module, "quy_trinh": quy_trinh, "phase": "",
                    "code": "blank_fitgap",
                    "severity": ISSUE_META["blank_fitgap"]["severity"],
                    "label": ISSUE_META["blank_fitgap"]["label"],
                    "detail": "Cột FIT/GAP trống",
                    "suggestion": ISSUE_META["blank_fitgap"]["suggestion"],
                })

        # ---- Phase-level issues ----
        phase_order = (
            data.all_phases
            or [pg.name for pg in data.phase_groups]
            or list(row.phases.keys())
        )
        for phase_name, pd in row.phases.items():
            status = _norm_status(pd.status)

            # Invalid status (không rỗng nhưng không nằm trong danh sách hợp lệ)
            if status and status not in VALID_STATUSES:
                issues.append({
                    "row_num": row.row_num, "ma_cn": ma_cn, "ten_cn": ten_cn,
                    "module": module, "quy_trinh": quy_trinh, "phase": phase_name,
                    "code": "invalid_status",
                    "severity": ISSUE_META["invalid_status"]["severity"],
                    "label": ISSUE_META["invalid_status"]["label"],
                    "detail": f"Status '{status}' không thuộc VALID_STATUSES",
                    "suggestion": ISSUE_META["invalid_status"]["suggestion"],
                })

            # End < Start — bỏ qua nếu đã Closed/Cancelled (việc đã xong, ép sửa ngày không có giá trị)
            if (
                pd.start_date and pd.end_date and pd.end_date < pd.start_date
                and not _is_closed_status(status)
            ):
                issues.append({
                    "row_num": row.row_num, "ma_cn": ma_cn, "ten_cn": ten_cn,
                    "module": module, "quy_trinh": quy_trinh, "phase": phase_name,
                    "code": "end_before_start",
                    "severity": ISSUE_META["end_before_start"]["severity"],
                    "label": ISSUE_META["end_before_start"]["label"],
                    "detail": f"Start={pd.start_date.isoformat()} > End={pd.end_date.isoformat()}",
                    "suggestion": ISSUE_META["end_before_start"]["suggestion"],
                })

            # Closed nhưng không có End date
            if _is_closed_status(status) and not pd.end_date and _has_planned_dates(pd):
                issues.append({
                    "row_num": row.row_num, "ma_cn": ma_cn, "ten_cn": ten_cn,
                    "module": module, "quy_trinh": quy_trinh, "phase": phase_name,
                    "code": "closed_no_end",
                    "severity": ISSUE_META["closed_no_end"]["severity"],
                    "label": ISSUE_META["closed_no_end"]["label"],
                    "detail": f"Status={status} nhưng ô End trống",
                    "suggestion": ISSUE_META["closed_no_end"]["suggestion"],
                })

            # WIP thiếu End — cùng gate predecessor + Start với Unassigned
            if is_missing_deadline_phase(
                row, phase_name, pd, phase_order,
                today=today, require_active_status=True,
            ):
                issues.append({
                    "row_num": row.row_num, "ma_cn": ma_cn, "ten_cn": ten_cn,
                    "module": module, "quy_trinh": quy_trinh, "phase": phase_name,
                    "code": "missing_deadline",
                    "severity": ISSUE_META["missing_deadline"]["severity"],
                    "label": ISSUE_META["missing_deadline"]["label"],
                    "detail": f"Status={status} nhưng ô End trống (chưa cập nhật deadline)",
                    "suggestion": ISSUE_META["missing_deadline"]["suggestion"],
                })

            # Blank PIC — cùng rule Unassigned (pred Closed + Start đã đến)
            if is_unassigned_phase(row, phase_name, pd, phase_order, today):
                issues.append({
                    "row_num": row.row_num, "ma_cn": ma_cn, "ten_cn": ten_cn,
                    "module": module, "quy_trinh": quy_trinh, "phase": phase_name,
                    "code": "blank_pic",
                    "severity": ISSUE_META["blank_pic"]["severity"],
                    "label": ISSUE_META["blank_pic"]["label"],
                    "detail": f"Phase '{phase_name}' đã tới Start nhưng chưa gán PIC",
                    "suggestion": ISSUE_META["blank_pic"]["suggestion"],
                })

            # U11 — Estimate MH vs duration (chỉ khi có cả Start+End+Estimate)
            if (
                pd.start_date and pd.end_date and pd.end_date >= pd.start_date
                and pd.estimate_mh is not None and pd.estimate_mh > 0
            ):
                duration_days = (pd.end_date - pd.start_date).days + 1
                # Quy đổi thô: 1 ngày làm ≈ 8 MH
                expected_mh = duration_days * 8.0
                ratio = pd.estimate_mh / expected_mh if expected_mh > 0 else 0
                # Flag khi lệch > 3× (estimate quá lớn hoặc quá nhỏ so với khoảng ngày)
                if ratio >= 3.0 or ratio <= (1.0 / 3.0):
                    issues.append({
                        "row_num": row.row_num, "ma_cn": ma_cn, "ten_cn": ten_cn,
                        "module": module, "quy_trinh": quy_trinh, "phase": phase_name,
                        "code": "estimate_vs_duration",
                        "severity": ISSUE_META["estimate_vs_duration"]["severity"],
                        "label": ISSUE_META["estimate_vs_duration"]["label"],
                        "detail": (
                            f"Estimate={pd.estimate_mh:g} MH vs duration={duration_days}d "
                            f"(≈{expected_mh:g} MH @8h/d), ratio={ratio:.1f}×"
                        ),
                        "suggestion": ISSUE_META["estimate_vs_duration"]["suggestion"],
                    })

        # ---- U10: Phase overlap trong cùng 1 function ----
        # So sánh mọi cặp phase có đủ Start+End; báo 1 issue / cặp (dedupe ma_cn ở summary).
        phase_items = [
            (pname, pd) for pname, pd in row.phases.items()
            if pd.start_date and pd.end_date and pd.end_date >= pd.start_date
        ]
        for i in range(len(phase_items)):
            for j in range(i + 1, len(phase_items)):
                n1, p1 = phase_items[i]
                n2, p2 = phase_items[j]
                # Config Local ↔ Config UAT được phép song song — bỏ qua
                if _is_allowed_parallel(n1, n2):
                    continue
                # Overlap inclusive: start1 <= end2 AND start2 <= end1
                if p1.start_date <= p2.end_date and p2.start_date <= p1.end_date:
                    issues.append({
                        "row_num": row.row_num, "ma_cn": ma_cn, "ten_cn": ten_cn,
                        "module": module, "quy_trinh": quy_trinh,
                        "phase": f"{n1} ∩ {n2}",
                        "code": "phase_overlap",
                        "severity": ISSUE_META["phase_overlap"]["severity"],
                        "label": ISSUE_META["phase_overlap"]["label"],
                        "detail": (
                            f"'{n1}' [{p1.start_date.isoformat()}→{p1.end_date.isoformat()}] "
                            f"chồng '{n2}' [{p2.start_date.isoformat()}→{p2.end_date.isoformat()}]"
                        ),
                        "suggestion": ISSUE_META["phase_overlap"]["suggestion"],
                    })

    # === 3. Summary ===
    by_severity: Counter = Counter()
    by_code: Counter = Counter()
    affected_row_nums: set[int] = set()
    # Dedup function cho missing_deadline / anomaly (card summary đếm theo function)
    missing_deadline_keys: set[str] = set()
    anomaly_keys: set[str] = set()
    anomaly_codes = ANOMALY_CODES
    for it in issues:
        by_severity[it["severity"]] += 1
        by_code[it["code"]] += 1
        affected_row_nums.add(it["row_num"])
        key = (it.get("ma_cn") or "").strip() or f"row:{it['row_num']}"
        if it["code"] == "missing_deadline":
            missing_deadline_keys.add(key)
        if it["code"] in anomaly_codes:
            anomaly_keys.add(key)

    total_rows = len(data.rows)
    affected = len(affected_row_nums)
    clean = max(0, total_rows - affected)
    clean_pct = round(100.0 * clean / total_rows, 1) if total_rows else 100.0

    anomaly_records = sum(by_code.get(c, 0) for c in anomaly_codes)

    return {
        "issues": issues,
        "summary": {
            "total_issues": len(issues),
            "by_severity": {
                "high": by_severity.get("high", 0),
                "medium": by_severity.get("medium", 0),
                "low": by_severity.get("low", 0),
            },
            "by_code": dict(by_code),
            "affected_rows": affected,
            "clean_rows": clean,
            "total_rows": total_rows,
            "clean_pct": clean_pct,
            # Function unique thiếu End khi đang làm (dedupe ma_cn)
            "missing_deadline_count": len(missing_deadline_keys),
            "missing_deadline_records": by_code.get("missing_deadline", 0),
            # Bất thường đo được (overlap / estimate / end<start / duplicate) — dedupe ma_cn
            "anomaly_count": len(anomaly_keys),
            "anomaly_records": anomaly_records,
            "anomaly_codes": sorted(anomaly_codes),
        },
    }


def count_missing_deadlines(
    data: ParsedData,
    today: date | None = None,
) -> tuple[int, int]:
    """Đếm function/phase thiếu End khi đang làm — dùng cho summary card.

    Cùng gate predecessor Closed + Start đã đến với Unassigned.

    Returns:
        (function_count, phase_records) — function dedupe theo ma_cn (fallback row_num).
    """
    today = today or date.today()
    func_keys: set[str] = set()
    records = 0
    for row in data.rows:
        ma_cn = _row_ma_cn(row)
        phase_order = (
            data.all_phases
            or [pg.name for pg in data.phase_groups]
            or list(row.phases.keys())
        )
        func_hit = False
        for phase_name, pd in row.phases.items():
            if is_missing_deadline_phase(
                row, phase_name, pd, phase_order,
                today=today, require_active_status=True,
            ):
                records += 1
                func_hit = True
        if func_hit:
            func_keys.add(ma_cn or f"row:{row.row_num}")
    return len(func_keys), records


def count_anomalies(data: ParsedData) -> tuple[int, int]:
    """Đếm function/record bất thường (overlap / estimate / end<start / duplicate).

    Lightweight scan (không gọi full compute_data_quality) để dùng ở summary card.

    Returns:
        (function_count, issue_records) — function dedupe theo ma_cn.
    """
    func_keys: set[str] = set()
    records = 0

    # Duplicate Mã CN
    ma_cn_counter: Counter = Counter()
    for row in data.rows:
        mc = _row_ma_cn(row)
        if mc:
            ma_cn_counter[mc] += 1
    for mc, n in ma_cn_counter.items():
        if n > 1:
            records += n
            func_keys.add(mc)

    for row in data.rows:
        ma_cn = _row_ma_cn(row)
        key = ma_cn or f"row:{row.row_num}"
        hit = False

        for _pname, pd in row.phases.items():
            if pd.start_date and pd.end_date and pd.end_date < pd.start_date:
                records += 1
                hit = True
            if (
                pd.start_date and pd.end_date and pd.end_date >= pd.start_date
                and pd.estimate_mh is not None and pd.estimate_mh > 0
            ):
                duration_days = (pd.end_date - pd.start_date).days + 1
                expected_mh = duration_days * 8.0
                ratio = pd.estimate_mh / expected_mh if expected_mh > 0 else 0
                if ratio >= 3.0 or ratio <= (1.0 / 3.0):
                    records += 1
                    hit = True

        phase_items = [
            (pname, pd) for pname, pd in row.phases.items()
            if pd.start_date and pd.end_date and pd.end_date >= pd.start_date
        ]
        for i in range(len(phase_items)):
            for j in range(i + 1, len(phase_items)):
                _n1, p1 = phase_items[i]
                _n2, p2 = phase_items[j]
                if p1.start_date <= p2.end_date and p2.start_date <= p1.end_date:
                    records += 1
                    hit = True

        if hit:
            func_keys.add(key)

    return len(func_keys), records
