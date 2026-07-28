# Kiến trúc hệ thống — V3 (Multi-Project)

## Luồng xử lý chính

```
[User chọn project X, upload .xlsx]
    → POST /api/projects/<slug>/upload?threshold=<N>
    → project_manager.py: kiểm tra project tồn tại, get_current_file_path()
    → File save vào uploads/projects/<slug>/current.xlsx
    → excel_parser.py: FunctionListParser().parse(file)
        → Load workbook với read_only=True + data_only=True (V3 speed: 4× nhanh hơn)
        → Streaming iter_rows(values_only=True) → matrix in memory
        → Row 1 → headers
        → Detect meta columns (Module, Priority, Complexity, FIT/GAP, Giai đoạn, Tên CN, Mã CN, Quy trình, Risk/Blocker...)
        → Detect phase groups bằng regex: "^(.+) - (.+)$"
        → Parse data rows → normalize dates, statuses, PICs
        → Normalize PIC names case-insensitively (SonHN6 == SONHN6)
        → Return: ParsedData
    → dashboard_engine.py: DashboardEngine(threshold).compute_all(parsed_data)
        → Tính 18 metrics (V1 + V2 additions)
        → Trong đó gọi analyzer/risk_scorer.py: compute_all_risk_scores(...)
        → Return: dict JSON-serializable
    → project_manager.get_snapshot_manager(slug).save_snapshot(xlsx, parsed_data, metrics)
        → Copy file → uploads/projects/<slug>/snapshots/{date}_functionlist.xlsx
        → Serialize ParsedData → .parsed.pkl
        → Update project's snapshot_index.json (max 30 bản)
    → project_manager.touch_last_upload(slug)  # cập nhật last_upload_at
    → _state[slug] = {data, metrics, filename, upload_time}  # cache memory
    → app._trim_payload(metrics)  # trim risk_scores→50, unassigned→300, stalled/duration→200
    → Response JSON: { project, metrics (trimmed), snapshots, upload_time }
```

## Cấu trúc thư mục (V3)

```
Project_Tracking/
├── start.bat / start.sh              # Launcher (V3: auto-kill port 5000)
├── requirements.txt                  # Deps (Flask, openpyxl, pandas, pytest, pytest-cov)
├── app.py                            # Flask server + 25+ API endpoints (project-scoped)
├── parser/
│   └── excel_parser.py               # Auto-detect + parse Function List (streaming iter_rows)
├── analyzer/
│   ├── dashboard_engine.py           # 18 metrics
│   ├── risk_scorer.py                # Risk score 0-100
│   ├── snapshot_manager.py           # Snapshot & load — per project
│   ├── compare_engine.py             # So sánh 2 snapshot / 2 project
│   └── project_manager.py            # V3: Multi-project CRUD + auto-migrate legacy
├── exporter/
│   └── excel_exporter.py             # 4 loại export: overdue / full / by-pic / compare
├── templates/
│   └── index.html                    # Single-page dashboard + project selector + modal
├── static/
│   ├── css/style.css                 # Dark mode, heatmap, gantt, treemap
│   └── js/dashboard.js               # Render tất cả section + project management + pagination
├── tests/                            # pytest — 187 tests (V3 + drill-down + global filter)
│   ├── conftest.py                   # Fixtures (tmp_path per test)
│   ├── test_parser.py                # 16 tests
│   ├── test_dashboard_engine.py      # 22 tests
│   ├── test_risk_scorer.py           # 14 tests
│   ├── test_compare_engine.py        # 8 tests
│   ├── test_snapshot_manager.py      # 9 tests
│   ├── test_exporter.py              # 6 tests
│   ├── test_api.py                   # 18 legacy HTTP tests
│   ├── test_project_manager.py       # 29 tests (V3 CRUD + export_dir)
│   ├── test_project_api.py           # 23 tests (V3 HTTP)
│   ├── test_drill_down.py            # 21 tests (drill-down engine)
│   ├── test_drill_down_api.py        # 10 tests (drill-down HTTP + export)
│   └── test_global_filter.py         # 13 tests (V3.1 module/process filter)
├── uploads/
│   └── projects/                     # V3: mỗi project 1 folder
│       ├── projects.json             # Index toàn bộ project
│       ├── default/                  # Auto-created project
│       │   ├── meta.json
│       │   ├── current.xlsx
│       │   ├── exports/              # (V3) Excel export riêng per-project
│       │   │   ├── Overdue_Report_YYYYMMDD.xlsx
│       │   │   ├── Full_Report_YYYYMMDD.xlsx
│       │   │   └── DrillDown_*.xlsx
│       │   └── snapshots/
│       │       ├── snapshot_index.json
│       │       ├── YYYY-MM-DD_functionlist.xlsx
│       │       └── YYYY-MM-DD_functionlist.parsed.pkl
│       └── <other-project-slug>/     # Client B, Client C...
└── docs/
    ├── README.md
    ├── ARCHITECTURE.md               # File này
    ├── DATA_MODEL.md
    ├── DASHBOARD_SPEC.md
    └── UPGRADE_V2.md                 # Original V2 spec (historical)
```

