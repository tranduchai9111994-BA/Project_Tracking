"""
Drill-Down — Từ 1 cell/segment trên biểu đồ → list function chi tiết.

Mỗi chart type có logic filter khác nhau:
- phase_matrix:      module × phase
- phase_stacked:     phase × status
- pic_workload:      pic × (status | overdue flag)
- priority:          priority value
- complexity:        complexity value
- fit_gap:           module × fit_gap value
- giai_doan:         giai_doan × phase
- module:            module value
- process:           quy_trinh value
- task_type:         nhóm công việc → phase group(s)
- effort_heatmap:    module × phase (có estimate MH)
- effort_pic:        pic × closed|remaining|all
- overdue:           mọi phase overdue
- unassigned:        phase active chưa PIC
- stalled:           task kẹt giữa 2 phase
- risk:              theo score band
- duration:          task duration bất thường
- timeline:          function trong module (hoặc 1 mã CN)

Output chuẩn cho mọi chart type: list of dict với các field:
    ma_cn, ten_cn, module, quy_trinh, priority, complexity, fit_gap,
    giai_doan, phase, status, pics, start_date, end_date,
    days_overdue, is_overdue, estimate_mh
"""
from datetime import date
from typing import Any, Callable, Optional

from parser.excel_parser import ParsedData, FunctionRow, PhaseData
from analyzer.overdue import is_phase_overdue
from analyzer.unassigned import is_unassigned_phase

# Status coi là "done" khi filter effort remaining
_DONE_STATUSES = frozenset({"Closed", "Cancelled"})


def _is_overdue(
    pd: PhaseData,
    today: date,
    *,
    row: Optional[FunctionRow] = None,
    phase_name: Optional[str] = None,
    phase_order: Optional[list[str]] = None,
) -> bool:
    """Phase overdue — đồng bộ ``analyzer.overdue.is_phase_overdue``."""
    return is_phase_overdue(
        pd, today, row=row, phase_name=phase_name, phase_order=phase_order,
    )


def _is_phase_active_for_unassigned(pd: PhaseData) -> bool:
    """Phase in-scope — đồng bộ ``analyzer.unassigned.is_phase_in_scope``."""
    from analyzer.unassigned import is_phase_in_scope
    return is_phase_in_scope(pd)


def _days_overdue(
    pd: PhaseData,
    today: date,
    *,
    row: Optional[FunctionRow] = None,
    phase_name: Optional[str] = None,
    phase_order: Optional[list[str]] = None,
) -> int:
    if not _is_overdue(
        pd, today, row=row, phase_name=phase_name, phase_order=phase_order,
    ):
        return 0
    return (today - pd.end_date).days


def _row_to_dict(
    row: FunctionRow,
    phase_name: Optional[str] = None,
    today: Optional[date] = None,
    phase_order: Optional[list[str]] = None,
) -> dict:
    """
    Build dict chuẩn cho drill-down output.
    Nếu phase_name → thông tin của phase đó.
    Nếu không → thông tin phase active nhất (ưu tiên In-progress > Assigned > Open).
    """
    today = today or date.today()
    meta = row.meta
    order = phase_order or list(row.phases.keys())

    if phase_name:
        pd = row.phases.get(phase_name, PhaseData())
        active_phase = phase_name
    else:
        # Tìm phase "active" nhất
        priority_order = ["In-progress", "Assigned", "Resolved", "Open", "Pending", "Closed", "Cancelled"]
        pd = PhaseData()
        active_phase = ""
        for pname, p in row.phases.items():
            if p.status:
                pd = p
                active_phase = pname
                break
        for prio_status in priority_order:
            for pname, p in row.phases.items():
                if p.status == prio_status:
                    pd = p
                    active_phase = pname
                    break
            if pd.status == prio_status:
                break

    from analyzer.rlog_weekly import _row_rlog_id

    return {
        "ma_cn": meta.get("ma_cn", ""),
        "ten_cn": meta.get("ten_cn", ""),
        "rlog_id": _row_rlog_id(row) or "",
        "module": meta.get("module", ""),
        "quy_trinh": meta.get("quy_trinh", ""),
        "priority": meta.get("priority", ""),
        "complexity": meta.get("complexity", ""),
        "fit_gap": meta.get("fit_gap", ""),
        "giai_doan": meta.get("giai_doan", ""),
        "phase": active_phase,
        "status": pd.status or "",
        "pics": pd.pics,
        "start_date": pd.start_date.isoformat() if pd.start_date else "",
        "end_date": pd.end_date.isoformat() if pd.end_date else "",
        "days_overdue": _days_overdue(
            pd, today, row=row, phase_name=active_phase or None, phase_order=order,
        ),
        "is_overdue": _is_overdue(
            pd, today, row=row, phase_name=active_phase or None, phase_order=order,
        ),
        "estimate_mh": pd.estimate_mh,
    }


