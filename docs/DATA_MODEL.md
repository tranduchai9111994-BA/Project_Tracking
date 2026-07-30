# Data Model — Function List Excel + Project Store

> Schema parse Excel (ổn định từ V2) + các file JSON / snapshot mở rộng tới
> Archive, Public API, Integrations, Mapping presets (2026-07).
> Kiến trúc tổng thể → [`ARCHITECTURE.md`](ARCHITECTURE.md).

## Cấu trúc file Excel đầu vào

### Sheet chính
Parser tìm sheet có tên chứa `"Function List"` hoặc `"functionlist"` (case-insensitive).
Nếu không tìm thấy → dùng sheet đầu tiên (`workbook.worksheets[0]`).

### Layout
- **Row 1**: Headers
- **Row 2+**: Data (mỗi row = 1 function/chức năng)

Parser bỏ qua row nào không có STT, Mã CN và Tên chức năng (ít nhất 1 trong 3 phải có giá trị).

## Nhóm cột Meta (thông tin chung của function)

Parser tự detect bằng keyword matching (`META_KEYWORDS` trong `parser/excel_parser.py`):

| Meta key       | Keyword header                                    | Ý nghĩa                    | Ví dụ                                     |
|----------------|---------------------------------------------------|----------------------------|-------------------------------------------|
| `stt`          | "STT", "No", "#"                                  | Số thứ tự                  | 1, 2, 3                                   |
| `ma_cn`        | "Mã CN", "Mã chức năng", "Function Code", "Code"  | Mã chức năng               | "TMS.FR.01"                               |
| `ten_cn`       | "Tên chức năng", "Function Name", "Tên CN"        | Tên function               | "Thiết lập Ca làm việc"                   |
| `module`       | "Module", "Phân hệ"                               | Module                     | "TMS", "HR", "PR", "SYS", "APP", "ESS"    |
| `system`       | "System", "Hệ thống"                              | Hệ thống                   | "iHRP"                                    |
| `fid`          | "FID", "Function ID"                              | Function ID gốc            | 502, 6084                                 |
| `quy_trinh`    | "Quy trình", "Process", "Business Process"        | Quy trình nghiệp vụ        | "TMS.BP.01 - Quy trình thực hiện chấm công"|
| `requirement_id` | "Requirement ID", "Req ID"                      | Mã requirement             |                                           |
| `fit_gap`      | "FIT/GAP", "FIT GAP", "Fit/Gap"                   | Phân loại FIT/GAP          | "FIT", "GAP", "Customization"             |
| `giai_doan`    | "Giai đoạn", "Stage"                              | Phase dự án                | "1", "2", "3" (hoặc "2A", "2.5")          |
| `priority`     | "Priority", "Ưu tiên", "Độ ưu tiên"               | Độ ưu tiên                 | "Must-have", "Should-have"                |
| `complexity`   | "Complexity", "Độ phức tạp"                       | Độ phức tạp                | "Low", "Medium", "High"                   |
| `mo_ta`        | "Mô tả", "Description"                            | Mô tả chi tiết             | Text tự do                                |
| `function_lq`  | "Function liên quan", "Related Function"          | Function liên quan         |                                           |
| `risk_blocker` | "Risk/Blocker", "Risk", "Blocker"                 | Rủi ro                     | Text tự do                                |
| `last_updated` | "Last Updated Date", "Last Updated", "Ngày cập nhật" | Ngày cập nhật cuối      | datetime                                  |
| `remark`       | "Remark", "Ghi chú chung"                         | Ghi chú                    | Text tự do                                |
| `ma_du_an`     | "Mã dự án", "Project Code", "Project"             | Mã dự án nguồn            | "MPHG_IHRP_2025_PM"                       |

**Rule detect:**
1. Exact match (case-insensitive) trước
2. Partial match (keyword là substring của header) — chỉ khi header **KHÔNG chứa " - "** (để tránh nhầm với phase attributes)

## Nhóm cột Phase (theo pattern "PhaseName - Attribute")

Parser tự phát hiện phase groups bằng regex `^(.+) - (.+)$` trên tên header row 1. Split theo `" - "` cuối cùng.

Ví dụ:
- `"Analysis - Start"` → phase="Analysis", attr="Start"
- `"Config UAT - Estimate MH"` → phase="Config UAT", attr="Estimate MH"

### Attribute types

| Attribute       | Property alias        | Ý nghĩa                  | Data type      |
|-----------------|-----------------------|--------------------------|----------------|
| Start / From / Planned | `start_col`    | Ngày bắt đầu             | date           |
| End / To / Actual      | `end_col`      | Ngày kết thúc            | date           |
| Status          | `status_col`          | Trạng thái               | string (enum)  |
| Estimate MH     | `estimate_col`        | Ước lượng man-hour       | number         |
| PIC / PIC FPT / PIC MPHG | `pic_cols` (list) | Người phụ trách       | multi-string   |
| Note            | `note_col`            | Ghi chú                  | text           |
| RlogID          | `extra`               | ID release log           | string         |
| Defect          | `extra`               | Số defect                | number         |
| Phase           | `extra`               | Phase con (1a, 2b...)    | string         |

**Note:** Property `pic_cols` scan tất cả attribute key có chứa "PIC" (case-insensitive) → hỗ trợ file có nhiều loại PIC (FPT/MPHG/khách hàng).

## Các Phase thường gặp

Thứ tự từ trái → phải trong file cũng là thứ tự thực hiện (parser preserve order):