## Module: `parser/excel_parser.py`

### Class: `FunctionListParser`

```python
class FunctionListParser:
    """
    Auto-detect cấu trúc file Function List.
    KHÔNG hardcode index cột — mọi thứ dựa trên header text row 1.
    """

    def parse(self, filepath: str) -> ParsedData:
        """Entry point. Đọc file .xlsx → ParsedData."""

    def _detect_headers(self, ws) -> dict[str, int]:
        """Row 1 → {header_text: col_index}"""

    def _detect_meta_columns(self, headers) -> dict[str, int | None]:
        """Tìm cột Module, Priority, Complexity... bằng keyword matching."""

    def _detect_phase_groups(self, headers) -> list[PhaseGroup]:
        """
        Tìm nhóm phase bằng pattern "PhaseName - Attribute".
        Return list of PhaseGroup, mỗi group có:
          - name: str (VD: "Analysis", "Dev", "Config UAT")
          - attributes: dict[str, int] mapping attribute name → col index
            Possible: Start/From/Planned, End/To/Actual, Status, Estimate MH,
                      PIC, PIC FPT, PIC MPHG, Note, RlogID, Defect, Phase
        """

    def _normalize_date(self, value) -> date | None:
        """datetime | "dd/MM/yyyy" | "yyyy-MM-dd HH:MM:SS" | "yyyy-MM-dd" | None"""

    def _normalize_status(self, value) -> str | None:
        """
        - Value trong VALID_STATUSES (case-insensitive) → return canonical
        - Value là số (Estimate MH lệch cột) → None
        - Không nhận diện → None
        """

    def _parse_pics(self, value) -> list[str]:
        """Tách PIC theo , ; + \n. Strip, filter empty và '-', 'n/a'."""

    def _normalize_pic_names(self, rows) -> None:
        """
        [V2] Merge PIC name case-insensitively.
        "SonHN6" + "SONHN6" → chuẩn hóa thành "SonHN6" (version có mix case).
        Modifies rows in-place.
        """
```

### Data Classes

```python
VALID_STATUSES = {"Open", "Assigned", "In-progress", "Resolved", "Closed", "Pending", "Cancelled"}

@dataclass
class PhaseGroup:
    name: str
    attributes: dict[str, int]

    @property
    def start_col(self) -> int | None:    # Start | From | Planned
    @property
    def end_col(self) -> int | None:      # End | To | Actual
    @property
    def status_col(self) -> int | None:
    @property
    def pic_cols(self) -> list[int]:      # Tất cả cột có "PIC" trong tên
    @property
    def estimate_col(self) -> int | None:
    @property
    def note_col(self) -> int | None:
    @property
    def task_type(self) -> str:           # Map name → "Phân tích" / "Lập trình" / ...

@dataclass
class PhaseData:
    start_date: date | None
    end_date: date | None
    status: str | None
    pics: list[str]
    estimate_mh: float | None
    note: str | None
    extra: dict[str, Any]                 # Defect, RlogID, Phase con...

@dataclass
class FunctionRow:
    row_num: int
    meta: dict[str, Any]                  # {stt, ma_cn, ten_cn, module, priority, complexity, ...}
    phases: dict[str, PhaseData]

@dataclass
class ParsedData:
    headers: dict[str, int]
    meta_columns: dict[str, int | None]
    phase_groups: list[PhaseGroup]
    rows: list[FunctionRow]
    all_modules: list[str]
    all_phases: list[str]
    all_pics: list[str]
    all_statuses: list[str]
    all_priorities: list[str]
    all_complexities: list[str]
    all_giai_doan: list[str]
```

