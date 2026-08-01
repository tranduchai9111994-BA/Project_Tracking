"""
PM Executive Dashboard — 1 trang tổng hợp cho PM/BA Lead.

Gộp: % done, SPI/CPI, top 5 risks, milestone, forecast date, scope creep %.
"""
from __future__ import annotations

from datetime import date
from typing import Any, Optional

from parser.excel_parser import ParsedData


def build_executive_dashboard(
    *,
    data: ParsedData,
    metrics: Optional[dict[str, Any]] = None,
    earned_value: Optional[dict[str, Any]] = None,
    completion_forecast: Optional[dict[str, Any]] = None,
    scope_creep: Optional[dict[str, Any]] = None,
    risk_scores: Optional[list[dict]] = None,
    mitigations: Optional[dict[str, dict]] = None,
    project_name: str = "",
    today: Optional[date] = None,
) -> dict[str, Any]:
    """
    Tổng hợp payload Executive Dashboard (JSON-serializable).
    Caller chịu trách nhiệm compute các khối con (tránh import vòng).
    """
    today = today or date.today()
    metrics = metrics or {}
    summary = metrics.get("summary") or {}

    pct_done = summary.get("overall_progress_pct")
    if pct_done is None:
        # Fallback: Closed last phase / total
        phases = data.all_phases or []
        if phases and data.rows:
            last = phases[-1]
            closed = sum(
                1 for r in data.rows
                if (r.phases.get(last) and (r.phases[last].status or "") == "Closed")
            )
            pct_done = round(closed / len(data.rows) * 100, 1)
        else:
            pct_done = 0.0

    evm_sm = (earned_value or {}).get("summary") or {}
    fc = completion_forecast or {}
    sc = scope_creep or {}
    sc_sm = sc.get("summary") or sc

    # Milestone từ forecast_gantt nếu có trong metrics
    milestones_raw = metrics.get("forecast_milestones") or metrics.get("milestones") or {}
    milestones: list[dict[str, Any]] = []
    if isinstance(milestones_raw, dict):
        for mid, info in milestones_raw.items():
            if not isinstance(info, dict):
                continue
            assess = info.get("assessment") or {}
            milestones.append({
                "id": mid,
                "label": info.get("label") or mid,
                "month": info.get("month"),
                "date": info.get("date") or info.get("end_date"),
                "status": assess.get("level") or info.get("status") or "",
                "text": assess.get("text") or "",
            })
    elif isinstance(milestones_raw, list):
        milestones = list(milestones_raw)

    if not milestones:
        try:
            from analyzer.forecast_gantt import compute_project_forecast
            computed = compute_project_forecast(data, today=today)
            for mid, info in (computed or {}).items():
                assess = info.get("assessment") or {}
                milestones.append({
                    "id": mid,
                    "label": info.get("label") or mid,
                    "month": info.get("month"),
                    "date": info.get("date") or info.get("end_date"),
                    "status": assess.get("level") or "",
                    "text": assess.get("text") or "",
                })
        except Exception:
            pass

    scores = list(risk_scores or metrics.get("risk_scores") or [])
    scores = sorted(scores, key=lambda x: -int(x.get("risk_score") or 0))
    top5 = []
    mit = mitigations or {}
    for r in scores[:5]:
        ma = str(r.get("ma_cn") or "").strip()
        entry = {
            "ma_cn": ma,
            "ten_cn": r.get("ten_cn") or "",
            "module": r.get("module") or "",
            "risk_score": r.get("risk_score") or 0,
            "risk_factors": r.get("risk_factors") or [],
            "mitigation": mit.get(ma) if ma else None,
        }
        top5.append(entry)

    scope_pct = sc_sm.get("creep_rate_pct")
    if scope_pct is None:
        scope_pct = sc_sm.get("cr_pct") or sc_sm.get("scope_creep_pct")
    if scope_pct is None:
        total_f = sc_sm.get("total_functions") or sc_sm.get("total") or summary.get("total_functions")
        cr_n = sc_sm.get("cr_count") or sc_sm.get("cr_functions") or 0
        try:
            scope_pct = round(float(cr_n) / float(total_f) * 100, 1) if total_f else 0.0
        except (TypeError, ValueError, ZeroDivisionError):
            scope_pct = 0.0

    scenarios = fc.get("scenarios") or {}
    band = fc.get("confidence_band") or {}

    return {
        "project_name": project_name,
        "today": today.isoformat(),
        "summary": {
            "pct_done": pct_done,
            "total_functions": summary.get("total_functions") or len(data.rows),
            "total_overdue": summary.get("total_overdue") or 0,
            "unassigned_count": summary.get("unassigned_count") or 0,
            "high_risk_count": summary.get("high_risk_count")
                or sum(1 for r in scores if int(r.get("risk_score") or 0) >= 50),
            "spi": evm_sm.get("spi"),
            "cpi": evm_sm.get("cpi"),
            "spi_label": evm_sm.get("spi_label"),
            "cpi_label": evm_sm.get("cpi_label"),
            "bac": evm_sm.get("bac"),
            "ev": evm_sm.get("ev"),
            "pv": evm_sm.get("pv"),
            "ac": evm_sm.get("ac"),
            "forecast_date": fc.get("forecast_date"),
            "forecast_status": fc.get("status"),
            "forecast_confidence": fc.get("confidence"),
            "forecast_band": {
                "optimistic": band.get("optimistic") or (scenarios.get("optimistic") or {}).get("forecast_date"),
                "most_likely": band.get("most_likely") or (scenarios.get("most_likely") or {}).get("forecast_date"),
                "pessimistic": band.get("pessimistic") or (scenarios.get("pessimistic") or {}).get("forecast_date"),
            },
            "scope_creep_pct": scope_pct,
            "cr_count": sc_sm.get("cr_count") or sc_sm.get("cr_functions") or 0,
        },
        "milestones": milestones,
        "top_risks": top5,
        "messages": [
            m for m in [
                *((earned_value or {}).get("messages") or [])[:2],
                fc.get("message") or "",
            ] if m
        ],
    }