1. **Analysis** — Phân tích
2. **Dev** — Lập trình
3. **Config Local** — Cấu hình môi trường Local/Test
4. **Config UAT** — Cấu hình môi trường UAT
5. **Document** — Tài liệu
6. **Config PROD** — Cấu hình Production
7. **UAT** — User Acceptance Testing (thường dùng From/To)
8. **Golive** — Go-live (thường dùng Planned/Actual + có Phase con)

Task type mapping (`TASK_TYPE_RULES`):

| Phase name regex   | Task type (tiếng Việt) |
|--------------------|------------------------|
| `(?i)analy`        | Phân tích              |
| `(?i)\bdev\b`      | Lập trình              |
| `(?i)local\|test`  | Kiểm thử               |
| `(?i)config.*uat`  | Cấu hình UAT           |
| `(?i)^uat$`        | UAT                    |
| `(?i)doc`          | Tài liệu               |
| `(?i)prod\|golive` | Cấu hình Golive        |
| Không match        | Giữ nguyên tên phase   |

## Giá trị Status hợp lệ

```
Open        → Chưa bắt đầu
Assigned    → Đã phân công
In-progress → Đang thực hiện
Resolved    → Đã xử lý, chờ verify
Closed      → Hoàn thành
Pending     → Tạm dừng
Cancelled   → Hủy bỏ
```

`VALID_STATUSES = {"Open", "Assigned", "In-progress", "Resolved", "Closed", "Pending", "Cancelled"}`

**Data quality rules:**
- Match case-insensitive → return canonical form
- **Nếu ô Status chứa số (1, 2, 8, 16…) → coi như NULL** (lỗi lệch cột với Estimate MH)
- Text không match → NULL

## Date Formats cần xử lý

Parser thử theo thứ tự:
1. `datetime.datetime` object → `.date()`
2. `datetime.date` object → return trực tiếp
3. `int`/`float` → NULL (không phải date, tránh nhầm với Excel serial number)
4. String parse theo các format:
   - `"%d/%m/%Y"`
   - `"%Y-%m-%d %H:%M:%S"`
   - `"%Y-%m-%d"`
   - `"%m/%d/%Y"` (fallback US format)
   - `"%d-%m-%Y"`
5. Không parse được → NULL

## PIC Parsing (V2 với case normalization)

Một ô PIC có thể chứa:
- Một người: `"SonHN6"`
- Nhiều người ngăn bởi `,`: `"BaoLQ31, NhiVN"`
- Nhiều người ngăn bởi `;`: `"CuongNM129;\nTungTT83"`
- Nhiều người ngăn bởi `+`: `"BaoLQ31+ NhiVN+NhuNHT3"`
- Nhiều người ngăn bởi `\n`: xuống dòng trong cell

**Split regex:** `[,;+\n]+`

Sau khi split → strip → filter empty và `"-"`, `"n/a"`.

### 🆕 V2: Case-insensitive normalization

Nếu 1 file có cả `"SonHN6"` và `"SONHN6"` (thường do type nhầm caps lock):
- Parser gộp lại thành 1 người, dùng version có **mix case** (không toàn upper)
- Không ảnh hưởng đến file gốc, chỉ chuẩn hóa trong memory

Ví dụ trước fix: 35 PIC unique (có SonHN6 + SONHN6). Sau fix: 32 PIC unique (đã merge).

## Overdue Logic

```python
def is_overdue(phase_data: PhaseData, today: date) -> bool:
    if phase_data.end_date is None:
        return False
    if phase_data.status in ("Closed", "Cancelled", None):
        return False
    return phase_data.end_date < today

def days_overdue(phase_data, today) -> int:
    if not is_overdue(phase_data, today):
        return 0
    return (today - phase_data.end_date).days
```

**Chú ý:** Status `Resolved` **KHÔNG được miễn overdue** (Resolved = đã xử lý chờ verify, nếu quá deadline vẫn coi là trễ). Chỉ `Closed` và `Cancelled` mới miễn overdue.

## Function-level vs Phase-level count

Đây là điểm dễ nhầm — V2 phân biệt rõ:

| Đại lượng                | Function-level (unique)        | Phase-level (records)          |
|--------------------------|--------------------------------|--------------------------------|
| Overdue count            | `summary.total_overdue`        | `summary.total_overdue_records` |
| Unassigned count         | `summary.unassigned_count`     | `summary.unassigned_records`   |
| Overdue list             | -                              | `metrics.overdue_list` (mỗi phase overdue = 1 record) |
| Unassigned list          | -                              | `metrics.unassigned_tasks`     |
| Module Overview overdue  | `module.overdue_count` (function-unique) | -                    |
| PIC Workload total_tasks | -                              | `pic_workload[i].total_tasks` (phase × PIC × function) |

**Ví dụ:** file 375 chức năng thực tế → 44 function có ít nhất 1 phase overdue → nhưng tổng phase-level record là 74 (nhiều function có 2-3 phase overdue).

Card summary dùng số function-unique để tránh gây hoang mang (VD: không nên hiển thị "610 chưa PIC" khi chỉ có 375 function). Bảng chi tiết dùng phase-level để PM biết chính xác phase nào.

## Ví dụ dữ liệu thực tế