## Module: `analyzer/dashboard_engine.py`

### Class: `DashboardEngine`

```python
class DashboardEngine:
    """Tính tất cả metrics từ ParsedData."""

    def __init__(self, today: date | None = None, long_duration_threshold: int = 3):
        self.today = today or date.today()
        self.long_duration_threshold = long_duration_threshold

    def compute_all(self, data: ParsedData) -> dict:
        """Return JSON-serializable dict với 18 metrics:"""
        return {
            # Core V1
            "structure": ...,
            "summary": ...,
            "module_overview": ...,
            "phase_status_matrix": ...,
            "progress_by_task_type": ...,
            "pic_workload": ...,
            "overdue_list": ...,
            "priority_breakdown": ...,
            "complexity_breakdown": ...,
            "fit_gap_analysis": ...,
            "giai_doan_progress": ...,
            "phase_progress_stacked": ...,
            # V2 P1
            "unassigned_tasks": ...,
            "duration_analysis": ...,
            "stalled_tasks": ...,
            "risk_scores": ...,
            # V2 P2/P3
            "effort_analysis": ...,
            "process_analysis": ...,
            "timeline_data": ...,
        }
```

### Summary schema (V2)

```python
{
    "total_functions": int,
    "total_overdue": int,             # Số function UNIQUE có ít nhất 1 phase overdue
    "total_overdue_records": int,     # Số phase-level record overdue (dùng cho bảng)
    "overall_progress_pct": float,    # % function Closed ở phase cuối
    "last_phase_name": str,           # Tên phase cuối (hiển thị bổ sung cho pct)
    "modules_count": int,
    "phases_count": int,
    "unassigned_count": int,          # Số function UNIQUE có ít nhất 1 phase chưa PIC
    "unassigned_records": int,        # Số phase-level record chưa PIC
    "high_risk_count": int,           # Số function có Risk Score >= 50
}
```

## Module: `analyzer/risk_scorer.py`

Tính Risk Score 0-100 cho mỗi function dựa trên 8 yếu tố có trọng số:

| Yếu tố | Điểm |
|---|---|
| Priority = Must-have | +20 |
| Priority = Should-have | +10 |
| Complexity = High | +15 |
| Complexity = Medium | +5 |
| Có ít nhất 1 phase overdue | +20 |
| Mỗi 7 ngày overdue | +10 (cap +30) |
| Phase active không có PIC | +15 |
| Có phase duration > threshold | +10 |
| Bị stalled (phase trước Closed, phase sau chưa bắt đầu) | +10 |
| Có Risk/Blocker note | +5 |

Cap tối đa 100 điểm.

## Module: `analyzer/snapshot_manager.py`

Lưu snapshot mỗi lần upload, phục vụ Compare Mode:
- File `.xlsx` gốc → `uploads/snapshots/{YYYY-MM-DD}_functionlist.xlsx`
- Serialized ParsedData → `.parsed.pkl` (pickle)
- Metadata trong `snapshot_index.json`
- Cùng ngày ghi đè, max 30 snapshots (auto cleanup)

## Module: `analyzer/compare_engine.py`

So sánh 2 ParsedData:
1. **Matching function**: primary key = Mã CN. Fallback = Tên CN + Module (exact match, case-insensitive)
2. **Detect**: new_functions, removed_functions, status_changes (forward/backward/lateral)
3. **Aggregate**: module_deltas, phase_deltas, transitions_agg, velocity metrics

## Module: `exporter/excel_exporter.py`

