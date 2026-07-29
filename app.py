"""
iHRP Function List Tracker — Flask Server (V2 + Projects)

V2 features:
- Advanced analytics: Unassigned, Duration, Stalled, Risk Score, Effort, Process, Timeline
- Snapshot & Compare mode per project
- Multi-project support: mỗi khách hàng/dự án 1 workspace riêng
- Auto-migrate snapshot cũ vào project "Default"
- Cross-project compare (Phase 2)
- Export/Import project package (zip)
- Multi-sheet export, export-by-PIC, export-compare
- Trim response payload cho tốc độ (top N items thay vì all)
"""
import io
import os
import sys
import shutil
import tempfile
import zipfile
from datetime import date, datetime
from typing import Any, Optional

from flask import Flask, jsonify, render_template, request, send_file

from parser.excel_parser import FunctionListParser
from analyzer.dashboard_engine import DashboardEngine
from analyzer.snapshot_manager import SnapshotManager
from analyzer.compare_engine import CompareEngine
from analyzer.project_manager import ProjectManager, Project
from analyzer.drill_down import drill_down as drill_down_fn, build_title as build_drill_title, SUPPORTED_CHARTS
from analyzer.portfolio import (
    search_across_projects,
    compare_projects,
    aggregate_rollup,
    rollup_summary_override,
    SEARCH_SCOPES,
)
from exporter.excel_exporter import (
    export_overdue_report,
    export_full_report,
    export_by_pic,
    export_compare_report,
    export_drill_down,
    export_pic_blacklist_report,
    export_portfolio_compare,
    export_chart,
    export_audit_report,
    export_sla_report,
    export_capacity_report,
    export_slow_heatmap_report,
    export_baseline_variance_report,
    export_fitgap_report,
    export_function_diff_report,
    SUPPORTED_EXPORT_CHARTS,
)

app = Flask(__name__)
app.config["UPLOAD_FOLDER"] = os.path.join(os.path.dirname(__file__), "uploads")
app.config["PROJECTS_FOLDER"] = os.path.join(app.config["UPLOAD_FOLDER"], "projects")
app.config["MAX_CONTENT_LENGTH"] = 50 * 1024 * 1024  # 50MB

os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)
os.makedirs(app.config["PROJECTS_FOLDER"], exist_ok=True)

# --------------------------------------------------------------------------
# Cache-busting cho static assets — mtime của file thành ?v= query param.
# Khi dev sửa dashboard.js / style.css, mtime đổi → browser tự fetch bản mới,
# tránh bug UI "hiện số 0" do trình duyệt cache JS/CSS cũ.
# --------------------------------------------------------------------------
_STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")


def _static_ver(rel_path: str) -> str:
    """Trả về mtime của file static để làm cache-busting query param."""
    full = os.path.join(_STATIC_DIR, rel_path.replace("/", os.sep))
    try:
        return str(int(os.path.getmtime(full)))
    except OSError:
        return "0"


@app.context_processor
def _inject_static_ver():
    return {"static_ver": _static_ver}

# ==========================================================================
# Global state — mỗi project 1 slot, cache metrics trong memory
# ==========================================================================
# App chạy local single-user nên dict trong memory là đủ.
# Cache TTL implicit: cho đến khi user upload file mới hoặc chuyển project.
_state: dict[str, dict[str, Any]] = {}
# _state[slug] = {"data": ParsedData, "metrics": dict, "filename": str, "upload_time": datetime}

_project_mgr = ProjectManager(app.config["PROJECTS_FOLDER"])
# Đảm bảo tồn tại project "default" ngay khi khởi động
_project_mgr.get_or_create_default()

# Phase 7 Slim: dọn export cũ + giới hạn snapshot khi start
try:
    from analyzer.disk_janitor import purge_old_exports, purge_excess_snapshots
    _n_exp = purge_old_exports(app.config["PROJECTS_FOLDER"], max_age_days=7)
    _n_snap = 0
    for _slug_name in os.listdir(app.config["PROJECTS_FOLDER"]):
        _snap_dir = os.path.join(app.config["PROJECTS_FOLDER"], _slug_name, "snapshots")
        _n_snap += purge_excess_snapshots(_snap_dir, keep=15)
    if _n_exp or _n_snap:
        print(f"[janitor] Đã xóa {_n_exp} export cũ, {_n_snap} snapshot thừa", file=sys.stderr)
except Exception as _janitor_err:
    print(f"[janitor] Bỏ qua: {_janitor_err}", file=sys.stderr)


# ==========================================================================
# Helpers
# ==========================================================================

# Trim payload để response nhẹ hơn ~40%. Frontend chỉ cần top N cho card overview.
PAYLOAD_LIMITS = {
    "risk_scores": 50,           # frontend hiển thị top 20
    "duration_items": 200,       # bảng chi tiết
    "stalled_items": 200,
    "unassigned_tasks": 300,     # bảng dài nhất, cần pagination FE
}


def _trim_payload(metrics: dict) -> dict:
    """
    Trả về bản copy metrics đã trim để giảm bandwidth.
    Tổng items và list gốc vẫn còn ở backend cho endpoint chi tiết.
    """
    trimmed = dict(metrics)  # shallow copy

    # Trim risk_scores → top 50
    rs = metrics.get("risk_scores")
    if isinstance(rs, list) and len(rs) > PAYLOAD_LIMITS["risk_scores"]:
        trimmed["risk_scores"] = rs[:PAYLOAD_LIMITS["risk_scores"]]
        trimmed["risk_scores_total"] = len(rs)

    # Trim duration_analysis.items → top 200
    da = metrics.get("duration_analysis")
    if isinstance(da, dict):
        items = da.get("items", [])
        if len(items) > PAYLOAD_LIMITS["duration_items"]:
            da_copy = dict(da)
            da_copy["items"] = items[:PAYLOAD_LIMITS["duration_items"]]
            da_copy["items_total"] = len(items)
            trimmed["duration_analysis"] = da_copy

    # Trim stalled_tasks.items → top 200
    st = metrics.get("stalled_tasks")
    if isinstance(st, dict):
        items = st.get("items", [])
        if len(items) > PAYLOAD_LIMITS["stalled_items"]:
            st_copy = dict(st)
            st_copy["items"] = items[:PAYLOAD_LIMITS["stalled_items"]]
            st_copy["items_total"] = len(items)
            trimmed["stalled_tasks"] = st_copy

    # Trim unassigned_tasks → top 300
    ua = metrics.get("unassigned_tasks", [])
    if isinstance(ua, list) and len(ua) > PAYLOAD_LIMITS["unassigned_tasks"]:
        trimmed["unassigned_tasks"] = ua[:PAYLOAD_LIMITS["unassigned_tasks"]]
        trimmed["unassigned_tasks_total"] = len(ua)

    return trimmed


def _resolve_slug(explicit_slug: Optional[str] = None) -> str:
    """
    Trả về slug hiện hành:
    - Nếu có explicit → dùng nó nếu tồn tại
    - Nếu không → query param `project` → default
    """
    if explicit_slug:
        if _project_mgr.project_exists(explicit_slug):
            return explicit_slug
        raise ValueError(f"Không tìm thấy project: {explicit_slug}")

    q = request.args.get("project")
    if q and _project_mgr.project_exists(q):
        return q
    return "default"


def _load_state_from_disk(slug: str) -> Optional[dict]:
    """
    Load state từ snapshot mới nhất của project nếu có, hoặc current.xlsx.
    Dùng khi server restart mà chưa upload lại.
    """
    proj = _project_mgr.get_project(slug)
    if not proj:
        return None

    # Ưu tiên current.xlsx
    current_path = _project_mgr.get_current_file_path(slug)
    file_to_load = None
    filename = "current.xlsx"
    if os.path.isfile(current_path):
        file_to_load = current_path
    else:
        # Fallback: snapshot mới nhất
        smgr = _project_mgr.get_snapshot_manager(slug)
        snaps = smgr.list_snapshots()
        if snaps:
            latest = snaps[0]
            file_to_load = os.path.join(smgr.dir, latest["filename"])
            filename = latest["filename"]

    if not file_to_load or not os.path.isfile(file_to_load):
        return None

    try:
        data = FunctionListParser().parse(file_to_load)
        metrics = DashboardEngine().compute_all(data)
        return {
            "data": data,
            "metrics": metrics,
            "filename": filename,
            "upload_time": datetime.fromtimestamp(os.path.getmtime(file_to_load)),
        }
    except Exception as e:
        # Log để user/dev thấy được lý do state không load được, tránh 404 im lặng
        import sys
        print(
            f"[project={slug}] Không load được state từ '{file_to_load}': "
            f"{type(e).__name__}: {e}",
            file=sys.stderr,
        )
        return None


def _get_state(slug: str) -> Optional[dict]:
    """Lấy state (memory hoặc load from disk). Return None nếu chưa upload."""
    if slug in _state:
        return _state[slug]
    loaded = _load_state_from_disk(slug)
    if loaded:
        _state[slug] = loaded
    return loaded


def _need_state(slug: str):
    """Helper: nếu chưa có state → trả về error response."""
    st = _get_state(slug)
    if st is None:
        return None, (
            jsonify({
                "error": f"Project '{slug}' chưa có file. Upload Function List trước.",
                "code": "NO_FILE",
            }),
            404,
        )
    return st, None


def _filter_parsed_data(
    data,
    modules: Optional[list[str]] = None,
    processes: Optional[list[str]] = None,
    pics: Optional[list[str]] = None,
    # Backward compat: 2 kwargs cũ (single string) — Wave 1 API + tests cũ
    module: str = "",
    process: str = "",
):
    """
    Tạo bản sao ParsedData chỉ chứa rows match module/process/pic filter.

    Semantics:
    - OR trong 1 chiều filter (VD: modules=[A,B] → module ∈ {A,B})
    - AND giữa các chiều (modules AND processes AND pics)
    - PIC match: row match nếu BẤT KỲ phase nào của row có PIC ∈ pics

    Args:
        data: ParsedData gốc
        modules: list module cần lọc (None/empty = không lọc chiều này)
        processes: list quy trình cần lọc
        pics: list PIC cần lọc
        module, process: legacy single-value (Wave 1) — auto convert sang list

    Returns:
        ParsedData mới với subset rows (giữ nguyên phase structure).
    """
    from parser.excel_parser import ParsedData

    # Merge legacy single-value vào list (backward compat với call site cũ + tests cũ)
    mod_list = list(modules) if modules else []
    if module:
        mod_list.append(module)
    proc_list = list(processes) if processes else []
    if process:
        proc_list.append(process)
    pic_list = list(pics) if pics else []

    # Dedupe + loại rỗng
    mod_set = {m for m in mod_list if m}
    proc_set = {p for p in proc_list if p}
    pic_set = {p for p in pic_list if p}

    if not mod_set and not proc_set and not pic_set:
        return data  # short-circuit — không lọc

    def _match(row) -> bool:
        # AND giữa các chiều, OR trong mỗi chiều
        if mod_set and row.meta.get("module", "") not in mod_set:
            return False
        if proc_set and row.meta.get("quy_trinh", "") not in proc_set:
            return False
        if pic_set:
            # Row match nếu có ÍT NHẤT 1 phase chứa ÍT NHẤT 1 PIC thuộc pic_set
            row_pics = set()
            for pd in row.phases.values():
                row_pics.update(pd.pics)
            if not (row_pics & pic_set):
                return False
        return True

    filtered_rows = [r for r in data.rows if _match(r)]

    # Recompute all_* fields (nhưng giữ nguyên phases từ data gốc để chart cấu trúc không đổi)
    all_modules = sorted({r.meta.get("module", "") for r in filtered_rows if r.meta.get("module")})
    all_priorities = sorted({r.meta.get("priority", "") for r in filtered_rows if r.meta.get("priority")})
    all_complexities = sorted({r.meta.get("complexity", "") for r in filtered_rows if r.meta.get("complexity")})
    all_giai_doan = sorted({str(r.meta.get("giai_doan", "")) for r in filtered_rows if r.meta.get("giai_doan")})
    all_processes = sorted({r.meta.get("quy_trinh", "") for r in filtered_rows if r.meta.get("quy_trinh")})

    pics_out = set()
    statuses_set = set()
    for r in filtered_rows:
        for pd in r.phases.values():
            pics_out.update(pd.pics)
            if pd.status:
                statuses_set.add(pd.status)

    return ParsedData(
        headers=data.headers,
        meta_columns=data.meta_columns,
        phase_groups=data.phase_groups,
        rows=filtered_rows,
        all_modules=all_modules,
        all_phases=data.all_phases,  # phase structure không đổi
        all_pics=sorted(pics_out),
        all_statuses=sorted(statuses_set),
        all_priorities=all_priorities,
        all_complexities=all_complexities,
        all_giai_doan=all_giai_doan,
        all_processes=all_processes,
        # Giữ data-quality log nhưng chỉ entry thuộc rows còn lại sau filter
        pic_blacklisted=_filter_dq_log(
            getattr(data, "pic_blacklisted", []) or [], filtered_rows
        ),
        estimate_mh_rejected=_filter_dq_log(
            getattr(data, "estimate_mh_rejected", []) or [], filtered_rows
        ),
    )