```json
{
  "row_num": 15,
  "meta": {
    "stt": 14,
    "ma_cn": "TMS.FR.14",
    "ten_cn": "Tổng hợp công từ máy chấm công",
    "module": "TMS",
    "system": "iHRP",
    "quy_trinh": "TMS.BP.01 - Quy trình thực hiện chấm công",
    "fit_gap": "FIT",
    "giai_doan": "2",
    "priority": "Must-have",
    "complexity": "Medium"
  },
  "phases": {
    "Analysis": {
      "start_date": "2026-04-03",
      "end_date": "2026-04-03",
      "status": "Closed",
      "pics": ["PhatTPT3"],
      "estimate_mh": 8
    },
    "Config UAT": {
      "start_date": null,
      "end_date": null,
      "status": "Assigned",
      "pics": [],
      "estimate_mh": null
    },
    "UAT": {
      "start_date": "2026-04-16",
      "end_date": "2026-04-17",
      "status": "Resolved",
      "pics": ["PhatTPT3"],
      "estimate_mh": 16,
      "note": null,
      "extra": {"Defect": 2}
    },
    "Golive": {
      "start_date": "2026-04-20",
      "end_date": "2026-04-20",
      "status": "Closed",
      "pics": [],
      "extra": {"Phase": "2A"}
    }
  }
}
```

## Multi-Project Layout (V3+)

Từ V3 trở đi, storage được tổ chức theo project (chi tiết đầy đủ + sơ đồ →
[`ARCHITECTURE.md`](ARCHITECTURE.md) §5):

```
uploads/
  projects/
    projects.json                       # Index tất cả project
    <slug>/                             # VD "minh-phu-2026"
      meta.json
      current.xlsx
      integrations.json                 # Registry API (no secrets)
      archive_settings.json
      project_settings.json
      bookmarks.json / function_notes.json / chart_notes.json / …
      exports/
      digests/
      snapshots/
        snapshot_index.json             # + source, archived
        YYYY-MM-DD_functionlist.xlsx|.parsed.pkl
        archive/                        # *.gz khi đã archive
```

Public tokens / PNG cache: `.project_store/<slug>/` (xem T33 bên dưới).

### `projects.json` format

```json
[
  {
    "slug": "default",
    "name": "Default",
    "description": "Project mặc định",
    "created_at": "2026-07-28T08:00:00",
    "last_upload_at": "2026-07-28T09:15:23",
    "is_archived": false,
    "tags": []
  },
  {
    "slug": "minh-phu-2026",
    "name": "Minh Phú 2026",
    "description": "Client Minh Phú, giai đoạn 2026",
    "created_at": "2026-07-28T10:30:00",
    "last_upload_at": null,
    "is_archived": false,
    "tags": []
  }
]
```

### Auto-migrate từ V2 cũ

Nếu có `uploads/snapshots/` và `uploads/current_functionlist.xlsx` (layout V2), khi khởi động ProjectManager sẽ:
1. Tạo project "default" với description "Auto-migrate từ V2 cũ"
2. Copy toàn bộ `uploads/snapshots/*.xlsx`, `*.pkl`, `snapshot_index.json` vào `uploads/projects/default/snapshots/`
3. Copy `uploads/current_functionlist.xlsx` sang `uploads/projects/default/current.xlsx`

Data cũ vẫn giữ nguyên ở vị trí gốc (để user có thể rollback thủ công nếu cần).

## Snapshot format (V2 + source + archive)

`uploads/projects/<slug>/snapshots/snapshot_index.json`:

```json
[
  {
    "date": "2026-07-28",
    "filename": "2026-07-28_functionlist.xlsx",
    "pickle": "2026-07-28_functionlist.parsed.pkl",
    "total_functions": 375,
    "overall_pct": 50.4,
    "overdue_count": 44,
    "unassigned_count": 186,
    "high_risk_count": 102,
    "upload_time": "2026-07-28T08:40:37",
    "source": "upload",
    "archived": false
  }
]
```

| Field | Ý nghĩa |
|-------|---------|
| `source` | `"upload"` (thủ công) hoặc `"sync:<integ_id>:<endpoint_id>"`. Entry cũ thiếu field → default `"upload"`. UI Lịch sử upload hiện cột **Nguồn** + filter. |
| `archived` | `true` → file đã gzip vào `snapshots/archive/`. Load vẫn transparent (decompress in-memory). |
| `archived_at` | ISO datetime khi archive (chỉ khi `archived=true`). |

Cùng ngày upload nhiều lần → ghi đè bản cũ. Giới hạn tổng 30 snapshots hot (bản cũ nhất tự xóa / có thể auto-archive trước). Xem [`ARCHIVE_GUIDE.md`](ARCHIVE_GUIDE.md).

## V4 — Bookmark / Notes / Digest / Settings

Mọi state ngoài Excel đều nằm trong `uploads/projects/<slug>/` dưới dạng JSON
đơn (read/write qua `_read_json` / `_write_json` trong `analyzer/project_store.py`).

### `bookmarks.json` (T24)

```json
{"functions": ["PR.FR.57", "HR.HRM.03"]}
```
- Key = danh sách `ma_cn`; dedupe giữ thứ tự user bấm ⭐.
- Ma_cn dùng vì stable qua re-upload (row_num thay đổi khi user thêm/bớt
  row Excel).

### `function_notes.json` (T24)

```json
{
  "PR.FR.57": {
    "note": "Cần confirm với BA Loan trước 15/08",
    "updated_at": "2026-07-29T10:15:00"
  }
}
```
- Value là dict `{note, updated_at}`. Note rỗng → tự xoá key.

### `chart_notes.json` (T28 — comment per-chart cho PDF export)

