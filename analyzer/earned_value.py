"""
Earned Value Management (EVM) — EV / PV / AC → SPI / CPI.

Định nghĩa (đơn vị: Man-Hour / MH):

  BAC (Budget at Completion)
    = tổng Estimate MH của mọi phase không Cancelled (ô trống → mặc định 8 MH,
      cùng DEFAULT_MH với forecast_manpower).

  EV (Earned Value) — giá trị đã “kiếm” được
    = Σ (pct_complete(status) × MH_phase)
    pct: Closed=100%, Resolved=90%, In-progress=50%, Assigned=25%,
         Open/Pending/blank=0%. Cancelled bỏ qua.

  PV (Planned Value) — giá trị lẽ ra phải xong theo baseline
    = Σ (pct_lịch_baseline × MH_baseline)
    · End_baseline ≤ today → 100%
    · Start_baseline > today → 0%
    · Start ≤ today < End → tỉ lệ ngày làm việc đã trôi / tổng duration baseline
    · Chỉ End (không Start) → 100% nếu End ≤ today, else 0%
    Không có baseline → PV = None, SPI = N/A (degraded).

  AC (Actual Cost) — proxy khi không có timesheet
    = Σ (số ngày làm việc thực tế × 8 MH/ngày)
    · Closed + có Start+End → Start→End
    · Đã bắt đầu (có Start) chưa Closed → Start→today
    · Không Start → không cộng AC (ghi nhận trong assumptions)
    Giả định: 1 ngày làm = 8 MH; bỏ T7/CN.

  SPI = EV / PV   (None nếu PV thiếu hoặc = 0)
  CPI = EV / AC   (None nếu AC = 0)

Diễn giải nhanh: SPI/CPI < 1 = chậm / vượt effort; > 1 = sớm / tiết kiệm.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta
from typing import Any, Optional

from parser.excel_parser import ParsedData, FunctionRow, PhaseData

from analyzer.forecast_manpower import DEFAULT_MH, MH_PER_MANDAY

# % hoàn thành theo status chuẩn (partial EV khi chưa Closed)
STATUS_PCT: dict[str, float] = {
    "Closed": 1.0,
    "Resolved": 0.9,
    "In-progress": 0.5,
    "Assigned": 0.25,
    "Open": 0.0,
    "Pending": 0.0,
}

_CANCELLED = "Cancelled"


def _parse_iso(d: Any) -> Optional[date]:
    if d is None:
        return None
    if isinstance(d, datetime):
        return d.date()
    if isinstance(d, date):
        return d
    if isinstance(d, str):
        s = d.strip()
        if not s:
            return None
        try:
            return datetime.fromisoformat(s.replace("Z", "")[:19]).date()
        except ValueError:
            pass
        for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%Y/%m/%d", "%d-%m-%Y"):
            try:
                return datetime.strptime(s[:10], fmt).date()
            except ValueError:
                continue
    return None


def _primary_key(row: FunctionRow) -> str:
    code = (row.meta.get("ma_cn") or "").strip().lower()
    if code:
        return f"code:{code}"
    ten = (row.meta.get("ten_cn") or "").strip().lower()
    mod = (row.meta.get("module") or "").strip().lower()
    return f"name:{ten}|{mod}"


def _index_rows(data: ParsedData) -> dict[str, FunctionRow]:
    out: dict[str, FunctionRow] = {}
    for row in data.rows:
        out[_primary_key(row)] = row
    return out


def _working_days(start: date, end: date) -> int:
    """Số ngày làm việc inclusive Start→End (bỏ T7/CN)."""
    if end < start:
        start, end = end, start
    n = 0
    d = start
    while d <= end:
        if d.weekday() < 5:
            n += 1
        d += timedelta(days=1)
    return max(n, 1)


def _phase_budget_mh(pd: PhaseData, default_mh: float = DEFAULT_MH) -> tuple[float, bool]:
    """MH ngân sách phase. Trả (mh, used_default)."""
    if pd.estimate_mh is not None and pd.estimate_mh > 0:
        return float(pd.estimate_mh), False
    return float(default_mh), True


def _status_pct(status: Optional[str]) -> Optional[float]:
    """None = Cancelled (bỏ)."""
    st = (status or "").strip()
    if st == _CANCELLED:
        return None
    if not st:
        return 0.0
    return STATUS_PCT.get(st, 0.0)


def _phase_meaningful(pd: PhaseData) -> bool:
    """Bỏ phase hoàn toàn trống (không status, không date, không MH)."""
    if pd.status or pd.start_date or pd.end_date:
        return True
    if pd.estimate_mh is not None and pd.estimate_mh > 0:
        return True
    return False


def _schedule_pct(
    start: Optional[date],
    end: Optional[date],
    today: date,
) -> Optional[float]:
    """
    % kế hoạch đã 'đến hạn' theo lịch baseline/plan.
    None = không đủ ngày để tính PV cho phase này.
    """
    if end is None and start is None:
        return None
    if end is not None and start is None:
        return 1.0 if end <= today else 0.0
    if start is not None and end is None:
        # Chỉ Start: đã qua ngày bắt đầu → coi 50% (interim yếu)
        return 0.5 if start <= today else 0.0
    assert start is not None and end is not None
    if end <= today:
        return 1.0
    if start > today:
        return 0.0
    total = _working_days(start, end)
    done = _working_days(start, today)
    return min(1.0, max(0.0, done / total))


def _as_date(v: Any) -> Optional[date]:
    if isinstance(v, date) and not isinstance(v, datetime):
        return v
    return _parse_iso(v)


def _actual_cost_mh(pd: PhaseData, today: date) -> tuple[float, str]:
    """
    Proxy AC (MH). Trả (mh, method).
    method rỗng = không tính được.

    Chỉ tính khi status cho thấy đã/đang làm (Closed/Resolved/In-progress/Assigned).
    Open/Pending thường chỉ là kế hoạch trên FL → không cộng AC.
    """
    st = (pd.status or "").strip()
    if st not in ("Closed", "Resolved", "In-progress", "Assigned"):
        return 0.0, ""

    start = _as_date(pd.start_date)
    end = _as_date(pd.end_date)

    if start is None:
        return 0.0, ""

    if st == "Closed" and end is not None:
        days = _working_days(start, end)
        return days * MH_PER_MANDAY, f"Closed {days}d × {MH_PER_MANDAY:g}"
    # Đã/đang làm → Start→today
    days = _working_days(start, today)
    return days * MH_PER_MANDAY, f"Actual {days}d × {MH_PER_MANDAY:g}"


def _safe_ratio(num: float, den: Optional[float]) -> Optional[float]:
    if den is None or den <= 0:
        return None
    return round(num / den, 3)


def compute_earned_value(
    current: ParsedData,
    baseline: Optional[ParsedData] = None,
    baseline_snapshot_id: Optional[str] = None,
    today: Optional[date] = None,
    default_mh: float = DEFAULT_MH,
) -> dict[str, Any]:
    """
    Tính EVM tổng + theo module.

    Returns JSON-serializable dict với summary, modules, assumptions, messages.
    """
    today = today or date.today()
    base_idx = _index_rows(baseline) if baseline is not None else {}
    has_baseline = baseline is not None

    # Accumulators
    bac = ev = ac = 0.0
    pv: Optional[float] = 0.0 if has_baseline else None
    phases_counted = 0
    phases_default_mh = 0
    phases_pv_timed = 0
    phases_pv_skipped = 0
    phases_ac_no_start = 0
    mh_from_estimate = 0.0
    mh_from_default = 0.0

    by_mod: dict[str, dict[str, float]] = defaultdict(
        lambda: {"bac": 0.0, "ev": 0.0, "pv": 0.0, "ac": 0.0, "phases": 0}
    )
    # Khi không baseline, module pv giữ 0 và không tính SPI

    for row in current.rows:
        mod = (row.meta.get("module") or "").strip() or "(trống)"
        key = _primary_key(row)
        base_row = base_idx.get(key) if has_baseline else None

        for phase_name, pd in row.phases.items():
            if not _phase_meaningful(pd):
                continue
            pct = _status_pct(pd.status)
            if pct is None:
                continue  # Cancelled

            mh, used_def = _phase_budget_mh(pd, default_mh)
            phases_counted += 1
            if used_def:
                phases_default_mh += 1
                mh_from_default += mh
            else:
                mh_from_estimate += mh

            bac += mh
            phase_ev = pct * mh
            ev += phase_ev

            cost, ac_method = _actual_cost_mh(pd, today)
            if not ac_method and pct > 0:
                phases_ac_no_start += 1
            ac += cost

            mod_acc = by_mod[mod]
            mod_acc["bac"] += mh
            mod_acc["ev"] += phase_ev
            mod_acc["ac"] += cost
            mod_acc["phases"] += 1

            # PV từ baseline
            if has_baseline and pv is not None:
                base_pd = None
                if base_row is not None:
                    base_pd = base_row.phases.get(phase_name)
                if base_pd is None or _status_pct(base_pd.status) is None:
                    phases_pv_skipped += 1
                    continue
                b_mh, _ = _phase_budget_mh(base_pd, default_mh)
                # Ưu tiên MH baseline; nếu baseline trống MH dùng current mh
                if base_pd.estimate_mh is None or base_pd.estimate_mh <= 0:
                    b_mh = mh
                b_start = _as_date(base_pd.start_date)
                b_end = _as_date(base_pd.end_date)
                sched = _schedule_pct(b_start, b_end, today)
                if sched is None:
                    phases_pv_skipped += 1
                    continue
                phases_pv_timed += 1
                phase_pv = sched * b_mh
                pv += phase_pv
                mod_acc["pv"] += phase_pv

    spi = _safe_ratio(ev, pv)
    cpi = _safe_ratio(ev, ac if ac > 0 else None)

    messages: list[str] = []
    if not has_baseline:
        messages.append(
            "Chưa có baseline — SPI không tính được. "
            "Đánh dấu 1 snapshot làm kế hoạch gốc để có PV."
        )
    elif pv is not None and pv <= 0:
        messages.append(
            "Baseline chưa có Start/End đủ để tính PV (PV=0) — SPI tạm N/A."
        )
    if phases_counted == 0:
        messages.append("Không có phase nào để tính EVM.")
    if ac <= 0 and ev > 0:
        messages.append(
            "AC=0 (thiếu Start date) — CPI tạm N/A. "
            "Proxy AC cần Start để đo duration thực tế."
        )
    if phases_default_mh > 0:
        messages.append(
            f"{phases_default_mh} phase dùng MH mặc định {default_mh:g} "
            "(không có Estimate MH)."
        )

    modules: list[dict[str, Any]] = []
    for mod, a in by_mod.items():
        m_pv = a["pv"] if has_baseline else None
        modules.append({
            "module": mod,
            "phases": int(a["phases"]),
            "bac": round(a["bac"], 2),
            "ev": round(a["ev"], 2),
            "pv": round(m_pv, 2) if m_pv is not None else None,
            "ac": round(a["ac"], 2),
            "spi": _safe_ratio(a["ev"], m_pv if has_baseline else None),
            "cpi": _safe_ratio(a["ev"], a["ac"] if a["ac"] > 0 else None),
        })
    modules.sort(key=lambda r: -abs((r["spi"] or 1) - 1) if r["spi"] is not None else -r["bac"])

    def _index_label(val: Optional[float], kind: str) -> str:
        if val is None:
            return "N/A"
        if val < 0.9:
            return "thấp" if kind == "spi" else "vượt effort"
        if val > 1.1:
            return "tốt" if kind == "spi" else "tiết kiệm"
        return "ổn"

    return {
        "definition": (
            "EV = Σ(pct_status × Estimate MH); "
            "PV = Σ(pct_lịch_baseline × MH); "
            "AC ≈ ngày làm thực tế × 8 MH; "
            "SPI=EV/PV; CPI=EV/AC."
        ),
        "assumptions": [
            f"Estimate MH trống → mặc định {default_mh:g} MH (giống Forecast Manpower).",
            "1 ngày làm việc = 8 MH; bỏ T7/CN khi đếm duration.",
            "Partial EV theo status: Closed 100%, Resolved 90%, "
            "In-progress 50%, Assigned 25%, Open/Pending 0%.",
            "AC là proxy (không có timesheet): Closed/Resolved/In-progress/Assigned "
            "× ngày làm (Start→End hoặc Start→today); Open/Pending không cộng AC.",
            "PV chỉ có khi đã đánh dấu baseline snapshot.",
        ],
        "baseline_snapshot_id": baseline_snapshot_id or None,
        "has_baseline": has_baseline,
        "today": today.isoformat(),
        "summary": {
            "bac": round(bac, 2),
            "ev": round(ev, 2),
            "pv": round(pv, 2) if pv is not None else None,
            "ac": round(ac, 2),
            "spi": spi,
            "cpi": cpi,
            "spi_label": _index_label(spi, "spi"),
            "cpi_label": _index_label(cpi, "cpi"),
            "phases_counted": phases_counted,
            "phases_default_mh": phases_default_mh,
            "phases_pv_timed": phases_pv_timed,
            "phases_pv_skipped": phases_pv_skipped,
            "phases_ac_no_start": phases_ac_no_start,
            "mh_from_estimate": round(mh_from_estimate, 2),
            "mh_from_default": round(mh_from_default, 2),
            "ev_pct_bac": round(ev / bac * 100, 1) if bac > 0 else None,
            "pv_pct_bac": round(pv / bac * 100, 1) if (pv is not None and bac > 0) else None,
        },
        "modules": modules,
        "messages": messages,
        "unit": "MH",
    }


def _week_monday(d: date) -> date:
    return d - timedelta(days=d.weekday())


def compute_evm_scurve(
    snapshots: list[tuple[date, ParsedData]],
    baseline: Optional[ParsedData] = None,
    *,
    baseline_snapshot_id: Optional[str] = None,
    default_mh: float = DEFAULT_MH,
    weekly: bool = True,
) -> dict[str, Any]:
    """
    S-curve EVM theo lịch sử snapshot.

    Mỗi điểm = compute_earned_value(snapshot, baseline, today=snapshot_date).
    Khi weekly=True: giữ snapshot mới nhất trong mỗi tuần (Monday key).

    snapshots: list (as_of_date, ParsedData) đã sort tăng dần theo date.
    """
    if not snapshots:
        return {
            "points": [],
            "weekly": weekly,
            "baseline_snapshot_id": baseline_snapshot_id,
            "has_baseline": baseline is not None,
            "message": "Chưa có snapshot lịch sử để vẽ S-curve.",
        }

    # Dedup theo tuần (hoặc theo ngày)
    picked: dict[str, tuple[date, ParsedData]] = {}
    for as_of, pdata in snapshots:
        if pdata is None:
            continue
        key = _week_monday(as_of).isoformat() if weekly else as_of.isoformat()
        # Giữ bản mới nhất trong bucket
        prev = picked.get(key)
        if prev is None or as_of >= prev[0]:
            picked[key] = (as_of, pdata)

    points: list[dict[str, Any]] = []
    for key in sorted(picked.keys()):
        as_of, pdata = picked[key]
        evm = compute_earned_value(
            pdata,
            baseline=baseline,
            baseline_snapshot_id=baseline_snapshot_id,
            today=as_of,
            default_mh=default_mh,
        )
        sm = evm.get("summary") or {}
        points.append({
            "date": as_of.isoformat(),
            "week": key if weekly else _week_monday(as_of).isoformat(),
            "bac": sm.get("bac"),
            "ev": sm.get("ev"),
            "pv": sm.get("pv"),
            "ac": sm.get("ac"),
            "spi": sm.get("spi"),
            "cpi": sm.get("cpi"),
        })

    msg = (
        f"{len(points)} điểm "
        + ("(tuần)" if weekly else "(ngày)")
        + (" · có baseline PV" if baseline is not None else " · chưa baseline (PV=N/A)")
    )
    return {
        "points": points,
        "weekly": weekly,
        "baseline_snapshot_id": baseline_snapshot_id,
        "has_baseline": baseline is not None,
        "message": msg,
    }