def _filter_dq_log(items: list[dict], filtered_rows) -> list[dict]:
    """Lọc data-quality log theo row_index còn lại sau filter rows."""
    keep_rows = {r.row_num for r in filtered_rows}
    return [it for it in items if it.get("row_index") in keep_rows]


def _project_to_dict(p: Project) -> dict:
    """Serialize Project + thêm số snapshot cho FE hiển thị nhanh."""
    smgr = _project_mgr.get_snapshot_manager(p.slug)
    snap_count = len(smgr.list_snapshots())
    return {
        "slug": p.slug,
        "name": p.name,
        "description": p.description,
        "created_at": p.created_at,
        "last_upload_at": p.last_upload_at,
        "is_archived": p.is_archived,
        "tags": p.tags,
        "snapshot_count": snap_count,
    }


# ==========================================================================
# Frontend routing
# ==========================================================================

@app.route("/")
def index():
    return render_template("index.html")


# ==========================================================================
# Project CRUD
# ==========================================================================

@app.route("/api/projects", methods=["GET"])
def list_projects():
    """Danh sách project. Query ?include_archived=1 để hiện cả archived."""
    include_archived = request.args.get("include_archived") in ("1", "true", "yes")
    projects = _project_mgr.list_projects(include_archived=include_archived)
    return jsonify({
        "success": True,
        "projects": [_project_to_dict(p) for p in projects],
    })


@app.route("/api/projects", methods=["POST"])
def create_project():
    """Tạo project mới. Body JSON: {name, description}"""
    body = request.get_json(silent=True) or {}
    name = body.get("name", "").strip()
    desc = body.get("description", "").strip()
    if not name:
        return jsonify({"error": "Tên project không được rỗng"}), 400
    try:
        proj = _project_mgr.create_project(name, desc)
        return jsonify({"success": True, "project": _project_to_dict(proj)}), 201
    except ValueError as e:
        return jsonify({"error": str(e)}), 400


@app.route("/api/projects/<slug>", methods=["GET"])
def get_project(slug):
    proj = _project_mgr.get_project(slug)
    if not proj:
        return jsonify({"error": "Không tìm thấy project"}), 404
    return jsonify({"success": True, "project": _project_to_dict(proj)})


@app.route("/api/projects/<slug>", methods=["PUT"])
def rename_project(slug):
    """Rename hoặc update description. Body: {name, description}."""
    body = request.get_json(silent=True) or {}
    name = body.get("name", "").strip()
    desc = body.get("description")
    if not name:
        return jsonify({"error": "Tên project không được rỗng"}), 400
    ok = _project_mgr.rename_project(slug, name, desc)
    if not ok:
        return jsonify({"error": "Không tìm thấy project"}), 404
    return jsonify({"success": True, "project": _project_to_dict(_project_mgr.get_project(slug))})


@app.route("/api/projects/<slug>", methods=["DELETE"])
def delete_project(slug):
    """
    Xóa project. Query ?soft=1 → chỉ archive (khôi phục được).
    Không xóa được 'default' để tránh mất state.
    """
    if slug == "default":
        return jsonify({"error": "Không được xóa project 'default'"}), 400
    soft = request.args.get("soft") in ("1", "true", "yes")
    if soft:
        ok = _project_mgr.archive_project(slug, True)
    else:
        ok = _project_mgr.delete_project(slug)
        _state.pop(slug, None)  # Xóa cache
    if not ok:
        return jsonify({"error": "Không tìm thấy project"}), 404
    return jsonify({"success": True})


@app.route("/api/projects/<slug>/restore", methods=["POST"])
def restore_project(slug):
    ok = _project_mgr.archive_project(slug, False)
    if not ok:
        return jsonify({"error": "Không tìm thấy project"}), 404
    return jsonify({"success": True})


# ==========================================================================
# Upload & core metrics (per-project)
# ==========================================================================

def _upload_and_process(slug: str) -> tuple:
    """
    Nội bộ: nhận multipart/form-data với file, xử lý và lưu state.
    Return: (response_json, status_code)
    """
    if "file" not in request.files:
        return jsonify({"error": "Không tìm thấy file trong request"}), 400

    file = request.files["file"]
    if not file.filename:
        return jsonify({"error": "Chưa chọn file"}), 400

    if not file.filename.lower().endswith((".xlsx", ".xls")):
        return jsonify({"error": "Chỉ hỗ trợ file .xlsx"}), 400

    threshold = request.args.get("threshold", default=3, type=int)

    # Lưu vào current.xlsx của project
    filepath = _project_mgr.get_current_file_path(slug)
    file.save(filepath)

    try:
        parser = FunctionListParser()
        data = parser.parse(filepath)

        engine = DashboardEngine(long_duration_threshold=threshold)
        metrics = engine.compute_all(data)

        upload_time = datetime.now()
        _state[slug] = {
            "data": data,
            "metrics": metrics,
            "filename": file.filename,
            "upload_time": upload_time,
        }

        # Auto lưu snapshot vào folder snapshots của project
        smgr = _project_mgr.get_snapshot_manager(slug)
        smgr.save_snapshot(filepath, data, metrics)

        # Cập nhật last_upload_at cho project
        _project_mgr.touch_last_upload(slug)

        # Upload history (meta only) + soft validation warnings
        from analyzer import project_store as ps
        from analyzer.audit_report import build_audit_issues
        import hashlib
        checksum = ""
        try:
            with open(filepath, "rb") as _bf:
                checksum = hashlib.md5(_bf.read()).hexdigest()
        except OSError:
            pass
        folder = _project_mgr.get_project_folder(slug)
        ps.append_upload_history(
            folder,
            filename=file.filename,
            row_count=len(data.rows),
            checksum=checksum,
            extra={
                "modules": len(data.all_modules),
                "phases": len(data.all_phases),
            },
        )

        warnings: list[dict] = []
        if len(data.rows) == 0:
            warnings.append({"level": "critical", "code": "empty_rows", "message": "File không có dòng chức năng nào"})
        if not data.all_phases:
            warnings.append({"level": "critical", "code": "no_phases", "message": "Không phát hiện phase group nào (pattern 'Phase - Attr')"})
        rej = getattr(data, "estimate_mh_rejected", []) or []
        if data.rows and len(rej) / max(len(data.rows), 1) > 0.1:
            warnings.append({
                "level": "warning",
                "code": "estimate_reject_rate",
                "message": f"{len(rej)} giá trị Estimate MH bị loại (>10% số function)",
            })
        try:
            audit = build_audit_issues(data, metrics)
            if audit["summary"].get("missing_meta_count", 0) > 0:
                warnings.append({
                    "level": "info",
                    "code": "missing_meta",
                    "message": f"{audit['summary']['missing_meta_count']} function thiếu meta (module/priority/...)",
                })
        except Exception:
            pass

        settings = ps.load_project_settings(folder)

        return jsonify({
            "success": True,
            "project": _project_to_dict(_project_mgr.get_project(slug)),
            "filename": file.filename,
            "rows_count": len(data.rows),
            "upload_time": upload_time.isoformat(),
            "metrics": _trim_payload(metrics),
            "snapshots": smgr.list_snapshots(),
            # Số token PIC bị parser blacklist — FE hiển thị badge count.
            # Không nằm trong metrics vì blacklist là data-quality info,
            # không cascade theo global filter.
            "pic_blacklist_count": len(getattr(data, "pic_blacklisted", []) or []),
            "warnings": warnings,
            "settings": settings,
        })
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"error": f"Lỗi khi parse file: {str(e)}"}), 500


@app.route("/api/projects/<slug>/upload", methods=["POST"])
def upload_to_project(slug):
    """Upload xlsx vào project cụ thể."""
    if not _project_mgr.project_exists(slug):
        return jsonify({"error": "Không tìm thấy project"}), 404
    result = _upload_and_process(slug)
    return result if isinstance(result, tuple) else result


@app.route("/api/upload", methods=["POST"])
def upload_legacy():
    """Legacy: upload không chỉ định project → project 'default'."""
    slug = request.args.get("project", "default")
    if not _project_mgr.project_exists(slug):
        _project_mgr.get_or_create_default()
        slug = "default"
    return _upload_and_process(slug)


def _parse_multi_arg(name: str) -> list[str]:
    """
    Parse query param dạng multi-value. Hỗ trợ CẢ 2 pattern (tương thích ngược):
    - Repeated: ?module=A&module=B
    - Comma-separated: ?module=A,B,C
    - Kết hợp: ?module=A,B&module=C  → [A, B, C]
    Trim + dedupe (giữ thứ tự xuất hiện lần đầu để URL của user không bị đảo).
    """
    raw_values = request.args.getlist(name)
    result: list[str] = []
    seen = set()
    for raw in raw_values:
        # 1 item có thể chứa comma → split thêm
        for part in raw.split(","):
            v = part.strip()
            if v and v not in seen:
                seen.add(v)
                result.append(v)
    return result


@app.route("/api/projects/<slug>/dashboard")
def dashboard_of_project(slug):
    st, err = _need_state(slug)
    if err:
        return err

    # Global filter (module / quy trình / pic) — multi-value, comma-separated hoặc repeated
    fmodules = _parse_multi_arg("module")
    fprocesses = _parse_multi_arg("process")
    fpics = _parse_multi_arg("pic")

    if fmodules or fprocesses or fpics:
        filtered_data = _filter_parsed_data(
            st["data"],
            modules=fmodules,
            processes=fprocesses,
            pics=fpics,
        )
        engine = DashboardEngine()
        metrics = engine.compute_all(filtered_data)
        applied_filter = {
            "modules": fmodules,
            "processes": fprocesses,
            "pics": fpics,
            "row_count": len(filtered_data.rows),
        }
    else:
        metrics = st["metrics"]
        applied_filter = None

    return jsonify({
        "success": True,
        "project": _project_to_dict(_project_mgr.get_project(slug)),
        "filename": st["filename"],
        "upload_time": st["upload_time"].isoformat() if st["upload_time"] else None,
        "metrics": _trim_payload(metrics),
        "snapshots": _project_mgr.get_snapshot_manager(slug).list_snapshots(),
        "applied_filter": applied_filter,
        # Count blacklist luôn tính từ st["data"] (parsed data gốc, không filter),
        # để badge count nhất quán khi user đổi filter.
        "pic_blacklist_count": len(getattr(st["data"], "pic_blacklisted", []) or []),
    })