4 loại export:
- `export_overdue_report(overdue_list, output_dir, filters)` — 1 sheet
- `export_full_report(metrics, output_dir)` — 6 sheet (Summary, Overdue, Unassigned, Long Duration, Stalled, High Risk)
- `export_by_pic(metrics, pic_name, output_dir)` — 3 sheet (Info, Overdue, Active)
- `export_compare_report(compare_result, old_date, new_date, output_dir)` — 5 sheet

Highlight màu theo mức trễ (>14d: đỏ, 7-14d: cam, 1-7d: vàng).

## API Endpoints (V3)

Toàn bộ endpoint có 2 dạng: **project-scoped** (recommended) và **legacy** (mặc định "default").

### Project CRUD (V3)
```
GET    /api/projects?include_archived=1    List projects
POST   /api/projects                       Create {name, description}
GET    /api/projects/<slug>                Get single project
PUT    /api/projects/<slug>                Rename {name, description}
DELETE /api/projects/<slug>?soft=1         Delete (soft=archive, không có param=xóa cứng)
POST   /api/projects/<slug>/restore        Unarchive
```

### Upload & Dashboard (per-project)
```
POST   /api/projects/<slug>/upload         Upload xlsx vào project
GET    /api/projects/<slug>/dashboard      Metrics (payload đã trim)
POST   /api/upload                         Legacy: upload vào 'default'
GET    /api/dashboard                      Legacy: dashboard 'default'
```

### Advanced analytics (per-project + legacy)
```
GET    /api/projects/<slug>/overdue?module=&pic=&phase=&min_days=&limit=&offset=
GET    /api/projects/<slug>/unassigned?module=&phase=&limit=&offset=
GET    /api/projects/<slug>/long-duration
GET    /api/projects/<slug>/stalled
GET    /api/projects/<slug>/risk-scores?top=<N>
```

### Snapshot & Compare (per-project)
```
GET    /api/projects/<slug>/snapshots
DELETE /api/projects/<slug>/snapshots/<date>
GET    /api/projects/<slug>/compare?old=<date>&new=<date>       Intra-project
POST   /api/projects/<slug>/upload-compare                       Upload file → compare với current
GET    /api/compare-cross?project_a=&snap_a=&project_b=&snap_b= Cross-project (V3)
```

### Exports (per-project)
```
GET    /api/projects/<slug>/export-overdue?module=&pic=&phase=
POST   /api/projects/<slug>/export-overdue                      (body JSON filters)
GET    /api/projects/<slug>/export-full-report
GET    /api/projects/<slug>/export-by-pic?pic=<name>
GET    /api/projects/<slug>/export-compare?old=&new=
```

### Project Package Export/Import (V3)
```
GET    /api/projects/<slug>/export-package     Download zip: xlsx + snapshots + meta
POST   /api/projects/import-package            Upload zip → tạo project mới
```

### Payload trimming (V3 speed)
Response `/upload` và `/dashboard` tự động trim để giảm bandwidth:
- `risk_scores` → top 50 (frontend chỉ hiện top 20)
- `unassigned_tasks` → top 300 (pagination FE)
- `duration_analysis.items` → top 200
- `stalled_tasks.items` → top 200

Kèm field `<name>_total` để FE biết số thực tế. Endpoint riêng (`/api/projects/<slug>/unassigned?limit=&offset=`) hỗ trợ pagination đầy đủ khi user cần xem all.

## Frontend UI

Single page (`templates/index.html`), Tailwind + Chart.js CDN. Layout:

```
┌────────────────────────────────────────────────────────────┐
│  HEADER: Title + Search bar + Dark mode toggle             │
├────────────────────────────────────────────────────────────┤
│  Refresh reminder banner (nếu upload > 24h)                │
│  Upload zone (drag & drop .xlsx)                           │
├────────────────────────────────────────────────────────────┤
│  SUMMARY (6 cards): Total | Progress | Overdue | Unassigned│
│                     | HighRisk | Modules                    │
├────────────────────────────────────────────────────────────┤
│  Action toolbar: Export Full | Export By PIC | Threshold    │
├────────────────────────────────────────────────────────────┤
│  COMPARE section (V2 P2): 2 snapshot dropdown + delta cards│
├────────────────────────────────────────────────────────────┤
│  WEEKLY DIGEST (V2 P2): report style + Print button        │
├─────────────────────┬──────────────────────────────────────┤
│  Module Overview    │  Task Type Chart                      │
├─────────────────────┴──────────────────────────────────────┤
│  Phase × Module Matrix (heatmap)                            │
├─────────────────────┬──────────────────────────────────────┤
│  Phase Stacked      │  PIC Workload                         │
├──────────┬──────────┼──────────────────────────────────────┤
│ Priority │ Complexity │ FIT/GAP                             │
├──────────┴──────────┴──────────────────────────────────────┤
│  Giai đoạn Progress                                         │
├────────────────────────────────────────────────────────────┤
│  🚨 Unassigned Tasks (V2 P1)                               │
├────────────────────────────────────────────────────────────┤
│  ⏱️ Duration Analysis (V2 P1): summary + box plot + scatter│
├────────────────────────────────────────────────────────────┤
│  🔄 Pipeline / Stalled Tasks (V2 P1): funnel + transitions │
├────────────────────────────────────────────────────────────┤
│  ⚡ Top 20 High-Risk Functions (V2 P1)                     │
├────────────────────────────────────────────────────────────┤
│  📊 Effort Analysis (V2 P2): MH heatmap + PIC MH bar       │
├────────────────────────────────────────────────────────────┤
│  🏷️ Process Analysis (V2 P3): treemap                     │
├────────────────────────────────────────────────────────────┤
│  📅 Timeline Gantt (V2 P3)                                 │
├────────────────────────────────────────────────────────────┤
│  ⚠️ Overdue Table (filterable + export)                    │
└────────────────────────────────────────────────────────────┘

+ Sidebar nav (fixed) để jump nhanh giữa các section
+ Fullscreen chart button trên mỗi biểu đồ
+ Escape key để đóng fullscreen
```

### Color scheme
- Background: `#f8fafc` (dark: `#0f172a`)
- Cards: white shadow-md rounded-xl (dark: `#1e293b`)
- Status colors: Closed=`#22c55e`, In-progress=`#3b82f6`, Assigned=`#f59e0b`, Open=`#6b7280`, Resolved=`#8b5cf6`, Pending=`#f97316`, Cancelled=`#ef4444`
- Overdue highlight: >14d = red, 7-14d = orange, 1-7d = yellow
- Risk score bar: ≥80 red, ≥50 orange, ≥30 yellow, <30 green

## Testing

Chạy toàn bộ test suite:
```bash
pytest tests/ -v
```

Xem coverage:
```bash
pytest tests/ --cov=parser --cov=analyzer --cov=exporter --cov-report=term-missing
```

Test được tổ chức theo module:
- `test_parser.py`: Auto-detect, date/status normalize, PIC parsing, edge cases
- `test_dashboard_engine.py`: Từng metric riêng biệt + summary consistency
- `test_risk_scorer.py`: Trọng số + cap 100
- `test_compare_engine.py`: Matching, status direction, velocity
- `test_snapshot_manager.py`: Save/load/delete + cleanup 30-item limit
- `test_exporter.py`: 4 loại export sinh file .xlsx hợp lệ
- `test_api.py`: HTTP integration cho legacy endpoints
- `test_project_manager.py`: V3 CRUD project + slug + auto-migrate legacy
- `test_project_api.py`: V3 HTTP integration cho project-scoped endpoints + import/export zip

**Kết quả hiện tại**: 187 tests / 90-120s runtime / 94%+ coverage.

Test breakdown:
- Core (V1/V2): `test_parser`, `test_dashboard_engine`, `test_risk_scorer`,
  `test_compare_engine`, `test_snapshot_manager`, `test_exporter`, `test_api`
- V3 Multi-project: `test_project_manager`, `test_project_api`
- V3 Drill-down: `test_drill_down`, `test_drill_down_api`
- V3.1 Global filter: `test_global_filter`

## Module: `analyzer/drill_down.py` (V3)

Từ 1 cell/segment biểu đồ → sinh list function chi tiết + xuất Excel riêng.