```json
{
  "summary": "Tuần 30/2026 — overdue giảm 22%. Trọng tâm: đẩy UAT CBLD.",
  "notes": {
    "section-overdue": "Push UAT CBLD trước 15/08",
    "section-module": "Module PR đã stable, HR còn 2 issue P1",
    "section-gantt-calendar": "Phase Analysis chậm 1 tuần vs kế hoạch"
  }
}
```

- `summary` ≤ 500 ký tự → hiển thị ở **trang cover** PDF (block xanh nhạt,
  prefix 💬).
- `notes[<section-id>]` ≤ 200 ký tự → hiển ngay dưới ảnh section trong PDF
  (italic, border-top, prefix "💬 Nhận xét:"). Empty value → xoá key
  (không render gì trong PDF).
- API `GET /api/projects/<slug>/chart-notes` → trả toàn bộ payload
  (default `{"summary":"", "notes":{}}`).
- API `PUT /api/projects/<slug>/chart-notes` → merge field-level:
  * `summary` trong body → replace summary hiện tại (rỗng = clear).
  * `notes[k]` = "" → xoá key `k`. `notes[k]` = "text" → set/update.
  * Field không truyền → giữ nguyên trong file.
- Backend truncate tự động (500/200) → FE không cần validate lại.

### `custom_dashboards.json` (Task 9 + T27/T28)

```json
[
  {
    "id": "cd_1690000000",
    "title": "Workload PIC theo phase Coding",
    "caption": "Chart tự tạo",
    "chart_type": "stackedBar",
    "x_field": "pic",
    "y_measure": "count",
    "series_field": "status",
    "palette": "default",
    "filters": {
      "modules": ["PR"],
      "processes": ["PRM.BP.03"],
      "pics": ["HoaTT81"],
      "statuses": ["In-progress"],
      "priorities": [],
      "complexities": [],
      "fitgaps": ["GAP"],
      "overdue_only": false,
      "open_only": true
    },
    "created_at": "2026-07-29T08:00:00"
  }
]
```

Filter object accept 7 dimension list (T28) + 2 boolean toggle. Backend
`_row_passes_filters` (`analyzer/generic_chart.py`) match với meta key
`quy_trinh` / `fit_gap` (theo parser, không dùng `process` / `fitgap`).

### `project_settings.json` (T26 + T29)

```json
{
  "upload_reminder_days": 7,
  "sla": {"must_have_days": 3, "should_have_days": 7},
  "digest": {
    "enabled": true,
    "day_of_week": 0,
    "hour": 9,
    "last_generated_date": "2026-07-29"
  },
  "progress_thresholds": {"in_progress": 30, "closed_soon": 70},
  "aging_wip_threshold": 14
}
```

- `digest.day_of_week`: 0=Thứ 2 … 6=Chủ Nhật (theo `datetime.weekday()`).
- `progress_thresholds` invariant: `in_progress < closed_soon` (BE tự
  chuẩn hoá khi PUT).
- Fields default nếu file thiếu — xem `analyzer/project_store.py :: DEFAULT_*`.

### `module_order.json` — thứ tự Module toàn dashboard

Path: `uploads/projects/<slug>/module_order.json`

```json
{
  "order": ["TMS", "HR", "PR", "SI"]
}
```

- **Load** cũng chấp nhận list thuần `["TMS",…]` hoặc rank map `{"TMS":1,"HR":2}`.
- **Default** khi chưa có file: alphabetical (giống parser cũ).
- Module mới (có trong Excel nhưng chưa trong `order`) → append cuối, alpha.
- Helper: `analyzer/module_order.py` (`sort_modules`, `module_sort_key`,
  `process_module_rank`) + `project_store.load/save/reset_module_order`.
- Áp vào `ParsedData.all_modules` sau parse/upload/load; filter giữ thứ tự
  parent (không re-alpha). Process tiles / overview-by-process / gantt
  group process sort theo module rank rồi tên process.

### `archive_settings.json` (T-AA)

Path: `uploads/projects/<slug>/archive_settings.json`

```json
{
  "enabled": true,
  "archive_after_days": 90,
  "auto_run_on_startup": true,
  "purge_after_days": 365
}
```

| Field | Default | Ý nghĩa |
|-------|---------|---------|
| `enabled` | `true` | Master switch auto-archive |
| `archive_after_days` | `90` | Archive snapshot cũ hơn N ngày (`0` = không bao giờ auto) |
| `auto_run_on_startup` | `true` | Daemon thread lúc Flask boot |
| `purge_after_days` | `365` | Xóa vĩnh viễn archive cũ hơn N ngày (`0` = không purge) |

API: `GET|PUT /api/projects/<slug>/archive-settings`,
`POST .../archive-run`, `POST .../snapshots/<id>/archive|restore`.
Chi tiết: [`ARCHIVE_GUIDE.md`](ARCHIVE_GUIDE.md).

### `digests/` folder (T26)

```
uploads/projects/<slug>/digests/
├── 20260722.xlsx
├── 20260729.xlsx
```

- Tên file: `YYYYMMDD.xlsx` (ngày sinh digest).
- Nội dung: giống `export_full_report` — 6 sheet Summary / Overdue /
  Unassigned / Long_Duration / Stalled / High_Risk.
- Không auto-cleanup — user tự xoá qua UI (nút 🗑).

### `integrations.json` (T30 + T30b — Registry API)

Cấu hình danh sách endpoint từ ứng dụng nguồn (iHRP prod/UAT, workload report,
GAP list, REST API team FIS…). Mỗi integration = 1 base URL + auth config +
n endpoint.

