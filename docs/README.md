# iHRP Function List Tracker — Local Dashboard App (V3)

## Mục đích
Ứng dụng web local (Python Flask + HTML/JS) cho PM/BA triển khai phần mềm iHRP/HRIS.
Upload file **Function List** (.xlsx) → App tự phân tích cấu trúc cột, phát hiện Phase/Status/Module/PIC → sinh dashboard tracking đa chiều + so sánh snapshot + phân tích risk.

**V3 mới:**
- 🗂️ **Multi-project**: mỗi khách hàng/dự án có workspace riêng
- 📦 **Export/Import project**: đóng gói toàn bộ project thành .zip để backup/di chuyển
- 🔀 **Cross-project compare**: so sánh 2 project với nhau
- ⚡ **Nhanh hơn 4×**: parse 502 rows chỉ 118ms nhờ streaming iter_rows
- 📥 **Pagination bảng dài**: giảm 60% payload frontend
- 🔍 **Drill-down biểu đồ**: click cell/segment biểu đồ → xem list function chi tiết + xuất Excel riêng cho phần đã click

## Cách chạy
```
start.bat          # Windows: double-click hoặc chạy trong terminal
./start.sh         # macOS/Linux
```
Trình duyệt tự mở tại `http://localhost:5000`.

**Windows note:** `start.bat` sẽ tự kill process đang chiếm port 5000 (dùng để tránh conflict khi có nhiều Flask app khác đang chạy). Nếu bị block do quyền, chạy `start.bat` với Administrator.

## Multi-Project (V3)

Mỗi project là 1 workspace độc lập với:
- File Function List riêng (`current.xlsx`)
- Snapshot history riêng
- Metrics + state trong memory riêng

### UI Project Selector
- Dropdown trong header cho phép switch nhanh giữa các project
- Nút ⚙️ mở modal "Quản lý project" để tạo/rename/archive/delete/import/export
- LocalStorage nhớ project đang chọn giữa các lần refresh

### Cách dùng
1. Mở app → mặc định có project "Default"
2. Nhấn ⚙️ → tạo project mới (VD: "Minh Phú 2026")
3. Chọn project từ dropdown → upload file .xlsx → data lưu vào project đó
4. Chuyển sang project khác → data project trước không mất, load lại được ngay

### Backup / Restore
- **Xuất project (.zip)**: nút "📦 Xuất project" trong modal → download zip chứa xlsx + snapshots + meta
- **Import (.zip)**: nút "📥 Import" → chọn zip → tự tạo project mới với slug unique

### Backward compat
Data cũ từ V2 (không có project) tự động migrate vào project "Default" khi khởi động lần đầu.

## Tính năng Core (V1 + V2, kế thừa qua V3)

### 1. Auto-detect cấu trúc file (KHÔNG hardcode cột)
- Đọc header row 1
- Nhận diện pattern `"Phase - Attribute"` (VD: `"Analysis - Status"`, `"Dev - PIC"`)
- Nhận diện cột meta: Module, Priority, Complexity, FIT/GAP, Giai đoạn, Quy trình, Risk/Blocker...
- Hỗ trợ file thêm/bớt cột mà **KHÔNG cần sửa code**
- Normalize PIC name case-insensitively (SonHN6 = SONHN6)

### 2. Dashboard đa chiều (18 sections)
**Core (V1):**
- Summary cards (Total / Progress / Overdue / Modules)
- Module overview table
- Phase × Status matrix (heatmap)
- Progress by task type (Phân tích, Lập trình, Kiểm thử...)
- PIC workload chart
- Priority / Complexity / FIT-GAP breakdowns
- Giai đoạn progress
- Phase progress stacked
- Overdue table (filterable + export)

**Advanced (V2 P1):**
- 🚨 Unassigned Tasks — phát hiện task chưa gán PIC
- ⏱️ Duration Analysis — task kéo dài bất thường (box plot + scatter)
- 🔄 Pipeline/Stalled — task bị kẹt giữa 2 phase
- ⚡ Risk Score — top 20 function có điểm rủi ro cao (0-100)

