"""
Compare Engine — So sánh 2 snapshot ParsedData.

Kết quả dict JSON-serializable dùng cho:
- Dashboard compare section
- Excel export compare
- Weekly digest

Chiến lược matching (rơi từ trên xuống nếu không có):
1. Mã CN chính xác (case-insensitive, strip)
2. Fallback: Tên CN + Module (case-insensitive)
Nếu không match ở cả 2 → coi là function mới/xóa.
"""
from collections import Counter, defaultdict
from datetime import date, datetime
from typing import Any, Optional

from parser.excel_parser import ParsedData, FunctionRow, PhaseData


# Thứ tự status: thấp → cao (dùng để xác định "forward" / "backward" khi status đổi)
STATUS_ORDER = {
    None: 0,
    "": 0,
    "Open": 1,
    "Assigned": 2,
    "In-progress": 3,
    "Resolved": 4,
    "Pending": 5,
    "Cancelled": 6,
    "Closed": 7,
}


class CompareEngine:
    """So sánh 2 ParsedData → CompareResult dict."""

    def compare(
        self,
        old: ParsedData,
        new: ParsedData,
        old_date: str,
        new_date: str,
    ) -> dict[str, Any]:
        # Build index cho old
        old_by_key, old_by_ten_module = self._build_index(old)
        new_by_key, new_by_ten_module = self._build_index(new)

        # Matching
        matched_pairs: list[tuple[FunctionRow, FunctionRow]] = []
        matched_new_keys: set[str] = set()

        for old_key, old_row in old_by_key.items():
            match = new_by_key.get(old_key)
            if match:
                matched_pairs.append((old_row, match))
                matched_new_keys.add(old_key)
            else:
                # Fallback: match theo Tên + Module
                fallback_key = self._ten_module_key(old_row)
                new_match = new_by_ten_module.get(fallback_key)
                if new_match:
                    matched_pairs.append((old_row, new_match))
                    # Đánh dấu key của new_match để loại khỏi "new_functions"
                    new_key = self._primary_key(new_match)
                    if new_key:
                        matched_new_keys.add(new_key)

        # New functions: có trong new, không có trong matched
        new_functions = []
        for new_key, new_row in new_by_key.items():
            if new_key not in matched_new_keys:
                # Kiểm tra thêm fallback bằng tên+module
                fallback_key = self._ten_module_key(new_row)
                if fallback_key in old_by_ten_module:
                    continue
                new_functions.append(self._row_to_dict(new_row))

        # Removed functions
        matched_old_keys = {self._primary_key(o) for (o, _) in matched_pairs}
        removed_functions = []
        for old_key, old_row in old_by_key.items():
            if old_key not in matched_old_keys:
                fallback_key = self._ten_module_key(old_row)
                if fallback_key in new_by_ten_module:
                    continue
                removed_functions.append(self._row_to_dict(old_row))

        # Status changes
        status_changes = []
        for old_row, new_row in matched_pairs:
            all_phases = set(old_row.phases.keys()) | set(new_row.phases.keys())
            for phase_name in all_phases:
                op = old_row.phases.get(phase_name, PhaseData())
                np = new_row.phases.get(phase_name, PhaseData())
                if op.status != np.status:
                    direction = self._direction(op.status, np.status)
                    status_changes.append({
                        "ma_cn": new_row.meta.get("ma_cn") or old_row.meta.get("ma_cn", ""),
                        "ten_cn": new_row.meta.get("ten_cn") or old_row.meta.get("ten_cn", ""),
                        "module": new_row.meta.get("module") or old_row.meta.get("module", ""),
                        "phase": phase_name,
                        "old_status": op.status or "",
                        "new_status": np.status or "",
                        "direction": direction,
                    })

        # Summary numbers
        old_total = len(old.rows)
        new_total = len(new.rows)
        old_pct = self._overall_pct(old)
        new_pct = self._overall_pct(new)
        old_overdue = self._count_overdue(old)
        new_overdue = self._count_overdue(new)

        # Module deltas
        module_deltas = self._module_deltas(old, new)

        # Phase deltas
        phase_deltas = self._phase_deltas(old, new)

        # Velocity
        velocity = self._velocity(
            old_date, new_date,
            old_pct=old_pct, new_pct=new_pct,
            new_total=new_total, old_total=old_total,
            status_changes=status_changes,
            new_functions=new_functions,
        )

        # Count status transitions (aggregate)
        transitions_agg = Counter()
        for sc in status_changes:
            key = f"{sc['old_status'] or 'None'} → {sc['new_status'] or 'None'}"
            transitions_agg[key] += 1

        return {
            "old_date": old_date,
            "new_date": new_date,
            "old_total": old_total,
            "new_total": new_total,
            "delta_total": new_total - old_total,
            "old_overall_pct": old_pct,
            "new_overall_pct": new_pct,
            "delta_pct": round(new_pct - old_pct, 2),
            "old_overdue": old_overdue,
            "new_overdue": new_overdue,
            "delta_overdue": new_overdue - old_overdue,
            "new_functions": new_functions,
            "removed_functions": removed_functions,
            "status_changes": status_changes,
            "module_deltas": module_deltas,
            "phase_deltas": phase_deltas,
            "velocity": velocity,
            "transitions_agg": dict(transitions_agg),
        }

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _primary_key(self, row: FunctionRow) -> Optional[str]:
        """Ưu tiên Mã CN. Fallback: STT + Tên CN."""
        ma = row.meta.get("ma_cn")
        if ma:
            return f"MA:{str(ma).strip().lower()}"
        stt = row.meta.get("stt")
        ten = row.meta.get("ten_cn")
        if stt is not None and ten:
            return f"STT:{stt}::{str(ten).strip().lower()}"
        return None

    def _ten_module_key(self, row: FunctionRow) -> str:
        ten = str(row.meta.get("ten_cn") or "").strip().lower()
        module = str(row.meta.get("module") or "").strip().lower()
        return f"{module}|{ten}"

    def _build_index(self, data: ParsedData) -> tuple[dict, dict]:
        """Return (primary_key_index, ten_module_index)."""
        primary_idx: dict[str, FunctionRow] = {}
        ten_module_idx: dict[str, FunctionRow] = {}
        for row in data.rows:
            k = self._primary_key(row)
            if k:
                primary_idx[k] = row
            fk = self._ten_module_key(row)
            if fk and fk != "|":
                ten_module_idx[fk] = row
        return primary_idx, ten_module_idx

    def _direction(self, old_status: Optional[str], new_status: Optional[str]) -> str:
        o = STATUS_ORDER.get(old_status, 0)
        n = STATUS_ORDER.get(new_status, 0)
        if n > o:
            return "forward"
        if n < o:
            return "backward"
        return "lateral"

    def _overall_pct(self, data: ParsedData) -> float:
        if not data.all_phases or not data.rows:
            return 0
        last_phase = data.all_phases[-1]
        closed = sum(
            1 for r in data.rows
            if r.phases.get(last_phase, PhaseData()).status == "Closed"
        )
        return round(closed / len(data.rows) * 100, 2)

    def _count_overdue(self, data: ParsedData) -> int:
        today = date.today()
        cnt = 0
        for r in data.rows:
            for _, pd in r.phases.items():
                if (pd.end_date
                    and pd.status not in ("Closed", "Cancelled", None)
                    and pd.end_date < today):
                    cnt += 1
                    break  # 1 function chỉ đếm 1 lần
        return cnt

    def _module_deltas(self, old: ParsedData, new: ParsedData) -> dict:
        """Tính chênh lệch tiến độ theo module."""
        result: dict[str, dict] = {}
        all_modules = sorted(set(old.all_modules) | set(new.all_modules))

        for m in all_modules:
            old_rows = [r for r in old.rows if r.meta.get("module") == m]
            new_rows = [r for r in new.rows if r.meta.get("module") == m]
            old_pct = self._closed_pct_last_phase(old_rows, old.all_phases)
            new_pct = self._closed_pct_last_phase(new_rows, new.all_phases)

            # Đếm function Closed mới trong new (chưa Closed ở old)
            old_by_key = {self._primary_key(r): r for r in old_rows if self._primary_key(r)}
            new_by_key = {self._primary_key(r): r for r in new_rows if self._primary_key(r)}

            newly_closed = 0
            newly_added = 0
            last_phase_new = new.all_phases[-1] if new.all_phases else None
            for k, nr in new_by_key.items():
                orig = old_by_key.get(k)
                new_status = nr.phases.get(last_phase_new, PhaseData()).status if last_phase_new else None
                if orig is None:
                    newly_added += 1
                    if new_status == "Closed":
                        newly_closed += 1
                else:
                    last_phase_old = old.all_phases[-1] if old.all_phases else None
                    old_status = orig.phases.get(last_phase_old, PhaseData()).status if last_phase_old else None
                    if new_status == "Closed" and old_status != "Closed":
                        newly_closed += 1

            result[m] = {
                "old_pct": old_pct,
                "new_pct": new_pct,
                "delta_pct": round(new_pct - old_pct, 2),
                "closed_count": newly_closed,
                "new_count": newly_added,
                "old_total": len(old_rows),
                "new_total": len(new_rows),
            }
        return result

    def _phase_deltas(self, old: ParsedData, new: ParsedData) -> dict:
        """% Closed từng phase, so sánh giữa old vs new."""
        all_phases = list(dict.fromkeys(old.all_phases + new.all_phases))  # union giữ order
        result = {}
        for p in all_phases:
            old_total = sum(1 for r in old.rows if r.phases.get(p, PhaseData()).status)
            old_closed = sum(1 for r in old.rows if r.phases.get(p, PhaseData()).status == "Closed")
            new_total = sum(1 for r in new.rows if r.phases.get(p, PhaseData()).status)
            new_closed = sum(1 for r in new.rows if r.phases.get(p, PhaseData()).status == "Closed")
            op = round(old_closed / old_total * 100, 1) if old_total > 0 else 0
            np_ = round(new_closed / new_total * 100, 1) if new_total > 0 else 0
            result[p] = {
                "old_closed_pct": op,
                "new_closed_pct": np_,
                "delta_pct": round(np_ - op, 2),
            }
        return result

    def _closed_pct_last_phase(self, rows: list[FunctionRow], phases: list[str]) -> float:
        if not phases or not rows:
            return 0
        last = phases[-1]
        closed = sum(1 for r in rows if r.phases.get(last, PhaseData()).status == "Closed")
        return round(closed / len(rows) * 100, 2)

    def _velocity(
        self, old_date: str, new_date: str,
        old_pct: float, new_pct: float,
        old_total: int, new_total: int,
        status_changes: list[dict],
        new_functions: list[dict],
    ) -> dict:
        """Tốc độ close + dự báo."""
        # Số ngày giữa 2 snapshot
        days_between = None
        try:
            if old_date and new_date and old_date != "uploaded_file":
                d1 = datetime.fromisoformat(old_date).date()
                d2 = datetime.fromisoformat(new_date).date()
                days_between = max(1, (d2 - d1).days)
        except ValueError:
            days_between = None

        # Đếm số function chuyển sang Closed (unique theo ma_cn)
        closed_ma_cns = {
            sc["ma_cn"] for sc in status_changes
            if sc["new_status"] == "Closed" and sc["old_status"] != "Closed"
        }
        functions_closed = len(closed_ma_cns)

        close_rate = None
        est_days_remaining = None
        if days_between and days_between > 0:
            close_rate = round(functions_closed / days_between, 2)
            if close_rate and close_rate > 0:
                remaining = new_total * (100 - new_pct) / 100
                est_days_remaining = round(remaining / close_rate, 1)

        return {
            "days_between": days_between,
            "functions_closed": functions_closed,
            "close_rate_per_day": close_rate,
            "est_days_remaining": est_days_remaining,
            "functions_new": len(new_functions),
            "net_progress": functions_closed - len(new_functions),
        }

    def _row_to_dict(self, row: FunctionRow) -> dict:
        return {
            "ma_cn": row.meta.get("ma_cn", ""),
            "ten_cn": row.meta.get("ten_cn", ""),
            "module": row.meta.get("module", ""),
            "priority": row.meta.get("priority", ""),
        }