**⚠️ QUAN TRỌNG: File này KHÔNG chứa username/password/token/API key.**
Credential được nạp qua file `.env` ở gốc project theo prefix riêng cho mỗi
auth method:

| Auth method | Biến `.env` đọc |
|-------------|-----------------|
| `form_login` | `<PREFIX>_USERNAME`, `<PREFIX>_PASSWORD` (PREFIX = `credential_env`) |
| `basic_auth` | `<PREFIX>_USERNAME`, `<PREFIX>_PASSWORD` (PREFIX = `credential_env`) |
| `bearer_token` | `<PREFIX>_TOKEN` (PREFIX = `bearer_env`) |
| `api_key` | `<PREFIX>_KEY` (PREFIX = `apikey_env`) |

Module `analyzer/integrations.py` đọc `os.environ` khi cần → nếu chưa set →
raise `ValueError` với tên biến thiếu (thông báo rõ ràng cho user, không leak
password khi log lỗi).

Cấu trúc file (T30b full schema — mọi field auth đều được lưu, nhưng chỉ field
tương ứng `auth.method` được backend sử dụng runtime):

```json
{
  "integrations": [
    {
      "id": "int_ab12cd34ef56",
      "name": "iHRP Production",
      "base_url": "https://ihrp.company.com",
      "auth": {
        "method": "form_login",
        "login_path": "/login",
        "username_field": "username",
        "password_field": "password",
        "extra_fields": {},
        "credential_env": "IHRP_PROD",
        "bearer_env": "",
        "apikey_env": "",
        "apikey_header": "X-API-Key",
        "apikey_location": "header",
        "verify_ssl": true
      },
      "endpoints": [
        {
          "id": "ep_1234567890",
          "name": "Function List Export",
          "path": "/api/functions/export",
          "http_method": "GET",
          "params": {"module": "all"},
          "response_type": "excel",
          "target_action": "snapshot",
          "data_path": "",
          "field_mapping": {}
        }
      ]
    },
    {
      "id": "int_fis_rest_api",
      "name": "FIS REST API",
      "base_url": "https://fis-api.company.com",
      "auth": {
        "method": "bearer_token",
        "bearer_env": "FIS_API",
        "apikey_header": "X-API-Key",
        "apikey_location": "header",
        "credential_env": "",
        "login_path": "/login",
        "username_field": "username",
        "password_field": "password",
        "extra_fields": {}
      },
      "endpoints": [
        {
          "id": "ep_fx_funcs",
          "name": "Functions Export",
          "path": "/v1/projects/ihrp/functions",
          "http_method": "GET",
          "params": {},
          "response_type": "json",
          "target_action": "snapshot",
          "data_path": "data.items",
          "field_mapping": {
            "Mã CN": "code",
            "Tên chức năng": "name",
            "Module": "module_code",
            "Priority": "priority",
            "FIT/GAP": "fit_gap",
            "Analysis - Start": "phases.analysis.start",
            "Analysis - End": "phases.analysis.end",
            "Analysis - Status": "phases.analysis.status",
            "Analysis - PIC": "phases.analysis.pic",
            "Dev - Start": "phases.dev.start",
            "Dev - Status": "phases.dev.status",
            "Dev - PIC": "phases.dev.pic"
          }
        }
      ],
      "last_sync_status": "ok",
      "last_synced_at": "2026-07-30T14:12:33",
      "last_sync_message": "Đã tải 375 dòng · snapshot 2026-07-30 · endpoint 'Functions Export' [json]"
    }
  ]
}
```

**Fields:**

| Field | Bắt buộc | Mô tả |
|-------|----------|-------|
| `id` | auto | Backend gán khi create; format `int_<uuid[:12]>`. |
| `name` | ✔ | Tên hiển thị (dài ≤120 ký tự). |
| `base_url` | ✔ | Phải có scheme http/https, không trailing slash. |
| `auth.method` | ✔ | `form_login` / `basic_auth` / `bearer_token` / `api_key` — tất cả first-class. |
| `auth.login_path` | (form_login) | Path GET/POST login (VD `/login`). |
| `auth.username_field` | (form_login) | Tên input trong form, mặc định `username`. |
| `auth.password_field` | (form_login) | Tên input trong form, mặc định `password`. |
| `auth.extra_fields` | (form_login) | Dict {name: value} — bổ sung field hidden (VD `submit=1`). |
| `auth.credential_env` | (form_login / basic_auth) | Prefix `.env` → đọc `<PREFIX>_USERNAME` + `_PASSWORD`. |
| `auth.bearer_env` | (bearer_token) | Prefix `.env` → đọc `<PREFIX>_TOKEN`. |
| `auth.apikey_env` | (api_key) | Prefix `.env` → đọc `<PREFIX>_KEY`. |
| `auth.apikey_header` | (api_key) | Tên header hoặc query param (VD `X-API-Key`, `api_key`). Default `X-API-Key`. |
| `auth.apikey_location` | (api_key) | `header` (default) hoặc `query`. |
| `auth.verify_ssl` | | `true` (default). `false` → `session.verify=False` (chỉ khi cert nội bộ thiếu CA). |
| `endpoints[].id` | auto | Format `ep_<uuid[:10]>`. |
| `endpoints[].name` | ✔ | Tên hiển thị. |
| `endpoints[].path` | ✔ | Path hoặc absolute URL (bắt đầu bằng `/` sẽ prefix `base_url`). |
| `endpoints[].http_method` | | `GET` (default) hoặc `POST`. |
| `endpoints[].params` | | Dict → query string cho GET, form body cho POST. `api_key` với `apikey_location=query` sẽ được merge tự động vào params. |
| `endpoints[].response_type` | | `excel` / `json`. `csv` reserve. |
| `endpoints[].target_action` | | `snapshot` (default) / `append` / `replace`. `replace` cũng update `current.xlsx`. |
| `endpoints[].data_path` | (json) | Dot-notation trỏ đến list-of-records. Trống → payload phải là array top-level. |
| `endpoints[].field_mapping` | (json) | Dict `{col_iHRP: json.dot.path}` — key = tên cột Excel sinh ra, value = path trong 1 record. |
| `last_synced_at` | | ISO datetime của lần sync ok gần nhất. |
| `last_sync_status` | | `ok` / `error` — sau mỗi sync/test tự update. |
| `last_sync_message` | | Message rút gọn (≤500 ký tự) — user thấy trong list. |

