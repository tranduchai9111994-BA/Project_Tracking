"""
Audit Report — Đánh giá chất lượng dữ liệu Function List (11 sheet).

Build dict issues từ ParsedData + metrics để exporter viết Excel.
Không hardcode cột — dùng meta/phase đã auto-detect + data-quality log từ parser.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date
from typing import Any, Optional

from parser.excel_parser import ParsedData, FunctionRow, PhaseData, VALID_STATUSES


DONE_STATUSES = {"Closed", "Cancelled"}


def build_audit_issues(
    parsed: ParsedData,
    metrics: dict[str, Any],
    today: Optional[date] = None,
) -> dict[str, Any]:
    """
    Tổng hợp các nhóm issue cho Report Đánh giá.

    Returns dict với keys:
      summary, missing_meta, date_errors, status_errors,
      pic_blacklist, estimate_rejected, unassigned, overdue,
      stalled, high_risk, discrepancy
    """
    today = today or date.today()
    summary_m = metrics.get("summary", {}) or {}

    missing_meta = _collect_missing_meta(parsed)
    date_errors = _collect_date_errors(parsed)
    status_errors = _collect_status_errors(parsed)
    pic_blacklist = list(getattr(parsed, "pic_blacklisted", []) or [])
    estimate_rejected = list(getattr(parsed, "estimate_mh_rejected", []) or [])
    unassigned = list(metrics.get("unassigned_tasks", []) or [])
    overdue = list(metrics.get("overdue_list", []) or [])
    stalled = list((metrics.get("stalled_tasks") or {}).get("items", []) or [])
    risk_scores = list(metrics.get("risk_scores", []) or [])
    high_risk = [r for r in risk_scores if (r.get("risk_score") or 0) >= 50]
    discrepancy = _collect_discrepancy(parsed, metrics)

    summary = {
        "total_functions": summary_m.get("total_functions", len(parsed.rows)),
        "modules_count": summary_m.get("modules_count", len(parsed.all_modules)),
        "phases_count": summary_m.get("phases_count", len(parsed.all_phases)),
        "overall_progress_pct": summary_m.get("overall_progress_pct", 0),
        "missing_meta_count": len(missing_meta),
        "date_errors_count": len(date_errors),
        "status_errors_count": len(status_errors),
        "pic_blacklist_count": len(pic_blacklist),
        "estimate_rejected_count": len(estimate_rejected),
        "unassigned_count": len(unassigned),
        "overdue_count": len(overdue),
        "stalled_count": len(stalled),
        "high_risk_count": len(high_risk),
        "discrepancy_count": len(discrepancy),
        "today": today.isoformat(),
    }

    return {
        "summary": summary,
        "missing_meta": missing_meta,
        "date_errors": date_errors,
        "status_errors": status_errors,
        "pic_blacklist": pic_blacklist,
        "estimate_rejected": estimate_rejected,
        "unassigned": unassigned,
        "overdue": overdue,
        "stalled": stalled,
        "high_risk": high_risk,
        "discrepancy": discrepancy,
    }


def _collect_missing_meta(parsed: ParsedData) -> list[dict]:
    """Function thiếu module / priority / complexity / fit_gap / ma_cn."""
    items: list[dict] = []
    for r in parsed.rows:
        missing: list[str] = []
        for key, label in [
            ("ma_cn", "Mã CN"),
            ("module", "Module"),
            ("priority", "Priority"),
            ("complexity", "Complexity"),
            ("fit_gap", "FIT/GAP"),
        ]:
            val = r.meta.get(key)
            if val is None or (isinstance(val, str) and not str(val).strip()):
                # Chỉ báo thiếu nếu cột meta đó tồn tại trong file
                if parsed.meta_columns.get(key):
                    missing.append(label)
        if missing:
            items.append({
                "row_index": r.row_num,
                "ma_cn": r.meta.get("ma_cn") or "",
                "ten_cn": r.meta.get("ten_cn") or "",
                "module": r.meta.get("module") or "",
                "missing_fields": ", ".join(missing),
            })
    return items


def _collect_date_errors(parsed: ParsedData) -> list[dict]:
    """End < Start; hoặc có End nhưng không parse được (đã None sau normalize)."""
    items: list[dict] = []
    for r in parsed.rows:
        for phase_name, pd in r.phases.items():
            if pd.start_date and pd.end_date and pd.end_date < pd.start_date:
                items.append({
                    "row_index": r.row_num,
                    "ma_cn": r.meta.get("ma_cn") or "",
                    "ten_cn": r.meta.get("ten_cn") or "",
                    "module": r.meta.get("module") or "",
                    "phase": phase_name,
                    "start_date": pd.start_date.isoformat(),
                    "end_date": pd.end_date.isoformat(),
                    "issue": "end_before_start",
                })
    return items


def _collect_status_errors(parsed: ParsedData) -> list[dict]:
    """
    Status lệch: giá trị numeric hoặc text không thuộc VALID_STATUSES.

    Parser đã set status=None cho numeric/invalid — phát hiện qua extra raw
    không khả thi sau parse. Heuristic: phase có Start/End/PIC/Estimate nhưng
    status None → ghi 'status_missing_with_activity' (mềm).
    Numeric/invalid thật sự đã bị drop; sheet này chủ yếu phục vụ discrepancy
    nhẹ + chỗ trống bất thường.
    """
    items: list[dict] = []
    for r in parsed.rows:
        for phase_name, pd in r.phases.items():
            has_activity = bool(
                pd.start_date or pd.end_date or pd.pics
                or (pd.estimate_mh is not None and pd.estimate_mh > 0)
            )
            if has_activity and not pd.status:
                items.append({
                    "row_index": r.row_num,
                    "ma_cn": r.meta.get("ma_cn") or "",
                    "ten_cn": r.meta.get("ten_cn") or "",
                    "module": r.meta.get("module") or "",
                    "phase": phase_name,
                    "issue": "status_missing_with_activity",
                    "detail": "Có date/PIC/estimate nhưng Status trống hoặc không hợp lệ",
                })
    return items


def _collect_discrepancy(parsed: ParsedData, metrics: dict) -> list[dict]:
    """
    Mâu thuẫn dữ liệu — VD:
    - Progress ~0% nhưng nhiều phase Closed
    - Nhiều Closed nhưng overall progress thấp bất thường theo module
    """
    items: list[dict] = []
    summary = metrics.get("summary", {}) or {}
    overall = float(summary.get("overall_progress_pct") or 0)

    # Per-function: đếm phase Closed vs total phase có status
    for r in parsed.rows:
        closed = 0
        with_status = 0
        for pd in r.phases.values():
            if pd.status:
                with_status += 1
                if pd.status == "Closed":
                    closed += 1
        if with_status == 0:
            continue
        pct = closed / with_status * 100
        # Nhiều Closed (>= 50%) nhưng last-phase chưa Closed và overall thấp
        # → không phải bug lớn; focus: 0% overall nhưng function này gần done
        last_phase = parsed.all_phases[-1] if parsed.all_phases else None
        last_pd = r.phases.get(last_phase, PhaseData()) if last_phase else PhaseData()
        if closed >= 2 and pct >= 50 and last_pd.status and last_pd.status not in DONE_STATUSES:
            # Có tiến độ phase trước nhưng last phase open — bình thường, skip
            pass
        # Function gần như toàn Closed nhưng last phase Open/In-progress lâu?
        if closed >= max(2, with_status - 1) and last_pd.status and last_pd.status not in DONE_STATUSES:
            items.append({
                "ma_cn": r.meta.get("ma_cn") or "",
                "ten_cn": r.meta.get("ten_cn") or "",
                "module": r.meta.get("module") or "",
                "issue": "mostly_closed_but_last_open",
                "detail": f"{closed}/{with_status} phase Closed nhưng phase cuối = {last_pd.status}",
                "closed_phases": closed,
                "status_phases": with_status,
            })

    # Module overview: progress 0% nhưng có nhiều Closed trong matrix
    matrix_wrap = metrics.get("phase_status_matrix") or {}
    matrix = matrix_wrap.get("data", matrix_wrap) if isinstance(matrix_wrap, dict) else {}
    module_overview = metrics.get("module_overview") or []
    for mo in module_overview:
        mod = mo.get("module") or ""
        pct = float(mo.get("progress_pct") or mo.get("pct_closed") or 0)
        closed_cells = 0
        mod_matrix = matrix.get(mod) if isinstance(matrix, dict) else None
        if isinstance(mod_matrix, dict):
            for phase_stats in mod_matrix.values():
                if isinstance(phase_stats, dict):
                    closed_cells += int(phase_stats.get("Closed") or 0)
        if pct <= 0 and closed_cells >= 3:
            items.append({
                "ma_cn": "",
                "ten_cn": "",
                "module": mod,
                "issue": "module_progress_zero_but_many_closed",
                "detail": f"Progress module ~{pct}% nhưng có {closed_cells} phase-record Closed",
                "closed_phases": closed_cells,
                "status_phases": 0,
            })

    # Overall progress 0 nhưng total Closed tasks lớn
    if overall <= 0:
        overdue_n = len(metrics.get("overdue_list") or [])
        # Đếm Closed từ effort
        closed_mh = float((metrics.get("effort_analysis") or {}).get("total_closed_mh") or 0)
        if closed_mh > 0:
            items.append({
                "ma_cn": "",
                "ten_cn": "",
                "module": "",
                "issue": "overall_zero_but_closed_effort",
                "detail": f"Overall progress {overall}% nhưng đã Closed {closed_mh} MH",
                "closed_phases": 0,
                "status_phases": 0,
            })
        if overdue_n == 0 and closed_mh == 0 and len(parsed.rows) > 0:
            # Không có gì — có thể dữ liệu thật sự chưa start
            pass

    return items


# Tên sheet chuẩn (11 sheet) — exporter + tests dùng chung
AUDIT_SHEET_NAMES = [
    "01_Summary",
    "02_Meta_Thieu",
    "03_Date_Loi",
    "04_Status_Lech",
    "05_PIC_Blacklist",
    "06_Estimate_Rejected",
    "07_Unassigned",
    "08_Overdue",
    "09_Stalled",
    "10_High_Risk",
    "11_Discrepancy",
]