**Advanced (V2 P2-P3):**
- 📊 Effort Analysis — Man-hour heatmap + PIC MH bar
- 🏷️ Process Analysis — treemap theo Quy trình
- 📅 Timeline Gantt — trực quan schedule
- 📊 Compare Snapshot — so sánh 2 lần upload + velocity
- 📈 Weekly Digest — báo cáo tuần tự động

### 3. Export Excel (4 loại)
- Overdue Report (single sheet, có filter)
- Full Report (6 sheet: Summary + Overdue + Unassigned + Long Duration + Stalled + High Risk)
- By-PIC Report (3 sheet: Info + Overdue + Active)
- Compare Report (5 sheet)

### 4. Snapshot & Compare
- Auto lưu snapshot mỗi lần upload → `uploads/snapshots/`
- Max 30 snapshots, cùng ngày ghi đè
- So sánh 2 snapshot bất kỳ → delta cards + module chart + weekly digest
- Cho phép upload file cũ để so sánh không lưu snapshot

### 5. UX
- Sidebar nav (fixed) để jump giữa 18 section
- Search bar tìm nhanh Mã CN / Tên / Module / PIC
- Dark mode toggle (persist trong localStorage)
- Fullscreen chart (click ⛶ hoặc Escape để đóng)
- Refresh reminder banner nếu data > 24h
- Threshold slider cho Duration Analysis

### 6. V3 UX (mới)
- 🗂️ Project selector + modal quản lý project (tạo/rename/archive/delete/import/export .zip)
- 🎯 **Global filter** (Module × Quy trình) — apply cho toàn dashboard, backend recompute metrics từ subset
- 🔍 **Drill-down** — click cell/segment/row biểu đồ → modal chi tiết + xuất Excel riêng cho phần đã click
- 📱 **Chart responsive** — CSS clamp() cho height scale mượt từ mobile → 2K + resize handler debounce
- 📦 **Export folder per-project** — mọi file Excel (overdue / full / by-pic / compare / drill-down) lưu vào `uploads/projects/<slug>/exports/` thay vì base uploads/

### 7. V4 Wave — PM/BA productivity + Presentation
- 🩺 **Data Quality panel (T21)** — auto-detect issue: status invalid, End<Start,
  PIC blank ở phase quan trọng, duplicate Mã CN… + xuất Excel highlight severity.
- ⏳ **Aging WIP tracking (T22)** — task In-progress vượt ngưỡng ngày cần push.
- ⌨️ **Command Palette (T23)** — Ctrl+K / Cmd+K / `/` jump nhanh section /
  action / function.
- ⭐ **Bookmark + Notes (T24)** — đánh dấu function cần theo dõi + note riêng,
  section "Bookmark của tôi" tự ẩn khi rỗng.
- 🎬 **Presentation Mode (T25)** — full-screen 1 section/lần, ← → điều hướng,
  Esc thoát; ẩn header/sidebar cho meeting.
- 📥 **Weekly Digest cron-lite (T26)** — auto-generate Excel digest theo lịch
  (day_of_week + hour), lưu `.project_store/<slug>/digests/YYYYMMDD.xlsx`.
- 🔎 **Drill-down inline cho custom dashboard (T27)** — click bar/pie chart
  wizard → modal chi tiết function match bucket.
- 🎛️ **Wizard filter multi-select (T28)** — 7 dimension (Module/Process/PIC/
  Status/Priority/Complexity/FIT-GAP) preview live.
- ⚙️ **Settings modal (T29)** — configure progress thresholds / aging WIP /
  digest schedule / SLA / reminder trong 1 chỗ.
- 👁 **UX7 View icon** — bảng lưới bỏ click-any-row, thay bằng icon 👁 cột cuối
  cho rõ affordance.
