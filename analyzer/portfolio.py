"""
Portfolio module — Cross-project search / compare / rollup.

3 chức năng chính:
1. `search_across_projects` — Text search trên tất cả project (theo mã CN, tên,
   PIC, quy trình). Dùng cho global search bar ở top header.
2. `compare_projects` — Trả bảng metrics side-by-side của 2-4 project để so sánh.
3. `aggregate_rollup` — Gộp N project thành 1 virtual ParsedData để chạy
   DashboardEngine bình thường + thêm per-project breakdown cho 2 chart mới.

Design decisions:
- Inject `state_loader` (Callable[[str], Optional[dict]]) để test mock được +
  app.py dùng lại `_get_state` (đã có cache in-memory).
- `state_loader` trả `{"data": ParsedData, "metrics": dict, ...}` hoặc None nếu
  project chưa upload file → skip silent, log vào `skipped_projects`.
- Không sửa `DashboardEngine._structure_info` (bị cấm trong ranh giới scope).
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from parser.excel_parser import ParsedData, PhaseGroup, FunctionRow, PhaseData


# Type alias cho state loader: slug → state dict (hoặc None nếu chưa upload).
# State dict phải có ít nhất "data" (ParsedData); "metrics" là optional (nếu None
# thì portfolio.py có thể compute lại từ data).
StateLoader = Callable[[str], Optional[dict]]


# Danh sách scope hợp lệ cho search
SEARCH_SCOPES = ("name", "code", "pic", "process", "all")

# Giới hạn kết quả search mặc định (an toàn cho payload FE)
DEFAULT_SEARCH_LIMIT = 50


# ==========================================================================
# Dataclasses cho type safety
# ==========================================================================

@dataclass
class SearchResult:
    """1 kết quả search — đại diện 1 function trong 1 project."""
    project_slug: str
    project_name: str
    ma_cn: str
    ten_cn: str
    module: str
    quy_trinh: str
    active_phase: str        # Phase đang active (chưa Closed/Cancelled) đầu tiên
    pic: list[str]           # PIC gộp từ tất cả phase (dedupe)
    overdue_flag: bool
    matched_field: str       # "name" | "code" | "pic" | "process"

    def to_dict(self) -> dict:
        return {
            "project_slug": self.project_slug,
            "project_name": self.project_name,
            "ma_cn": self.ma_cn,
            "ten_cn": self.ten_cn,
            "module": self.module,
            "quy_trinh": self.quy_trinh,
            "active_phase": self.active_phase,
            "pic": self.pic,
            "overdue_flag": self.overdue_flag,
            "matched_field": self.matched_field,
        }


# ==========================================================================
# Search
# ==========================================================================

def search_across_projects(
    project_mgr,
    state_loader: StateLoader,
    query: str,
    scope: str = "all",
    limit: int = DEFAULT_SEARCH_LIMIT,
    include_archived: bool = False,
) -> dict:
    """
    Search text `query` qua tất cả project. Case-insensitive, substring match.

    Args:
        project_mgr: ProjectManager instance
        state_loader: callable(slug) → state dict {"data": ParsedData, ...} | None
        query: từ khoá (trim + lower trước khi match)
        scope: "name" | "code" | "pic" | "process" | "all"
        limit: giới hạn kết quả trả về (mặc định 50)
        include_archived: có search project bị archive không

    Returns:
        dict {
            "results": list[SearchResult.to_dict()],
            "total": int,          # tổng kết quả trước khi cắt limit
            "projects_searched": int,
            "projects_skipped": list[{slug, reason}],
            "truncated": bool,     # True nếu total > limit
        }
    """
    query = (query or "").strip().lower()
    if not query:
        return {
            "results": [],
            "total": 0,
            "projects_searched": 0,
            "projects_skipped": [],
            "truncated": False,
        }
    if scope not in SEARCH_SCOPES:
        scope = "all"

    projects = project_mgr.list_projects(include_archived=include_archived)
    results: list[SearchResult] = []
    skipped: list[dict] = []
    searched = 0

    for proj in projects:
        state = state_loader(proj.slug)
        if state is None or state.get("data") is None:
            skipped.append({"slug": proj.slug, "reason": "no_file"})
            continue
        searched += 1
        data: ParsedData = state["data"]

        for row in data.rows:
            match_field = _row_matches(row, query, scope)
            if not match_field:
                continue
            results.append(_row_to_search_result(row, proj, data, match_field))

    total = len(results)
    truncated = total > limit
    if truncated:
        # Sort để kết quả ổn định: overdue lên đầu, sau đó theo project + mã CN
        results.sort(key=lambda r: (not r.overdue_flag, r.project_slug, r.ma_cn))
        results = results[:limit]
    else:
        results.sort(key=lambda r: (not r.overdue_flag, r.project_slug, r.ma_cn))

    return {
        "results": [r.to_dict() for r in results],
        "total": total,
        "projects_searched": searched,
        "projects_skipped": skipped,
        "truncated": truncated,
    }


def _row_matches(row: FunctionRow, q: str, scope: str) -> Optional[str]:
    """Return matched_field ('name'|'code'|'pic'|'process') hoặc None."""
    ma_cn = str(row.meta.get("ma_cn") or "").lower()
    ten_cn = str(row.meta.get("ten_cn") or "").lower()
    quy_trinh = str(row.meta.get("quy_trinh") or "").lower()

    if scope in ("code", "all") and ma_cn and q in ma_cn:
        return "code"
    if scope in ("name", "all") and ten_cn and q in ten_cn:
        return "name"
    if scope in ("process", "all") and quy_trinh and q in quy_trinh:
        return "process"
    if scope in ("pic", "all"):
        for pd in row.phases.values():
            for pic in pd.pics:
                if q in pic.lower():
                    return "pic"
    return None


def _row_to_search_result(
    row: FunctionRow, proj, data: ParsedData, matched: str
) -> SearchResult:
    """Convert FunctionRow → SearchResult (gộp PIC + tìm active phase)."""
    all_pics = set()
    active_phase = ""
    has_overdue = False
    from datetime import date
    today = date.today()

    for phase_name in data.all_phases:
        pd = row.phases.get(phase_name)
        if not pd:
            continue
        all_pics.update(pd.pics)
        # Active phase = phase đầu tiên có status ≠ Closed/Cancelled
        if not active_phase and pd.status and pd.status not in ("Closed", "Cancelled"):
            active_phase = phase_name
        # Overdue check
        if pd.end_date and pd.end_date < today and pd.status not in ("Closed", "Cancelled", None):
            has_overdue = True

    return SearchResult(
        project_slug=proj.slug,
        project_name=proj.name,
        ma_cn=str(row.meta.get("ma_cn") or ""),
        ten_cn=str(row.meta.get("ten_cn") or ""),
        module=str(row.meta.get("module") or ""),
        quy_trinh=str(row.meta.get("quy_trinh") or ""),
        active_phase=active_phase,
        pic=sorted(all_pics),
        overdue_flag=has_overdue,
        matched_field=matched,
    )


# ==========================================================================
# Compare
# ==========================================================================

# Tên metric hiển thị + direction: True = càng cao càng tốt, False = càng thấp
# càng tốt. Dùng cho FE highlight best/worst.
COMPARE_METRICS: list[tuple[str, str, bool]] = [
    # (key, label, higher_is_better)
    ("total_functions",     "Tổng function",       True),
    ("overall_progress_pct", "Tiến độ (%)",         True),
    ("total_overdue",        "Overdue",             False),
    ("unassigned_count",     "Chưa PIC",            False),
    ("high_risk_count",      "High risk",           False),
    ("stalled_count",        "Stalled",             False),
    ("modules_count",        "Số Module",           True),
    ("processes_count",      "Số Quy trình",        True),
    ("pics_count",           "Số PIC",              True),
    ("last_phase_name",      "Phase cuối",          None),   # None = không đánh giá
]


def compare_projects(
    project_mgr,
    state_loader: StateLoader,
    slugs: list[str],
) -> dict:
    """
    Compare 2-4 project side-by-side.

    Args:
        project_mgr: ProjectManager
        state_loader: callable(slug) → state dict
        slugs: list slug cần so sánh (bỏ trùng, giữ thứ tự)

    Returns:
        dict {
            "projects": [{slug, name, ...}],       # metadata các project được compare
            "metrics": {                            # metric_key → {slug: value, ...}
                "total_functions": {"a": 100, "b": 200},
                ...
            },
            "metric_labels": [{key, label, higher_is_better}],  # cho FE render
            "best_worst": {                         # slug tốt/tệ nhất cho mỗi metric
                "total_functions": {"best": "b", "worst": "a"},
                ...
            },
            "skipped": [{slug, reason}],
        }
    """
    # Dedupe giữ thứ tự
    seen = set()
    slugs_ordered = []
    for s in slugs:
        if s and s not in seen:
            seen.add(s)
            slugs_ordered.append(s)

    projects_meta = []
    metrics: dict[str, dict[str, Any]] = {k: {} for k, _, _ in COMPARE_METRICS}
    skipped: list[dict] = []

    for slug in slugs_ordered:
        proj = project_mgr.get_project(slug)
        if proj is None:
            skipped.append({"slug": slug, "reason": "not_found"})
            continue
        state = state_loader(slug)
        if state is None or state.get("data") is None:
            skipped.append({"slug": slug, "reason": "no_file"})
            continue

        data: ParsedData = state["data"]
        m = state.get("metrics") or _compute_metrics_fallback(data)
        summary = m.get("summary", {})
        stalled = m.get("stalled_tasks", {})
        stalled_items = stalled.get("items", []) if isinstance(stalled, dict) else []

        projects_meta.append({
            "slug": proj.slug,
            "name": proj.name,
            "description": proj.description,
            "is_archived": proj.is_archived,
        })

        metrics["total_functions"][slug] = summary.get("total_functions", 0)
        metrics["overall_progress_pct"][slug] = summary.get("overall_progress_pct", 0)
        metrics["total_overdue"][slug] = summary.get("total_overdue", 0)
        metrics["unassigned_count"][slug] = summary.get("unassigned_count", 0)
        metrics["high_risk_count"][slug] = summary.get("high_risk_count", 0)
        metrics["stalled_count"][slug] = len(stalled_items)
        metrics["modules_count"][slug] = summary.get("modules_count", 0)
        metrics["processes_count"][slug] = len(data.all_processes)
        metrics["pics_count"][slug] = len(data.all_pics)
        metrics["last_phase_name"][slug] = summary.get("last_phase_name", "")

    # Tính best/worst cho mỗi metric (chỉ metric có higher_is_better != None)
    best_worst: dict[str, dict[str, str]] = {}
    for key, _, higher_better in COMPARE_METRICS:
        if higher_better is None:
            continue
        vals = metrics[key]
        # Chỉ so sánh trên số (bỏ str, None)
        numeric = {s: v for s, v in vals.items() if isinstance(v, (int, float))}
        if len(numeric) < 2:
            continue
        max_slug = max(numeric, key=numeric.get)
        min_slug = min(numeric, key=numeric.get)
        # Nếu tất cả bằng nhau thì không highlight
        if numeric[max_slug] == numeric[min_slug]:
            continue
        best_worst[key] = {
            "best": max_slug if higher_better else min_slug,
            "worst": min_slug if higher_better else max_slug,
        }

    return {
        "projects": projects_meta,
        "metrics": metrics,
        "metric_labels": [
            {"key": k, "label": lbl, "higher_is_better": hib}
            for k, lbl, hib in COMPARE_METRICS
        ],
        "best_worst": best_worst,
        "skipped": skipped,
    }


def _compute_metrics_fallback(data: ParsedData) -> dict:
    """
    Nếu state không có sẵn metrics → tự compute bằng DashboardEngine.
    Chỉ dùng trong hoàn cảnh test/edge — thực tế app.py luôn có cache metrics.
    """
    from analyzer.dashboard_engine import DashboardEngine
    return DashboardEngine().compute_all(data)


# ==========================================================================
# Rollup
# ==========================================================================

def aggregate_rollup(
    project_mgr,
    state_loader: StateLoader,
    slugs: Optional[list[str]] = None,
    include_archived: bool = False,
) -> dict:
    """
    Gộp N project thành 1 virtual ParsedData + tính per-project stats.

    Behavior:
    - `slugs=None` hoặc rỗng → dùng tất cả project non-archived (mặc định).
    - `slugs` explicit → dùng đúng list đó (kể cả archived nếu user chọn).
    - Project chưa upload → skip silent.

    Aggregation:
    - Rows: concat theo thứ tự slug. Thêm `_project_slug` + `_project_name` vào
      `row.meta` để FE biết row thuộc project nào.
    - Phase groups: union theo tên phase (giữ thứ tự xuất hiện lần đầu). Nếu 2
      project có cùng tên phase nhưng khác attribute → merge attributes (giữ
      col_idx của project đầu tiên).
    - Rows của project A không có phase của project B → PhaseData rỗng (không
      crash DashboardEngine).

    Returns:
        dict {
            "aggregated": ParsedData,               # virtual data, chạy được engine
            "per_project": [                         # cho 2 chart mới
                {"slug", "name", "total", "progress_pct", "overdue", "unassigned",
                 "high_risk", "on_time"}
            ],
            "skipped": [{slug, reason}],
            "projects_count": int,                   # số project đã aggregate
        }
    """
    if slugs:
        # Explicit slugs — dedupe, giữ thứ tự
        seen = set()
        target = []
        for s in slugs:
            if s and s not in seen:
                seen.add(s)
                target.append(s)
    else:
        # Default: all non-archived
        target = [p.slug for p in project_mgr.list_projects(include_archived=include_archived)]

    combined_rows: list[FunctionRow] = []
    phase_group_map: dict[str, PhaseGroup] = {}   # phase_name → merged PhaseGroup
    phase_order: list[str] = []
    per_project: list[dict] = []
    skipped: list[dict] = []

    # Tổng offset row_num để tránh trùng row_num giữa các project (FE có thể dùng)
    row_num_offset = 0

    for slug in target:
        proj = project_mgr.get_project(slug)
        if proj is None:
            skipped.append({"slug": slug, "reason": "not_found"})
            continue
        state = state_loader(slug)
        if state is None or state.get("data") is None:
            skipped.append({"slug": slug, "reason": "no_file"})
            continue

        data: ParsedData = state["data"]

        # Copy rows với meta enriched
        for row in data.rows:
            new_meta = dict(row.meta)
            new_meta["_project_slug"] = proj.slug
            new_meta["_project_name"] = proj.name
            new_row = FunctionRow(
                row_num=row.row_num + row_num_offset,
                meta=new_meta,
                phases=dict(row.phases),  # shallow copy, PhaseData vẫn share (OK vì read-only)
            )
            combined_rows.append(new_row)

        # Offset lớn để tránh trùng (10000 = đủ cho tất cả use case thực tế)
        row_num_offset += max(len(data.rows) * 2, 10000)

        # Merge phase groups
        for pg in data.phase_groups:
            if pg.name not in phase_group_map:
                phase_order.append(pg.name)
                phase_group_map[pg.name] = PhaseGroup(
                    name=pg.name,
                    attributes=dict(pg.attributes),  # copy để không mutate gốc
                )
            # Nếu đã có, giữ attributes cũ (project đầu tiên win — đơn giản, không
            # cần rename column khi conflict)

        # Per-project stats — dùng metrics đã cache nếu có
        m = state.get("metrics") or _compute_metrics_fallback(data)
        summary = m.get("summary", {})
        total = summary.get("total_functions", len(data.rows))
        overdue = summary.get("total_overdue", 0)
        per_project.append({
            "slug": proj.slug,
            "name": proj.name,
            "total": total,
            "progress_pct": summary.get("overall_progress_pct", 0),
            "overdue": overdue,
            "on_time": max(0, total - overdue),
            "unassigned": summary.get("unassigned_count", 0),
            "high_risk": summary.get("high_risk_count", 0),
        })

    # Xây ParsedData virtual
    merged_phase_groups = [phase_group_map[n] for n in phase_order]

    # Recompute các all_* fields từ combined_rows
    all_modules = sorted({str(r.meta.get("module") or "") for r in combined_rows if r.meta.get("module")})
    all_priorities = sorted({str(r.meta.get("priority") or "") for r in combined_rows if r.meta.get("priority")})
    all_complexities = sorted({str(r.meta.get("complexity") or "") for r in combined_rows if r.meta.get("complexity")})
    all_giai_doan = sorted({str(r.meta.get("giai_doan") or "") for r in combined_rows if r.meta.get("giai_doan")})
    all_processes = sorted({str(r.meta.get("quy_trinh") or "") for r in combined_rows if r.meta.get("quy_trinh")})

    pics_set: set[str] = set()
    statuses_set: set[str] = set()
    for r in combined_rows:
        for pd in r.phases.values():
            pics_set.update(pd.pics)
            if pd.status:
                statuses_set.add(pd.status)

    aggregated = ParsedData(
        headers={},                    # không dùng khi aggregate
        meta_columns={},
        phase_groups=merged_phase_groups,
        rows=combined_rows,
        all_modules=all_modules,
        all_phases=phase_order,
        all_pics=sorted(pics_set),
        all_statuses=sorted(statuses_set),
        all_priorities=all_priorities,
        all_complexities=all_complexities,
        all_giai_doan=all_giai_doan,
        all_processes=all_processes,
        pic_blacklisted=[],            # rollup không track blacklist (data-quality)
        estimate_mh_rejected=[],       # rollup không track estimate reject
    )

    return {
        "aggregated": aggregated,
        "per_project": per_project,
        "skipped": skipped,
        "projects_count": len(per_project),
    }


def rollup_summary_override(rollup_result: dict, engine_metrics: dict) -> dict:
    """
    Override 1 số field trong `engine_metrics["summary"]` cho phù hợp với ngữ
    cảnh rollup:
    - `overall_progress_pct` — dùng weighted average theo total function của
      từng project (fair hơn "% closed union last_phase" khi phase_groups khác).
    - Thêm field `projects_count`, `projects_included` cho FE.

    Args:
        rollup_result: kết quả từ `aggregate_rollup`
        engine_metrics: kết quả `DashboardEngine.compute_all(aggregated)`

    Returns:
        Bản copy của engine_metrics với summary đã override.
    """
    per_project = rollup_result.get("per_project", [])
    total_all = sum(p["total"] for p in per_project)
    if total_all > 0:
        weighted_pct = sum(p["progress_pct"] * p["total"] for p in per_project) / total_all
        weighted_pct = round(weighted_pct, 1)
    else:
        weighted_pct = 0

    # Shallow copy để không mutate metrics gốc (có thể được cache)
    new_metrics = dict(engine_metrics)
    new_summary = dict(engine_metrics.get("summary", {}))
    new_summary["overall_progress_pct"] = weighted_pct
    new_summary["projects_count"] = rollup_result.get("projects_count", 0)
    new_summary["projects_included"] = [p["slug"] for p in per_project]
    # Note: last_phase_name khi rollup là "union", nghĩa mờ → set thành empty
    # để FE hiển thị "Weighted avg" thay vì tên phase.
    new_summary["last_phase_name"] = ""
    new_metrics["summary"] = new_summary
    return new_metrics
