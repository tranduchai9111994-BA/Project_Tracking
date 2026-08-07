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
    # U11 — Estimate MH lệch so với duration (chỉ flag estimate QUÁ LỚN so với cửa sổ ngày)
    "estimate_vs_duration": {
        "severity": "low",
        "label": "Estimate MH lệch duration",
        "suggestion": "Estimate > 3× (End−Start+1)×8h — thường do nhập sai số hoặc lệch cột. Estimate nhỏ hơn cửa sổ ngày là bình thường.",
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


def is_row_fully_done(row: FunctionRow) -> bool:
    """True nếu function đã coi như hoàn thành hết:

    - Có ít nhất 1 phase Closed hoặc Cancelled (nghĩa là function đã đi
      vào quy trình, không phải row rỗng).
    - Không phase nào còn ở trạng thái active
      (Open/Assigned/In-progress/Resolved/Pending).
    - Blank status coi như "phase không áp dụng cho function này" — không
      cản trở kết luận done (VD function không có phase UAT thì UAT blank).

    DQ bỏ toàn bộ flag của những function này để tránh nhiễu report — user
    đã Closed hết rồi thì flag «thiếu deadline / overlap / estimate lệch»
    không còn actionable. Chỉ giữ scan structural (duplicate ma_cn) trên
    những row chưa done — copies fully-done không đóng góp vào count.
    """
    has_done = False
    for pd in row.phases.values():
        status = _norm_status(pd.status)
        if not status:
            continue
        if _is_active_status(status):
            return False
        if _is_closed_status(status):
            has_done = True
    return has_done


# --------------------------------------------------------------------------
# Analysis deadline gate (rule PMO 06/08/2026 — phản hồi screenshot DQ)
# --------------------------------------------------------------------------
# 1) Chưa tới deadline Analysis → KHÔNG đưa function lên DQ
#    (VD TMS.FR.65 Analysis End=09/07 khi today=08/06 → skip hết).
# 2) Đã tới deadline nhưng Analysis chưa Closed → chỉ flag phase Analysis
#    («cái gần nhất»). Không flag Config/Document/Dev overlap phía sau —
#    phân tích chưa xong thì các task sau chưa actionable.
# 3) Analysis đã Closed → quét DQ bình thường cho các phase sau.
# --------------------------------------------------------------------------

_ANALYSIS_GATE_SKIP = "skip"
_ANALYSIS_GATE_ONLY = "analysis_only"
_ANALYSIS_GATE_FULL = "full"


def find_analysis_phase_name(data: ParsedData, row: FunctionRow | None = None) -> str | None:
    """Tên phase Phân tích — không hardcode «Analysis».

    Ưu tiên: PhaseGroup.task_type == «Phân tích» → tên chứa analy/phân tích
    → phase đầu trong all_phases nếu khớp keyword.
    """
    phases = set((row.phases if row else {}) or {})
    # 1) task_type từ phase_groups
    for pg in data.phase_groups or []:
        if getattr(pg, "task_type", None) == "Phân tích":
            if not phases or pg.name in phases:
                return pg.name
    # 2) keyword trên tên
    order = list(data.all_phases or []) or [pg.name for pg in (data.phase_groups or [])]
    if row is not None and not order:
        order = list(row.phases.keys())
    for name in order:
        if phases and name not in phases:
            continue
        n = _norm_phase_name(name)
        if "analy" in n or "phan tich" in n or "phân tích" in n:
            return name
    return None


def _analysis_deadline(pd) -> date | None:
    """Deadline Analysis = End ưu tiên, không có End thì lấy Start."""
    if pd is None:
        return None
    return pd.end_date or pd.start_date


def analysis_dq_scope(
    data: ParsedData,
    row: FunctionRow,
    today: date | None = None,
) -> tuple[str, str | None]:
    """
    Trả ``(scope, analysis_phase_name)``.

    scope:
      - ``skip``: chưa tới deadline Analysis → bỏ hết issue của function.
      - ``analysis_only``: đã tới deadline, Analysis chưa Closed → chỉ
        flag phase Analysis (+ meta row-level vẫn cho phép).
      - ``full``: Analysis đã Closed / không có phase Analysis → quét bình thường.
    """
    today = today or date.today()
    name = find_analysis_phase_name(data, row)
    if not name:
        return _ANALYSIS_GATE_FULL, None
    pd = row.phases.get(name)
    if pd is None:
        return _ANALYSIS_GATE_FULL, name
    status = _norm_status(pd.status)
    if _is_closed_status(status):
        return _ANALYSIS_GATE_FULL, name
    deadline = _analysis_deadline(pd)
    if deadline is not None and deadline > today:
        return _ANALYSIS_GATE_SKIP, name
    # Đã tới deadline (hoặc chưa có ngày — coi là cần nhìn Analysis trước)
    return _ANALYSIS_GATE_ONLY, name


def _phase_allowed_by_analysis_scope(
    scope: str,
    analysis_name: str | None,
    phase_name: str,
) -> bool:
    """True nếu issue gắn ``phase_name`` được phép dưới scope hiện tại."""
    if scope == _ANALYSIS_GATE_SKIP:
        return False
    if scope == _ANALYSIS_GATE_FULL:
        return True
    # analysis_only: chỉ đúng phase Analysis (không gồm «Dev ∩ Config…»)
    return bool(analysis_name) and phase_name == analysis_name


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

    # === 1. Detect trùng Mã CN (làm 1 pass để nhóm) — chỉ đếm những row
    # CHƯA done và đã vào cửa sổ Analysis (không skip vì chưa tới deadline).
    ma_cn_counter: Counter = Counter()
    ma_cn_first_row: dict[str, int] = {}
    for row in data.rows:
        if is_row_fully_done(row):
            continue
        scope, _ = analysis_dq_scope(data, row, today)
        if scope == _ANALYSIS_GATE_SKIP:
            continue
        mc = _row_ma_cn(row)
        if mc:
            ma_cn_counter[mc] += 1
            ma_cn_first_row.setdefault(mc, row.row_num)

    duplicated_codes = {k for k, v in ma_cn_counter.items() if v > 1}

    # === 2. Duyệt từng row → detect các issue ===
    for row in data.rows:
        # Function đã Closed/Cancelled toàn bộ phase → bỏ qua mọi flag DQ.
        # Rule PMO 06/08/2026: "nếu tất cả status là closed hết thì không
        # đếm lên để tránh thừa". User đã đóng project/function rồi thì
        # blank Priority / thiếu deadline / overlap phase không còn cần fix.
        if is_row_fully_done(row):
            continue

        # Chưa tới deadline Analysis → không đưa function lên DQ.
        scope, analysis_name = analysis_dq_scope(data, row, today)
        if scope == _ANALYSIS_GATE_SKIP:
            continue

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
            if not _phase_allowed_by_analysis_scope(scope, analysis_name, phase_name):
                continue
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
            # Phase đã Closed/Cancelled → bỏ qua (việc đã xong, lệch MH không còn actionable).
            if (
                pd.start_date and pd.end_date and pd.end_date >= pd.start_date
                and pd.estimate_mh is not None and pd.estimate_mh > 0
                and not _is_closed_status(status)
            ):
                duration_days = (pd.end_date - pd.start_date).days + 1
                # Quy đổi thô: 1 ngày lịch ≈ 8 MH nếu làm full ngày.
                # Chỉ flag estimate >> cửa sổ ngày (ratio ≥ 3) — dấu hiệu nhập sai.
                # Estimate << cửa sổ ngày (VD 1.5 MH / 1 ngày) là bình thường.
                expected_mh = duration_days * 8.0
                ratio = pd.estimate_mh / expected_mh if expected_mh > 0 else 0
                if ratio >= 3.0:
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
        # analysis_only/skip → không flag overlap phase sau (phân tích chưa xong).
        if scope == _ANALYSIS_GATE_FULL:
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
                    s1 = _norm_status(p1.status)
                    s2 = _norm_status(p2.status)
                    # Cả 2 phase đã Closed/Cancelled → overlap lịch sử, không cần fix.
                    if _is_closed_status(s1) and _is_closed_status(s2):
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

    Cùng gate predecessor Closed + Start đã đến với Unassigned + Analysis gate.

    Returns:
        (function_count, phase_records) — function dedupe theo ma_cn (fallback row_num).
    """
    today = today or date.today()
    func_keys: set[str] = set()
    records = 0
    for row in data.rows:
        # Function đã done toàn bộ → không đếm (đồng bộ compute_data_quality).
        if is_row_fully_done(row):
            continue
        scope, analysis_name = analysis_dq_scope(data, row, today)
        if scope == _ANALYSIS_GATE_SKIP:
            continue
        ma_cn = _row_ma_cn(row)
        phase_order = (
            data.all_phases
            or [pg.name for pg in data.phase_groups]
            or list(row.phases.keys())
        )
        func_hit = False
        for phase_name, pd in row.phases.items():
            if not _phase_allowed_by_analysis_scope(scope, analysis_name, phase_name):
                continue
            if is_missing_deadline_phase(
                row, phase_name, pd, phase_order,
                today=today, require_active_status=True,
            ):
                records += 1
                func_hit = True
        if func_hit:
            func_keys.add(ma_cn or f"row:{row.row_num}")
    return len(func_keys), records


def count_anomalies(
    data: ParsedData,
    today: date | None = None,
) -> tuple[int, int]:
    """Đếm function/record bất thường (overlap / estimate / end<start / duplicate).

    Lightweight scan (không gọi full compute_data_quality) để dùng ở summary card.
    Tôn trọng Analysis deadline gate (cùng compute_data_quality).

    Returns:
        (function_count, issue_records) — function dedupe theo ma_cn.
    """
    today = today or date.today()
    func_keys: set[str] = set()
    records = 0

    # Duplicate Mã CN — chỉ đếm những row chưa done + không skip Analysis,
    # đồng bộ compute_data_quality.
    ma_cn_counter: Counter = Counter()
    for row in data.rows:
        if is_row_fully_done(row):
            continue
        scope, _ = analysis_dq_scope(data, row, today)
        if scope == _ANALYSIS_GATE_SKIP:
            continue
        mc = _row_ma_cn(row)
        if mc:
            ma_cn_counter[mc] += 1
    for mc, n in ma_cn_counter.items():
        if n > 1:
            records += n
            func_keys.add(mc)

    for row in data.rows:
        # Function đã done toàn bộ → skip mọi flag anomaly.
        if is_row_fully_done(row):
            continue
        scope, analysis_name = analysis_dq_scope(data, row, today)
        if scope == _ANALYSIS_GATE_SKIP:
            continue
        ma_cn = _row_ma_cn(row)
        key = ma_cn or f"row:{row.row_num}"
        hit = False

        for pname, pd in row.phases.items():
            if not _phase_allowed_by_analysis_scope(scope, analysis_name, pname):
                continue
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

        # Overlap chỉ khi Analysis đã Closed (scope=full)
        if scope == _ANALYSIS_GATE_FULL:
            phase_items = [
                (pname, pd) for pname, pd in row.phases.items()
                if pd.start_date and pd.end_date and pd.end_date >= pd.start_date
            ]
            for i in range(len(phase_items)):
                for j in range(i + 1, len(phase_items)):
                    n1, p1 = phase_items[i]
                    n2, p2 = phase_items[j]
                    if _is_allowed_parallel(n1, n2):
                        continue
                    if p1.start_date <= p2.end_date and p2.start_date <= p1.end_date:
                        records += 1
                        hit = True

        if hit:
            func_keys.add(key)

    return len(func_keys), records
