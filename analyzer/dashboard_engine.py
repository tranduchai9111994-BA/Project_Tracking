"""
Dashboard Engine — Tính toán tất cả metrics từ ParsedData.
Trả về dict JSON-serializable để gửi cho frontend.
"""
from collections import Counter, defaultdict
from datetime import date
from typing import Any

from parser.excel_parser import ParsedData, FunctionRow, PhaseData
from analyzer.overdue import is_phase_overdue, row_has_overdue


def _project_codes_from_rows(data: ParsedData) -> list[str]:
    """Unique Mã dự án từ rows — fallback khi pickle cũ chưa có all_project_codes."""
    return sorted({
        str(r.meta.get("ma_du_an", "")).strip()
        for r in data.rows
        if r.meta.get("ma_du_an") and str(r.meta.get("ma_du_an")).strip()
    })


class DashboardEngine:
    """Tính toán các dashboard metrics."""

    def __init__(self, today: date | None = None, long_duration_threshold: int = 3):
        self.today = today or date.today()
        self.long_duration_threshold = long_duration_threshold

    def compute_all(
        self,
        data: ParsedData,
        prev_summary: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Entry point: tính tất cả metrics.

        prev_summary: summary snapshot trước (optional) → gắn `summary.deltas`.
        """
        # Import cục bộ để tránh circular
        from analyzer.risk_scorer import compute_pmo_risk

        # Phase D: risk + resource/dependency dimensions (single-project overload)
        pmo = compute_pmo_risk(
            data,
            self.today,
            long_duration_threshold=self.long_duration_threshold,
        )
        risk_scores = pmo["risk_scores"]
        summary = self._summary(data, risk_scores)
        summary["deltas"] = self.compute_summary_deltas(summary, prev_summary)
        stalled_tasks = self._stalled_tasks(data)
        summary["issue_tab_counts"] = self._issue_tab_counts(
            data, summary, len(stalled_tasks.get("items") or []),
        )

        return {
            "structure": self._structure_info(data),
            "summary": summary,
            "module_overview": self._module_overview(data),
            "phase_status_matrix": self._phase_status_matrix(data),
            "progress_by_task_type": self._progress_by_task_type(data),
            "pic_workload": self._pic_workload(data),
            "overdue_list": self._overdue_list(data),
            "priority_breakdown": self._priority_breakdown(data),
            "complexity_breakdown": self._complexity_breakdown(data),
            "fit_gap_analysis": self._fit_gap_analysis(data),
            "giai_doan_progress": self._giai_doan_progress(data),
            "phase_progress_stacked": self._phase_progress_stacked(data),
            # === V2 additions ===
            "unassigned_tasks": self._unassigned_tasks(data),
            "duration_analysis": self._duration_analysis(data, self.long_duration_threshold),
            "stalled_tasks": stalled_tasks,
            "risk_scores": risk_scores,
            "pmo_risk": {
                "summary": pmo["summary"],
                "dimensions": pmo["dimensions"],
                "modules": pmo["modules"],
                "cascade": pmo["cascade"],
                "scoring_notes": pmo["scoring_notes"],
            },
            "effort_analysis": self._effort_analysis(data),
            "process_analysis": self._process_analysis(data),
            "timeline_data": self._timeline_data(data),
            # === Upgrade Wave P4–P5 ===
            "burndown_velocity": self._burndown_velocity(data),
            "sla_violations": self._sla_violations(data),
            "slow_heatmap": self._slow_heatmap(data),
            "dependency_blockers": self._dependency_blockers(data),
            "baseline_variance": self._baseline_variance(data),
            # Rlog coded tuần này + kế hoạch tuần tới
            "rlog_weekly": self._rlog_weekly(data),
        }

    # ------------------------------------------------------------------
    # Structure info (để frontend biết có gì)
    # ------------------------------------------------------------------

    def _structure_info(self, data: ParsedData) -> dict:
        # Cascade filter: mapping Module → list Quy trình để FE lọc dropdown
        # khi user đổi module. Dùng set để dedupe, sau đó sort để UI ổn định.
        processes_by_module: dict[str, set[str]] = defaultdict(set)
        # Cascade filter: mapping Module → list PIC (gộp mọi phase của module).
        # 1 PIC có thể xuất hiện ở nhiều module → dedupe theo (module, pic).
        pics_by_module: dict[str, set[str]] = defaultdict(set)
        for r in data.rows:
            mod = r.meta.get("module")
            proc = r.meta.get("quy_trinh")
            if mod and proc:
                processes_by_module[mod].add(str(proc))
            if mod:
                # Gom mọi PIC xuất hiện ở bất kỳ phase nào của row
                for pd in r.phases.values():
                    for pic in pd.pics:
                        if pic:
                            pics_by_module[mod].add(pic)
        processes_by_module_sorted = {
            m: sorted(procs) for m, procs in processes_by_module.items()
        }
        pics_by_module_sorted = {
            m: sorted(pics) for m, pics in pics_by_module.items()
        }

        # T28 — Chart Config filter multi-select cần luôn full domain values
        # cho các trường FIT/GAP + Task type. Compute từ rows để không phải
        # đổi parser dataclass.
        all_fit_gap: set[str] = set()
        for r in data.rows:
            v = str(r.meta.get("fit_gap") or "").strip()
            if not v:
                continue
            # Cell có thể là "FIT" / "GAP" / "FIT / GAP" / "FIT, GAP"
            for token in v.replace("/", ",").split(","):
                token = token.strip()
                if token:
                    all_fit_gap.add(token)
        return {
            "all_modules": data.all_modules,
            "all_phases": data.all_phases,
            "all_pics": data.all_pics,
            "all_statuses": data.all_statuses,
            "all_priorities": data.all_priorities,
            "all_complexities": data.all_complexities,
            "all_giai_doan": data.all_giai_doan,
            "all_processes": data.all_processes,
            "all_project_codes": list(getattr(data, "all_project_codes", None) or _project_codes_from_rows(data)),
            "all_fit_gap": sorted(all_fit_gap),
            "processes_by_module": processes_by_module_sorted,
            "pics_by_module": pics_by_module_sorted,
            "phase_groups": [
                {"name": pg.name, "task_type": pg.task_type, "attributes": list(pg.attributes.keys())}
                for pg in data.phase_groups
            ],
        }

    # ------------------------------------------------------------------
    # Summary cards
    # ------------------------------------------------------------------

    def _summary(self, data: ParsedData, risk_scores: list[dict] | None = None) -> dict:
        total = len(data.rows)

        # ==== Overdue: đếm function unique VÀ phase-level record ====
        order = data.all_phases
        overdue_functions = sum(
            1 for r in data.rows if self._row_has_overdue(r, order)
        )
        overdue_records = 0
        for r in data.rows:
            for phase_name, pd in r.phases.items():
                if self._is_overdue(pd, r, phase_name, order):
                    overdue_records += 1

        # ==== Tiến độ chung (weighted_all): % phase-record Closed / (row × phase) ====
        # Định nghĩa: coi mọi phase đều phải làm. Phase blank = "chưa làm" (đếm vào mẫu số).
        # → Đo baseline nghiêm khắc, phản ánh đúng tiến độ tổng thể qua các phase.
        last_phase = data.all_phases[-1] if data.all_phases else None
        all_phases_count = len(data.all_phases)
        if total > 0 and all_phases_count > 0:
            total_records = total * all_phases_count
            closed_records = sum(
                1
                for r in data.rows
                for ph in data.all_phases
                if r.phases.get(ph, PhaseData()).status == "Closed"
            )
            overall_pct = round(closed_records / total_records * 100, 1)
        else:
            overall_pct = 0
        # Giữ last-phase % riêng cho FE hiển thị badge phụ nếu cần
        if last_phase and total > 0:
            closed_last = sum(1 for r in data.rows
                              if r.phases.get(last_phase, PhaseData()).status == "Closed")
            last_phase_pct = round(closed_last / total * 100, 1)
        else:
            last_phase_pct = 0

        # ==== Unassigned: đếm function unique VÀ phase-level ====
        # Gate: in-scope + thiếu PIC + predecessor Closed + Start đã đến.
        from analyzer.unassigned import is_unassigned_phase
        phase_order = data.all_phases
        unassigned_functions = 0
        unassigned_records = 0
        for r in data.rows:
            func_has_unassigned = False
            for phase_name, pd in r.phases.items():
                if is_unassigned_phase(
                    r, phase_name, pd, phase_order, self.today,
                ):
                    unassigned_records += 1
                    func_has_unassigned = True
            if func_has_unassigned:
                unassigned_functions += 1

        # ==== High-risk (>= 50 điểm) ====
        high_risk_count = 0
        if risk_scores:
            high_risk_count = sum(1 for r in risk_scores if r["risk_score"] >= 50)

        # ==== Missing deadline: WIP (active status) thiếu End — dedupe function ====
        from analyzer.data_quality import (
            count_missing_deadlines, count_anomalies, compute_data_quality,
        )
        missing_deadline_count, missing_deadline_records = count_missing_deadlines(
            data, today=self.today,
        )
        anomaly_count, anomaly_records = count_anomalies(data, today=self.today)

        # DQ High only (secondary card) — total issues đưa vào tooltip/subtitle
        dq_high_count = 0
        dq_total_count = 0
        dq_affected_rows = 0
        try:
            dq = compute_data_quality(data, today=self.today)
            dq_summary = dq.get("summary") or {}
            sev = dq_summary.get("by_severity") or {}
            dq_high_count = int(sev.get("high") or 0)
            dq_total_count = int(dq_summary.get("total_issues") or 0)
            # Số FUNCTION có ≥1 issue (không phải số issue) — dùng để tính % lỗi
            # đúng nghĩa (1 function có thể có nhiều issue → total_issues > total_functions).
            dq_affected_rows = int(dq_summary.get("affected_rows") or 0)
        except Exception:
            pass

        return {
            "total_functions": total,
            "total_overdue": overdue_functions,          # legacy: dùng cho card
            "total_overdue_records": overdue_records,    # phase-level, dùng cho bảng
            "overall_progress_pct": overall_pct,         # weighted: closed_records / (row × phase)
            "last_phase_progress_pct": last_phase_pct,   # % Closed ở phase cuối (metric phụ)
            "last_phase_name": last_phase or "",
            "progress_formula": "weighted_all",           # để FE biết cách hiển thị/giải thích
            "modules_count": len(data.all_modules),
            "processes_count": len(getattr(data, "all_processes", []) or []),
            "phases_count": len(data.all_phases),
            "unassigned_count": unassigned_functions,    # đổi ngữ nghĩa: giờ là số function unique
            "unassigned_records": unassigned_records,    # phase-level
            "high_risk_count": high_risk_count,
            "missing_deadline_count": missing_deadline_count,
            "missing_deadline_records": missing_deadline_records,
            "anomaly_count": anomaly_count,
            "anomaly_records": anomaly_records,
            "dq_high_count": dq_high_count,
            "dq_total_count": dq_total_count,
            "dq_affected_rows": dq_affected_rows,
            "deltas": {},
        }

    def _issue_tab_counts(
        self,
        data: ParsedData,
        summary: dict[str, Any],
        stalled_count: int,
        aging_threshold: int = 14,
    ) -> dict[str, int]:
        """Số đếm badge trên từng tab Issues hub — toàn bộ dự án, không filter cục bộ."""
        from analyzer.advanced_metrics import compute_aging_wip
        from analyzer.duration_flag import compute_long_duration
        from analyzer.fid_check import compute_fid_issues
        from analyzer.source_checklist import compute_source_checklist
        from analyzer.weekly_gap_report import compute_weekly_gap

        aging_sm = (compute_aging_wip(data, threshold_days=aging_threshold, today=self.today)
                    .get("summary") or {})
        fid_sm = (compute_fid_issues(data).get("summary") or {})
        sc_sm = (compute_source_checklist(data).get("summary") or {})
        dur_sm = (compute_long_duration(data).get("summary") or {})
        wg_sm = (compute_weekly_gap(data).get("summary") or {})

        return {
            "overdue": int(summary.get("total_overdue") or 0),
            "unassigned": int(summary.get("unassigned_count") or 0),
            "stalled": stalled_count,
            "aging_wip": int(aging_sm.get("total_aging") or 0),
            "dq": int(summary.get("dq_total_count") or 0),
            "fid_issues": int(fid_sm.get("total_issues") or 0),
            "source_checklist": int(sc_sm.get("total_pending") or 0),
            "duration_flag": int(dur_sm.get("total") or 0),
            "weekly_gap": int(wg_sm.get("total") or 0),
        }

    @staticmethod
    def compute_summary_deltas(
        summary: dict[str, Any],
        prev_summary: dict[str, Any] | None,
    ) -> dict[str, Any]:
        """Delta vs snapshot trước. Key → {delta, prev, curr}. Hide FE khi delta=0."""
        if not prev_summary:
            return {}
        keys = (
            ("total_functions", "total_functions"),
            ("overall_progress_pct", "overall_progress_pct"),
            ("total_overdue", "total_overdue"),
            ("unassigned_count", "unassigned_count"),
            ("high_risk_count", "high_risk_count"),
            ("missing_deadline_count", "missing_deadline_count"),
            ("dq_high_count", "dq_high_count"),
            ("modules_count", "modules_count"),
        )
        # Alias từ snapshot_index
        aliases = {
            "overall_progress_pct": ("overall_pct", "overall_progress_pct"),
            "total_overdue": ("overdue_count", "total_overdue"),
        }
        out: dict[str, Any] = {}
        for sk, _ in keys:
            curr = summary.get(sk)
            prev = prev_summary.get(sk)
            if prev is None and sk in aliases:
                for alt in aliases[sk]:
                    if alt in prev_summary:
                        prev = prev_summary.get(alt)
                        break
            if curr is None or prev is None:
                continue
            try:
                c = float(curr)
                p = float(prev)
            except (TypeError, ValueError):
                continue
            delta = c - p
            out[sk] = {
                "delta": round(delta, 2) if abs(delta - round(delta)) > 1e-9 else int(round(delta)),
                "prev": prev,
                "curr": curr,
            }
        return out

    @staticmethod
    def attach_summary_deltas(
        metrics: dict[str, Any],
        prev_summary: dict[str, Any] | None,
    ) -> dict[str, Any]:
        """Gắn deltas vào metrics['summary'] (không phá shape cũ)."""
        if not isinstance(metrics, dict):
            return metrics
        summary = metrics.get("summary")
        if not isinstance(summary, dict):
            return metrics
        summary["deltas"] = DashboardEngine.compute_summary_deltas(summary, prev_summary)
        return metrics

    # ------------------------------------------------------------------
    # Module overview (Bảng A)
    # ------------------------------------------------------------------

    def _module_overview(self, data: ParsedData) -> list[dict]:
        return self._overview_by(data, group_by="module")

    def _overview_by(self, data: ParsedData, group_by: str = "module") -> list[dict]:
        """Task 17: aggregate overview theo `module` | `process` | `both`.

        - `module`  → 1 row / module (như cũ).
        - `process` → 1 row / (module, quy_trinh), giữ cột module để phân biệt.
        - `both`    → giống module + attach `children[]` là các process rows
          của module đó → FE render nested/expand.
        """
        gb = (group_by or "module").lower().strip()
        if gb == "process":
            return self._overview_by_process(data)
        if gb == "both":
            mod_rows = self._overview_by(data, group_by="module")
            proc_rows = self._overview_by_process(data)
            by_mod: dict[str, list[dict]] = {}
            for pr in proc_rows:
                by_mod.setdefault(pr["module"], []).append(pr)
            for m in mod_rows:
                m["children"] = by_mod.get(m["module"], [])
            return mod_rows
        # default: module
        result = []
        module_rows = self._group_by_module(data)
        stalled_by_module = self._stalled_counts_by_module(data)
        for idx, module in enumerate(data.all_modules, 1):
            rows = module_rows.get(module, [])
            result.append(self._one_overview_entry(
                data, rows, idx=idx, label=module, module=module,
                stalled_count=stalled_by_module.get(module, 0),
            ))
        return result

    def _stalled_counts_by_module(self, data: ParsedData) -> dict[str, int]:
        """Số function stalled per module — dùng cho module_risk_level (A2)."""
        counts: dict[str, int] = defaultdict(int)
        for item in self._stalled_tasks(data)["items"]:
            counts[item["module"]] += 1
        return counts

    def _overview_by_process(self, data: ParsedData) -> list[dict]:
        """1 row / (module, quy_trinh) — sort theo module_order rồi process."""
        from analyzer.module_order import module_sort_key
        by_key: dict[tuple[str, str], list] = {}
        for r in data.rows:
            m = r.meta.get("module") or ""
            p = r.meta.get("quy_trinh") or ""
            if not p:
                continue  # skip row không có quy_trinh
            by_key.setdefault((m, p), []).append(r)
        order = data.all_modules
        sorted_keys = sorted(
            by_key.keys(),
            key=lambda t: (module_sort_key(t[0], order), t[1]),
        )
        result = []
        for idx, (m, p) in enumerate(sorted_keys, 1):
            rows = by_key[(m, p)]
            result.append(self._one_overview_entry(
                data, rows, idx=idx, label=p, module=m, process=p,
            ))
        return result

    def _one_overview_entry(
        self, data: ParsedData, rows, *, idx: int, label: str,
        module: str, process: str = "", stalled_count: int = 0,
    ) -> dict:
        """Đóng gói 1 entry overview theo weighted_all formula."""
        total = len(rows)
        all_phases_cnt = len(data.all_phases)
        quy_trinh_set = {r.meta.get("quy_trinh") for r in rows if r.meta.get("quy_trinh")}
        quy_trinh_count = len(quy_trinh_set)
        if total > 0 and all_phases_cnt > 0:
            closed_records = sum(
                1
                for r in rows
                for ph in data.all_phases
                if r.phases.get(ph, PhaseData()).status == "Closed"
            )
            progress_pct = round(closed_records / (total * all_phases_cnt) * 100, 2)
        else:
            progress_pct = 0
        active_phase = self._detect_active_phase(rows, data.all_phases)
        overdue_count = sum(
            1 for r in rows if self._row_has_overdue(r, data.all_phases)
        )
        # Còn lại = function chưa Closed phase cuối (khớp drill scope=remaining).
        remaining = 0
        last_phase = data.all_phases[-1] if data.all_phases else None
        for r in rows:
            if last_phase:
                st = (r.phases.get(last_phase, PhaseData()).status or "")
                if st != "Closed":
                    remaining += 1
            else:
                remaining += 1
        # MH còn lại (nếu có estimate) — tỷ lệ phase chưa Closed/Cancelled
        remaining_mh = 0.0
        for r in rows:
            est = r.meta.get("estimate_mh")
            if est is None:
                continue
            try:
                est_f = float(est)
            except (TypeError, ValueError):
                continue
            if est_f <= 0 or not data.all_phases:
                continue
            open_phases = sum(
                1 for ph in data.all_phases
                if (r.phases.get(ph, PhaseData()).status or "") not in ("Closed", "Cancelled")
            )
            if open_phases > 0:
                remaining_mh += est_f * (open_phases / len(data.all_phases))
        overdue_pct = round(overdue_count / total * 100, 2) if total else 0
        # % function đình trệ — dùng tỷ lệ, không flag risk chỉ vì 1 item còn lại.
        stalled_pct = round(stalled_count / total * 100, 2) if total else 0
        # A2 — risk_level: overdue/stalled theo %, progress thấp → warning.
        # Ngưỡng: risk nếu overdue>20% hoặc stalled>20%; warning nếu overdue>10%
        # hoặc stalled>10% hoặc progress<50%. Remaining/DQ không tự thành risk.
        reasons: list[str] = []
        if overdue_pct > 20:
            reasons.append(f"Trễ {overdue_pct}% (>20%)")
        if stalled_pct > 20:
            reasons.append(f"Đình trệ {stalled_pct}% (>20%)")
        if reasons:
            risk_level = "risk"
        else:
            if overdue_pct > 10:
                reasons.append(f"Trễ {overdue_pct}% (>10%)")
            if stalled_pct > 10:
                reasons.append(f"Đình trệ {stalled_pct}% (>10%)")
            if progress_pct < 50:
                reasons.append(f"Tiến độ {progress_pct}% (<50%)")
            risk_level = "warning" if reasons else "safe"
        return {
            "stt": idx,
            "module": module,
            "process": process,
            "label": label,
            "total": total,
            "quy_trinh_count": quy_trinh_count,
            "progress_pct": progress_pct,
            "active_phase": active_phase,
            "overdue_count": overdue_count,
            "overdue_pct": overdue_pct,
            "stalled_count": stalled_count,
            "stalled_pct": stalled_pct,
            "risk_level": risk_level,
            "risk_reason": "; ".join(reasons) if reasons else "An toàn",
            # Còn lại = function chưa Closed phase cuối (khớp drill scope=remaining).
            "remaining": remaining,
            "remaining_mh": round(remaining_mh, 1),
        }

    # ------------------------------------------------------------------
    # Phase × Status matrix
    # ------------------------------------------------------------------

    def _phase_status_matrix(self, data: ParsedData, group_by: str = "module") -> dict:
        """Ma trận rows × phases với % Closed và status counts.

        group_by:
        - "module"  → rows là module (như cũ, backward compatible).
        - "process" → rows là quy trình (giữ nguyên tên đầy đủ, VD
          "PRM.BP.03 - Quy trình tính lương sản phẩm"), kèm meta module
          để hiển thị cột phụ.
        """
        gb = (group_by or "module").lower().strip()
        all_statuses_ordered = ["Closed", "In-progress", "Assigned", "Resolved", "Open", "Pending", "Cancelled"]

        if gb == "process":
            # Group rows theo quy trình → sort theo module_order rồi tên process.
            from analyzer.module_order import module_sort_key
            by_proc: dict[str, list[FunctionRow]] = {}
            proc_module_map: dict[str, str] = {}
            for r in data.rows:
                proc = str(r.meta.get("quy_trinh") or "").strip()
                if not proc:
                    continue
                by_proc.setdefault(proc, []).append(r)
                # Ghi lại module đại diện (module đầu tiên gặp) — trong data thực
                # 1 quy trình thường chỉ nằm trong 1 module.
                if proc not in proc_module_map:
                    proc_module_map[proc] = str(r.meta.get("module") or "")
            order = data.all_modules
            row_labels = sorted(
                by_proc.keys(),
                key=lambda p: (
                    module_sort_key(proc_module_map.get(p, ""), order),
                    p,
                ),
            )
        else:
            gb = "module"
            by_proc = {m: [r for r in data.rows if r.meta.get("module") == m] for m in data.all_modules}
            proc_module_map = {m: m for m in data.all_modules}
            row_labels = list(data.all_modules)

        matrix: dict[str, dict] = {}
        for label in row_labels:
            matrix[label] = {}
            rows = by_proc.get(label, [])
            total_rows = len(rows)
            for phase_name in data.all_phases:
                status_counts = Counter()
                total_with_status = 0
                overdue_cell = 0
                not_started_late = 0
                for r in rows:
                    pd = r.phases.get(phase_name, PhaseData())
                    if pd.status:
                        status_counts[pd.status] += 1
                        total_with_status += 1
                    if is_phase_overdue(
                        pd, self.today, row=r, phase_name=phase_name,
                        phase_order=data.all_phases,
                    ):
                        overdue_cell += 1
                    if (
                        (pd.status or "") in ("", "Open")
                        and pd.start_date and pd.start_date < self.today
                    ):
                        not_started_late += 1

                closed = status_counts.get("Closed", 0)
                # weighted_all: denominator = total_rows (phase blank vẫn là mẫu số
                # → tránh 100% giả khi chỉ 1 phase đã fill).
                pct_closed = round(closed / total_rows * 100, 1) if total_rows > 0 else 0
                overdue_pct_cell = round(overdue_cell / total_rows * 100, 1) if total_rows > 0 else 0
                not_started_pct_cell = round(not_started_late / total_rows * 100, 1) if total_rows > 0 else 0
                # A3 — highlight khâu rủi ro: nhiều trễ hạn > risk; nhiều chưa
                # bắt đầu mà đã qua Start date > warning.
                if overdue_pct_cell > 30:
                    cell_risk_class = "risk"
                elif not_started_pct_cell > 50:
                    cell_risk_class = "warning"
                else:
                    cell_risk_class = "safe"

                matrix[label][phase_name] = {
                    "total": total_rows,
                    "total_with_status": total_with_status,
                    "pct_closed": pct_closed,
                    "overdue_pct": overdue_pct_cell,
                    "not_started_pct": not_started_pct_cell,
                    "cell_risk_class": cell_risk_class,
                    **{s: status_counts.get(s, 0) for s in all_statuses_ordered},
                }

        # Bottleneck row: per phase, số row-label "stuck"
        # (= có ≥1 function chưa Closed ở phase đó VÀ (overdue HOẶC stalled sang phase này))
        from analyzer.stalled import phase_stuck_info

        phases = list(data.all_phases)
        bottleneck: dict[str, int] = {ph: 0 for ph in phases}
        for label in row_labels:
            rows = by_proc.get(label, [])
            for phase_name in phases:
                stuck = any(
                    phase_stuck_info(r, phase_name, phases, self.today) is not None
                    for r in rows
                )
                if stuck:
                    bottleneck[phase_name] += 1

        # A3 — hàng tổng theo phase (% cell risk) + cột tổng theo module (health chung).
        phase_risk_summary: dict[str, dict] = {}
        for ph in phases:
            n = len(row_labels) or 1
            risk_cells = sum(1 for lbl in row_labels if matrix[lbl][ph]["cell_risk_class"] == "risk")
            risk_pct = round(risk_cells / n * 100, 1)
            phase_risk_summary[ph] = {
                "risk_pct": risk_pct,
                "badge": "risk" if risk_pct > 30 else ("warning" if risk_pct > 10 else "safe"),
            }

        module_risk_summary: dict[str, dict] = {}
        for lbl in row_labels:
            risk_cells = sum(1 for ph in phases if matrix[lbl][ph]["cell_risk_class"] == "risk")
            warn_cells = sum(1 for ph in phases if matrix[lbl][ph]["cell_risk_class"] == "warning")
            badge = "risk" if risk_cells > 0 else ("warning" if warn_cells > 0 else "safe")
            module_risk_summary[lbl] = {
                "risk_cells": risk_cells, "warning_cells": warn_cells, "badge": badge,
            }

        return {
            "phases": phases,
            # Backward compat: 'modules' key luôn có (là row labels), nhưng
            # thêm 'row_labels' + 'group_by' + 'row_module_map' cho FE mode process.
            "modules": row_labels,
            "row_labels": row_labels,
            "group_by": gb,
            "row_module_map": proc_module_map,
            "statuses": all_statuses_ordered,
            "data": matrix,
            "bottleneck": bottleneck,
            "phase_risk_summary": phase_risk_summary,
            "module_risk_summary": module_risk_summary,
        }

    # ------------------------------------------------------------------
    # Progress by task type
    # ------------------------------------------------------------------

    def _progress_by_task_type(self, data: ParsedData) -> dict:
        # Xây task types từ phase groups
        task_types = []
        task_phase_map = defaultdict(list)  # task_type → [phase_names]
        seen = set()

        for pg in data.phase_groups:
            tt = pg.task_type
            task_phase_map[tt].append(pg.name)
            if tt not in seen:
                task_types.append(tt)
                seen.add(tt)

        # Tính % closed mỗi group × task_type (weighted_all).
        # Denominator = len(rows_group) × len(phases_for_tt) — coi phase blank là chưa làm.
        def _aggregate_by(get_key):
            grouped: dict = defaultdict(list)
            for r in data.rows:
                k = get_key(r)
                if k:
                    grouped[k].append(r)
            out: dict = {}
            for key, rows in grouped.items():
                out[key] = {}
                for tt in task_types:
                    phases_for_tt = task_phase_map[tt]
                    total_records = len(rows) * len(phases_for_tt)
                    closed_count = sum(
                        1
                        for r in rows
                        for ph in phases_for_tt
                        if r.phases.get(ph, PhaseData()).status == "Closed"
                    )
                    pct = round(closed_count / total_records * 100, 2) if total_records > 0 else 0
                    out[key][tt] = pct
            return out

        by_module = _aggregate_by(lambda r: r.meta.get("module") or "")
        # Task 17: thêm by_process cho toggle nhóm theo Quy trình.
        by_process = _aggregate_by(lambda r: r.meta.get("quy_trinh") or "")

        return {
            "task_types": task_types,
            "task_phase_map": {k: v for k, v in task_phase_map.items()},
            "by_module": by_module,
            "by_process": by_process,
        }

    # ------------------------------------------------------------------
    # PIC workload
    # ------------------------------------------------------------------

    def _pic_workload(self, data: ParsedData) -> list[dict]:
        """
        Workload theo PIC. Bao gồm:
        - Aggregate: tổng across all phase
        - by_phase: breakdown chi tiết cho từng phase (FE dùng để filter chart)

        by_phase[phase_name] = {total, closed, in_progress, assigned, overdue}
        Chỉ include phase mà PIC thực sự có tham gia (total > 0) để giảm payload.
        """
        # Factory tạo dict thống kê rỗng (dùng cả cho aggregate lẫn per-phase)
        def _empty_stat():
            return {"total": 0, "closed": 0, "in_progress": 0,
                    "assigned": 0, "overdue": 0}

        pic_stats: dict[str, dict] = defaultdict(lambda: {
            "total_tasks": 0, "closed": 0, "in_progress": 0,
            "overdue": 0, "assigned": 0,
            "phases": Counter(),
            "by_phase": defaultdict(_empty_stat),
        })

        for r in data.rows:
            for phase_name, pd in r.phases.items():
                for pic in pd.pics:
                    st = pic_stats[pic]
                    st["total_tasks"] += 1
                    st["phases"][phase_name] += 1
                    ph = st["by_phase"][phase_name]
                    ph["total"] += 1

                    if pd.status == "Closed":
                        st["closed"] += 1
                        ph["closed"] += 1
                    elif pd.status == "In-progress":
                        st["in_progress"] += 1
                        ph["in_progress"] += 1
                    elif pd.status == "Assigned":
                        st["assigned"] += 1
                        ph["assigned"] += 1

                    if self._is_overdue(pd, r, phase_name, data.all_phases):
                        st["overdue"] += 1
                        ph["overdue"] += 1

        result = []
        for pic, stats in sorted(pic_stats.items(), key=lambda x: x[1]["total_tasks"], reverse=True):
            result.append({
                "pic": pic,
                "total_tasks": stats["total_tasks"],
                "closed": stats["closed"],
                "in_progress": stats["in_progress"],
                "assigned": stats["assigned"],
                "overdue": stats["overdue"],
                "phases": dict(stats["phases"]),
                # Convert defaultdict → dict để JSON-serializable + gọn payload
                "by_phase": {ph: dict(v) for ph, v in stats["by_phase"].items()},
            })

        return result

    # ------------------------------------------------------------------
    # Overdue list
    # ------------------------------------------------------------------

    def _overdue_list(self, data: ParsedData) -> list[dict]:
        overdue_items = []
        order = data.all_phases
        for r in data.rows:
            for phase_name, pd in r.phases.items():
                if self._is_overdue(pd, r, phase_name, order):
                    days = (self.today - pd.end_date).days
                    overdue_items.append({
                        "stt": r.meta.get("stt", r.row_num),
                        "ma_cn": r.meta.get("ma_cn", ""),
                        "ten_cn": r.meta.get("ten_cn", ""),
                        "module": r.meta.get("module", ""),
                        "quy_trinh": r.meta.get("quy_trinh") or r.meta.get("process") or "",
                        "phase": phase_name,
                        "end_date": pd.end_date.isoformat() if pd.end_date else "",
                        "days_overdue": days,
                        "status": pd.status or "",
                        "pic": pd.pics,
                        "priority": r.meta.get("priority", ""),
                        "note": pd.note or "",
                    })

        # Sắp xếp theo số ngày trễ giảm dần
        overdue_items.sort(key=lambda x: x["days_overdue"], reverse=True)
        return overdue_items

    # ------------------------------------------------------------------
    # Priority / Complexity / FIT-GAP breakdowns
    # ------------------------------------------------------------------

    def _priority_breakdown(self, data: ParsedData) -> dict:
        counts = Counter(r.meta.get("priority", "N/A") for r in data.rows)
        return dict(counts)

    def _complexity_breakdown(self, data: ParsedData) -> dict:
        counts = Counter(r.meta.get("complexity", "N/A") for r in data.rows)
        return dict(counts)

    def _fit_gap_analysis(self, data: ParsedData) -> dict:
        """FIT/GAP breakdown theo module."""
        result = {}
        for module in data.all_modules:
            rows = [r for r in data.rows if r.meta.get("module") == module]
            counts = Counter(r.meta.get("fit_gap", "N/A") for r in rows)
            result[module] = dict(counts)
        return result

    # ------------------------------------------------------------------
    # Giai đoạn progress
    # ------------------------------------------------------------------

    def _giai_doan_progress(self, data: ParsedData) -> dict:
        """
        % Closed theo giai đoạn × phase, dùng WEIGHTED_ALL pattern.

        Denominator = len(rows) của giai đoạn (KHÔNG phải total_with_status),
        để chart phản ánh đúng tiến độ: nếu 1 phase có 1 Closed + 40 phase blank
        thì pct = 1/41 ≈ 2%, KHÔNG phải 100%. Coi phase blank ("chưa làm") là
        chưa done — nhất quán với công thức `overall_progress_pct` weighted_all
        ở summary card.

        Trả thêm `total_with_status` để tooltip hiển thị được (VD "8/45 rows,
        tính trên tổng 45 function của giai đoạn").
        """
        result = {}
        for gd in data.all_giai_doan:
            rows = [r for r in data.rows if str(r.meta.get("giai_doan", "")) == gd]
            denom = len(rows)  # tổng function của giai đoạn — weighted_all
            result[gd] = {}
            for phase_name in data.all_phases:
                total_with_status = 0
                closed = 0
                for r in rows:
                    pd = r.phases.get(phase_name, PhaseData())
                    if pd.status:
                        total_with_status += 1
                        if pd.status == "Closed":
                            closed += 1
                pct = round(closed / denom * 100, 1) if denom > 0 else 0
                result[gd][phase_name] = {
                    "total": denom,
                    "total_with_status": total_with_status,
                    "closed": closed,
                    "pct": pct,
                }
        return result

    # ------------------------------------------------------------------
    # Phase progress stacked
    # ------------------------------------------------------------------

    def _phase_progress_stacked(self, data: ParsedData) -> dict:
        """Bar stacked số function từng status ở mỗi phase.

        Thêm bucket "(Blank)" để tổng mỗi phase = total functions. Trước
        đây bỏ qua row có phase status blank khiến Analysis chỉ 311 trong
        khi tổng function là 388 → user nhầm số. Blank ở đây có 2 nguồn:
        (a) phase không tồn tại trong row.phases, (b) phase tồn tại nhưng
        status chưa fill (rất phổ biến với các phase downstream chưa tới).
        """
        statuses_ordered = ["Closed", "In-progress", "Assigned", "Resolved", "Open", "Pending", "Cancelled", "(Blank)"]
        phase_data = {}
        total = len(data.rows)
        for phase_name in data.all_phases:
            counts = Counter()
            blank_count = 0
            for r in data.rows:
                pd = r.phases.get(phase_name, PhaseData())
                if pd.status:
                    counts[pd.status] += 1
                else:
                    blank_count += 1
            phase_data[phase_name] = {s: counts.get(s, 0) for s in statuses_ordered if s != "(Blank)"}
            phase_data[phase_name]["(Blank)"] = blank_count
            # Đảm bảo tổng = total; nếu lệch (do status không nằm trong
            # statuses_ordered — VD lỗi dữ liệu số 1/2/8) thì dồn vào Blank
            # để user vẫn thấy đúng total, tránh chart bị "hụt cột".
            summed = sum(phase_data[phase_name][s] for s in statuses_ordered)
            if summed < total:
                phase_data[phase_name]["(Blank)"] += (total - summed)

        return {
            "phases": data.all_phases,
            "statuses": statuses_ordered,
            "data": phase_data,
        }

    # ==================================================================
    # ============  V2 ADDITIONS (Advanced Analytics)  =================
    # ==================================================================

    # ------------------------------------------------------------------
    # B1 — Unassigned Tasks (task active nhưng không có PIC)
    # ------------------------------------------------------------------

    def _unassigned_tasks(self, data: ParsedData) -> list[dict]:
        """
        Danh sách phase thiếu PIC khi đã tới lượt.

        Tới lượt = in-scope + predecessor Closed (phase đầu: không cần pred)
        + Start đã đến (không Start: End đã đến hoặc status Open/Assigned/
        In-progress). Không flag khi Start còn tương lai.
        """
        from analyzer.unassigned import is_unassigned_phase
        from analyzer.rlog_weekly import _row_rlog_id

        results = []
        phase_order = data.all_phases
        for r in data.rows:
            rlog_id = _row_rlog_id(r) or ""
            for phase_name, pd in r.phases.items():
                if not is_unassigned_phase(
                    r, phase_name, pd, phase_order, self.today,
                ):
                    continue
                # Phase trước + start-gate — phục vụ cột Lý do export
                pred_phase = ""
                is_first = False
                try:
                    idx = phase_order.index(phase_name)
                    is_first = idx == 0
                    if idx > 0:
                        pred_phase = phase_order[idx - 1]
                except ValueError:
                    pass
                if pd.start_date is not None:
                    start_gate = "start"
                elif pd.end_date is not None and pd.end_date <= self.today:
                    start_gate = "end"
                else:
                    start_gate = "active_status"
                results.append({
                    "ma_cn": r.meta.get("ma_cn", ""),
                    "ten_cn": r.meta.get("ten_cn", ""),
                    "rlog_id": rlog_id,
                    "module": r.meta.get("module", ""),
                    "quy_trinh": r.meta.get("quy_trinh") or r.meta.get("process") or "",
                    "phase": phase_name,
                    "predecessor_phase": pred_phase,
                    "is_first_phase": is_first,
                    "start_date": pd.start_date.isoformat() if pd.start_date else "",
                    "start_gate": start_gate,
                    # Nếu status blank thì hiện "(chưa fill)" cho FE dễ hiểu
                    "status": pd.status or "(chưa fill status)",
                    "priority": r.meta.get("priority", ""),
                    "complexity": r.meta.get("complexity", ""),
                    "end_date": pd.end_date.isoformat() if pd.end_date else "",
                    "is_overdue": self._is_overdue(
                        pd, r, phase_name, data.all_phases,
                    ),
                    "days_overdue": (
                        (self.today - pd.end_date).days
                        if self._is_overdue(pd, r, phase_name, data.all_phases)
                        else 0
                    ),
                })
        # Sort: overdue trước, sau đó Must-have trước
        results.sort(key=lambda x: (
            0 if x["is_overdue"] else 1,
            0 if "Must" in (x.get("priority") or "") else 1,
            -x["days_overdue"],
        ))
        return results

    # ------------------------------------------------------------------
    # B2 — Duration Analysis (task kéo dài bất thường)
    # ------------------------------------------------------------------

    def _duration_analysis(self, data: ParsedData, threshold_days: int = 3) -> dict:
        """
        Phân tích duration của task:
        - Planned: có Start và End
        - Elapsed: đang In-progress, có Start, chưa có End → tính từ Start đến today
        Trả về: distribution theo phase + danh sách task > threshold + scatter data.
        """
        items = []
        durations_by_phase: dict[str, list[int]] = defaultdict(list)
        scatter_points = []  # {estimate_mh, duration, status, type}

        for r in data.rows:
            for phase_name, pd in r.phases.items():
                duration = None
                dur_type = None

                if pd.start_date and pd.end_date:
                    diff = (pd.end_date - pd.start_date).days
                    if diff >= 0:
                        duration = diff
                        dur_type = "planned"
                elif pd.start_date and not pd.end_date and pd.status == "In-progress":
                    diff = (self.today - pd.start_date).days
                    if diff >= 0:
                        duration = diff
                        dur_type = "elapsed"

                if duration is None:
                    continue

                durations_by_phase[phase_name].append(duration)

                # Scatter: chỉ lấy điểm có estimate MH
                if pd.estimate_mh is not None and pd.estimate_mh > 0:
                    scatter_points.append({
                        "estimate_mh": pd.estimate_mh,
                        "duration": duration,
                        "type": dur_type,
                        "status": pd.status,
                        "ma_cn": r.meta.get("ma_cn", ""),
                        "phase": phase_name,
                    })

                # Chi tiết: chỉ giữ task chưa Closed/Cancelled và > threshold
                if duration > threshold_days and pd.status not in ("Closed", "Cancelled"):
                    items.append({
                        "ma_cn": r.meta.get("ma_cn", ""),
                        "ten_cn": r.meta.get("ten_cn", ""),
                        "module": r.meta.get("module", ""),
                        "quy_trinh": r.meta.get("quy_trinh") or r.meta.get("process") or "",
                        "phase": phase_name,
                        "start_date": pd.start_date.isoformat() if pd.start_date else "",
                        "end_date": pd.end_date.isoformat() if pd.end_date else "",
                        "duration_days": duration,
                        "duration_type": dur_type,
                        "threshold_days": threshold_days,
                        "status": pd.status,
                        "pic": pd.pics,
                        "priority": r.meta.get("priority", ""),
                        "estimate_mh": pd.estimate_mh,
                    })

        items.sort(key=lambda x: x["duration_days"], reverse=True)

        # Distribution stats
        distribution = {}
        for phase, durs in durations_by_phase.items():
            if not durs:
                continue
            s = sorted(durs)
            n = len(s)
            distribution[phase] = {
                "min": s[0],
                "max": s[-1],
                "median": s[n // 2],
                "q1": s[max(0, n // 4)],
                "q3": s[min(n - 1, 3 * n // 4)],
                "avg": round(sum(s) / n, 1),
                "count": n,
            }

        over_3 = sum(1 for i in items if i["duration_days"] > 3)
        over_7 = sum(1 for i in items if i["duration_days"] > 7)
        all_durations = [d for lst in durations_by_phase.values() for d in lst]
        avg_all = round(sum(all_durations) / len(all_durations), 1) if all_durations else 0

        return {
            "threshold_days": threshold_days,
            "items": items,
            "distribution": distribution,
            "scatter": scatter_points,
            "summary": {
                "avg_duration": avg_all,
                "count_over_3": over_3,
                "count_over_7": over_7,
                "total_items": len(items),
            },
        }

    # ------------------------------------------------------------------
    # B3 — Stalled Tasks (bottleneck giữa 2 phase liên tiếp)
    # ------------------------------------------------------------------

    def _stalled_tasks(self, data: ParsedData) -> dict:
        """
        Function bị kẹt: phase trước Closed, phase sau None/Open **và đã tới Start**
        (Start tương lai → không đình trễ — PRM.FR.53).
        Bỏ qua function đã xong toàn trình (phase cuối Closed, hoặc mọi
        phase Closed/Cancelled). Kèm funnel Closed/phase + transition heatmap.
        """
        from analyzer.gantt_calendar import _is_outlier_date
        from analyzer.stalled import is_fully_closed, is_stalled_transition, prev_phases_all_closed

        items = []
        phase_names = [pg.name for pg in data.phase_groups]

        # Funnel: đếm số function đã Closed ở từng phase
        funnel = []
        for phase_name in phase_names:
            closed_count = sum(
                1 for r in data.rows
                if r.phases.get(phase_name) and r.phases[phase_name].status == "Closed"
            )
            funnel.append({"phase": phase_name, "closed": closed_count})

        # Detect stalled + transition matrix
        transition = defaultdict(int)  # (from_phase, to_phase) -> count stalled
        for r in data.rows:
            if is_fully_closed(r, phase_names):
                continue
            for i in range(len(phase_names) - 1):
                # Chỉ xét cặp (curr→next) khi mọi phase trước curr đã Closed.
                # Nếu phase đầu (VD Analysis) chưa Closed → bỏ qua mọi cặp tiếp.
                if not prev_phases_all_closed(r, phase_names, i):
                    continue

                curr = phase_names[i]
                nxt = phase_names[i + 1]
                curr_pd = r.phases.get(curr)
                next_pd = r.phases.get(nxt)

                if not is_stalled_transition(curr_pd, next_pd, self.today):
                    continue

                wait_days = 0
                # Bỏ date outlier (VD 1936-03-26) khi tính Chờ (ngày) —
                # cùng logic Gantt `_is_outlier_date`.
                if curr_pd.end_date and not _is_outlier_date(curr_pd.end_date, self.today):
                    wait_days = (self.today - curr_pd.end_date).days

                transition[(curr, nxt)] += 1

                items.append({
                    "ma_cn": r.meta.get("ma_cn", ""),
                    "ten_cn": r.meta.get("ten_cn", ""),
                    "module": r.meta.get("module", ""),
                    "quy_trinh": r.meta.get("quy_trinh") or r.meta.get("process") or "",
                    "completed_phase": curr,
                    "waiting_phase": nxt,
                    "completed_date": curr_pd.end_date.isoformat() if curr_pd.end_date else "",
                    "waiting_start_date": (
                        next_pd.start_date.isoformat()
                        if next_pd and next_pd.start_date else ""
                    ),
                    "waiting_end_date": (
                        next_pd.end_date.isoformat() if next_pd and next_pd.end_date else ""
                    ),
                    "waiting_status": (next_pd.status or "") if next_pd else "",
                    "wait_days": wait_days,
                    "priority": r.meta.get("priority", ""),
                })

        items.sort(key=lambda x: x["wait_days"], reverse=True)

        # Chuyển transition dict → list dễ render
        transition_list = [
            {"from": f, "to": t, "count": c}
            for (f, t), c in transition.items()
        ]

        return {
            "items": items,
            "funnel": funnel,
            "phases": phase_names,
            "transitions": transition_list,
        }

    # ------------------------------------------------------------------
    # B4 — Effort Analysis (Man-hour)
    # ------------------------------------------------------------------

    def _effort_analysis(self, data: ParsedData) -> dict:
        """
        Tổng hợp Estimate MH theo Module × Phase, theo PIC, và burndown.

        Chỉ dùng estimate_mh hợp lệ (parser đã set None nếu reject datetime/outlier).
        Đơn vị raw luôn là MH — FE convert sang MD/MM (1 MD = 8 MH, 1 MM = 22 MD).
        """
        module_phase_mh: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
        pic_mh: dict[str, dict[str, float]] = defaultdict(lambda: {"total": 0.0, "closed": 0.0, "remaining": 0.0})
        total_est = 0.0
        total_closed_mh = 0.0
        # Task chưa done (status not Closed/Cancelled) có estimate — cho FE mode "Chưa done"
        open_tasks: list[dict] = []
        done_statuses = {"Closed", "Cancelled"}

        for r in data.rows:
            module = r.meta.get("module") or "N/A"
            for phase_name, pd in r.phases.items():
                if pd.estimate_mh is None or pd.estimate_mh <= 0:
                    continue
                mh = float(pd.estimate_mh)
                module_phase_mh[module][phase_name] += mh
                total_est += mh
                is_closed = pd.status == "Closed"
                if is_closed:
                    total_closed_mh += mh
                # PIC breakdown
                if pd.pics:
                    share = mh / len(pd.pics)
                    for pic in pd.pics:
                        pic_mh[pic]["total"] += share
                        if is_closed:
                            pic_mh[pic]["closed"] += share
                        else:
                            pic_mh[pic]["remaining"] += share

                # Open tasks: chưa Closed/Cancelled, có estimate
                status = pd.status or ""
                if status not in done_statuses:
                    open_tasks.append({
                        "ma_cn": r.meta.get("ma_cn") or "",
                        "ten_cn": r.meta.get("ten_cn") or "",
                        "module": module,
                        "phase": phase_name,
                        "pic": list(pd.pics),
                        "status": status,
                        "end_date": pd.end_date.isoformat() if pd.end_date else "",
                        "estimate_mh": round(mh, 1),
                    })

        remaining_mh = total_est - total_closed_mh

        # Top PIC theo MH (giảm dần)
        pic_list = [
            {
                "pic": pic,
                "total_mh": round(v["total"], 1),
                "closed_mh": round(v["closed"], 1),
                "remaining_mh": round(v["remaining"], 1),
            }
            for pic, v in sorted(pic_mh.items(), key=lambda x: x[1]["total"], reverse=True)
        ]

        # Sort open tasks theo end_date (rỗng xuống cuối), rồi ma_cn
        def _open_sort_key(t: dict):
            ed = t.get("end_date") or "9999-99-99"
            return (ed, t.get("ma_cn") or "")

        open_tasks.sort(key=_open_sort_key)

        # Chuyển heatmap thành dict lồng
        heatmap = {
            m: {p: round(v, 1) for p, v in phases.items()}
            for m, phases in module_phase_mh.items()
        }

        return {
            "heatmap": heatmap,
            "modules": data.all_modules,
            "phases": data.all_phases,
            "by_pic": pic_list,
            "open_tasks_by_pic": open_tasks,
            "total_estimated": round(total_est, 1),
            "total_closed_mh": round(total_closed_mh, 1),
            "remaining_mh": round(remaining_mh, 1),
            "closed_pct": round(total_closed_mh / total_est * 100, 1) if total_est > 0 else 0,
        }

    # ------------------------------------------------------------------
    # B6 — Process Analysis (Quy trình)
    # ------------------------------------------------------------------

    def _process_analysis(self, data: ParsedData) -> list[dict]:
        """Group function theo Quy trình → % Closed, module liên quan, PIC chính.

        Sort: theo module_order (module đại diện) rồi tên process — để tiles
        «Phân tích theo Quy trình» group theo module rank.
        """
        from analyzer.module_order import process_module_rank, sort_modules

        process_map: dict[str, list[FunctionRow]] = defaultdict(list)
        for r in data.rows:
            qt = r.meta.get("quy_trinh")
            if qt:
                process_map[str(qt)].append(r)

        last_phase = data.all_phases[-1] if data.all_phases else None
        all_phases_cnt = len(data.all_phases)
        order = data.all_modules
        results = []
        for qt, rows in process_map.items():
            total = len(rows)
            modules = sort_modules(
                {r.meta.get("module") for r in rows if r.meta.get("module")},
                order,
            )
            overdue = sum(
                1 for r in rows if self._row_has_overdue(r, data.all_phases)
            )

            # % weighted_all: closed_records / (row × phase)
            if total > 0 and all_phases_cnt > 0:
                closed_records = sum(
                    1
                    for r in rows
                    for ph in data.all_phases
                    if r.phases.get(ph, PhaseData()).status == "Closed"
                )
                pct = round(closed_records / (total * all_phases_cnt) * 100, 1)
            else:
                pct = 0

            # PIC chính (top 3 xuất hiện nhiều nhất)
            pic_counter = Counter()
            for r in rows:
                for _, pd in r.phases.items():
                    for pic in pd.pics:
                        pic_counter[pic] += 1
            top_pics = [p for p, _ in pic_counter.most_common(3)]

            results.append({
                "process": qt,
                "total": total,
                "modules": modules,
                "pct_closed": pct,
                "overdue": overdue,
                "top_pics": top_pics,
            })

        results.sort(key=lambda x: (
            process_module_rank(x["modules"], order),
            x["process"],
        ))
        return results

    # ------------------------------------------------------------------
    # B5 — Timeline Data (Gantt style)
    # ------------------------------------------------------------------

    def _timeline_data(self, data: ParsedData) -> dict:
        """
        Trả dữ liệu cho Gantt-style timeline.

        Cấu trúc (Bug 1 rework — thêm function-level rows):
        - `data[module][phase]`: aggregate (giữ để tương thích test cũ + FE cũ)
        - `functions_by_module[module]`: list function detail
            {ma_cn, ten_cn, priority, has_overdue, phases: [
                {name, start, end, status, pics, overdue, pct}
            ]}
          → dùng cho Gantt mới: mỗi function 1 row, phase là segment.
        """
        result: dict[str, dict[str, dict]] = {}
        functions_by_module: dict[str, list[dict]] = {}

        for module in data.all_modules:
            result[module] = {}
            rows = [r for r in data.rows if r.meta.get("module") == module]

            # Aggregate cũ — giữ nguyên cho tests + fallback FE
            for phase_name in data.all_phases:
                starts = []
                ends = []
                total = 0
                closed = 0
                overdue = 0
                for r in rows:
                    pd = r.phases.get(phase_name)
                    if not pd:
                        continue
                    if pd.start_date:
                        starts.append(pd.start_date)
                    if pd.end_date:
                        ends.append(pd.end_date)
                    if pd.status:
                        total += 1
                        if pd.status == "Closed":
                            closed += 1
                    if self._is_overdue(pd, r, phase_name, data.all_phases):
                        overdue += 1

                if starts and ends:
                    result[module][phase_name] = {
                        "start": min(starts).isoformat(),
                        "end": max(ends).isoformat(),
                        "total": total,
                        "closed": closed,
                        "overdue": overdue,
                        "pct_closed": round(closed / total * 100, 1) if total > 0 else 0,
                    }

            # Function-level detail — chỉ include function có ít nhất 1 phase có date
            func_list = []
            for r in rows:
                phase_segments = []
                has_overdue = False
                for phase_name in data.all_phases:
                    pd = r.phases.get(phase_name)
                    if pd is None:
                        continue
                    # Bỏ qua phase không có bất kỳ date/status nào (chưa touch)
                    if not pd.start_date and not pd.end_date and not pd.status:
                        continue
                    is_od = self._is_overdue(pd, r, phase_name, data.all_phases)
                    if is_od:
                        has_overdue = True
                    phase_segments.append({
                        "name": phase_name,
                        "start": pd.start_date.isoformat() if pd.start_date else None,
                        "end": pd.end_date.isoformat() if pd.end_date else None,
                        "status": pd.status,
                        "pics": pd.pics,
                        "overdue": is_od,
                    })
                if not phase_segments:
                    continue
                func_list.append({
                    "ma_cn": r.meta.get("ma_cn", ""),
                    "ten_cn": r.meta.get("ten_cn", ""),
                    "priority": r.meta.get("priority", ""),
                    "quy_trinh": r.meta.get("quy_trinh", ""),
                    "has_overdue": has_overdue,
                    "phases": phase_segments,
                })
            # Sort: function có overdue lên đầu, sau đó theo mã CN
            func_list.sort(key=lambda x: (not x["has_overdue"], x["ma_cn"]))
            functions_by_module[module] = func_list

        # Group theo quy trình (cho Gantt mode "process")
        functions_by_process: dict[str, list[dict]] = {}
        for module, func_list in functions_by_module.items():
            for f in func_list:
                proc = f.get("quy_trinh") or "N/A"
                entry = dict(f)
                entry["module"] = module
                functions_by_process.setdefault(proc, []).append(entry)
        for proc in functions_by_process:
            functions_by_process[proc].sort(key=lambda x: (not x["has_overdue"], x["ma_cn"]))

        return {
            "today": self.today.isoformat(),
            "modules": data.all_modules,
            "phases": data.all_phases,
            "data": result,
            "functions_by_module": functions_by_module,
            "functions_by_process": functions_by_process,
            "processes": sorted(functions_by_process.keys()),
            "total_functions": sum(len(v) for v in functions_by_module.values()),
        }

    def _burndown_velocity(self, data: ParsedData) -> dict:
        from analyzer.advanced_metrics import compute_burndown_velocity
        return compute_burndown_velocity(data, self.today)

    def _sla_violations(self, data: ParsedData) -> dict:
        from analyzer.advanced_metrics import compute_sla_violations
        return compute_sla_violations(data, self.today)

    def _slow_heatmap(self, data: ParsedData) -> dict:
        from analyzer.advanced_metrics import compute_slow_heatmap
        return compute_slow_heatmap(data, self.today)

    def _dependency_blockers(self, data: ParsedData) -> dict:
        from analyzer.advanced_metrics import compute_dependency_blockers
        return compute_dependency_blockers(data)

    def _baseline_variance(self, data: ParsedData) -> dict:
        from analyzer.advanced_metrics import compute_baseline_variance
        return compute_baseline_variance(data)

    def _rlog_weekly(self, data: ParsedData) -> dict:
        """Rlog coded tuần này + kế hoạch Dev tuần tới (ISO week)."""
        from analyzer.rlog_weekly import compute_rlog_weekly
        return compute_rlog_weekly(data, today=self.today)

    # ==================================================================
    # ============  END V2 ADDITIONS  ==================================
    # ==================================================================

    # ------------------------------------------------------------------
    # Helper methods
    # ------------------------------------------------------------------

    def _is_overdue(
        self,
        pd: PhaseData,
        row: FunctionRow | None = None,
        phase_name: str | None = None,
        phase_order: list[str] | None = None,
    ) -> bool:
        """
        Kiểm tra phase data có overdue không.

        Định nghĩa (theo .cursorrules):
          - Có End date
          - End date < today
          - Status KHÔNG phải "Closed" hoặc "Cancelled"

        Note: Status = None/blank vẫn tính là OVERDUE nếu có End < today.
        Ngoại lệ: status blank nhưng phase SAU đã Closed/Cancelled → không
        overdue (false positive sync API, VD TMS.FR.84 UAT blank + Golive Closed).
        """
        return is_phase_overdue(
            pd, self.today,
            row=row, phase_name=phase_name, phase_order=phase_order,
        )

    def _is_phase_active(self, pd: PhaseData) -> bool:
        """Phase in-scope — ủy quyền ``analyzer.unassigned.is_phase_in_scope``."""
        from analyzer.unassigned import is_phase_in_scope
        return is_phase_in_scope(pd)

    def _row_has_overdue(
        self,
        row: FunctionRow,
        phase_order: list[str] | None = None,
    ) -> bool:
        """Kiểm tra function row có bất kỳ phase nào overdue."""
        return row_has_overdue(row, self.today, phase_order)

    def _group_by_module(self, data: ParsedData) -> dict[str, list[FunctionRow]]:
        result = defaultdict(list)
        for r in data.rows:
            m = r.meta.get("module")
            if m:
                result[m].append(r)
        return result

    def _detect_active_phase(self, rows: list[FunctionRow], all_phases: list[str]) -> str:
        """
        Tìm phase đang active nhất trong module.
        - Nếu tất cả function đã Closed phase cuối → "✓ Hoàn thành"
        - Nếu chưa bắt đầu (phase nào cũng chưa có status) → "Chưa bắt đầu"
        - Ngược lại: phase có nhiều task chưa Closed nhất
        """
        if not all_phases:
            return ""

        # Kiểm tra "hoàn thành hết" ở phase cuối
        last_phase = all_phases[-1]
        all_last_closed = all(
            r.phases.get(last_phase, PhaseData()).status == "Closed"
            for r in rows
        ) if rows else False
        if all_last_closed:
            return "✓ Hoàn thành"

        # Đếm phase active
        phase_active_count = Counter()
        has_any_status = False
        for r in rows:
            for phase_name in all_phases:
                pd = r.phases.get(phase_name, PhaseData())
                if pd.status:
                    has_any_status = True
                if pd.status and pd.status not in ("Closed", "Cancelled"):
                    phase_active_count[phase_name] += 1

        if not has_any_status:
            return "Chưa bắt đầu"
        if phase_active_count:
            return phase_active_count.most_common(1)[0][0]
        # Có status nhưng tất cả đều Closed/Cancelled (không đủ phase cuối)
        return "Đang hoàn tất"