@app.route("/api/dashboard")
def dashboard_legacy():
    """Legacy: dashboard mặc định = project 'default'."""
    try:
        slug = _resolve_slug()
    except ValueError as e:
        return jsonify({"error": str(e)}), 404
    return dashboard_of_project(slug)


# ==========================================================================
# Advanced analytics (per-project + legacy fallback)
# ==========================================================================

def _apply_list_filters(items: list, filter_map: dict) -> list:
    """Filter list of dicts theo dict {key: value}, bỏ qua value falsy."""
    result = items
    for k, v in filter_map.items():
        if not v:
            continue
        if k == "pic":
            result = [i for i in result if v in i.get("pic", [])]
        elif k == "min_days":
            try:
                min_v = int(v)
                result = [i for i in result if i.get("days_overdue", 0) >= min_v]
            except (TypeError, ValueError):
                pass
        else:
            result = [i for i in result if i.get(k) == v]
    return result


@app.route("/api/projects/<slug>/overdue")
@app.route("/api/overdue")
def get_overdue(slug=None):
    """Overdue full list (chưa trim). Support paginate qua ?limit=&offset=."""
    try:
        slug = slug or _resolve_slug()
    except ValueError as e:
        return jsonify({"error": str(e)}), 404
    st, err = _need_state(slug)
    if err:
        return err

    overdue = st["metrics"].get("overdue_list", [])
    filters = {
        "module": request.args.get("module"),
        "pic": request.args.get("pic"),
        "phase": request.args.get("phase"),
        "min_days": request.args.get("min_days"),
    }
    overdue = _apply_list_filters(overdue, filters)

    total = len(overdue)
    limit = request.args.get("limit", type=int)
    offset = request.args.get("offset", default=0, type=int)
    if limit:
        overdue = overdue[offset:offset + limit]

    return jsonify({"success": True, "overdue": overdue, "total": total, "offset": offset})


@app.route("/api/projects/<slug>/unassigned")
@app.route("/api/unassigned")
def get_unassigned(slug=None):
    """Unassigned với pagination."""
    try:
        slug = slug or _resolve_slug()
    except ValueError as e:
        return jsonify({"error": str(e)}), 404
    st, err = _need_state(slug)
    if err:
        return err

    items = st["metrics"].get("unassigned_tasks", [])
    filters = {"module": request.args.get("module"), "phase": request.args.get("phase")}
    items = _apply_list_filters(items, filters)

    total = len(items)
    limit = request.args.get("limit", type=int)
    offset = request.args.get("offset", default=0, type=int)
    if limit:
        items = items[offset:offset + limit]

    return jsonify({"success": True, "items": items, "total": total, "offset": offset})


@app.route("/api/projects/<slug>/long-duration")
@app.route("/api/long-duration")
def get_long_duration(slug=None):
    try:
        slug = slug or _resolve_slug()
    except ValueError as e:
        return jsonify({"error": str(e)}), 404
    st, err = _need_state(slug)
    if err:
        return err
    return jsonify({"success": True, "data": st["metrics"].get("duration_analysis", {})})


@app.route("/api/projects/<slug>/stalled")
@app.route("/api/stalled")
def get_stalled(slug=None):
    try:
        slug = slug or _resolve_slug()
    except ValueError as e:
        return jsonify({"error": str(e)}), 404
    st, err = _need_state(slug)
    if err:
        return err
    return jsonify({"success": True, "data": st["metrics"].get("stalled_tasks", {})})


@app.route("/api/projects/<slug>/risk-scores")
@app.route("/api/risk-scores")
def get_risk_scores(slug=None):
    try:
        slug = slug or _resolve_slug()
    except ValueError as e:
        return jsonify({"error": str(e)}), 404
    st, err = _need_state(slug)
    if err:
        return err
    all_scores = st["metrics"].get("risk_scores", [])
    top = request.args.get("top", default=20, type=int)
    items = all_scores[:top]
    return jsonify({"success": True, "items": items, "total": len(all_scores)})


# ==========================================================================
# Drill-Down — click biểu đồ → list function chi tiết + export Excel
# ==========================================================================

def _parse_drill_filters(source: dict) -> dict:
    """Extract các filter key hợp lệ từ query string hoặc JSON body."""
    # BUG FIX: thiếu 'task_type', 'ma_cn', 'level' → drill task_type / risk / timeline
    # nhận filters rỗng, trả 0 items. Bổ sung mọi filter key mà analyzer/drill_down.py cần.
    valid_keys = (
        "module", "phase", "status", "pic", "priority",
        "complexity", "fit_gap", "giai_doan", "process",
        "task_type", "ma_cn", "level",
    )
    return {k: source.get(k, "") for k in valid_keys if source.get(k, "") != ""}


@app.route("/api/projects/<slug>/drill-down")
@app.route("/api/drill-down")
def drill_down_endpoint(slug=None):
    """
    GET params:
      - chart: 1 trong SUPPORTED_CHARTS
      - filters: module, phase, status, pic, priority, complexity, fit_gap, giai_doan, process
    Trả: {items: [...], total: N, title: "..."}
    """
    try:
        slug = slug or _resolve_slug()
    except ValueError as e:
        return jsonify({"error": str(e)}), 404
    st, err = _need_state(slug)
    if err:
        return err

    chart = request.args.get("chart", "")
    if chart not in SUPPORTED_CHARTS:
        return jsonify({
            "error": f"Chart không hỗ trợ: '{chart}'. Supported: {list(SUPPORTED_CHARTS)}"
        }), 400

    filters = _parse_drill_filters(request.args)
    # Global filter (từ filter bar chính) — pre-filter data trước khi run drill.
    # Prefix "_g_" để không conflict với chart-specific filter (VD `module` là chart filter).
    data_scoped = _apply_global_filter_from_request(st["data"], request.args)
    try:
        items = drill_down_fn(data_scoped, chart, filters)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400

    title = build_drill_title(chart, filters)
    return jsonify({
        "success": True,
        "chart": chart,
        "filters": filters,
        "title": title,
        "items": items,
        "total": len(items),
    })


def _apply_global_filter_from_request(data, source):
    """Đọc _g_module / _g_process / _g_pic từ query string hoặc dict → apply _filter_parsed_data."""
    def _mv(key: str) -> list[str]:
        # Hỗ trợ cả query args (getlist) lẫn plain dict (comma-split)
        if hasattr(source, "getlist"):
            vals = source.getlist(key)
        else:
            raw = source.get(key, "")
            vals = [raw] if isinstance(raw, str) else list(raw or [])
        out = []
        for v in vals:
            for part in str(v).split(","):
                part = part.strip()
                if part:
                    out.append(part)
        return out

    g_modules = _mv("_g_module")
    g_processes = _mv("_g_process")
    g_pics = _mv("_g_pic")
    if not (g_modules or g_processes or g_pics):
        return data
    return _filter_parsed_data(
        data,
        modules=g_modules,
        processes=g_processes,
        pics=g_pics,
    )


@app.route("/api/projects/<slug>/drill-down/export", methods=["POST"])
@app.route("/api/drill-down/export", methods=["POST"])
def drill_down_export(slug=None):
    """
    POST JSON: {chart, filters: {...}}
    Trả file Excel .xlsx.
    """
    try:
        slug = slug or _resolve_slug()
    except ValueError as e:
        return jsonify({"error": str(e)}), 404
    st, err = _need_state(slug)
    if err:
        return err

    body = request.get_json(silent=True) or {}
    chart = body.get("chart", "")
    if chart not in SUPPORTED_CHARTS:
        return jsonify({
            "error": f"Chart không hỗ trợ: '{chart}'. Supported: {list(SUPPORTED_CHARTS)}"
        }), 400

    filters = _parse_drill_filters(body.get("filters", {}))
    # Global filter (từ body.global_filter — FE gửi khi export)
    gf = body.get("global_filter", {}) or {}
    data_scoped = _apply_global_filter_from_request(st["data"], {
        "_g_module": gf.get("modules", []),
        "_g_process": gf.get("processes", []),
        "_g_pic": gf.get("pics", []),
    })
    try:
        items = drill_down_fn(data_scoped, chart, filters)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400

    title = build_drill_title(chart, filters)
    filepath = export_drill_down(
        items,
        title=title,
        subtitle=f"Project: {slug} | Tổng: {len(items)} function",
        output_dir=_project_mgr.get_export_dir(slug),
    )
    return send_file(filepath, as_attachment=True, download_name=os.path.basename(filepath))


# ==========================================================================
# Snapshot & Compare (per-project + cross-project)
# ==========================================================================

@app.route("/api/projects/<slug>/snapshots", methods=["GET"])
@app.route("/api/snapshots", methods=["GET"])
def list_snapshots(slug=None):
    try:
        slug = slug or _resolve_slug()
    except ValueError as e:
        return jsonify({"error": str(e)}), 404
    smgr = _project_mgr.get_snapshot_manager(slug)
    return jsonify({"success": True, "snapshots": smgr.list_snapshots()})


@app.route("/api/projects/<slug>/snapshots/<snapshot_date>", methods=["DELETE"])
@app.route("/api/snapshots/<snapshot_date>", methods=["DELETE"])
def delete_snapshot(snapshot_date: str, slug=None):
    try:
        slug = slug or _resolve_slug()
    except ValueError as e:
        return jsonify({"error": str(e)}), 404
    smgr = _project_mgr.get_snapshot_manager(slug)
    ok = smgr.delete_snapshot(snapshot_date)
    if not ok:
        return jsonify({"error": "Không tìm thấy snapshot"}), 404
    return jsonify({"success": True, "snapshots": smgr.list_snapshots()})


@app.route("/api/projects/<slug>/compare")
@app.route("/api/compare")
def compare_snapshots(slug=None):
    """Compare 2 snapshot trong CÙNG 1 project."""
    try:
        slug = slug or _resolve_slug()
    except ValueError as e:
        return jsonify({"error": str(e)}), 404

    old_date = request.args.get("old")
    new_date = request.args.get("new")
    if not old_date or not new_date:
        return jsonify({"error": "Thiếu tham số old/new"}), 400

    smgr = _project_mgr.get_snapshot_manager(slug)
    old_data = smgr.load_snapshot(old_date)
    new_data = smgr.load_snapshot(new_date)
    if not old_data or not new_data:
        return jsonify({"error": "Không tìm thấy snapshot"}), 404

    result = CompareEngine().compare(
        old_data["parsed"], new_data["parsed"],
        old_date=old_date, new_date=new_date,
    )
    return jsonify({"success": True, "result": result})