# ==========================================================================
# Chart-specific filters
# ==========================================================================

def _filter_phase_matrix(data: ParsedData, filters: dict, today: date) -> list[dict]:
    """Filter cho matrix Phase × (Module|Quy trình). Bắt buộc phase; module
    HOẶC process (b9: bổ sung process — matrix nhóm theo quy trình khi
    user toggle 'Nhóm theo Quy trình').
    """
    module = filters.get("module", "")
    process = filters.get("process", "")
    phase = filters.get("phase", "")
    result = []
    for row in data.rows:
        if module and row.meta.get("module") != module:
            continue
        if process and row.meta.get("quy_trinh") != process:
            continue
        pd = row.phases.get(phase)
        if pd is None:
            continue
        result.append(_row_to_dict(row, phase_name=phase, today=today))
    return result


def _filter_phase_stacked(data: ParsedData, filters: dict, today: date) -> list[dict]:
    """Filter theo phase + status. Show phase đó."""
    phase = filters.get("phase", "")
    status = filters.get("status", "")
    result = []
    for row in data.rows:
        pd = row.phases.get(phase)
        if pd is None:
            continue
        # "" hoặc "Chưa có" → status None hoặc rỗng
        pd_status = pd.status or ""
        if pd_status != status:
            continue
        result.append(_row_to_dict(row, phase_name=phase, today=today))
    return result


def _filter_pic_workload(data: ParsedData, filters: dict, today: date) -> list[dict]:
    """
    Filter theo PIC + optional status.
    Nếu status = 'overdue' → chỉ những phase overdue của PIC.
    """
    pic = filters.get("pic", "")
    status = filters.get("status", "")  # "Closed" | "In-progress" | "Assigned" | "overdue" | ""
    result = []
    for row in data.rows:
        for phase_name, pd in row.phases.items():
            if pic not in pd.pics:
                continue
            if status == "overdue":
                if not _is_overdue(
                    pd, today,
                    row=row, phase_name=phase_name,
                    phase_order=data.all_phases,
                ):
                    continue
            elif status:
                if pd.status != status:
                    continue
            result.append(_row_to_dict(
                row, phase_name=phase_name, today=today,
                phase_order=data.all_phases,
            ))
    return result


def _filter_priority(data: ParsedData, filters: dict, today: date) -> list[dict]:
    priority = filters.get("priority", "")
    return [
        _row_to_dict(row, today=today)
        for row in data.rows
        if row.meta.get("priority") == priority
    ]


def _filter_complexity(data: ParsedData, filters: dict, today: date) -> list[dict]:
    complexity = filters.get("complexity", "")
    return [
        _row_to_dict(row, today=today)
        for row in data.rows
        if row.meta.get("complexity") == complexity
    ]


def _filter_fit_gap(data: ParsedData, filters: dict, today: date) -> list[dict]:
    module = filters.get("module", "")
    fit_gap = filters.get("fit_gap", "")
    result = []
    for row in data.rows:
        if module and row.meta.get("module") != module:
            continue
        if row.meta.get("fit_gap") != fit_gap:
            continue
        result.append(_row_to_dict(row, today=today))
    return result


