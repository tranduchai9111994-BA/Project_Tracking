"""
Dashboard Engine — Tính toán tất cả metrics từ ParsedData.
Trả về dict JSON-serializable để gửi cho frontend.
"""
from collections import Counter, defaultdict
from datetime import date
from typing import Any

from parser.excel_parser import ParsedData, FunctionRow, PhaseData


class DashboardEngine:
    """Tính toán các dashboard metrics."""

    def __init__(self, today: date | None = None, long_duration_threshold: int = 3):
        self.today = today or date.today()
        self.long_duration_threshold = long_duration_threshold

    def compute_all(self, data: ParsedData) -> dict[str, Any]:
        """Entry point: tính tất cả metrics."""
        # Import cục bộ để tránh circular
        from analyzer.risk_scorer import compute_all_risk_scores

        risk_scores = compute_all_risk_scores(data, self.today, self.long_duration_threshold)

        return {
            "structure": self._structure_info(data),
            "summary": self._summary(data, risk_scores),
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
            "stalled_tasks": self._stalled_tasks(data),
            "risk_scores": risk_scores,
            "effort_analysis": self._effort_analysis(data),
            "process_analysis": self._process_analysis(data),
            "timeline_data": self._timeline_data(data),
            # === Upgrade Wave P4–P5 ===
            "burndown_velocity": self._burndown_velocity(data),
            "sla_violations": self._sla_violations(data),
            "slow_heatmap": self._slow_heatmap(data),
            "dependency_blockers": self._dependency_blockers(data),
            "baseline_variance": self._baseline_variance(data),
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

        return {
            "all_modules": data.all_modules,
            "all_phases": data.all_phases,
            "all_pics": data.all_pics,
            "all_statuses": data.all_statuses,
            "all_priorities": data.all_priorities,
            "all_complexities": data.all_complexities,
            "all_giai_doan": data.all_giai_doan,
            "all_processes": data.all_processes,
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
        overdue_functions = sum(1 for r in data.rows if self._row_has_overdue(r))
        overdue_records = 0
        for r in data.rows:
            for _, pd in r.phases.items():
                if self._is_overdue(pd):
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
        unassigned_functions = 0
        unassigned_records = 0
        for r in data.rows:
            func_has_unassigned = False
            for _, pd in r.phases.items():
                if pd.status and pd.status not in ("Closed", "Cancelled") and not pd.pics:
                    unassigned_records += 1
                    func_has_unassigned = True
            if func_has_unassigned:
                unassigned_functions += 1

        # ==== High-risk (>= 50 điểm) ====
        high_risk_count = 0
        if risk_scores:
            high_risk_count = sum(1 for r in risk_scores if r["risk_score"] >= 50)

        return {
            "total_functions": total,
            "total_overdue": overdue_functions,          # legacy: dùng cho card
            "total_overdue_records": overdue_records,    # phase-level, dùng cho bảng
            "overall_progress_pct": overall_pct,         # weighted: closed_records / (row × phase)
            "last_phase_progress_pct": last_phase_pct,   # % Closed ở phase cuối (metric phụ)
            "last_phase_name": last_phase or "",
            "progress_formula": "weighted_all",           # để FE biết cách hiển thị/giải thích
            "modules_count": len(data.all_modules),
            "phases_count": len(data.all_phases),
            "unassigned_count": unassigned_functions,    # đổi ngữ nghĩa: giờ là số function unique
            "unassigned_records": unassigned_records,    # phase-level
            "high_risk_count": high_risk_count,
        }

    # ------------------------------------------------------------------
    # Module overview (Bảng A)
    # ------------------------------------------------------------------

    def _module_overview(self, data: ParsedData) -> list[dict]:
        result = []
        module_rows = self._group_by_module(data)
        last_phase = data.all_phases[-1] if data.all_phases else None

        for idx, module in enumerate(data.all_modules, 1):
            rows = module_rows.get(module, [])
            total = len(rows)

            # Đếm quy trình unique
            quy_trinh_set = {r.meta.get("quy_trinh") for r in rows if r.meta.get("quy_trinh")}
            quy_trinh_count = len(quy_trinh_set)

            # % weighted_all: closed_records / (row × phase)
            all_phases_cnt = len(data.all_phases)
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

            # Phase đang active nhiều nhất (trạng thái chung)
            active_phase = self._detect_active_phase(rows, data.all_phases)

            # Đếm overdue
            overdue_in_module = sum(1 for r in rows if self._row_has_overdue(r))

            result.append({
                "stt": idx,
                "module": module,
                "total": total,
                "quy_trinh_count": quy_trinh_count,
                "progress_pct": progress_pct,
                "active_phase": active_phase,
                "overdue_count": overdue_in_module,
            })

        return result

    # ------------------------------------------------------------------
    # Phase × Status matrix
    # ------------------------------------------------------------------

    def _phase_status_matrix(self, data: ParsedData) -> dict:
        matrix = {}
        all_statuses_ordered = ["Closed", "In-progress", "Assigned", "Resolved", "Open", "Pending", "Cancelled"]

        for module in data.all_modules:
            matrix[module] = {}
            rows = [r for r in data.rows if r.meta.get("module") == module]
            total_rows = len(rows)

            for phase_name in data.all_phases:
                status_counts = Counter()
                total_with_status = 0
                for r in rows:
                    pd = r.phases.get(phase_name, PhaseData())
                    if pd.status:
                        status_counts[pd.status] += 1
                        total_with_status += 1

                closed = status_counts.get("Closed", 0)
                # weighted_all: denominator = total_rows (không phải total_with_status).
                # Phase blank = "chưa làm" → đếm vào mẫu số → không bị 100% giả.
                pct_closed = round(closed / total_rows * 100, 1) if total_rows > 0 else 0

                matrix[module][phase_name] = {
                    "total": total_rows,                    # tổng rows CÓ THỂ có phase này
                    "total_with_status": total_with_status, # rows đã điền status (info phụ)
                    "pct_closed": pct_closed,
                    **{s: status_counts.get(s, 0) for s in all_statuses_ordered},
                }

        return {
            "phases": data.all_phases,
            "modules": data.all_modules,
            "statuses": all_statuses_ordered,
            "data": matrix,
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

        # Tính % closed mỗi module × task_type (weighted_all).
        # Denominator = len(rows_module) × len(phases_for_tt) — coi phase blank là chưa làm.
        by_module = {}
        for module in data.all_modules:
            rows = [r for r in data.rows if r.meta.get("module") == module]
            by_module[module] = {}
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
                by_module[module][tt] = pct

        return {
            "task_types": task_types,
            "task_phase_map": {k: v for k, v in task_phase_map.items()},
            "by_module": by_module,
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

                    if self._is_overdue(pd):
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
        for r in data.rows:
            for phase_name, pd in r.phases.items():
                if self._is_overdue(pd):
                    days = (self.today - pd.end_date).days
                    overdue_items.append({
                        "stt": r.meta.get("stt", r.row_num),
                        "ma_cn": r.meta.get("ma_cn", ""),
                        "ten_cn": r.meta.get("ten_cn", ""),
                        "module": r.meta.get("module", ""),
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
        statuses_ordered = ["Closed", "In-progress", "Assigned", "Resolved", "Open", "Pending", "Cancelled"]
        phase_data = {}
        for phase_name in data.all_phases:
            counts = Counter()
            for r in data.rows:
                pd = r.phases.get(phase_name, PhaseData())
                if pd.status:
                    counts[pd.status] += 1
            phase_data[phase_name] = {s: counts.get(s, 0) for s in statuses_ordered}

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
        """Danh sách phase đang active (status ≠ Closed/Cancelled) mà không có PIC."""
        results = []
        for r in data.rows:
            for phase_name, pd in r.phases.items():
                if pd.status and pd.status not in ("Closed", "Cancelled"):
                    if not pd.pics:
                        results.append({
                            "ma_cn": r.meta.get("ma_cn", ""),
                            "ten_cn": r.meta.get("ten_cn", ""),
                            "module": r.meta.get("module", ""),
                            "phase": phase_name,
                            "status": pd.status,
                            "priority": r.meta.get("priority", ""),
                            "complexity": r.meta.get("complexity", ""),
                            "end_date": pd.end_date.isoformat() if pd.end_date else "",
                            "is_overdue": self._is_overdue(pd),
                            "days_overdue": (self.today - pd.end_date).days if self._is_overdue(pd) else 0,
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
                        "phase": phase_name,
                        "start_date": pd.start_date.isoformat() if pd.start_date else "",
                        "end_date": pd.end_date.isoformat() if pd.end_date else "",
                        "duration_days": duration,
                        "duration_type": dur_type,
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
        Function bị kẹt: phase trước Closed nhưng phase sau vẫn None/Open.
        Kèm funnel data (số function Closed mỗi phase) và transition heatmap.
        """
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
            for i in range(len(phase_names) - 1):
                curr = phase_names[i]
                nxt = phase_names[i + 1]
                curr_pd = r.phases.get(curr)
                next_pd = r.phases.get(nxt)

                curr_done = curr_pd and curr_pd.status == "Closed"
                next_not_started = (not next_pd) or (next_pd.status in (None, "Open"))

                if curr_done and next_not_started:
                    wait_days = 0
                    if curr_pd.end_date:
                        wait_days = (self.today - curr_pd.end_date).days

                    transition[(curr, nxt)] += 1

                    items.append({
                        "ma_cn": r.meta.get("ma_cn", ""),
                        "ten_cn": r.meta.get("ten_cn", ""),
                        "module": r.meta.get("module", ""),
                        "completed_phase": curr,
                        "waiting_phase": nxt,
                        "completed_date": curr_pd.end_date.isoformat() if curr_pd.end_date else "",
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
        """Group function theo Quy trình → % Closed, module liên quan, PIC chính."""
        process_map: dict[str, list[FunctionRow]] = defaultdict(list)
        for r in data.rows:
            qt = r.meta.get("quy_trinh")
            if qt:
                process_map[str(qt)].append(r)

        last_phase = data.all_phases[-1] if data.all_phases else None
        all_phases_cnt = len(data.all_phases)
        results = []
        for qt, rows in process_map.items():
            total = len(rows)
            modules = sorted({r.meta.get("module") for r in rows if r.meta.get("module")})
            overdue = sum(1 for r in rows if self._row_has_overdue(r))

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

        results.sort(key=lambda x: (-x["total"], x["process"]))
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
                    if self._is_overdue(pd):
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
                    is_od = self._is_overdue(pd)
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

    # ==================================================================
    # ============  END V2 ADDITIONS  ==================================
    # ==================================================================

    # ------------------------------------------------------------------
    # Helper methods
    # ------------------------------------------------------------------

    def _is_overdue(self, pd: PhaseData) -> bool:
        """Kiểm tra phase data có overdue không."""
        if pd.end_date is None:
            return False
        if pd.status in ("Closed", "Cancelled", None):
            return False
        return pd.end_date < self.today

    def _row_has_overdue(self, row: FunctionRow) -> bool:
        """Kiểm tra function row có bất kỳ phase nào overdue."""
        return any(self._is_overdue(pd) for pd in row.phases.values())

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