@app.route("/api/compare-cross")
def compare_cross_project():
    """
    Compare snapshot giữa 2 project khác nhau (Phase 2).
    Query: ?project_a=<slug>&snap_a=<date>&project_b=<slug>&snap_b=<date>
    """
    pa = request.args.get("project_a")
    sa = request.args.get("snap_a")
    pb = request.args.get("project_b")
    sb = request.args.get("snap_b")
    if not (pa and sa and pb and sb):
        return jsonify({"error": "Thiếu tham số project_a/snap_a/project_b/snap_b"}), 400

    smgr_a = _project_mgr.get_snapshot_manager(pa)
    smgr_b = _project_mgr.get_snapshot_manager(pb)
    a = smgr_a.load_snapshot(sa)
    b = smgr_b.load_snapshot(sb)
    if not a or not b:
        return jsonify({"error": "Không tìm thấy 1 trong 2 snapshot"}), 404

    result = CompareEngine().compare(
        a["parsed"], b["parsed"],
        old_date=f"{pa}:{sa}", new_date=f"{pb}:{sb}",
    )
    proj_a = _project_mgr.get_project(pa)
    proj_b = _project_mgr.get_project(pb)
    return jsonify({
        "success": True,
        "project_a": _project_to_dict(proj_a) if proj_a else None,
        "project_b": _project_to_dict(proj_b) if proj_b else None,
        "snap_a": sa,
        "snap_b": sb,
        "result": result,
    })


@app.route("/api/projects/<slug>/upload-compare", methods=["POST"])
@app.route("/api/upload-compare", methods=["POST"])
def upload_compare(slug=None):
    """Upload file cũ để so sánh với file hiện tại của project (không lưu snapshot)."""
    try:
        slug = slug or _resolve_slug()
    except ValueError as e:
        return jsonify({"error": str(e)}), 404
    st, err = _need_state(slug)
    if err:
        return err

    if "file" not in request.files:
        return jsonify({"error": "Không tìm thấy file"}), 400
    file = request.files["file"]
    if not file.filename or not file.filename.lower().endswith((".xlsx", ".xls")):
        return jsonify({"error": "File không hợp lệ"}), 400

    tmp_path = os.path.join(app.config["UPLOAD_FOLDER"], f"tmp_compare_{slug}.xlsx")
    file.save(tmp_path)

    try:
        old_data = FunctionListParser().parse(tmp_path)
        result = CompareEngine().compare(
            old_data, st["data"],
            old_date="uploaded_file",
            new_date=date.today().isoformat(),
        )
        return jsonify({"success": True, "result": result})
    except Exception as e:
        return jsonify({"error": f"Lỗi so sánh: {str(e)}"}), 500
    finally:
        try:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
        except OSError:
            pass


# ==========================================================================
# Exports (per-project + legacy)
# ==========================================================================

@app.route("/api/projects/<slug>/export-overdue", methods=["GET", "POST"])
@app.route("/api/export-overdue", methods=["GET", "POST"])
def export_overdue(slug=None):
    try:
        slug = slug or _resolve_slug()
    except ValueError as e:
        return jsonify({"error": str(e)}), 404
    st, err = _need_state(slug)
    if err:
        return err

    if request.method == "POST":
        filters = request.get_json(silent=True) or {}
    else:
        filters = {
            "module": request.args.get("module"),
            "pic": request.args.get("pic"),
            "phase": request.args.get("phase"),
        }
        filters = {k: v for k, v in filters.items() if v}

    try:
        filepath = export_overdue_report(
            overdue_list=st["metrics"].get("overdue_list", []),
            output_dir=_project_mgr.get_export_dir(slug),
            filters=filters if filters else None,
        )
        return send_file(filepath, as_attachment=True, download_name=os.path.basename(filepath))
    except Exception as e:
        return jsonify({"error": f"Lỗi khi xuất file: {str(e)}"}), 500


@app.route("/api/projects/<slug>/export-full-report")
@app.route("/api/export-full-report")
def export_full(slug=None):
    try:
        slug = slug or _resolve_slug()
    except ValueError as e:
        return jsonify({"error": str(e)}), 404
    st, err = _need_state(slug)
    if err:
        return err
    try:
        filepath = export_full_report(st["metrics"], _project_mgr.get_export_dir(slug))
        return send_file(filepath, as_attachment=True, download_name=os.path.basename(filepath))
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"error": f"Lỗi khi xuất file: {str(e)}"}), 500


@app.route("/api/projects/<slug>/export-chart", methods=["GET", "POST"])
def export_chart_endpoint(slug):
    """
    Xuất Excel 1 chart từ metrics.
    Query/body: chart (bắt buộc) + optional module/process/pic filters.
    Khi có filter → recompute metrics trên subset rồi export.
    """
    st, err = _need_state(slug)
    if err:
        return err

    if request.method == "POST":
        body = request.get_json(silent=True) or {}
        chart = (body.get("chart") or "").strip()
        fmodules = body.get("modules") or body.get("module") or []
        fprocesses = body.get("processes") or body.get("process") or []
        fpics = body.get("pics") or body.get("pic") or []
        if isinstance(fmodules, str):
            fmodules = [x.strip() for x in fmodules.split(",") if x.strip()]
        if isinstance(fprocesses, str):
            fprocesses = [x.strip() for x in fprocesses.split(",") if x.strip()]
        if isinstance(fpics, str):
            fpics = [x.strip() for x in fpics.split(",") if x.strip()]
    else:
        chart = (request.args.get("chart") or "").strip()
        fmodules = _parse_multi_arg("module")
        fprocesses = _parse_multi_arg("process")
        fpics = _parse_multi_arg("pic")

    if not chart:
        return jsonify({"error": "Thiếu tham số chart"}), 400
    if chart not in SUPPORTED_EXPORT_CHARTS:
        return jsonify({
            "error": f"Chart không hỗ trợ: {chart}",
            "supported": sorted(SUPPORTED_EXPORT_CHARTS),
        }), 400

    try:
        if fmodules or fprocesses or fpics:
            filtered = _filter_parsed_data(
                st["data"], modules=fmodules, processes=fprocesses, pics=fpics,
            )
            metrics = DashboardEngine().compute_all(filtered)
            subtitle = (
                f"Filter: module={fmodules or '-'} · process={fprocesses or '-'} · "
                f"pic={fpics or '-'} · {len(filtered.rows)} function"
            )
        else:
            metrics = st["metrics"]
            subtitle = ""

        filepath = export_chart(
            chart=chart,
            metrics=metrics,
            output_dir=_project_mgr.get_export_dir(slug),
            subtitle=subtitle,
        )
        return send_file(filepath, as_attachment=True, download_name=os.path.basename(filepath))
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"error": f"Lỗi khi xuất chart: {str(e)}"}), 500


@app.route("/api/projects/<slug>/audit-report", methods=["GET", "POST"])
def audit_report_endpoint(slug):
    """
    Xuất Report Đánh giá (11 sheet).
    Query/body: scope=all|filtered (+ module/process/pic nếu filtered).
    """
    st, err = _need_state(slug)
    if err:
        return err

    if request.method == "POST":
        body = request.get_json(silent=True) or {}
        scope = (body.get("scope") or "all").strip().lower()
        fmodules = body.get("modules") or body.get("module") or []
        fprocesses = body.get("processes") or body.get("process") or []
        fpics = body.get("pics") or body.get("pic") or []
        if isinstance(fmodules, str):
            fmodules = [x.strip() for x in fmodules.split(",") if x.strip()]
        if isinstance(fprocesses, str):
            fprocesses = [x.strip() for x in fprocesses.split(",") if x.strip()]
        if isinstance(fpics, str):
            fpics = [x.strip() for x in fpics.split(",") if x.strip()]
    else:
        scope = (request.args.get("scope") or "all").strip().lower()
        fmodules = _parse_multi_arg("module")
        fprocesses = _parse_multi_arg("process")
        fpics = _parse_multi_arg("pic")

    try:
        if scope == "filtered" and (fmodules or fprocesses or fpics):
            data = _filter_parsed_data(
                st["data"], modules=fmodules, processes=fprocesses, pics=fpics,
            )
            metrics = DashboardEngine().compute_all(data)
            subtitle = (
                f"Scope: filtered · module={fmodules or '-'} · process={fprocesses or '-'} · "
                f"pic={fpics or '-'} · {len(data.rows)} function"
            )
        else:
            data = st["data"]
            metrics = st["metrics"]
            subtitle = "Scope: all"

        filepath = export_audit_report(
            data, metrics,
            output_dir=_project_mgr.get_export_dir(slug),
            subtitle=subtitle,
        )
        return send_file(filepath, as_attachment=True, download_name=os.path.basename(filepath))
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"error": f"Lỗi khi xuất audit report: {str(e)}"}), 500


@app.route("/api/projects/<slug>/pic-blacklist", methods=["GET"])
@app.route("/api/pic-blacklist", methods=["GET"])
def get_pic_blacklist(slug=None):
    """
    Trả về danh sách PIC bị blacklist trong file hiện tại của project.
    Response: {success, items, total, keywords}
      - items: list dict metadata cell bị bỏ
      - keywords: các keyword unique đã match (VD ["Closed", "In-progress"])

    Đây là báo cáo data-quality — giúp user phát hiện cell Excel bị lệch cột
    Status sang PIC. Không filter theo global filter — luôn là toàn dataset.
    """
    try:
        slug = slug or _resolve_slug()
    except ValueError as e:
        return jsonify({"error": str(e)}), 404
    st, err = _need_state(slug)
    if err:
        return err

    data = st["data"]
    items = list(getattr(data, "pic_blacklisted", []) or [])
    # Unique keyword list — cho FE hiển thị chip filter/summary
    keywords = sorted({it.get("matched_keyword", "") for it in items if it.get("matched_keyword")})

    return jsonify({
        "success": True,
        "items": items,
        "total": len(items),
        "keywords": keywords,
    })


@app.route("/api/projects/<slug>/pic-blacklist/export", methods=["GET", "POST"])
@app.route("/api/pic-blacklist/export", methods=["GET", "POST"])
def export_pic_blacklist(slug=None):
    """Xuất Excel .xlsx báo cáo PIC bị blacklist. Không filter — toàn dataset."""
    try:
        slug = slug or _resolve_slug()
    except ValueError as e:
        return jsonify({"error": str(e)}), 404
    st, err = _need_state(slug)
    if err:
        return err

    items = list(getattr(st["data"], "pic_blacklisted", []) or [])
    try:
        filepath = export_pic_blacklist_report(
            items=items,
            output_dir=_project_mgr.get_export_dir(slug),
            subtitle=(
                f"Project: {slug} | Tổng: {len(items)} token | "
                f"File: {st.get('filename', '')}"
            ),
        )
        return send_file(filepath, as_attachment=True, download_name=os.path.basename(filepath))
    except Exception as e:
        return jsonify({"error": f"Lỗi khi xuất file: {str(e)}"}), 500


@app.route("/api/projects/<slug>/export-by-pic")
@app.route("/api/export-by-pic")
def export_pic(slug=None):
    try:
        slug = slug or _resolve_slug()
    except ValueError as e:
        return jsonify({"error": str(e)}), 404
    st, err = _need_state(slug)
    if err:
        return err

    pic = request.args.get("pic")
    if not pic:
        return jsonify({"error": "Thiếu tham số pic"}), 400
    try:
        filepath = export_by_pic(st["metrics"], pic, _project_mgr.get_export_dir(slug))
        return send_file(filepath, as_attachment=True, download_name=os.path.basename(filepath))
    except Exception as e:
        return jsonify({"error": f"Lỗi khi xuất file: {str(e)}"}), 500