def _filter_giai_doan(data: ParsedData, filters: dict, today: date) -> list[dict]:
    """Filter theo giai_doan + optional phase."""
    gd = filters.get("giai_doan", "")
    phase = filters.get("phase", "")
    result = []
    for row in data.rows:
        if str(row.meta.get("giai_doan", "")) != str(gd):
            continue
        result.append(_row_to_dict(row, phase_name=phase or None, today=today))
    return result


def _filter_module(data: ParsedData, filters: dict, today: date) -> list[dict]:
    module = filters.get("module", "")
    return [
        _row_to_dict(row, today=today)
        for row in data.rows
        if row.meta.get("module") == module
    ]


def _filter_process(data: ParsedData, filters: dict, today: date) -> list[dict]:
    process = filters.get("process", "")
    return [
        _row_to_dict(row, today=today)
        for row in data.rows
        if row.meta.get("quy_trinh") == process
    ]


def _phases_for_task_type(data: ParsedData, task_type: str) -> list[str]:
    """Map label công việc → danh sách phase name (theo PhaseGroup.task_type)."""
    return [pg.name for pg in data.phase_groups if pg.task_type == task_type]


def _filter_task_type(data: ParsedData, filters: dict, today: date) -> list[dict]:
    """
    Filter theo nhóm công việc (Phân tích / Lập trình / …).
    Optional module. Trả 1 row/phase thuộc các phase của task_type.
    """
    task_type = filters.get("task_type", "")
    module = filters.get("module", "")
    phases = _phases_for_task_type(data, task_type)
    if not phases:
        return []
    result = []
    for row in data.rows:
        if module and row.meta.get("module") != module:
            continue
        for phase_name in phases:
            pd = row.phases.get(phase_name)
            if pd is None:
                continue
            # Chỉ hiện phase có status (cùng logic progress_by_task_type)
            if not pd.status:
                continue
            result.append(_row_to_dict(row, phase_name=phase_name, today=today))
    return result


def _filter_effort_heatmap(data: ParsedData, filters: dict, today: date) -> list[dict]:
    """Rows của module có estimate_mh > 0 ở phase đó."""
    module = filters.get("module", "")
    phase = filters.get("phase", "")
    result = []
    for row in data.rows:
        if row.meta.get("module") != module:
            continue
        pd = row.phases.get(phase)
        if pd is None or pd.estimate_mh is None or pd.estimate_mh <= 0:
            continue
        result.append(_row_to_dict(row, phase_name=phase, today=today))
    return result


def _filter_effort_pic(data: ParsedData, filters: dict, today: date) -> list[dict]:
    """
    Phase của PIC đó.
    status = closed | remaining | all (mặc định all).
    """
    pic = filters.get("pic", "")
    status = (filters.get("status") or "all").lower()
    result = []
    for row in data.rows:
        for phase_name, pd in row.phases.items():
            if pic not in pd.pics:
                continue
            if pd.estimate_mh is None or pd.estimate_mh <= 0:
                continue
            st = pd.status or ""
            if status == "closed":
                if st != "Closed":
                    continue
            elif status == "remaining":
                if st in _DONE_STATUSES:
                    continue
            # all → không lọc status
            result.append(_row_to_dict(row, phase_name=phase_name, today=today))
    return result


