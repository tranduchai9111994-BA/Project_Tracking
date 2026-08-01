"""
Module dependency / cascade delay (Phase D) — model tối giản.

Giả định:
  - Thứ tự module = `module_order.json` (PM cấu hình) hoặc alphabetical.
  - Module đứng trước là predecessor của module đứng sau.
  - "Cổng" (gate) của predecessor = phase Config / Cấu hình (auto-detect
    theo tên phase). Không có Config → lấy phase giữa chuỗi (tránh UAT/Golive).
  - Nếu gate của predecessor chưa đạt ngưỡng % Closed → mọi module phía
    sau bị cảnh báo cascade delay.

Không thay dependency function-level (`function_lq` trong advanced_metrics).
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date
from typing import Any, Optional, Sequence

from parser.excel_parser import ParsedData, FunctionRow, PhaseData

from analyzer.module_order import sort_modules
from analyzer.overdue import is_phase_overdue

# Phase gate keywords (auto-detect, không hardcode tên cột Excel)
GATE_KEYWORDS = (
    "config", "cấu hình", "cau hinh", "cấuhình", "cfg", "setup",
)
# Phase muộn — tránh chọn làm gate khi không có Config
LATE_KEYWORDS = ("uat", "golive", "go-live", "go live", "deploy", "release")

DEFAULT_GATE_CLOSED_THRESHOLD = 0.70  # 70% Closed


def pick_gate_phase(phase_names: Sequence[str]) -> Optional[str]:
    """
    Chọn phase làm cổng predecessor.
    Ưu tiên tên chứa Config/Cấu hình; không có → phase giữa (bỏ UAT/Golive nếu được).
    """
    names = [str(p).strip() for p in phase_names if str(p).strip()]
    if not names:
        return None
    for p in names:
        low = p.lower()
        if any(k in low for k in GATE_KEYWORDS):
            return p
    # Bỏ phase muộn rồi lấy phần giữa
    early = [
        p for p in names
        if not any(k in p.lower() for k in LATE_KEYWORDS)
    ]
    pool = early or names
    return pool[len(pool) // 2] if pool else names[0]


def _phase_in_scope(pd: PhaseData) -> bool:
    st = (pd.status or "").strip().lower()
    if st == "cancelled":
        return False
    return bool(pd.status or pd.start_date or pd.end_date)


def module_gate_stats(
    rows: list[FunctionRow],
    gate_phase: str,
    *,
    today: Optional[date] = None,
    phase_order: Optional[list[str]] = None,
) -> dict[str, Any]:
    """Thống kê Closed / overdue trên phase gate của 1 module."""
    today = today or date.today()
    total = 0
    closed = 0
    overdue_open = 0
    for row in rows:
        pd = row.phases.get(gate_phase)
        if pd is None or not _phase_in_scope(pd):
            continue
        total += 1
        st = (pd.status or "").strip()
        if st == "Closed":
            closed += 1
            continue
        if is_phase_overdue(
            pd, today, row=row, phase_name=gate_phase, phase_order=phase_order,
        ):
            overdue_open += 1

    closed_pct = round(100.0 * closed / total, 1) if total else 100.0
    return {
        "gate_phase": gate_phase,
        "total": total,
        "closed": closed,
        "overdue_open": overdue_open,
        "closed_pct": closed_pct,
        "ready": total == 0 or (closed / total) >= DEFAULT_GATE_CLOSED_THRESHOLD,
    }


def compute_module_cascade(
    data: ParsedData,
    module_order: Optional[Sequence[str]] = None,
    *,
    today: Optional[date] = None,
    gate_closed_threshold: float = DEFAULT_GATE_CLOSED_THRESHOLD,
) -> dict[str, Any]:
    """
    Cascade delay theo thứ tự module.

    Returns:
      gate_phase, ordered_modules, by_module, warnings, modules_blocked,
      blocked_by_map (module → nearest unfinished predecessor), assumptions
    """
    today = today or date.today()
    ordered = sort_modules(data.all_modules or [], module_order)
    phase_names = list(data.all_phases or [])
    gate = pick_gate_phase(phase_names)
    order = phase_names

    by_mod_rows: dict[str, list[FunctionRow]] = defaultdict(list)
    for row in data.rows:
        m = str(row.meta.get("module") or "").strip()
        if m:
            by_mod_rows[m].append(row)

    by_module: list[dict[str, Any]] = []
    stats_by: dict[str, dict] = {}
    for mod in ordered:
        if gate:
            st = module_gate_stats(
                by_mod_rows.get(mod, []), gate,
                today=today, phase_order=order,
            )
        else:
            st = {
                "gate_phase": None,
                "total": 0,
                "closed": 0,
                "overdue_open": 0,
                "closed_pct": 100.0,
                "ready": True,
            }
        # Override ready theo threshold tham số
        tot = st["total"]
        if tot > 0:
            st["ready"] = (st["closed"] / tot) >= gate_closed_threshold
        st = {**st, "module": mod, "function_count": len(by_mod_rows.get(mod, []))}
        stats_by[mod] = st
        by_module.append(st)

    # Nearest unfinished predecessor → blocked map
    blocked_by: dict[str, str] = {}
    warnings: list[dict[str, Any]] = []
    last_blocker: Optional[str] = None
    for mod in ordered:
        st = stats_by[mod]
        if last_blocker:
            blocked_by[mod] = last_blocker
            pred = stats_by[last_blocker]
            warnings.append({
                "module": mod,
                "blocked_by": last_blocker,
                "gate_phase": pred.get("gate_phase"),
                "gate_closed_pct": pred.get("closed_pct"),
                "gate_overdue_open": pred.get("overdue_open", 0),
                "message": (
                    f"Module «{mod}» có nguy cơ trễ dây chuyền: "
                    f"predecessor «{last_blocker}» phase "
                    f"«{pred.get('gate_phase') or '?'}» mới "
                    f"{pred.get('closed_pct')}% Closed"
                    + (
                        f" ({pred.get('overdue_open')} còn overdue)"
                        if pred.get("overdue_open")
                        else ""
                    )
                ),
            })
        # Predecessor chưa sẵn sàng → trở thành blocker cho mọi module sau
        if not st.get("ready", True) and st.get("total", 0) > 0:
            last_blocker = mod

    return {
        "gate_phase": gate,
        "gate_closed_threshold": gate_closed_threshold,
        "ordered_modules": ordered,
        "by_module": by_module,
        "warnings": warnings,
        "modules_blocked": sorted(blocked_by.keys()),
        "blocked_by_map": blocked_by,
        "warning_count": len(warnings),
        "assumptions": [
            "Thứ tự module = module_order (Cài đặt) hoặc alphabetical.",
            "Gate = phase Config/Cấu hình (auto-detect); không có thì phase giữa chuỗi.",
            f"Predecessor chưa sẵn sàng khi gate Closed < {int(gate_closed_threshold * 100)}%.",
            "Mọi module phía sau nearest unfinished predecessor → cảnh báo cascade.",
        ],
    }