**Backward compat**: Entry cũ (T30 gốc) chỉ có `credential_env` sẽ tiếp tục
hoạt động với `form_login` / `basic_auth`. `_sanitize_auth` tự fill default
cho các field mới (`bearer_env=""`, `apikey_env=""`, `apikey_location="header"`).

**Sync flow (khi user bấm 🔄):**

1. Read integration + endpoint → xác định auth method + response type.
2. `_prepare_authenticated_session(auth)` — 1 hàm phân nhánh 4 method:
    - `form_login`: resolve creds → GET login page → parse CSRF → POST login →
      verify (final URL, keywords lỗi trong body).
    - `basic_auth`: resolve creds → set `Authorization: Basic <base64>` vào
      session headers.
    - `bearer_token`: resolve `<PREFIX>_TOKEN` → set
      `Authorization: Bearer <token>` vào session headers.
    - `api_key`: resolve `<PREFIX>_KEY` → set vào session headers HOẶC vào
      `extra_query_params` (tuỳ `apikey_location`).
3. `_fetch_endpoint(session, endpoint, extra_query)` — GET/POST endpoint URL,
   merge `extra_query` vào params.
4. Nếu `response_type=excel`: detect qua Content-Type / extension → xlsx_bytes
   = response.content.
5. Nếu `response_type=json`: parse `r.json()` → `extract_records(payload, data_path)`
   → `build_xlsx_from_json_records(records, field_mapping)` → xlsx_bytes.
6. Lưu tạm `<project_dir>/synced_YYYYMMDD_HHMM.xlsx`.
7. Parse bằng `FunctionListParser` → tính metrics bằng `DashboardEngine`.
8. `SnapshotManager.save_snapshot(...)` — append vào project.
9. Nếu `target_action = replace` → copy đè `current.xlsx` + `touch_last_upload`.
10. Update `last_sync_status = ok`, `last_synced_at`, `last_sync_message`.
11. Trả `{status, message, snapshot_id, rows_imported, filename, response_type}`.

**Preview endpoint (auto-suggest mapping):**
- `POST /api/projects/<slug>/integrations/<id>/preview-json` với body `{endpoint_id}`.
- Backend gọi endpoint (dùng auth) → nhận 1 sample record → flatten thành
  `{"dot.path": sample_value}` (max 100 keys, depth 5).
- FE dùng heuristic tên field → suggest mapping (VD `code` → `Mã CN`,
  `phases.dev.status` → `Dev - Status`). User có thể sửa lại trước khi Lưu.

**Error handling:**
- Timeout: 30s per request (không retry).
- Network fail / HTTP 4xx-5xx / content-type sai → `status=error` + message rõ
  ràng để user biết fix `.env` hay URL/params.
- JSON response mà thiếu `field_mapping` → error "chưa cấu hình field_mapping".
- JSON response với `data_path` sai → error "Không trích được record nào từ JSON".
- Log KHÔNG bao giờ chứa password/token/key (chỉ log tên biến khi thiếu).

**Security:**
- Credentials chỉ tồn tại trong biến môi trường process, không cache session
  giữa request.
- Response từ `/test`, `/sync`, `/preview-json` KHÔNG expose credential.
- Session cookie chỉ giữ trong lifetime của 1 request (`session.close()` ngay
  sau khi lấy file, kể cả khi có exception).
- Bearer token / API key được inject vào headers của session; session bị
  destroy sau mỗi call → không leak sang request khác.

## V4 — Gantt Calendar payload

Endpoint `GET /api/projects/<slug>/gantt-calendar?group_by=<>&granularity=<>`
trả về payload cho FE HTML table (Excel-style 3-tier header).

**Query params:**
- `group_by`: `module` | `phan_he` | `process` | `quy_trinh` | `function`.
  (`phan_he` alias `module` — theo `.cursorrules` chú thích module/phân hệ
  là 1 khái niệm.)
- `granularity`: `day` | `week` | `month` | `auto` (mặc định `auto`).
  Auto lựa chọn: <60 ngày → day, ≤400 ngày → week, khác → month.
- Global filter chung: `module` / `process` / `pic` (multi, comma hoặc
  repeat) — apply qua `_filtered_data_from_request`.

**Response JSON shape:**