def _dedupe_by_ma_cn(items: list[dict]) -> list[dict]:
    """Gom nhiều phase-record của cùng 1 function → 1 row.

    Dùng cho drill 'overdue' và 'unassigned' — card summary đếm distinct
    function nên drill phải khớp count. Trước đây drill trả phase-records
    khiến card=47 nhưng modal='85' → user confuse.

    Nguyên tắc aggregate cho 1 nhóm cùng ma_cn:
      - ``phase``: join tên các phase (thứ tự lần lượt xuất hiện, VD
        "Analysis, UAT"). Nếu chỉ 1 phase → giữ nguyên.
      - ``status``: join unique các status (đã sort). Nếu chỉ 1 status →
        giữ nguyên (statusBadge render đúng màu).
      - ``pics``: union unique tất cả pics của các phase.
      - ``start_date``: sớm nhất.
      - ``end_date``: sớm nhất (phase overdue nặng nhất).
      - ``days_overdue``: max.
      - ``is_overdue``: True nếu bất kỳ phase nào overdue.
      - ``estimate_mh``: tổng (nếu số, null nếu không có phase nào có MH).
      - ``phase_count``: số phase gộp (để user biết row này gộp mấy phase).
    Các meta field (module, ten_cn, priority, complexity, fit_gap,
    giai_doan, quy_trinh) giữ nguyên vì cùng function → giống nhau.
    Row có ma_cn rỗng vẫn giữ nguyên (không gom được).
    """
    by_code: dict[str, dict] = {}
    order: list[str] = []
    for it in items:
        code = it.get("ma_cn", "") or ""
        # Fallback: nếu ma_cn rỗng, mỗi item tự thành 1 row (không thể gom).
        key = code if code else f"__anon_{len(order)}"
        if key not in by_code:
            by_code[key] = {
                # Copy meta + placeholder cho aggregate field
                **it,
                "_phase_list": [],
                "_status_set": set(),
                "_pics_set": set(),
                "_start_dates": [],
                "_end_dates": [],
                "_days": [],
                "_est": [],
                "_extras": {},  # giữ các extra field VD wait_days, risk_score
                "is_overdue": bool(it.get("is_overdue")),
            }
            order.append(key)
        agg = by_code[key]
        ph = it.get("phase") or ""
        if ph and ph not in agg["_phase_list"]:
            agg["_phase_list"].append(ph)
        st = it.get("status") or ""
        if st:
            agg["_status_set"].add(st)
        for p in it.get("pics") or []:
            if p:
                agg["_pics_set"].add(p)
        if it.get("start_date"):
            agg["_start_dates"].append(it["start_date"])
        if it.get("end_date"):
            agg["_end_dates"].append(it["end_date"])
        if it.get("days_overdue"):
            try:
                agg["_days"].append(int(it["days_overdue"]))
            except (TypeError, ValueError):
                pass
        if it.get("is_overdue"):
            agg["is_overdue"] = True
        est = it.get("estimate_mh")
        if isinstance(est, (int, float)):
            agg["_est"].append(est)

    result = []
    for key in order:
        agg = by_code[key]
        phase_list = agg.pop("_phase_list", [])
        status_set = sorted(agg.pop("_status_set", set()))
        pics_set = sorted(agg.pop("_pics_set", set()))
        start_dates = sorted([d for d in agg.pop("_start_dates", []) if d])
        end_dates = sorted([d for d in agg.pop("_end_dates", []) if d])
        days = agg.pop("_days", [])
        est = agg.pop("_est", [])
        agg.pop("_extras", None)
        agg["phase"] = ", ".join(phase_list) if phase_list else agg.get("phase", "")
        agg["status"] = ", ".join(status_set) if status_set else agg.get("status", "")
        agg["pics"] = pics_set
        agg["start_date"] = start_dates[0] if start_dates else ""
        agg["end_date"] = end_dates[0] if end_dates else ""
        agg["days_overdue"] = max(days) if days else 0
        agg["estimate_mh"] = sum(est) if est else None
        agg["phase_count"] = len(phase_list)
        result.append(agg)
    return result