@app.route("/api/projects/<slug>/export-compare")
@app.route("/api/export-compare")
def export_compare(slug=None):
    try:
        slug = slug or _resolve_slug()
    except ValueError as e:
        return jsonify({"error": str(e)}), 404

    old_date = request.args.get("old")
    new_date = request.args.get("new")
    if not old_date or not new_date:
        return jsonify({"error": "Thiếu tham số old/new"}), 400

    smgr = _project_mgr.get_snapshot_manager(slug)
    old = smgr.load_snapshot(old_date)
    new = smgr.load_snapshot(new_date)
    if not old or not new:
        return jsonify({"error": "Không tìm thấy snapshot"}), 404

    result = CompareEngine().compare(
        old["parsed"], new["parsed"],
        old_date=old_date, new_date=new_date,
    )
    try:
        filepath = export_compare_report(
            result, old_date, new_date, _project_mgr.get_export_dir(slug)
        )
        return send_file(filepath, as_attachment=True, download_name=os.path.basename(filepath))
    except Exception as e:
        return jsonify({"error": f"Lỗi khi xuất: {str(e)}"}), 500


# ==========================================================================
# Project package: Export/Import (Phase 2)
# ==========================================================================

@app.route("/api/projects/<slug>/export-package")
def export_package(slug):
    """
    Đóng gói toàn bộ project (current.xlsx + snapshots + meta) thành zip.
    Dùng để backup hoặc chuyển sang máy khác.
    """
    proj = _project_mgr.get_project(slug)
    if not proj:
        return jsonify({"error": "Không tìm thấy project"}), 404

    pdir = _project_mgr._project_dir(slug)  # OK use internal
    if not os.path.isdir(pdir):
        return jsonify({"error": "Thư mục project trống"}), 400

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for root, _, files in os.walk(pdir):
            for f in files:
                abs_path = os.path.join(root, f)
                rel_path = os.path.relpath(abs_path, pdir)
                zf.write(abs_path, arcname=os.path.join(slug, rel_path))
    buf.seek(0)

    download_name = f"project_{slug}_{date.today().isoformat()}.zip"
    return send_file(
        buf,
        mimetype="application/zip",
        as_attachment=True,
        download_name=download_name,
    )


@app.route("/api/projects/import-package", methods=["POST"])
def import_package():
    """
    Import project từ file zip (đã xuất bằng export-package).
    Zip cấu trúc: {slug}/meta.json, {slug}/current.xlsx, {slug}/snapshots/...
    Nếu slug đã tồn tại → generate slug mới (VD: dev-2).
    """
    if "file" not in request.files:
        return jsonify({"error": "Thiếu file"}), 400
    file = request.files["file"]
    if not file.filename or not file.filename.lower().endswith(".zip"):
        return jsonify({"error": "Chỉ hỗ trợ .zip"}), 400

    tmp_zip = os.path.join(app.config["UPLOAD_FOLDER"], "_import_tmp.zip")
    file.save(tmp_zip)

    try:
        with zipfile.ZipFile(tmp_zip, "r") as zf:
            # Xác định slug gốc từ prefix folder trong zip
            names = zf.namelist()
            if not names:
                return jsonify({"error": "Zip rỗng"}), 400
            first_seg = names[0].split("/")[0]
            if not first_seg:
                return jsonify({"error": "Cấu trúc zip không hợp lệ"}), 400

            # Đọc meta.json để lấy tên
            meta_content = None
            for name in names:
                if name.endswith("meta.json"):
                    with zf.open(name) as f:
                        import json as _json
                        meta_content = _json.load(f)
                        break

            new_name = meta_content.get("name") if meta_content else first_seg
            new_desc = meta_content.get("description", "") if meta_content else ""

            # Tạo project mới với tên (slug tự sinh unique)
            new_proj = _project_mgr.create_project(new_name, new_desc)

            # Extract toàn bộ zip vào folder mới
            target_dir = _project_mgr._project_dir(new_proj.slug)
            with tempfile.TemporaryDirectory() as td:
                zf.extractall(td)
                src_root = os.path.join(td, first_seg)
                if not os.path.isdir(src_root):
                    return jsonify({"error": "Zip không có folder project ở gốc"}), 400
                # Move files sang target
                for item in os.listdir(src_root):
                    s = os.path.join(src_root, item)
                    d = os.path.join(target_dir, item)
                    if os.path.isfile(s):
                        shutil.copy2(s, d)
                    elif os.path.isdir(s):
                        if os.path.exists(d):
                            shutil.rmtree(d)
                        shutil.copytree(s, d)

            return jsonify({
                "success": True,
                "project": _project_to_dict(_project_mgr.get_project(new_proj.slug)),
            })
    except zipfile.BadZipFile:
        return jsonify({"error": "File zip không hợp lệ"}), 400
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"error": f"Lỗi import: {str(e)}"}), 500
    finally:
        try:
            os.remove(tmp_zip)
        except OSError:
            pass


# ==========================================================================
# Portfolio (Cross-project) — Level 1/2/3
# ==========================================================================
# 4 endpoint mới, KHÔNG sửa endpoint cũ. Reuse `_get_state` để tận dụng cache
# in-memory + auto-load từ disk (đã có sẵn).

def _portfolio_state_loader(slug: str):
    """State loader cho portfolio.py — bridge `_get_state` vào contract."""
    return _get_state(slug)


@app.route("/api/portfolio/search", methods=["GET"])
def portfolio_search():
    """
    Global search text qua tất cả project.
    Query params:
      - q: từ khoá (bắt buộc, min 1 ký tự)
      - scope: "name" | "code" | "pic" | "process" | "all" (default: all)
      - limit: giới hạn kết quả (default 50, max 200)
      - include_archived: 1/0 — search cả project archived (default 0)
    """
    q = (request.args.get("q") or "").strip()
    scope = (request.args.get("scope") or "all").strip().lower()
    if scope not in SEARCH_SCOPES:
        scope = "all"
    try:
        limit = int(request.args.get("limit") or 50)
    except (TypeError, ValueError):
        limit = 50
    limit = max(1, min(limit, 200))
    include_archived = request.args.get("include_archived") in ("1", "true", "yes")

    result = search_across_projects(
        _project_mgr,
        _portfolio_state_loader,
        query=q,
        scope=scope,
        limit=limit,
        include_archived=include_archived,
    )
    return jsonify({
        "success": True,
        "query": q,
        "scope": scope,
        **result,
    })


@app.route("/api/portfolio/compare", methods=["POST"])
def portfolio_compare():
    """
    Compare 2-4 project. Body JSON: {slugs: ["a", "b", ...]}
    """
    body = request.get_json(silent=True) or {}
    slugs = body.get("slugs") or []
    if not isinstance(slugs, list):
        return jsonify({"error": "slugs phải là list"}), 400
    slugs = [str(s).strip() for s in slugs if s]
    if len(slugs) < 2:
        return jsonify({"error": "Cần chọn ít nhất 2 project để so sánh"}), 400

    result = compare_projects(_project_mgr, _portfolio_state_loader, slugs)
    return jsonify({"success": True, **result})


@app.route("/api/portfolio/compare/export", methods=["POST"])
def portfolio_compare_export():
    """
    Export bảng compare summary ra Excel. Body JSON: {slugs: [...]}
    """
    body = request.get_json(silent=True) or {}
    slugs = body.get("slugs") or []
    if not isinstance(slugs, list) or len(slugs) < 2:
        return jsonify({"error": "Cần ít nhất 2 project"}), 400
    slugs = [str(s).strip() for s in slugs if s]

    result = compare_projects(_project_mgr, _portfolio_state_loader, slugs)
    try:
        # Lưu vào folder uploads chung (không thuộc project cụ thể nào)
        filepath = export_portfolio_compare(result, app.config["UPLOAD_FOLDER"])
        return send_file(filepath, as_attachment=True, download_name=os.path.basename(filepath))
    except Exception as e:
        return jsonify({"error": f"Lỗi khi xuất Excel: {str(e)}"}), 500


@app.route("/api/portfolio/rollup", methods=["GET"])
def portfolio_rollup():
    """
    Portfolio Dashboard Rollup — gộp N project → 1 virtual dashboard.
    Query params:
      - slugs: CSV list slug (default: all non-archived)
      - include_archived: 1/0 (áp dụng khi slugs rỗng)
    """
    slugs_raw = request.args.get("slugs")
    if slugs_raw:
        slugs = [s.strip() for s in slugs_raw.split(",") if s.strip()]
    else:
        slugs = None
    include_archived = request.args.get("include_archived") in ("1", "true", "yes")

    rollup = aggregate_rollup(
        _project_mgr,
        _portfolio_state_loader,
        slugs=slugs,
        include_archived=include_archived,
    )

    if rollup["projects_count"] == 0:
        return jsonify({
            "error": "Không có project nào có file để rollup",
            "skipped": rollup["skipped"],
        }), 404

    engine = DashboardEngine()
    metrics = engine.compute_all(rollup["aggregated"])
    overridden = rollup_summary_override(rollup, metrics)

    return jsonify({
        "success": True,
        "metrics": _trim_payload(overridden),
        "per_project": rollup["per_project"],
        "skipped": rollup["skipped"],
        "projects_count": rollup["projects_count"],
    })


# ==========================================================================
# Project stores — capacity / saved views / history / settings / aliases
# ==========================================================================

def _project_dir_for(slug: str) -> str:
    return _project_mgr.get_project_folder(slug)


@app.route("/api/projects/<slug>/capacity", methods=["GET", "PUT"])
def project_capacity(slug: str):
    from analyzer import project_store as ps
    if not _project_mgr.project_exists(slug):
        return jsonify({"error": "Project không tồn tại"}), 404
    folder = _project_dir_for(slug)
    if request.method == "GET":
        return jsonify(ps.load_capacity(folder))
    body = request.get_json(silent=True) or {}
    return jsonify(ps.save_capacity(folder, body))


@app.route("/api/projects/<slug>/saved-views", methods=["GET", "POST"])
def project_saved_views(slug: str):
    from analyzer import project_store as ps
    if not _project_mgr.project_exists(slug):
        return jsonify({"error": "Project không tồn tại"}), 404
    folder = _project_dir_for(slug)
    if request.method == "GET":
        return jsonify({"views": ps.load_saved_views(folder)})
    body = request.get_json(silent=True) or {}
    views = ps.upsert_saved_view(folder, body)
    return jsonify({"views": views})


@app.route("/api/projects/<slug>/saved-views/<view_id>", methods=["DELETE"])
def project_delete_saved_view(slug: str, view_id: str):
    from analyzer import project_store as ps
    if not _project_mgr.project_exists(slug):
        return jsonify({"error": "Project không tồn tại"}), 404
    views = ps.delete_saved_view(_project_dir_for(slug), view_id)
    return jsonify({"views": views})


# ==========================================================================
# Section order (Task 4b — drag-drop customize)
# ==========================================================================

@app.route("/api/projects/<slug>/section-order", methods=["GET", "POST"])
def project_section_order(slug: str):
    """
    GET → trả section_order hiện tại (list id string, hoặc [] nếu chưa set).
    POST → body {order: [id1, id2, ...]} — lưu và trả về order đã lưu.
    """
    from analyzer import project_store as ps
    if not _project_mgr.project_exists(slug):
        return jsonify({"error": "Project không tồn tại"}), 404
    folder = _project_dir_for(slug)
    if request.method == "GET":
        return jsonify({"order": ps.load_section_order(folder)})
    body = request.get_json(silent=True) or {}
    order = body.get("order") or body.get("section_order") or []
    if not isinstance(order, list):
        return jsonify({"error": "order phải là list"}), 400
    saved = ps.save_section_order(folder, order)
    return jsonify({"order": saved})


