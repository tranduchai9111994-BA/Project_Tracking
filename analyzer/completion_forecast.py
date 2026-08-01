"""
Predictive completion date — dự báo ngày xong từ velocity snapshot history.

Công thức (linear, không ML):
  remaining = số phase-record chưa Closed/Cancelled (có status hoặc có date)
  velocity  = trung bình Closed/tuần trong 4 tuần gần nhất
              (reuse compute_burndown_velocity)
  weeks_needed = remaining / velocity
  forecast_date = today + ceil(weeks_needed) tuần (làm tròn lên ngày)

Edge cases (message tiếng Việt):
  - remaining == 0 → đã xong
  - không có lịch sử Closed → không đủ dữ liệu
  - velocity == 0 → đứng yên, không dự báo được
"""
from __future__ import annotations

import math
from datetime import date, timedelta
from typing import Any, Optional

from parser.excel_parser import ParsedData

from analyzer.advanced_metrics import compute_burndown_velocity

DONE = frozenset({"Closed", "Cancelled"})


def count_remaining_phases(data: ParsedData) -> dict[str, int]:
    """Đếm phase còn lại / đã xong / tổng (bỏ Cancelled + blank hoàn toàn)."""
    remaining = 0
    closed = 0
    total = 0
    for row in data.rows:
        for _ph, pd in row.phases.items():
            st = (pd.status or "").strip()
            if st == "Cancelled":
                continue
            if not st and not pd.end_date and not pd.start_date:
                continue
            total += 1
            if st == "Closed":
                closed += 1
            else:
                remaining += 1
    return {
        "remaining": remaining,
        "closed": closed,
        "total": total,
    }


def compute_completion_forecast(
    data: ParsedData,
    today: Optional[date] = None,
    phase: Optional[str] = None,
) -> dict[str, Any]:
    """
    Dự báo ngày hoàn thành từ velocity 4 tuần.

    Returns dict JSON-serializable với:
      status: done | ok | no_history | zero_velocity
      forecast_date, weeks_needed, velocity_4w, remaining, …
      confidence: low|medium|high (band đơn giản theo số tuần lịch sử)
      message: tiếng Việt cho UI
    """
    today = today or date.today()
    counts = count_remaining_phases(data)
    remaining = counts["remaining"]
    closed = counts["closed"]
    total = counts["total"]

    burndown = compute_burndown_velocity(data, today=today, phase=phase)
    velocity = float(burndown.get("velocity_4w") or 0)
    weeks_hist = len(burndown.get("weeks") or [])

    base: dict[str, Any] = {
        "remaining": remaining,
        "closed": closed,
        "total": total,
        "velocity_4w": velocity,
        "weeks_history": weeks_hist,
        "burndown": {
            "weeks": burndown.get("weeks") or [],
            "closed_per_week": burndown.get("closed_per_week") or [],
        },
        "scope_phase": (phase or "").strip(),
        "forecast_date": None,
        "weeks_needed": None,
        "confidence": "low",
        "confidence_band": None,
        "status": "ok",
        "message": "",
    }

    if total == 0:
        base["status"] = "no_history"
        base["message"] = "Chưa có phase nào để dự báo."
        return base

    if remaining == 0:
        base["status"] = "done"
        base["forecast_date"] = today.isoformat()
        base["weeks_needed"] = 0
        base["confidence"] = "high"
        base["message"] = "Đã Closed hết — dự án hoàn thành (theo phase đang theo dõi)."
        return base

    if weeks_hist == 0 or (burndown.get("total_closed_events") or 0) == 0:
        base["status"] = "no_history"
        base["message"] = (
            f"Còn {remaining} phase chưa xong nhưng chưa có lịch sử Closed "
            "theo tuần — upload thêm snapshot / cập nhật End khi Closed để đo velocity."
        )
        return base

    if velocity <= 0:
        base["status"] = "zero_velocity"
        base["message"] = (
            f"Còn {remaining} phase, nhưng velocity 4 tuần = 0 "
            "(không Closed gần đây) — không dự báo được ngày xong."
        )
        return base

    weeks_needed = remaining / velocity
    weeks_ceil = max(1, int(math.ceil(weeks_needed))) if weeks_needed > 0 else 0
    forecast = today + timedelta(days=weeks_ceil * 7)

    # 3 kịch bản velocity từ 4 tuần gần nhất (reuse burndown)
    closed_pw = list(burndown.get("closed_per_week") or [])
    last4 = closed_pw[-4:] if closed_pw else []
    v_opt = float(max(last4)) if last4 else velocity
    v_pes_candidates = [c for c in last4 if c > 0]
    v_pes = float(min(v_pes_candidates)) if v_pes_candidates else (
        float(min(last4)) if last4 else velocity
    )
    # Pessimistic không được = 0 nếu còn remaining (tránh chia 0) — fallback nhỏ
    if v_opt <= 0:
        v_opt = velocity
    if v_pes <= 0:
        v_pes = max(velocity * 0.5, 0.1)

    def _scenario(label: str, vel: float) -> dict[str, Any]:
        wn = remaining / vel if vel > 0 else None
        if wn is None:
            return {
                "label": label,
                "velocity": round(vel, 2),
                "weeks_needed": None,
                "forecast_date": None,
            }
        wceil = max(1, int(math.ceil(wn))) if wn > 0 else 0
        return {
            "label": label,
            "velocity": round(vel, 2),
            "weeks_needed": round(wn, 1),
            "forecast_date": (today + timedelta(days=wceil * 7)).isoformat(),
        }

    scenarios = {
        "optimistic": _scenario("Lạc quan (best 4w)", v_opt),
        "most_likely": _scenario("Khả năng cao (avg 4w)", velocity),
        "pessimistic": _scenario("Bi quan (worst 4w)", v_pes),
    }
    opt_date = scenarios["optimistic"]["forecast_date"]
    pes_date = scenarios["pessimistic"]["forecast_date"]
    likely_date = scenarios["most_likely"]["forecast_date"]

    # Confidence qualitative + band = pessimistic → optimistic
    if weeks_hist >= 8 and velocity >= 2:
        conf = "high"
        pad = 1
    elif weeks_hist >= 4:
        conf = "medium"
        pad = 1
    else:
        conf = "low"
        pad = 2

    base.update({
        "status": "ok",
        "weeks_needed": round(weeks_needed, 1),
        "forecast_date": forecast.isoformat(),
        "confidence": conf,
        "scenarios": scenarios,
        "confidence_band": {
            # low = sớm hơn (optimistic), high = muộn hơn (pessimistic)
            "low": opt_date or (today + timedelta(days=max(0, weeks_ceil - pad) * 7)).isoformat(),
            "mid": likely_date or forecast.isoformat(),
            "high": pes_date or (today + timedelta(days=(weeks_ceil + pad) * 7)).isoformat(),
            "pad_weeks": pad,
            "optimistic": opt_date,
            "most_likely": likely_date,
            "pessimistic": pes_date,
        },
        "message": (
            f"Ước tính xong khoảng {forecast.strftime('%d/%m/%Y')} "
            f"(còn {remaining} phase ÷ {velocity:g} Closed/tuần ≈ {weeks_needed:.1f} tuần)"
            + (
                f" · band {opt_date} → {pes_date}"
                if opt_date and pes_date else ""
            )
            + "."
        ),
    })
    return base