def _filter_overdue(data: ParsedData, filters: dict, today: date) -> list[dict]:
    """Tất cả overdue → dedupe theo ma_cn: 1 row / function.

    Trước đây trả về phase-records (VD 1 function trễ ở 2 phase = 2 row).
    Giờ dedupe cho khớp card summary (đếm distinct function). Cột phase
    hiện dạng "Analysis, UAT" — user vẫn thấy được danh sách phase trễ.
    Hỗ trợ filter module/phase/pic tùy chọn (chỉ hạn chế phase-records
    trước khi gom).
    """
    module = filters.get("module", "")
    phase_f = filters.get("phase", "")
    pic = filters.get("pic", "")
    records = []
    for row in data.rows:
        if module and row.meta.get("module") != module:
            continue
        for phase_name, pd in row.phases.items():
            if phase_f and phase_name != phase_f:
                continue
            if pic and pic not in pd.pics:
                continue
            if not _is_overdue(
                pd, today,
                row=row, phase_name=phase_name,
                phase_order=data.all_phases,
            ):
                continue
            records.append(_row_to_dict(
                row, phase_name=phase_name, today=today,
                phase_order=data.all_phases,
            ))
    # Gom theo ma_cn (case-sensitive): 1 function trễ nhiều phase → 1 row.
    result = _dedupe_by_ma_cn(records)
    result.sort(key=lambda x: x["days_overdue"], reverse=True)
    return result


def _filter_unassigned(data: ParsedData, filters: dict, today: date) -> list[dict]:
    """Phase thiếu PIC khi đã tới lượt → dedupe theo ma_cn.

    Đồng bộ ``analyzer.unassigned.is_unassigned_phase`` (in-scope + predecessor
    Closed + Start đã đến). Card summary và drill cùng rule → count khớp.
    """
    module = filters.get("module", "")
    phase_f = filters.get("phase", "")
    phase_order = data.all_phases
    records = []
    for row in data.rows:
        if module and row.meta.get("module") != module:
            continue
        for phase_name, pd in row.phases.items():
            if phase_f and phase_name != phase_f:
                continue
            if not is_unassigned_phase(
                row, phase_name, pd, phase_order, today,
            ):
                continue
            records.append(_row_to_dict(
                row, phase_name=phase_name, today=today,
                phase_order=phase_order,
            ))
    result = _dedupe_by_ma_cn(records)
    result.sort(key=lambda x: (0 if x["is_overdue"] else 1, -x["days_overdue"]))
    return result


def _filter_stalled(data: ParsedData, filters: dict, today: date) -> list[dict]:
    """
    Function bị kẹt: phase trước Closed, phase sau None/Open, End phase chờ
    đã quá (end < today). Không End → không stalled.
    Bỏ qua function đã xong toàn trình (phase cuối Closed / all Closed|Cancelled).
    Optional phase = completed_phase hoặc waiting_phase.
    """
    from analyzer.gantt_calendar import _is_outlier_date
    from analyzer.stalled import is_fully_closed, is_stalled_transition

    phase_f = filters.get("phase", "")
    module = filters.get("module", "")
    phase_names = [pg.name for pg in data.phase_groups]
    result = []
    for row in data.rows:
        if module and row.meta.get("module") != module:
            continue
        if is_fully_closed(row, phase_names):
            continue
        for i in range(len(phase_names) - 1):
            curr = phase_names[i]
            nxt = phase_names[i + 1]
            if phase_f and phase_f not in (curr, nxt):
                continue
            curr_pd = row.phases.get(curr)
            next_pd = row.phases.get(nxt)
            if not is_stalled_transition(curr_pd, next_pd, today):
                continue
            # Hiện phase đang chờ (waiting)
            item = _row_to_dict(row, phase_name=nxt, today=today)
            item["completed_phase"] = curr
            item["waiting_phase"] = nxt
            item["completed_date"] = (
                curr_pd.end_date.isoformat() if curr_pd and curr_pd.end_date else ""
            )
            # Bỏ date outlier (VD 1936) khi tính wait_days — cùng Gantt
            wait_days = 0
            if curr_pd and curr_pd.end_date and not _is_outlier_date(curr_pd.end_date, today):
                wait_days = (today - curr_pd.end_date).days
            item["wait_days"] = wait_days
            result.append(item)
    result.sort(key=lambda x: x.get("wait_days", 0), reverse=True)
    return result


def _risk_level_match(score: int, level: str) -> bool:
    """level: high|medium|low|all|'' ('' = high)."""
    lv = (level or "high").lower()
    if lv in ("all", "*"):
        return True
    if lv in ("high", "high_risk"):
        return score >= 50
    if lv == "medium":
        return 30 <= score < 50
    if lv == "low":
        return score < 30
    return score >= 50