```jsonc
{
  "group_by": "module",
  "granularity": "week",
  "min_date": "2026-05-25",     // đã snap về đầu tuần/tháng
  "max_date": "2026-08-30",
  "today": "2026-07-30",
  "today_col": 9,                // index cột chứa ngày hôm nay (null nếu ngoài range)
  "columns": [
    {
      "idx": 0,
      "label": "W22",            // day: "01-Jun", month: "Jun-26"
      "start": "2026-05-25",     // ISO inclusive
      "end":   "2026-05-31",
      "month_label": "May-26",
      "week_num": 22,
      "week_date_label": "25-May"  // chỉ có khi granularity=week
    }
    // ...
  ],
  "month_spans": [
    {"label": "May-26", "colspan": 1},
    {"label": "Jun-26", "colspan": 4},
    {"label": "Jul-26", "colspan": 5},
    {"label": "Aug-26", "colspan": 5}
  ],
  "week_spans": [                 // chỉ có khi granularity=day
    {"label": "W22", "week_num": 22, "colspan": 7}
  ],
  "rows": [
    {
      "name": "TMS",              // "M1 · P1" cho process, "F1 · Tên..." cho function
      "module": "TMS",
      "process": "",
      "func_count": 15,
      "start": "2026-06-01",
      "end":   "2026-08-15",
      "pct":   72,                // weighted_all: closed_records / (rows × phases)
      "category": "summary",      // phase1|phase2|phase3|milestone|summary|idle
      "active_phase": "",         // chỉ set khi group_by=function
      "overdue_count": 3,
      "span_start_col": 1,
      "span_end_col":   11,
      "cells": [false, true, true, true, ..., false]  // len = columns.length
    }
  ],
  "legend": {
    "phase1":    {"label": "Phân tích / Config",  "color": "#3b82f6"},
    "phase2":    {"label": "Lập trình / Test",    "color": "#f59e0b"},
    "phase3":    {"label": "UAT",                 "color": "#a855f7"},
    "milestone": {"label": "Golive / Milestone",  "color": "#22c55e"},
    "summary":   {"label": "Tổng hợp (aggregate)", "color": "#1f2937"},
    "idle":      {"label": "Chưa có ngày",         "color": "#94a3b8"}
  },
  "empty": false                  // true khi không có phase Start/End nào
}
```

**Ghi chú compute:**
- Row `start` = min của tất cả `PhaseData.start_date` (mọi phase, mọi
  function trong nhóm); row `end` = max end. Nếu không có → cả 2 = None
  và cells rỗng.
- `pct` = weighted_all (giống module_overview) — coi phase blank là
  "chưa làm" (đếm vào mẫu số) để không đẩy % giả tạo lên 100%.
- `category` cho aggregate mode (module/process) = `summary`. Cho function
  mode = category của phase active nhất — map từ `PhaseGroup.task_type`
  ("Phân tích" → `phase1`, "Lập trình" → `phase2`, "UAT" → `phase3`,
  "Golive" → `milestone`).
- `cells[i]` = True nếu cột i overlap `[row.start, row.end]` (inclusive
  interval intersection). `span_start_col` / `span_end_col` = index của
  cell active đầu / cuối cho FE / Excel vẽ bar liên tục.

## T32 — Excel Column Mapping Wizard

### `excel_mapping_presets.json` (per-project)

Path: `.project_store/<slug>/excel_mapping_presets.json`

Schema:
```json
{
  "presets": [
    {
      "name": "MPHG Template",
      "mapping": {
        "Mã CN": "Function Code",
        "Tên chức năng": "Function Name",
        "Module": "Phan he",
        "Analysis - Start": "AnalysisStart",
        "Analysis - End": "AnalysisEnd",
        "Analysis - Status": "AnalysisStatus"
      },
      "updated_at": "2026-07-30T09:12:34"
    }
  ]
}
```

**Constraints:**
- Cap 30 preset / project (drop cũ nhất khi vượt).
- Preset name tối đa 80 ký tự.
- Mapping key/value tối đa 200 ký tự mỗi cái, cap 200 entries.
- Save cùng name → OVERWRITE (upsert).

**API:**
- `GET /api/projects/<slug>/mapping-presets` → `{"presets": [...]}` (sort
  desc updated_at).
- `POST /api/projects/<slug>/mapping-presets` body `{name, mapping}`
  → 201 với list mới.
- `DELETE /api/projects/<slug>/mapping-presets/<name>` → 200 hoặc 404.

### Upload preview response

`POST /api/upload-preview` (không theo project) — nhận `multipart/form-data`
với `file`, query `?project_slug=<slug>` (optional).

**Response:**
```json
{
  "success": true,
  "tmp_id": "abc123def456",
  "filename": "Function List MPHG.xlsx",
  "sheet_name": "Function List",
  "headers": ["Function Code", "Function Name", "Phan he", ...],
  "preview_rows": [
    ["PR.FR.01", "Tính lương cơ bản", "PR", "2026-01-01", ...],
    ...
  ],
  "ihrp_columns": ["Mã CN", "Tên chức năng", "Module", ...],
  "auto_suggest": {
    "Mã CN": [{"header": "Function Code", "score": 0.85}, ...],
    "Tên chức năng": [{"header": "Function Name", "score": 0.92}, ...]
  },
  "presets": [ /* nếu ?project_slug= có */ ]
}
```

- `tmp_id`: hex 16 ký tự (uuid4 hex slice) → file lưu tại `uploads/tmp/<tmp_id>.xlsx`.
- File tự động cleanup sau 24h (`_prune_old_tmp_uploads`) mỗi upload-preview.
- Fuzzy score: 0.0-1.0. Kết hợp SequenceMatcher + alias bilingual bonus.
- `preview_rows`: 5 dòng đầu (datetime → ISO string cho JSON-safe).

