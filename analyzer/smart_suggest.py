"""
A7 — Smart Suggest: gợi ý dashboard nên bật thêm cho giai đoạn hiện tại.

Đọc `summary` đã tính sẵn (không tính lại từ đầu) để quyết định:
  - Theo metrics hiện tại (overdue nhiều, risk cao, DQ lỗi nhiều) → gợi ý ngay.
  - Theo giai đoạn dự án (overall_progress_pct) → gợi ý dashboard phù hợp
    đầu / giữa / cuối dự án.

section_id trả về khớp với id các <section> hiện có trên dashboard (đã được
gom vào hub trong sidebar_hubs.js) — FE dùng `scrollToSection(section_id)`
để mở hub + tab tương ứng, không cần cơ chế visible_sections riêng.
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Optional


def _count_functions_ending_within(data: Any, today: date, days: int = 14) -> int:
    """C1 — số function unique có ≥1 phase chưa Closed/Cancelled với End rơi
    trong [today, today+days]."""
    if data is None:
        return 0
    end_limit = today + timedelta(days=days)
    ma_cns: set[str] = set()
    for row in getattr(data, "rows", []):
        for pd in row.phases.values():
            status = (pd.status or "").strip().lower()
            if status in ("closed", "cancelled"):
                continue
            if pd.end_date and today <= pd.end_date <= end_limit:
                ma_cns.add(row.meta.get("ma_cn") or "")
                break
    ma_cns.discard("")
    return len(ma_cns)


def compute_smart_suggestions(
    state: dict[str, Any],
    *,
    overdue_history: Optional[list[int]] = None,
    today: Optional[date] = None,
) -> dict[str, Any]:
    """
    overdue_history: total_overdue của các snapshot gần nhất, sắp cũ → mới
    (VD 3 tuần liên tiếp) — dùng cho C3. None/rỗng → bỏ qua gợi ý trend.
    """
    today = today or date.today()
    metrics = state.get("metrics") or {}
    summary = metrics.get("summary") or {}
    progress = float(summary.get("overall_progress_pct") or 0)

    suggestions: list[dict[str, Any]] = []
    seen_sections: set[str] = set()

    def _add(section_id: str, title: str, reason: str, priority: str) -> None:
        if section_id in seen_sections:
            return
        seen_sections.add(section_id)
        suggestions.append({"section_id": section_id, "title": title, "reason": reason, "priority": priority})

    # --- Gợi ý theo metrics hiện tại ---
    total_overdue = int(summary.get("total_overdue") or 0)
    if total_overdue > 10:
        _add("section-aging-wip", "WIP tồn đọng",
             f"{total_overdue} function trễ — bật WIP để xem đầu việc tồn đọng lâu nhất và ưu tiên xử lý.", "high")

    high_risk_count = int(summary.get("high_risk_count") or 0)
    if high_risk_count > 20:
        _add("section-risk", "Risk Score chi tiết",
             f"{high_risk_count} function rủi ro cao — bật Risk Score để xem yếu tố gây rủi ro.", "high")

    dq_high_count = int(summary.get("dq_high_count") or 0)
    if dq_high_count > 5:
        _add("section-dataquality", "Chất lượng dữ liệu",
             f"{dq_high_count} lỗi data nghiêm trọng — bật DQ để làm sạch FL.", "high")

    # --- C1 — deadline sắp tới (2 tuần) ---
    upcoming_2w = _count_functions_ending_within(state.get("data"), today, days=14)
    if upcoming_2w > 10:
        _add("section-pic-upcoming", "PIC tuần tới",
             f"{upcoming_2w} function đến hạn trong 2 tuần — kiểm tra phân bổ PIC.", "high")

    # --- C2 — data quality nhiều lỗi → gợi ý re-import FL ---
    # dq_affected_rows = số FUNCTION có ≥1 issue (không phải số issue — 1 function
    # có thể có nhiều issue nên total_issues/dq_high_count có thể > total_functions).
    total_functions = int(summary.get("total_functions") or 0)
    dq_affected_rows = int(summary.get("dq_affected_rows") or 0)
    if total_functions > 0 and dq_affected_rows > 0:
        dq_pct = min(dq_affected_rows, total_functions) / total_functions * 100
        if dq_pct > 5:
            _add("section-function-diff", "Function Diff + FL Re-import",
                 f"{dq_pct:.0f}% function có lỗi data — xuất FL chỉnh sửa rồi import lại.", "medium")

    # --- C3 — overdue tăng liên tục nhiều tuần ---
    if overdue_history and len(overdue_history) >= 3 and all(
        overdue_history[i] < overdue_history[i + 1] for i in range(len(overdue_history) - 1)
    ):
        _add("section-burndown", "Burndown + Velocity",
             f"Overdue tăng {len(overdue_history)} tuần liên tiếp — xem velocity có đang chậm lại.", "high")

    # --- Gợi ý theo giai đoạn dự án ---
    if progress < 30:
        _add("section-scope-creep", "Theo dõi Scope Creep",
             "Dự án đầu giai đoạn — bật Scope Creep để kiểm soát phát sinh sớm.", "medium")
        _add("section-rlog", "Rlog tuần",
             "Giai đoạn phân tích — theo dõi Rlog coded/plan hàng tuần.", "medium")
    elif progress < 70:
        _add("section-pic-overload", "PIC Overload",
             "Giai đoạn dev/test cao điểm — kiểm tra ai đang quá tải.", "high")
        _add("section-burndown", "Burndown + Velocity",
             f"Tiến độ {progress:.0f}% — theo dõi tốc độ Closed/tuần.", "medium")
        _add("section-baseline", "Baseline SV",
             "So sánh tiến độ thực tế vs kế hoạch gốc.", "medium")
    else:
        _add("section-uat-quality", "UAT Quality",
             f"Tiến độ {progress:.0f}% — sắp UAT/Golive, theo dõi defect/reopen.", "high")
        _add("section-forecast-gantt", "Forecast UAT/Golive",
             "Giai đoạn cuối — xem milestone tháng dự kiến.", "high")
        _add("section-evm", "EVM (SPI/CPI)",
             "Gần kết thúc — đánh giá hiệu suất tổng thể bằng Earned Value.", "medium")
        _add("section-capacity", "Capacity PIC",
             "Kiểm tra công suất còn lại per PIC cho giai đoạn UAT.", "medium")

    suggestions.sort(key=lambda s: 0 if s["priority"] == "high" else 1)

    if progress < 30:
        phase = "early"
    elif progress < 70:
        phase = "mid"
    else:
        phase = "late"

    return {
        "suggestions": suggestions,
        "project_phase": phase,
        "progress_pct": round(progress, 1),
    }