def _filter_risk(data: ParsedData, filters: dict, today: date) -> list[dict]:
    """Filter theo risk score band; optional module / ma_cn."""
    from analyzer.risk_scorer import compute_all_risk_scores

    level = filters.get("level", "")
    module = filters.get("module", "")
    ma_cn = filters.get("ma_cn", "")
    scores = compute_all_risk_scores(data, today)
    by_code = {r["ma_cn"]: r for r in scores}
    result = []
    for row in data.rows:
        code = row.meta.get("ma_cn", "")
        if ma_cn and code != ma_cn:
            continue
        if module and row.meta.get("module") != module:
            continue
        info = by_code.get(code) or {}
        score = int(info.get("risk_score") or 0)
        if not _risk_level_match(score, level):
            continue
        item = _row_to_dict(row, today=today)
        item["risk_score"] = score
        item["risk_factors"] = list(info.get("risk_factors") or [])
        result.append(item)
    result.sort(key=lambda x: x.get("risk_score", 0), reverse=True)
    return result


def _filter_duration(data: ParsedData, filters: dict, today: date) -> list[dict]:
    """
    Duration analysis items (planned hoặc elapsed).
    Optional phase / module. Threshold mặc định 3 ngày (khớp engine).
    """
    phase_f = filters.get("phase", "")
    module = filters.get("module", "")
    threshold = 3
    try:
        if filters.get("threshold"):
            threshold = int(filters["threshold"])
    except (TypeError, ValueError):
        threshold = 3

    result = []
    for row in data.rows:
        if module and row.meta.get("module") != module:
            continue
        for phase_name, pd in row.phases.items():
            if phase_f and phase_name != phase_f:
                continue
            duration = None
            if pd.start_date and pd.end_date:
                diff = (pd.end_date - pd.start_date).days
                if diff >= 0:
                    duration = diff
            elif pd.start_date and not pd.end_date and pd.status == "In-progress":
                diff = (today - pd.start_date).days
                if diff >= 0:
                    duration = diff
            if duration is None:
                continue
            # Khớp engine: chỉ giữ chưa Closed/Cancelled và > threshold
            if duration <= threshold or (pd.status in _DONE_STATUSES):
                continue
            item = _row_to_dict(row, phase_name=phase_name, today=today)
            item["duration_days"] = duration
            result.append(item)
    result.sort(key=lambda x: x.get("duration_days", 0), reverse=True)
    return result


def _filter_timeline(data: ParsedData, filters: dict, today: date) -> list[dict]:
    """Functions trong module (hoặc 1 function theo ma_cn)."""
    module = filters.get("module", "")
    ma_cn = filters.get("ma_cn", "")
    result = []
    for row in data.rows:
        if module and row.meta.get("module") != module:
            continue
        if ma_cn and row.meta.get("ma_cn") != ma_cn:
            continue
        result.append(_row_to_dict(row, today=today))
    return result


# ==========================================================================
# Registry — dispatch table
# ==========================================================================

_FILTERS: dict[str, Callable[[ParsedData, dict, date], list[dict]]] = {
    "phase_matrix":  _filter_phase_matrix,
    "phase_stacked": _filter_phase_stacked,
    "pic_workload":  _filter_pic_workload,
    "priority":      _filter_priority,
    "complexity":    _filter_complexity,
    "fit_gap":       _filter_fit_gap,
    "giai_doan":     _filter_giai_doan,
    "module":        _filter_module,
    "process":       _filter_process,
    "task_type":     _filter_task_type,
    "effort_heatmap": _filter_effort_heatmap,
    "effort_pic":    _filter_effort_pic,
    "overdue":       _filter_overdue,
    "unassigned":    _filter_unassigned,
    "stalled":       _filter_stalled,
    "risk":          _filter_risk,
    "duration":      _filter_duration,
    "timeline":      _filter_timeline,
}