### Chart types hỗ trợ (`SUPPORTED_CHARTS`)

| Chart key      | Filter keys yêu cầu           | Nguồn UI                            |
|----------------|-------------------------------|-------------------------------------|
| `phase_matrix` | `module`, `phase`             | Click cell trong Phase × Module     |
| `phase_stacked`| `phase`, `status`             | Click bar Phase Stacked             |
| `pic_workload` | `pic`, optional `status`      | Click bar PIC Workload              |
| `priority`     | `priority`                    | Click segment Priority doughnut     |
| `complexity`   | `complexity`                  | Click segment Complexity doughnut   |
| `fit_gap`      | `module`, `fit_gap`           | Click bar FIT/GAP                    |
| `giai_doan`    | `giai_doan`, optional `phase` | Click bar Giai đoạn                 |
| `module`       | `module`                      | Click row Module Overview           |
| `process`      | `process`                     | (chuẩn bị cho treemap click)        |

### Output schema (unified cho mọi chart)

```python
{
    "ma_cn", "ten_cn", "module", "quy_trinh", "priority", "complexity",
    "fit_gap", "giai_doan", "phase", "status", "pics",
    "start_date", "end_date", "days_overdue", "is_overdue", "estimate_mh"
}
```

### API

```
GET  /api/projects/<slug>/drill-down?chart=<name>&module=&phase=&status=&pic=&...
POST /api/projects/<slug>/drill-down/export   Body JSON: {chart, filters}
```

## Global Filter (V3.1)

Ở section trên dashboard cho phép user chọn Module và/hoặc Quy trình →
`renderDashboard()` gọi lại `/api/projects/<slug>/dashboard?module=X&process=Y`,
backend `_filter_parsed_data()` tạo `ParsedData` subset (shared refs cho phase_groups)
rồi `DashboardEngine().compute_all()` lại. UI reflect toàn bộ 18 section.

Response có field `applied_filter = {module, process, row_count}` để badge FE hiển thị.

## Chart Responsive (V3.1)

- Container `.chart-box` dùng CSS `clamp(min, vh-based, max)` để height scale mượt
  theo viewport (mobile → desktop → 2K)
- `createChart()` force `responsive: true` + `maintainAspectRatio: false`
- Window resize handler debounced 150ms gọi `chart.resize()` cho tất cả instance

## Module: `analyzer/project_manager.py` (V3)

### Class: `ProjectManager`

```python
class ProjectManager:
    """
    Quản lý danh sách project + storage per-project.
    Auto-migrate legacy V2 layout (uploads/snapshots/) vào 'default'.
    """
    def __init__(self, base_dir: str)                       # uploads/projects/

    # CRUD
    def create_project(name, description) -> Project
    def list_projects(include_archived=False) -> list[Project]
    def get_project(slug) -> Optional[Project]
    def rename_project(slug, new_name, new_description) -> bool
    def delete_project(slug) -> bool                         # hard delete
    def archive_project(slug, archived=True) -> bool         # soft delete
    def touch_last_upload(slug) -> None

    # Storage per-project
    def get_snapshot_manager(slug) -> SnapshotManager        # scoped to project folder
    def get_current_file_path(slug) -> str                   # /projects/<slug>/current.xlsx
    def get_project_folder(slug) -> str                      # /projects/<slug>/
    def get_export_dir(slug) -> str                          # /projects/<slug>/exports/ (auto-create)
    def project_exists(slug) -> bool
    def get_or_create_default() -> Project                   # ensure 'default' exists
```

### Slug generation
- `slugify("Minh Phú 2026")` → `"minh-phu-2026"` (bỏ dấu, lowercase, dashes)
- Nếu trùng: append `-2`, `-3`... để unique

### Auto-migrate legacy V2
Khi ProjectManager khởi tạo và `projects.json` chưa tồn tại:
1. Check `uploads/snapshots/` và `uploads/current_functionlist.xlsx`
2. Nếu có → tạo project "default" và copy files vào
3. Nếu không → chỉ tạo empty index
4. Chỉ chạy 1 lần; lần thứ 2 khởi tạo với index đã có sẽ skip