@app.route("/api/projects/<slug>/section-order/reset", methods=["POST"])
def project_section_order_reset(slug: str):
    """Xoá custom section_order → FE fallback về HTML default."""
    from analyzer import project_store as ps
    if not _project_mgr.project_exists(slug):
        return jsonify({"error": "Project không tồn tại"}), 404
    ps.reset_section_order(_project_dir_for(slug))
    return jsonify({"order": []})


# ==========================================================================
# Chart configs (Task 6 — Phase A: inline edit title/caption/visibility)
# ==========================================================================

@app.route("/api/projects/<slug>/chart-config", methods=["GET", "POST", "DELETE"])
def project_chart_config(slug: str):
    """
    GET → trả full map {target_id: {title?, caption?, hidden?}}.
    POST → body {target_id, title?, caption?, hidden?} → upsert 1 chart.
           Nếu tất cả field trong body rỗng → xoá config cho target đó.
    DELETE:
      · ?target=<id> → xoá 1 target.
      · Không query → reset toàn bộ chart configs.
    """
    from analyzer import project_store as ps
    if not _project_mgr.project_exists(slug):
        return jsonify({"error": "Project không tồn tại"}), 404
    folder = _project_dir_for(slug)

    if request.method == "GET":
        return jsonify({"configs": ps.load_chart_configs(folder)})

    if request.method == "POST":
        body = request.get_json(silent=True) or {}
        target_id = body.get("target_id") or body.get("chart_id") or ""
        if not target_id:
            return jsonify({"error": "target_id bắt buộc"}), 400
        # Pass through TOÀN BỘ field (Phase A + Phase B). Sanitize logic ở
        # project_store._sanitize_chart_config sẽ chỉ giữ key hợp lệ.
        entry: dict = {
            "title": body.get("title"),
            "caption": body.get("caption"),
            "hidden": bool(body.get("hidden")),
            "type": body.get("type") or body.get("chart_type"),
            "x_field": body.get("x_field"),
            "y_measure": body.get("y_measure"),
            "series_field": body.get("series_field"),
            "palette": body.get("palette") or body.get("colors"),
            "filter_override": body.get("filter_override"),
        }
        all_cfg = ps.upsert_chart_config(folder, target_id, entry)
        return jsonify({"configs": all_cfg})

    # DELETE
    target_id = request.args.get("target", "").strip()
    if target_id:
        all_cfg = ps.delete_chart_config(folder, target_id)
        return jsonify({"configs": all_cfg})
    ps.reset_chart_configs(folder)
    return jsonify({"configs": {}})


@app.route("/api/projects/<slug>/chart-fields")
def project_chart_fields(slug: str):
    """
    Task 8: trả về danh sách field / measure / chart_type / palette phù hợp
    với FE dropdown. Không phụ thuộc file uploaded (static enum).
    """
    from analyzer.generic_chart import get_available_fields
    if not _project_mgr.project_exists(slug):
        return jsonify({"error": "Project không tồn tại"}), 404
    return jsonify(get_available_fields())


# ==========================================================================
# Custom dashboards (Task 9 — Dynamic Dashboard Builder)
# ==========================================================================

@app.route("/api/projects/<slug>/custom-dashboard", methods=["GET", "POST"])
def project_custom_dashboards(slug: str):
    """GET → list toàn bộ. POST → thêm/update 1 custom dashboard."""
    from analyzer import project_store as ps
    if not _project_mgr.project_exists(slug):
        return jsonify({"error": "Project không tồn tại"}), 404
    folder = _project_dir_for(slug)
    if request.method == "GET":
        return jsonify({"items": ps.load_custom_dashboards(folder)})
    body = request.get_json(silent=True) or {}
    saved = ps.upsert_custom_dashboard(folder, body)
    if not saved:
        return jsonify({"error": "Dữ liệu không hợp lệ (thiếu title hoặc x_field)"}), 400
    return jsonify({"item": saved, "items": ps.load_custom_dashboards(folder)})


@app.route("/api/projects/<slug>/custom-dashboard/<item_id>", methods=["PUT", "DELETE"])
def project_custom_dashboard_item(slug: str, item_id: str):
    from analyzer import project_store as ps
    if not _project_mgr.project_exists(slug):
        return jsonify({"error": "Project không tồn tại"}), 404
    folder = _project_dir_for(slug)
    if request.method == "PUT":
        body = request.get_json(silent=True) or {}
        body["id"] = item_id
        saved = ps.upsert_custom_dashboard(folder, body)
        if not saved:
            return jsonify({"error": "Dữ liệu không hợp lệ"}), 400
        return jsonify({"item": saved})
    items = ps.delete_custom_dashboard(folder, item_id)
    return jsonify({"items": items})


@app.route("/api/projects/<slug>/custom-dashboard/<item_id>/data")
def project_custom_dashboard_data(slug: str, item_id: str):
    """Aggregate data cho 1 custom dashboard — reuse aggregate_chart từ Task 8."""
    from analyzer import project_store as ps
    from analyzer.generic_chart import aggregate_chart
    state, err = _require_state(slug)
    if err:
        return err
    items = ps.load_custom_dashboards(_project_dir_for(slug))
    item = next((i for i in items if i.get("id") == item_id), None)
    if not item:
        return jsonify({"error": "Custom dashboard không tồn tại"}), 404
    filters = dict(item.get("filters") or {})
    # Merge global filter nếu query có
    for k, gk in [("modules", "module"), ("processes", "process"), ("pics", "pic")]:
        gv = _parse_multi_arg(gk)
        if gv:
            filters[k] = list(set(filters.get(k, []) + gv)) or gv
    try:
        result = aggregate_chart(
            state["data"],
            x_field=item["x_field"],
            y_measure=item.get("y_measure", "count"),
            series_field=item.get("series_field") or None,
            filters=filters,
        )
    except Exception as e:
        return jsonify({"error": f"Aggregate failed: {e}"}), 400
    result["config"] = item
    return jsonify(result)


@app.route("/api/projects/<slug>/custom-dashboard/<item_id>/export")
def project_custom_dashboard_export(slug: str, item_id: str):
    """Xuất Excel — 1 sheet chứa aggregated data + 1 sheet metadata."""
    from analyzer import project_store as ps
    from analyzer.generic_chart import aggregate_chart, FIELDS, MEASURES
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill
    from tempfile import mkdtemp
    from datetime import datetime
    import os
    state, err = _require_state(slug)
    if err:
        return err
    items = ps.load_custom_dashboards(_project_dir_for(slug))
    item = next((i for i in items if i.get("id") == item_id), None)
    if not item:
        return jsonify({"error": "Custom dashboard không tồn tại"}), 404
    agg = aggregate_chart(
        state["data"],
        x_field=item["x_field"],
        y_measure=item.get("y_measure", "count"),
        series_field=item.get("series_field") or None,
        filters=item.get("filters") or {},
    )
    wb = Workbook()
    ws = wb.active
    ws.title = "Data"
    xlabel = FIELDS.get(item["x_field"], item["x_field"])
    headers = [xlabel] + [ds["label"] for ds in agg["datasets"]]
    ws.append(headers)
    for c in ws[1]:
        c.font = Font(bold=True, color="FFFFFF")
        c.fill = PatternFill("solid", fgColor="2563EB")
    for i, x in enumerate(agg["labels"]):
        row = [x] + [ds["data"][i] for ds in agg["datasets"]]
        ws.append(row)
    for col_idx, _ in enumerate(headers, 1):
        ws.column_dimensions[chr(64 + col_idx) if col_idx <= 26 else "A" + chr(64 + col_idx - 26)].width = 18
    meta_ws = wb.create_sheet("Info")
    meta_rows = [
        ["Title", item.get("title")],
        ["Caption", item.get("caption")],
        ["X field", xlabel],
        ["Y measure", MEASURES.get(item.get("y_measure"), item.get("y_measure"))],
        ["Series field", FIELDS.get(item.get("series_field"), item.get("series_field") or "-")],
        ["Chart type", item.get("chart_type")],
        ["Palette", item.get("palette")],
        ["Filters", str(item.get("filters") or {})],
        ["Created at", item.get("created_at")],
        ["Total rows after filter", agg["meta"].get("total_rows_after_filter")],
        ["Exported at", datetime.now().isoformat(timespec="seconds")],
    ]
    for r in meta_rows:
        meta_ws.append(r)
    meta_ws.column_dimensions["A"].width = 22
    meta_ws.column_dimensions["B"].width = 60
    for c in meta_ws["A"]:
        c.font = Font(bold=True)
    out_dir = mkdtemp(prefix="custom_dash_")
    safe_name = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in item.get("title", "custom"))[:40]
    fpath = os.path.join(out_dir, f"custom_{safe_name}_{item_id[:12]}.xlsx")
    wb.save(fpath)
    return send_file(fpath, as_attachment=True,
                     download_name=os.path.basename(fpath))


# ==========================================================================
# Task 17: overview theo `module | process | both` (rebuild bảng khi user
# đổi segmented control mà không cần full re-fetch dashboard).
# ==========================================================================

@app.route("/api/projects/<slug>/module-overview")
def project_module_overview(slug: str):
    """
    BUG P0-B fix: endpoint TRƯỚC ĐÂY dùng `state["data"]` (raw, không filter).
    Khi user chọn group_by=process kèm global filter (VD chỉ 1 module), backend
    vẫn tính trên toàn bộ data → bảng hiển thị ALL processes, không apply filter.
    Fix: dùng `_filtered_data_from_request()` để tôn trọng module/process/pic
    truyền qua query params.
    """
    from analyzer.dashboard_engine import DashboardEngine
    state, err = _require_state(slug)
    if err:
        return err
    group_by = (request.args.get("group_by") or "module").lower()
    if group_by not in ("module", "process", "both"):
        group_by = "module"
    data = _filtered_data_from_request(state)
    # DashboardEngine.__init__(today=None, ...): pass no arg → dùng date.today().
    engine = DashboardEngine()
    return jsonify({
        "group_by": group_by,
        "rows": engine._overview_by(data, group_by=group_by),
        "applied_filter": {
            "modules": _parse_multi_arg("module"),
            "processes": _parse_multi_arg("process"),
            "pics": _parse_multi_arg("pic"),
        },
    })


# ==========================================================================
# Kanban (Task 10 — Kanban theo tuần)
# ==========================================================================

@app.route("/api/projects/<slug>/kanban")
def project_kanban(slug: str):
    """
    Query params:
      week_offset: int (default 0) — 0=tuần này, 1=tuần sau, -1=tuần trước
      module, process, pic, role: multi (comma hoặc repeat)
      search: text
    """
    from analyzer import project_store as ps
    from analyzer.kanban import compute_kanban
    state, err = _require_state(slug)
    if err:
        return err
    try:
        offset = int(request.args.get("week_offset") or 0)
    except ValueError:
        offset = 0
    filters = {
        "modules": _parse_multi_arg("module"),
        "processes": _parse_multi_arg("process"),
        "pics": _parse_multi_arg("pic"),
        "roles": _parse_multi_arg("role"),
        "search": request.args.get("search") or "",
    }
    # Task 14: role_map auto-detect từ phase (không đọc pic_role_map cũ nữa).
    from analyzer.kanban import infer_pic_roles
    role_map = infer_pic_roles(state["data"])
    return jsonify(compute_kanban(
        state["data"],
        week_offset=offset,
        pic_role_map=role_map,
        filters=filters,
    ))