- 🔌 **Registry API + Đồng bộ dữ liệu (T30 + T30b)** — cấu hình danh sách API
  endpoint từ nhiều ứng dụng nguồn (iHRP prod/UAT, workload report, GAP list,
  REST API team FIS…), bấm 1 nút để tự auth → tải Excel/JSON → parse → append
  snapshot. Hỗ trợ **4 auth method first-class** (`form_login`, `basic_auth`,
  `bearer_token`, `api_key` header/query) và **2 response type** (`excel`,
  `json` với `data_path` + `field_mapping` dot-notation). Credential nạp qua
  `.env` (KHÔNG lưu JSON) — mỗi method dùng prefix env riêng:
  `<PREFIX>_USERNAME/_PASSWORD` (form/basic), `<PREFIX>_TOKEN` (bearer),
  `<PREFIX>_KEY` (api_key). Chi tiết:
  [`docs/INTEGRATIONS_GUIDE.md`](INTEGRATIONS_GUIDE.md).

## Tech Stack
- Backend: Python 3.10+ / Flask 3
- Frontend: HTML + Tailwind CSS + Chart.js (CDN, không cần build)
- Excel: openpyxl (KHÔNG dùng pandas — tự viết aggregation)
- HTTP client (T30): `requests` + `beautifulsoup4` (parse CSRF khi login form)
- **Không cần database, không cần Node.js, không cần Docker**
- Test: pytest (dev: `requests-mock` cho mock HTTP)

## Cấu hình `.env` (T30 + T30b Registry API)

Nếu dùng tính năng Đồng bộ dữ liệu, tạo file `.env` ở gốc project (đã sẵn
trong `.gitignore`, không commit lên repo). Copy từ template:

```bash
cp .env.example .env
```

Sau đó điền credential tuỳ theo **auth method** của integration:

```
# form_login / basic_auth  →  <PREFIX>_USERNAME, <PREFIX>_PASSWORD
IHRP_PROD_USERNAME=your_username
IHRP_PROD_PASSWORD=your_password

# bearer_token  →  <PREFIX>_TOKEN
FIS_API_TOKEN=eyJhbGciOiJIUzI1NiIs...

# api_key  →  <PREFIX>_KEY
FIS_API_KEY=sk-abc-1234567890
```

Xem `docs/INTEGRATIONS_GUIDE.md` để biết:
- Cách F12 Network reverse-engineer `login_path` + tên field cho `form_login`.
- Cách config `data_path` + `field_mapping` cho JSON API response.
- Cách dùng "Auto-suggest field mapping" từ 1 sample record.

## Public API (T33 — REST + iframe + PNG)

Cho phép bên thứ 3 (partner, khách hàng, Confluence, Word, email) truy cập
dashboard mà không cần đăng nhập app chính. Xem `docs/PUBLIC_API_GUIDE.md`.

Tình trạng roadmap:
- ✅ **Task 2A** — REST + token CRUD + rate limit (60 req/60s/token) —
  endpoint `/public/api/v1/projects/<slug>/{summary,charts/<id>,functions}`.
  Token: `pub_<40 hex>`, SHA-256 hash storage, scope-based ACL, revoke idempotent.
- 🚧 **Task 2B** — iframe embed + PNG snapshot (Playwright headless — cần
  `python -m playwright install chromium` ~200MB nếu dùng).
- 🚧 **Task 2C** — Settings tab "🌐 Public API" với UI generate token +
  snippet copy REST/iframe/PNG.

Quick start (Task 2A):
```bash
# Tạo token
curl -X POST http://localhost:5000/api/projects/mphg/public-tokens \
  -H "Content-Type: application/json" \
  -d '{"name":"Confluence embed","scope":["summary","module-overview"]}'
# → {"token": "pub_...", ...} — LƯU NGAY vì chỉ trả 1 lần.

# Gọi API
curl -H "X-API-Key: pub_..." http://localhost:5000/public/api/v1/projects/mphg/summary
```

## Cấu trúc
Xem `docs/ARCHITECTURE.md` để biết chi tiết.

## Development

Chạy test suite:
```bash
pytest tests/ -v
```

Với coverage:
```bash
pytest tests/ --cov=parser --cov=analyzer --cov=exporter --cov-report=term-missing
```