### Upload confirm request

`POST /api/upload-confirm` body:
```json
{
  "tmp_id": "abc123def456",
  "project_slug": "mphg",
  "column_mapping": {"Mã CN": "Function Code", "Analysis - Start": "AnalysisStart"},
  "threshold": 3,
  "filename": "Function List MPHG.xlsx"
}
```

- `column_mapping` rỗng → parser dùng auto-detect thuần (backward compat).
- `tmp_id` MUST match `[a-f0-9]{n}` (path traversal guard) → không thì 400.
- File tạm bị copy sang `<project_folder>/current.xlsx` rồi delete → không
  còn ở `uploads/tmp/`.
- Response: dashboard payload chuẩn (giống `/upload`) + 2 field mới:
  `column_mapping_applied: bool`, `column_mapping_count: int`.

### Parser behavior

`FunctionListParser.parse(filepath, column_mapping: Optional[dict[str, str]] = None)`:

- `column_mapping = None` → hoạt động như trước.
- `column_mapping = {ihrp_std: actual_header}` → thêm alias iHRP standard
  vào `headers` dict với cùng col_index:
  ```python
  # Trước: headers = {"Function Code": 1, "Function Name": 2, ...}
  # Sau apply mapping {"Mã CN": "Function Code"}:
  # headers = {"Function Code": 1, "Function Name": 2, "Mã CN": 1, ...}
  ```
- Header gốc GIỮ nguyên (không remove) → auto-detect keyword vẫn hoạt động
  cho các cột không được map.
- `actual` không tồn tại trong `headers` → skip thầm lặng.


---

## T33 — Public API (REST + token storage)

Xem chi tiết ở `docs/PUBLIC_API_GUIDE.md`. Ở đây chỉ liệt kê schema storage
và các endpoint được thêm.

### Storage `public_tokens.json`

File: `.project_store/<slug>/public_tokens.json`

```json
{
  "tokens": [
    {
      "id": "abc123def4567890...",
      "name": "Confluence embed",
      "token_prefix": "pub_a1b2c3d4",
      "token_hash": "sha256_hex_64_chars...",
      "scope": ["module-overview", "summary"],
      "created_at": "2026-07-30T03:15:22Z",
      "last_used_at": null,
      "revoked": false
    }
  ]
}
```

**Field detail**
- `id` — uuid4 hex 32 ký tự. Public identifier — user có thể thấy trong list.
- `name` — human-readable (VD "Partner Company X", "Confluence FIS team").
  Max 100 ký tự.
- `token_prefix` — 12 ký tự đầu của plaintext token (`pub_` + 8 hex). Dùng
  cho UI hint ("Token nào đang chạy?") — không thể revert về full token.
- `token_hash` — SHA-256 hex của full plaintext token. Verify bằng cách
  hash input rồi `secrets.compare_digest`. **Không lưu plaintext**.
- `scope` — list[str] scope key (`summary`, `overdue`, `module-overview`, ...
  hoặc `*` = wildcard). Sync với `analyzer/public_api.py::PUBLIC_SCOPES`.
- `created_at` / `last_used_at` — ISO 8601 UTC (kết thúc `Z`).
- `revoked` — bool. True → verify always fail; giữ entry cho audit.

**Cap**
- Tối đa 50 token active / project (revoke để reset). Tránh abuse (VD script
  lỡ generate liên tục).

### Endpoints admin (yêu cầu là owner project — hiện chưa có auth layer
riêng, tận dụng single-user local)

| Method | Path | Body / Response |
|--------|------|-----------------|
| GET    | `/api/projects/<slug>/public-tokens` | `{"tokens": [masked_entry, ...]}` |
| POST   | `/api/projects/<slug>/public-tokens` | Body `{"name":"","scope":[]}` → `{"token": "pub_...", "entry": masked_entry, "warning": "..."}` |
| DELETE | `/api/projects/<slug>/public-tokens/<token_id>` | `{"ok": true, "revoked": "<id>"}` |
| GET    | `/api/projects/<slug>/public-scopes` | `{"scopes": [{"key":"","label":""}, ...]}` — metadata multi-select FE |

### Endpoints public (yêu cầu header `X-API-Key` hoặc `?token=`)

| Method | Path | Scope required |
|--------|------|----------------|
| GET | `/public/api/v1/projects/<slug>/summary` | `summary` |
| GET | `/public/api/v1/projects/<slug>/charts/<chart_id>` | `<chart_id>` (dynamic) |
| GET | `/public/api/v1/projects/<slug>/functions?page=&size=` | `functions` |

`<chart_id>` hợp lệ: xem `analyzer/public_api.py::PUBLIC_SCOPES` (bỏ 3 key
`*`, `summary`, `functions`).

### Rate limit
- In-memory dict `{token_id: deque[timestamp]}` — sliding window 60s, cap
  60 req.
- Vượt → HTTP 429 + header `Retry-After: <seconds>` + body
  `{"error": "...", "retry_after": <s>}`.
- Reset khi restart process. Prod đa worker cần Redis (chưa impl).

### CORS
- `Access-Control-Allow-Origin: *`
- `Access-Control-Allow-Methods: GET, OPTIONS`
- `Access-Control-Allow-Headers: X-API-Key, Content-Type`
- `Access-Control-Max-Age: 3600` (preflight cache 1h)
- OPTIONS preflight trả 204 no-content, không cần token.