SUPPORTED_CHARTS = tuple(_FILTERS.keys())


def drill_down(
    data: ParsedData,
    chart: str,
    filters: dict[str, Any],
    today: Optional[date] = None,
) -> list[dict]:
    """
    Entry point: return list function chi tiết cho 1 chart cụ thể.
    Raises ValueError nếu chart không hỗ trợ.
    """
    if chart not in _FILTERS:
        raise ValueError(f"Chart không hỗ trợ drill-down: {chart}. Supported: {SUPPORTED_CHARTS}")
    fn = _FILTERS[chart]
    today = today or date.today()
    return fn(data, filters, today)


def build_title(chart: str, filters: dict) -> str:
    """Sinh tiêu đề mặc định cho modal/export dựa vào chart + filter."""
    if chart == "phase_matrix":
        key = filters.get("module") or filters.get("process", "")
        return f"{key} × {filters.get('phase', '')}"
    if chart == "phase_stacked":
        return f"Phase {filters.get('phase', '')} — Status: {filters.get('status', '')}"
    if chart == "pic_workload":
        s = filters.get("status", "")
        label = f"PIC {filters.get('pic', '')}"
        if s:
            label += f" — {s if s != 'overdue' else 'Overdue'}"
        return label
    if chart == "priority":
        return f"Priority: {filters.get('priority', '')}"
    if chart == "complexity":
        return f"Complexity: {filters.get('complexity', '')}"
    if chart == "fit_gap":
        m = filters.get("module", "")
        return f"FIT/GAP: {filters.get('fit_gap', '')}" + (f" — Module {m}" if m else "")
    if chart == "giai_doan":
        gd = filters.get("giai_doan", "")
        p = filters.get("phase", "")
        return f"Giai đoạn {gd}" + (f" — Phase {p}" if p else "")
    if chart == "module":
        return f"Module: {filters.get('module', '')}"
    if chart == "process":
        return f"Quy trình: {filters.get('process', '')}"
    if chart == "task_type":
        tt = filters.get("task_type", "")
        m = filters.get("module", "")
        return f"Công việc: {tt}" + (f" — Module {m}" if m else "")
    if chart == "effort_heatmap":
        return f"Effort MH: {filters.get('module', '')} × {filters.get('phase', '')}"
    if chart == "effort_pic":
        s = filters.get("status", "all")
        label = f"Effort PIC: {filters.get('pic', '')}"
        if s and s != "all":
            label += f" — {'Closed' if s == 'closed' else 'Còn lại'}"
        return label
    if chart == "overdue":
        parts = ["Task trễ deadline"]
        if filters.get("module"):
            parts.append(f"Module {filters['module']}")
        if filters.get("phase"):
            parts.append(f"Phase {filters['phase']}")
        if filters.get("pic"):
            parts.append(f"PIC {filters['pic']}")
        return " — ".join(parts)
    if chart == "unassigned":
        return "Task chưa có PIC" + (
            f" — Phase {filters['phase']}" if filters.get("phase") else ""
        )
    if chart == "stalled":
        return "Task bị Đình trệ" + (
            f" — Phase {filters['phase']}" if filters.get("phase") else ""
        )
    if chart == "risk":
        level = filters.get("level", "high") or "high"
        labels = {
            "high": "Rủi ro cao (≥50)",
            "high_risk": "Rủi ro cao (≥50)",
            "medium": "Rủi ro trung bình (30–49)",
            "low": "Rủi ro thấp (<30)",
            "all": "Tất cả Risk Score",
        }
        return labels.get(level, f"Risk: {level}")
    if chart == "duration":
        return "Duration bất thường" + (
            f" — Phase {filters['phase']}" if filters.get("phase") else ""
        )
    if chart == "timeline":
        m = filters.get("module", "")
        code = filters.get("ma_cn", "")
        if code:
            return f"Timeline: {code}" + (f" ({m})" if m else "")
        return f"Timeline: Module {m}" if m else "Timeline"
    return chart
