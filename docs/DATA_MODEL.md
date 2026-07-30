# Data Model — Function List Excel (V2)

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

## Multi-Project Layout (V3)

Từ V3 trở đi, storage được tổ chức theo project:

```
uploads/
  projects/
    projects.json                       # Index tất cả project
    <slug>/                             # Slug từ tên (VD "minh-phu-2026")
      meta.json                         # Metadata riêng
      current.xlsx                      # File Function List hiện tại
      snapshots/
        snapshot_index.json
        YYYY-MM-DD_functionlist.xlsx
        YYYY-MM-DD_functionlist.parsed.pkl
```

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

## Snapshot format (V2)

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
    "upload_time": "2026-07-28T08:40:37"
  }
]
```

Cùng ngày upload nhiều lần → ghi đè bản cũ. Giới hạn tổng 30 snapshots (bản cũ nhất tự xóa).

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

### `integrations.json` (T30 — Registry API)

Cấu hình danh sách endpoint từ ứng dụng nguồn (iHRP prod/UAT, workload report,
GAP list…). Mỗi integration = 1 base URL + auth config + n endpoint.

**⚠️ QUAN TRỌNG: File này KHÔNG chứa username/password.** Credential được nạp
qua file `.env` ở gốc project theo prefix `credential_env`:

```
<PREFIX>_USERNAME=abc
<PREFIX>_PASSWORD=xyz
```

Module `analyzer/integrations.py` đọc `os.environ` khi cần → nếu chưa set →
raise `ValueError` với tên biến thiếu (thông báo rõ ràng cho user).

Cấu trúc file:

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
        "credential_env": "IHRP_PROD"
      },
      "endpoints": [
        {
          "id": "ep_1234567890",
          "name": "Function List Export",
          "path": "/api/functions/export",
          "http_method": "GET",
          "params": {"module": "all"},
          "response_type": "excel",
          "target_action": "snapshot"
        }
      ],
      "created_at": "2026-07-30T08:30:00",
      "last_synced_at": "2026-07-30T14:12:33",
      "last_sync_status": "ok",
      "last_sync_message": "Đã tải 375 dòng · snapshot 2026-07-30"
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
| `auth.method` | ✔ | MVP: `form_login`. Reserve: `basic_auth`, `bearer_token`, `api_key` (chưa support). |
| `auth.login_path` | | Path GET/POST login (VD `/login`). |
| `auth.username_field` | | Tên input trong form, mặc định `username`. |
| `auth.password_field` | | Tên input trong form, mặc định `password`. |
| `auth.extra_fields` | | Dict {name: value} — bổ sung field hidden (VD `submit=1`). |
| `auth.credential_env` | ✔ (để sync) | Prefix biến `.env` — hệ thống đọc `<PREFIX>_USERNAME` + `_PASSWORD`. |
| `endpoints[].id` | auto | Format `ep_<uuid[:10]>`. |
| `endpoints[].name` | ✔ | Tên hiển thị. |
| `endpoints[].path` | ✔ | Path hoặc absolute URL (nếu bắt đầu bằng `/` sẽ prefix `base_url`). |
| `endpoints[].http_method` | | `GET` (default) hoặc `POST`. |
| `endpoints[].params` | | Dict → query string cho GET, form body cho POST. |
| `endpoints[].response_type` | | MVP: `excel`. Reserve: `json`, `csv`. |
| `endpoints[].target_action` | | `snapshot` (default) / `append` / `replace`. `replace` cũng update `current.xlsx` để dashboard load ngay dữ liệu mới. |
| `last_synced_at` | | ISO datetime của lần sync ok gần nhất. |
| `last_sync_status` | | `ok` / `error` — sau mỗi sync/test tự update. |
| `last_sync_message` | | Message rút gọn (≤500 ký tự) — user thấy trong list. |

**Sync flow (khi user bấm 🔄):**

1. Read integration → resolve credentials từ `.env`.
2. `requests.Session()` GET login page → parse CSRF token (bs4 hoặc regex).
3. POST login form với user/pass + CSRF + extra_fields.
4. Verify login (heuristic: HTTP 200, final URL không quay lại login path,
   body không chứa `invalid|incorrect|sai mật khẩu|…`).
5. GET/POST endpoint URL với params → nhận response.
6. Detect Excel qua `Content-Type` (`application/vnd.*ms-excel*` /
   `openxmlformats-officedocument…` / `octet-stream` + extension `.xlsx`).
7. Lưu tạm `<project_dir>/synced_YYYYMMDD_HHMM.xlsx`.
8. Parse bằng `FunctionListParser` → tính metrics.
9. `SnapshotManager.save_snapshot(...)` — append vào project (dùng logic có sẵn).
10. Nếu `target_action = replace` → thêm bước copy đè `current.xlsx` + `touch_last_upload`.
11. Update `last_sync_status = ok`, `last_synced_at`, `last_sync_message`.
12. Trả `{status, message, snapshot_id, rows_imported, filename}` cho FE.

**Error handling:**
- Timeout: 30s per request (không retry).
- Network fail / HTTP 4xx-5xx / content-type sai → `status=error` + message rõ
  ràng để user biết fix `.env` hay URL/params.
- Log KHÔNG bao giờ chứa password (chỉ log tên biến khi thiếu).

**Security:**
- Credentials chỉ tồn tại trong biến môi trường process, không cache session
  giữa request.
- Response từ `/test` và `/sync` KHÔNG expose password.
- Session cookie chỉ giữ trong lifetime của 1 request (session.close() ngay
  sau khi lấy file).