@app.route("/api/projects/<slug>/pic-roles", methods=["GET", "POST"])
def project_pic_roles(slug: str):
    """Task 14: role auto-detect từ phase — GET vẫn trả map derived, POST no-op.

    - GET → `{map, all_pics, all_roles: ["BA","Dev"]}` — map derived,
      không đọc từ store.
    - POST → return 200 với warning "Role auto-detected, manual map disabled".
    """
    from analyzer.kanban import unique_pics, infer_pic_roles
    if not _project_mgr.project_exists(slug):
        return jsonify({"error": "Project không tồn tại"}), 404
    state = _get_state(slug)
    all_pics = unique_pics(state["data"]) if state and state.get("data") else []
    derived_map = infer_pic_roles(state["data"]) if state and state.get("data") else {}
    if request.method == "GET":
        return jsonify({
            "map": derived_map,
            "all_pics": all_pics,
            "all_roles": ["BA", "Dev"],
            "auto_detected": True,
        })
    # POST — no-op (backward-compat). Client cũ có thể vẫn call save.
    app.logger.warning("[pic-roles] POST ignored: role auto-detected from phase (Task 14).")
    return jsonify({
        "map": derived_map,
        "all_pics": all_pics,
        "all_roles": ["BA", "Dev"],
        "auto_detected": True,
        "warning": "Role auto-detected từ phase, manual map đã bị vô hiệu.",
    })


@app.route("/api/projects/<slug>/chart-aggregate", methods=["POST"])
def project_chart_aggregate(slug: str):
    """
    Task 8/9: aggregate data để render chart tuỳ chỉnh.
    Body:
      {
        "x_field": "module",
        "y_measure": "count",
        "series_field": "status" | null,
        "filters": {"modules":[...], "processes":[...], ...},
        "apply_global_filter": true  # nếu true → merge với globalFilters từ query
      }
    """
    from analyzer.generic_chart import aggregate_chart
    state, err = _require_state(slug)
    if err:
        return err
    body = request.get_json(silent=True) or {}
    data = state["data"]
    filters = body.get("filters") or {}
    # Merge global filter từ query (nếu FE muốn)
    if body.get("apply_global_filter"):
        gmods = _parse_multi_arg("module")
        gprocs = _parse_multi_arg("process")
        gpics = _parse_multi_arg("pic")
        if gmods:
            filters["modules"] = list(set(filters.get("modules", []) + gmods)) or gmods
        if gprocs:
            filters["processes"] = list(set(filters.get("processes", []) + gprocs)) or gprocs
        if gpics:
            filters["pics"] = list(set(filters.get("pics", []) + gpics)) or gpics
    try:
        result = aggregate_chart(
            data,
            x_field=body.get("x_field") or "module",
            y_measure=body.get("y_measure") or "count",
            series_field=body.get("series_field") or None,
            filters=filters,
            limit_x=int(body.get("limit_x") or 50),
        )
    except Exception as e:
        return jsonify({"error": f"Aggregate failed: {e}"}), 400
    return jsonify(result)


@app.route("/api/projects/<slug>/upload-history")
def project_upload_history(slug: str):
    from analyzer import project_store as ps
    if not _project_mgr.project_exists(slug):
        return jsonify({"error": "Project không tồn tại"}), 404
    return jsonify({"items": ps.load_upload_history(_project_dir_for(slug))})


@app.route("/api/projects/<slug>/settings", methods=["GET", "PUT"])
def project_settings(slug: str):
    from analyzer import project_store as ps
    if not _project_mgr.project_exists(slug):
        return jsonify({"error": "Project không tồn tại"}), 404
    folder = _project_dir_for(slug)
    if request.method == "GET":
        return jsonify(ps.load_project_settings(folder))
    body = request.get_json(silent=True) or {}
    return jsonify(ps.save_project_settings(folder, body))


@app.route("/api/projects/<slug>/phase-aliases", methods=["GET", "PUT"])
def project_phase_aliases(slug: str):
    from analyzer import project_store as ps
    if not _project_mgr.project_exists(slug):
        return jsonify({"error": "Project không tồn tại"}), 404
    folder = _project_dir_for(slug)
    if request.method == "GET":
        return jsonify({"aliases": ps.load_phase_aliases(folder)})
    body = request.get_json(silent=True) or {}
    aliases = body.get("aliases", body)
    return jsonify({"aliases": ps.save_phase_aliases(folder, aliases)})


# --------------------------------------------------------------------------
# P4/P5 analytics endpoints — mỗi endpoint mỏng, chỉ pipe engine → JSON.
# Tất cả nhận query params: module, process, pic (comma-separated) để filter cascade.
# --------------------------------------------------------------------------

def _require_state(slug: str):
    """Helper — trả (state, err_response). None state nghĩa là chưa upload."""
    if not _project_mgr.project_exists(slug):
        return None, (jsonify({"error": "Project không tồn tại"}), 404)
    state = _get_state(slug)
    if not state or not state.get("data"):
        return None, (jsonify({"error": "Chưa upload file"}), 404)
    return state, None


def _filtered_data_from_request(state):
    """Đọc query params (module/process/pic) → return ParsedData đã filter (hoặc gốc nếu không có filter)."""
    fmodules = _parse_multi_arg("module")
    fprocesses = _parse_multi_arg("process")
    fpics = _parse_multi_arg("pic")
    if not (fmodules or fprocesses or fpics):
        return state["data"]
    return _filter_parsed_data(
        state["data"],
        modules=fmodules,
        processes=fprocesses,
        pics=fpics,
    )


@app.route("/api/projects/<slug>/capacity-load")
def project_capacity_load(slug: str):
    """Remaining MH vs capacity — hỗ trợ filter module/process/pic."""
    from analyzer import project_store as ps
    from analyzer.advanced_metrics import compute_capacity_load
    state, err = _require_state(slug)
    if err:
        return err
    data = _filtered_data_from_request(state)
    cap = ps.load_capacity(_project_dir_for(slug))
    return jsonify(compute_capacity_load(data, cap))


@app.route("/api/projects/<slug>/burndown")
def project_burndown(slug: str):
    from analyzer.advanced_metrics import compute_burndown_velocity
    state, err = _require_state(slug)
    if err:
        return err
    data = _filtered_data_from_request(state)
    return jsonify(compute_burndown_velocity(data))


@app.route("/api/projects/<slug>/sla")
def project_sla(slug: str):
    from analyzer import project_store as ps
    from analyzer.advanced_metrics import compute_sla_violations
    state, err = _require_state(slug)
    if err:
        return err
    data = _filtered_data_from_request(state)
    settings = ps.load_project_settings(_project_dir_for(slug))
    sla = settings.get("sla") or {}
    return jsonify(compute_sla_violations(
        data,
        must_have_days=int(sla.get("must_have_days", 3)),
        should_have_days=int(sla.get("should_have_days", 7)),
    ))


@app.route("/api/projects/<slug>/slow-heatmap")
def project_slow_heatmap(slug: str):
    from analyzer.advanced_metrics import compute_slow_heatmap
    state, err = _require_state(slug)
    if err:
        return err
    data = _filtered_data_from_request(state)
    return jsonify(compute_slow_heatmap(data))


@app.route("/api/projects/<slug>/dependency-blockers")
def project_dependency_blockers(slug: str):
    from analyzer.advanced_metrics import compute_dependency_blockers
    state, err = _require_state(slug)
    if err:
        return err
    data = _filtered_data_from_request(state)
    return jsonify(compute_dependency_blockers(data))


@app.route("/api/projects/<slug>/baseline-variance")
def project_baseline_variance(slug: str):
    from analyzer.advanced_metrics import compute_baseline_variance
    state, err = _require_state(slug)
    if err:
        return err
    data = _filtered_data_from_request(state)
    return jsonify(compute_baseline_variance(data))


# ==========================================================================
# Excel exports cho 4 section Phase 4/5 (Vấn đề 3 + Rule V4 "xuất ALL").
# Accept GET (dùng query string) và POST (body JSON) — cả 2 đều đọc global
# filter từ query string (?module=, ?process=, ?pic=) để tương thích form-submit
# cũ. FE mới nên POST JSON body {module: [], process: [], pic: []} → convert
# sang args-like dict để reuse _filtered_data_from_request contract.
# ==========================================================================


def _filter_state_from_body_or_args(state):
    """
    Đọc filter từ (a) POST body JSON hoặc (b) query args, apply _filter_parsed_data.

    Body JSON format: {"module": ["A","B"], "process": ["X"], "pic": ["Y"]}
    Query args: module=A,B&process=X&pic=Y (repeated hoặc comma-separated).
    Return (filtered_data, filters_dict_for_subtitle).
    """
    body = request.get_json(silent=True) or {} if request.method == "POST" else {}

    def _as_list(v) -> list[str]:
        if v is None:
            return []
        if isinstance(v, str):
            return [x.strip() for x in v.split(",") if x.strip()]
        if isinstance(v, list):
            out = []
            for it in v:
                out.extend(_as_list(it))
            return out
        return []

    # Ưu tiên body, fallback về query args
    fmods = _as_list(body.get("module") or body.get("modules")) or _parse_multi_arg("module")
    fprocs = _as_list(body.get("process") or body.get("processes")) or _parse_multi_arg("process")
    fpics = _as_list(body.get("pic") or body.get("pics")) or _parse_multi_arg("pic")

    if not (fmods or fprocs or fpics):
        return state["data"], {"modules": [], "processes": [], "pics": []}
    filtered = _filter_parsed_data(
        state["data"],
        modules=fmods,
        processes=fprocs,
        pics=fpics,
    )
    return filtered, {"modules": fmods, "processes": fprocs, "pics": fpics}


@app.route("/api/projects/<slug>/export-sla", methods=["GET", "POST"])
def export_sla(slug: str):
    """Xuất Excel SLA — vi phạm deadline theo Priority. Áp global filter."""
    from analyzer import project_store as ps
    from analyzer.advanced_metrics import compute_sla_violations
    state, err = _require_state(slug)
    if err:
        return err
    try:
        data, filters = _filter_state_from_body_or_args(state)
        settings = ps.load_project_settings(_project_dir_for(slug))
        sla_cfg = settings.get("sla") or {}
        payload = compute_sla_violations(
            data,
            must_have_days=int(sla_cfg.get("must_have_days", 3)),
            should_have_days=int(sla_cfg.get("should_have_days", 7)),
        )
        filepath = export_sla_report(
            payload=payload,
            output_dir=_project_mgr.get_export_dir(slug),
            filters=filters,
        )
        return send_file(filepath, as_attachment=True, download_name=os.path.basename(filepath))
    except Exception as e:
        return jsonify({"error": f"Lỗi xuất SLA: {str(e)}"}), 500


@app.route("/api/projects/<slug>/export-capacity", methods=["GET", "POST"])
def export_capacity(slug: str):
    """Xuất Excel Capacity PIC — remaining MH vs công suất."""
    from analyzer import project_store as ps
    from analyzer.advanced_metrics import compute_capacity_load
    state, err = _require_state(slug)
    if err:
        return err
    try:
        data, filters = _filter_state_from_body_or_args(state)
        cap = ps.load_capacity(_project_dir_for(slug))
        payload = compute_capacity_load(data, cap)
        filepath = export_capacity_report(
            payload=payload,
            output_dir=_project_mgr.get_export_dir(slug),
            filters=filters,
        )
        return send_file(filepath, as_attachment=True, download_name=os.path.basename(filepath))
    except Exception as e:
        return jsonify({"error": f"Lỗi xuất Capacity: {str(e)}"}), 500


@app.route("/api/projects/<slug>/export-slow", methods=["GET", "POST"])
def export_slow(slug: str):
    """Xuất Excel Slow Heatmap — Ai đang chậm (PIC × Phase)."""
    from analyzer.advanced_metrics import compute_slow_heatmap
    state, err = _require_state(slug)
    if err:
        return err
    try:
        data, filters = _filter_state_from_body_or_args(state)
        payload = compute_slow_heatmap(data)
        filepath = export_slow_heatmap_report(
            payload=payload,
            output_dir=_project_mgr.get_export_dir(slug),
            filters=filters,
        )
        return send_file(filepath, as_attachment=True, download_name=os.path.basename(filepath))
    except Exception as e:
        return jsonify({"error": f"Lỗi xuất Slow Heatmap: {str(e)}"}), 500


@app.route("/api/projects/<slug>/export-baseline", methods=["GET", "POST"])
def export_baseline(slug: str):
    """
    Xuất Excel Baseline vs Actual — variance ngày.
    Rule V4: dùng top=None để compute trả ALL items, KHÔNG cắt 200 như API JSON.
    """
    from analyzer.advanced_metrics import compute_baseline_variance
    state, err = _require_state(slug)
    if err:
        return err
    try:
        data, filters = _filter_state_from_body_or_args(state)
        # top=None → không cắt top 200 (rule "xuất ALL record" cho Excel)
        full_payload = compute_baseline_variance(data, top=None)
        filepath = export_baseline_variance_report(
            payload=full_payload,
            output_dir=_project_mgr.get_export_dir(slug),
            filters=filters,
            all_items=full_payload.get("items"),
        )
        return send_file(filepath, as_attachment=True, download_name=os.path.basename(filepath))
    except Exception as e:
        return jsonify({"error": f"Lỗi xuất Baseline: {str(e)}"}), 500


# ==========================================================================
# Function Traceability (BA — Task 1)
# ==========================================================================
# BA nhập mã CN / tên chức năng → autocomplete + modal "Hồ sơ chức năng"
# hiển thị full lifecycle: meta + từng phase (Start/End/Status/PIC) + summary
# (đang ở phase nào, có trễ không, next deadline). Auto-detect cột theo .cursorrules.
# ==========================================================================


@app.route("/api/projects/<slug>/function-search")
def function_search(slug: str):
    """
    Autocomplete tra cứu function. Query params:
    - q: chuỗi search (mã CN / tên / module / quy trình), tối thiểu 1 ký tự
    - limit: số kết quả max (default 10)

    Trả `{items: [...]}` — mỗi item có row_num để mở detail modal.
    """
    from analyzer.function_traceability import search_functions
    state, err = _require_state(slug)
    if err:
        return err
    q = (request.args.get("q") or "").strip()
    try:
        limit = int(request.args.get("limit", 10))
    except (TypeError, ValueError):
        limit = 10
    limit = max(1, min(limit, 50))  # kẹp 1–50

    items = search_functions(state["data"], q, limit=limit)
    return jsonify({"query": q, "count": len(items), "items": items})


@app.route("/api/projects/<slug>/function-detail/<int:row_num>")
def function_detail(slug: str, row_num: int):
    """Full lifecycle của 1 function (theo row_num Excel gốc)."""
    from analyzer.function_traceability import get_function_detail
    state, err = _require_state(slug)
    if err:
        return err
    result = get_function_detail(state["data"], row_num)
    if result is None:
        return jsonify({"error": f"Không tìm thấy function row {row_num}"}), 404
    return jsonify(result)


# ==========================================================================
# FIT/GAP Dashboard (BA — Task 2)
# ==========================================================================
# BA cần section riêng để quản lý lifecycle GAP: cards summary + 3 chart
# (module / quy trình / priority) + bảng aging GAP > 14 ngày. Global filter
# (module/process/pic) apply. Xuất Excel tuân rule V4 (xuất ALL).
# ==========================================================================


@app.route("/api/projects/<slug>/fitgap-analytics")
def fitgap_analytics(slug: str):
    """Cards + 3 chart data + aging list. Apply global filter module/process/pic."""
    from analyzer.fitgap_analytics import compute_fitgap_analytics
    state, err = _require_state(slug)
    if err:
        return err
    data = _filtered_data_from_request(state)
    # Cho phép override aging threshold qua query param (BA có thể thử 7/21/30 ngày)
    try:
        thr = int(request.args.get("aging_threshold_days", 14))
    except (TypeError, ValueError):
        thr = 14
    thr = max(1, min(thr, 365))
    return jsonify(compute_fitgap_analytics(data, aging_threshold_days=thr))


@app.route("/api/projects/<slug>/export-fitgap", methods=["GET", "POST"])
def export_fitgap(slug: str):
    """Xuất Excel FIT/GAP Dashboard (multi-sheet, xuất ALL). Áp global filter."""
    from analyzer.fitgap_analytics import compute_fitgap_analytics
    state, err = _require_state(slug)
    if err:
        return err
    try:
        data, filters = _filter_state_from_body_or_args(state)
        try:
            thr = int(request.args.get("aging_threshold_days", 14))
        except (TypeError, ValueError):
            thr = 14
        payload = compute_fitgap_analytics(data, aging_threshold_days=thr)
        filepath = export_fitgap_report(
            payload=payload,
            output_dir=_project_mgr.get_export_dir(slug),
            filters=filters,
        )
        return send_file(filepath, as_attachment=True, download_name=os.path.basename(filepath))
    except Exception as e:
        return jsonify({"error": f"Lỗi xuất FIT/GAP: {str(e)}"}), 500


# ==========================================================================
# Function Diff (BA — Task 3)
# ==========================================================================
# So sánh state hiện tại với snapshot upload trước. Snapshot đã có sẵn dưới
# dạng pickled ParsedData (SnapshotManager). Không cần tạo JSON snapshot
# riêng — pickle rẻ hơn và đã có sẵn full data.
#
# Match function bằng Mã CN, fallback theo (Tên + Module). Trả 6 tab data:
# Added / Deleted / PIC / Priority-Complexity / FIT-GAP / Phase Status.
# ==========================================================================


def _resolve_diff_previous_snapshot(slug: str, vs: str):
    """
    Chọn snapshot đóng vai "trước" khi diff.

    Args:
        vs: 'previous' (mặc định) → snapshot ngay trước current;
            hoặc YYYY-MM-DD → snapshot cụ thể.

    Return: (parsed_data_prev, meta_dict, error_response_or_None)
    """
    smgr = _project_mgr.get_snapshot_manager(slug)
    snaps = smgr.list_snapshots()
    if not snaps:
        return None, None, (
            jsonify({"error": "Chưa có snapshot nào để so sánh", "code": "NO_SNAPSHOT"}),
            404,
        )

    if vs and vs != "previous":
        # snapshot cụ thể theo date
        loaded = smgr.load_snapshot(vs)
        if not loaded:
            return None, None, (jsonify({"error": f"Snapshot {vs} không tồn tại"}), 404)
        return loaded["parsed"], loaded["meta"], None

    # vs=previous → snapshot ngay trước current.
    # snapshot mới nhất (index 0) là snapshot chính hôm nay (thường trùng current).
    # → 'previous' đúng phải là index 1. Nếu chỉ có 1 snapshot → không diff được.
    if len(snaps) < 2:
        return None, None, (
            jsonify({
                "error": "Chỉ có 1 snapshot — chưa có snapshot trước để so sánh. "
                         "Upload file lần thứ 2 để bắt đầu track diff.",
                "code": "SINGLE_SNAPSHOT",
                "current_snapshot": snaps[0] if snaps else None,
            }),
            404,
        )

    prev_entry = snaps[1]
    loaded = smgr.load_snapshot(prev_entry["date"])
    if not loaded:
        return None, None, (jsonify({"error": "Không load được snapshot trước"}), 500)
    return loaded["parsed"], loaded["meta"], None


@app.route("/api/projects/<slug>/function-diff")
def function_diff(slug: str):
    """
    So sánh state hiện tại với snapshot trước.
    Query params:
    - vs: 'previous' (default) hoặc YYYY-MM-DD của snapshot cụ thể.
    """
    from analyzer.function_diff import compute_function_diff
    state, err = _require_state(slug)
    if err:
        return err

    vs = request.args.get("vs", "previous").strip() or "previous"
    prev_data, prev_meta, err2 = _resolve_diff_previous_snapshot(slug, vs)
    if err2:
        return err2

    # Meta cho snapshot "current" — dùng thông tin _state
    current_meta = {
        "date": state["upload_time"].date().isoformat() if state.get("upload_time") else None,
        "filename": state.get("filename", "current.xlsx"),
        "total_functions": len(state["data"].rows),
    }

    payload = compute_function_diff(
        current=state["data"],
        previous=prev_data,
        current_meta=current_meta,
        previous_meta=prev_meta,
    )
    # List snapshots để FE hiển thị dropdown "so với snapshot nào"
    payload["available_snapshots"] = _project_mgr.get_snapshot_manager(slug).list_snapshots()
    return jsonify(payload)


@app.route("/api/projects/<slug>/export-function-diff")
def export_function_diff(slug: str):
    """Xuất Excel Function Diff (multi-sheet, xuất ALL). Query: ?vs="""
    from analyzer.function_diff import compute_function_diff
    state, err = _require_state(slug)
    if err:
        return err

    vs = request.args.get("vs", "previous").strip() or "previous"
    prev_data, prev_meta, err2 = _resolve_diff_previous_snapshot(slug, vs)
    if err2:
        return err2

    current_meta = {
        "date": state["upload_time"].date().isoformat() if state.get("upload_time") else None,
        "filename": state.get("filename", "current.xlsx"),
        "total_functions": len(state["data"].rows),
    }

    try:
        payload = compute_function_diff(
            current=state["data"],
            previous=prev_data,
            current_meta=current_meta,
            previous_meta=prev_meta,
        )
        filepath = export_function_diff_report(
            payload=payload,
            output_dir=_project_mgr.get_export_dir(slug),
        )
        return send_file(filepath, as_attachment=True, download_name=os.path.basename(filepath))
    except Exception as e:
        return jsonify({"error": f"Lỗi xuất Function Diff: {str(e)}"}), 500


# ==========================================================================
# Main
# ==========================================================================

if __name__ == "__main__":
    import sys

    debug_mode = "--debug" in sys.argv
    reloader = debug_mode  # chỉ auto-reload khi user bật --debug

    print("\n" + "=" * 60)
    print("  iHRP Function List Tracker (V3)")
    print("  http://localhost:5000")
    if debug_mode:
        print("  Mode: DEBUG (auto-reload BAT khi sua file)")
    else:
        print("  Mode: PRODUCTION (on dinh, khong auto-reload)")
    print("=" * 60 + "\n")
    try:
        app.run(debug=debug_mode, use_reloader=reloader, port=5000, host="0.0.0.0")
    except Exception as e:
        print(f"\n[LOI] Server crash: {e}")
        import traceback
        traceback.print_exc()
        input("\nNhan Enter de thoat...")
