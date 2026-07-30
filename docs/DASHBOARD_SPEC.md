# Dashboard Specification — V3 (18 sections + drill-down + global filter)

Dashboard chia thành 3 nhóm section:
- **Core V1** (10 sections): summary, module, task-type, matrix, phase stack, PIC, priority/complexity/fitgap, giai đoạn, overdue
- **Advanced V2 P1** (4 sections): unassigned, duration, stalled, risk
- **Advanced V2 P2-P3** (4 sections): effort, process, timeline, compare + weekly digest

Ngoài ra có các thành phần UX toàn cục: sidebar nav, search bar, dark mode toggle, fullscreen chart, refresh reminder.

**V3 mở rộng UX:**
- 🗂️ Project selector + Project Manager Modal (dropdown header)
- 🎯 Global filter (Module × Quy trình) — apply cho toàn dashboard, `applied_filter` badge hiện row count
- 🔍 Drill-down modal — click cell/segment/row biểu đồ → hiện table function chi tiết, sort/lọc, xuất Excel riêng
- 📱 Chart responsive — dùng CSS clamp() để scale mượt theo viewport, resize handler cho window

---

## 1. Summary Cards (V2 — 6 cards)

6 cards ngang hàng trên cùng:

| Card                | Giá trị                                            | Icon | Border color | Semantic                                     |
|---------------------|----------------------------------------------------|------|--------------|----------------------------------------------|
| Tổng chức năng      | `summary.total_functions`                          | 📋   | blue-500     | Đếm row có data                              |
| Closed phase cuối   | `summary.overall_progress_pct` + phase name        | ✅   | green-500    | % function đã Closed ở phase cuối cùng       |
| Function trễ deadline | `summary.total_overdue` (+ phase-level records) | ⚠️   | red-500      | Số function unique (không phải phase count!) |
| Function chưa PIC   | `summary.unassigned_count` (+ phase-level records) | 🚨   | orange-500   | Số function unique có ít nhất 1 phase chưa PIC |
| High-risk (≥50 điểm)| `summary.high_risk_count`                          | ⚡   | rose-500     | Function có Risk Score ≥ 50                  |
| Số Module           | `summary.modules_count`                            | 📦   | purple-500   | Unique modules                               |

**Chú ý V2 fix:** Card hiển thị function-unique để tránh gây hoang mang. Phase-level count hiện trong ngoặc nhỏ hơn (VD: `44 function (74 phase)`).

---

## 2. Module Overview Table (Bảng A)

| Cột          | Mô tả                                                                       |
|--------------|------------------------------------------------------------------------------|
| STT          | 1, 2, 3...                                                                  |
| Phân hệ      | Tên Module                                                                  |
| SL           | Tổng function trong module                                                  |
| QT           | Đếm quy trình unique                                                        |
| Tiến độ      | % function Closed ở phase cuối (progress bar)                               |
| Đang ở       | Phase active nhất (hoặc "✓ Hoàn thành" / "Chưa bắt đầu" / "Đang hoàn tất") |
| Trễ          | Số function unique có overdue                                                |

**V2 fix:** Nếu tất cả function của module đã Closed phase cuối → `active_phase = "✓ Hoàn thành"` để không confusing với hiển thị "đang ở Document" khi thực chất đã 100%.

**Conditional formatting progress bar:**
- 100%: xanh lá đậm
- ≥80%: xanh lá
- ≥50%: vàng
- ≥20%: cam
- <20%: đỏ

---

## 3. Tiến độ theo công việc (Grouped Bar Chart)

- Trục X: Task types (auto detect từ phase name — Phân tích, Lập trình, Kiểm thử, Cấu hình UAT, UAT, Cấu hình Golive, Tài liệu)
- Trục Y: % Closed (0-100%)
- Mỗi Module = 1 group bar

**Mapping tự động** trong `PhaseGroup.task_type` (xem `DATA_MODEL.md` bảng "Các Phase thường gặp").

---

## 4. Phase × Module Matrix (Heatmap)

Bảng pivot:
- Row: Module
- Col: Phase
- Cell: `pct_closed` với heatmap background

**Heatmap color:**
- 100%: đậm xanh lá (#166534)
- 80-99%: xanh lá (#22c55e)
- 50-79%: vàng (#eab308)
- 20-49%: cam (#f97316)
- 0-19%: đỏ (#ef4444)
- Không có data: xám nhạt

**Hover tooltip:** hiển thị `Module / Phase: X/Y Closed (Z%)`.

---

## 5. Phase Progress — Stacked Bar Chart

- Trục X: Các Phase (Analysis, Dev, Config Local, Config UAT, Document, Config PROD, UAT, Golive)
- Trục Y: Số function
- Stack theo Status: Closed, In-progress, Assigned, Resolved, Open, Pending, Cancelled

---

## 6. PIC Workload — Horizontal Bar Chart

- Trục Y: Tên PIC (top 15 theo total_tasks giảm dần)
- Trục X: Số phase-level tasks
- Stack: Closed / In-progress / Assigned / Overdue

**V2 note:** `total_tasks` là **phase-level count** (1 function × N phase × M PIC = N×M records). Không phải số function unique. Cần đặt tooltip giải thích rõ.

---

## 7. Priority Doughnut

- Segments: Must-have / Should-have / Could-have / Won't-have (auto tùy file)
- Filter bỏ giá trị "None" / "N/A"

---

## 8. Complexity Doughnut

- Segments: Low / Medium / High
- Palette: `["#22c55e", "#f59e0b", "#ef4444", "#6b7280"]`

---

## 9. FIT/GAP — Stacked Bar (theo Module)

- Trục X: Module
- Stack: FIT / GAP / Customization / Pending
- Auto-detect all types trong file

---

## 10. Giai đoạn Progress (nếu có cột Giai đoạn)

- Trục X: Phase
- Grouped bar: mỗi giai đoạn (1/2/3) = 1 group
- Trục Y: % Closed
- Section auto-hide nếu file không có cột "Giai đoạn"

---

## 🆕 11. Unassigned Tasks (V2 P1)

Bảng liệt kê phase-level records có `status ∈ (Open|Assigned|In-progress|Resolved|Pending)` nhưng `pics == []`.

**Columns:** #, Mã CN, Tên CN, Module, Phase, Status, Priority, Deadline, Trễ (ngày)

**Row styling:**
- Overdue + unassigned: `bg-red-100 border-l-4 border-red-500` (rủi ro cao nhất)
- Must-have + unassigned (không overdue): `bg-orange-100 border-l-4 border-orange-500`
- Còn lại: bình thường

**Sort:** overdue trước → Must-have trước → ngày trễ giảm dần

---

## 🆕 12. Duration Analysis (V2 P1)

### Summary cards (4 cards)
- TB duration
- Task > 3 ngày
- Task > 7 ngày
- Ngưỡng cảnh báo (điều chỉnh được ở toolbar)

### Box plot theo Phase (dùng horizontal bar Chart.js)
- Range bar: min → max
- Median dot (đỏ)
- Avg dot (xanh, rectRot)
- Tooltip: `min=X, Q1=Y, med=Z, Q3=W, max=V, avg=U (n=N)`

### Scatter: Duration vs Estimate MH
- X: Estimate MH
- Y: Duration (ngày)
- 3 datasets: Đã Closed (xanh), Đang chạy elapsed (đỏ), Khác (xám)
- Tooltip: `Mã CN — Phase: Xh → Yd`

### Bảng chi tiết
Columns: #, Mã CN, Tên CN, Module, Phase, Start, End, Duration, Loại (KH/Đang), Status, PIC.
Row highlight theo mức trễ giống overdue table.

**Ngưỡng threshold:** slider ở toolbar (mặc định 3, cho phép 1-30). Threshold áp dụng backend khi upload; nếu chỉnh sau upload → client-side filter tạm thời.

---

## 🆕 13. Pipeline / Stalled Tasks (V2 P1)

Detect function bị kẹt: phase trước Closed nhưng phase sau vẫn None/Open.

### Funnel chart (custom HTML, không dùng Chart.js)
- Row cho mỗi phase, chiều rộng bar = số function Closed / max_closed
- Gradient blue → green

### Transitions list
- List các cặp `(from_phase → to_phase)` bị kẹt kèm count
- Sort giảm dần theo count

### Bảng chi tiết
Columns: #, Mã CN, Tên CN, Module, Phase đã xong, Phase chờ, Xong ngày, Chờ (ngày), Priority.
Row highlight nếu wait_days > 7d (orange) hoặc > 14d (red).

---

## 🆕 14. Risk Score — Top 20 High-Risk Functions (V2 P1)

Bảng sort theo risk_score giảm dần, top 20.

**Columns:** #, Mã CN, Tên CN, Module, Priority, Risk Score (bar), Yếu tố rủi ro (tags).

**Color coding risk bar:**
- ≥80: đỏ (#ef4444)
- ≥50: cam (#f97316)
- ≥30: vàng (#eab308)
- <30: xanh (#22c55e)

**Factor tags:** hiển thị dưới dạng chip đỏ nhạt.

Xem `ARCHITECTURE.md` phần `risk_scorer.py` để hiểu công thức trọng số.

---

## 🆕 15. Effort Analysis (Man-hour) (V2 P2)

### Summary cards (4 cards)
- Tổng Estimate MH
- MH đã Closed
- MH còn lại
- % MH Closed

### MH Heatmap: Module × Phase
- Bảng với background theo intensity `rgba(59, 130, 246, opacity)` (opacity theo tỉ lệ MH của cell / max)
- Cell rỗng: xám nhạt

### PIC Effort chart
- Horizontal stacked bar (top 15 PIC theo total_mh)
- Stack: Đã Closed MH (green) + Còn lại MH (orange)

**Chia MH giữa nhiều PIC:** nếu 1 phase có N PIC → mỗi PIC gánh MH/N.

---

## 🆕 16. Process Analysis (Quy trình treemap) (V2 P3)

Group function theo `meta.quy_trinh`:
- Total function per process
- % Closed
- Modules liên quan
- Overdue count
- Top 3 PIC chính

**Layout:** custom flexbox treemap-like — chiều rộng cell proportional với total function, chiều cao cố định.

**Color:** background theo % Closed (>80% xanh, 50-80% vàng, 20-50% cam, <20% đỏ).

Section auto-hide nếu file không có cột "Quy trình".

---

## 🆕 17. Timeline Gantt (V2 P3)

Với mỗi Module × Phase có ít nhất 1 function có start/end:
- Bar horizontal từ min(start_date) → max(end_date)
- Chiều dài normalized theo tổng timeline (min → max toàn dataset)
- Đường dọc đỏ = TODAY marker
- Bar color:
  - Đỏ nếu có overdue
  - Xanh lá nếu ≥80% Closed
  - Vàng nếu ≥50% Closed
  - Xanh dương nếu <50%
- Text trên bar: `pct_closed%`

---

## 🆕 17b. Gantt Calendar — Excel-style timeline (V4)

Section `section-gantt-calendar` — HTML table cuộn ngang, header 3 tầng
(Month/Week/Day) khớp format Excel Project Plan mà user đang dùng. Không
thay thế Timeline Gantt cũ, cung cấp view lịch dễ đọc hơn cho họp PM.

**Toolbar:**
- Group by: **Module** · **Quy trình** · **Function** (persist trong
  localStorage per project).
- Granularity: **Day** · **Week** · **Month** (auto lựa chọn theo range
  nếu không set: <60d=day, ≤400d=week, >400d=month).
- Nút **📥 Xuất Excel**.

**Header 3 tầng:**
- Row 1: **Month** (colspan theo số week/day trong tháng — VD "Jun-26").
- Row 2 (chỉ hiện khi granularity=day hoặc week): **Week** — số tuần ISO,
  VD "W22" (day mode: colspan=7, week mode: colspan=1 kèm "01-Jun").
- Row 3 (chỉ granularity=day): **Day** — "01-Jun".

**Data row:**
- Cột đầu: tên row + suffix `(N func · ⚠ K trễ)` + active phase `[Dev]`.
- Cell active: overlap `[row.start, row.end]` → tô màu nhạt của category
  phase, text `pct%` in đậm màu đậm ở cell giữa bar.
- Cell inactive: trống, background trắng (hoặc hồng nhạt nếu là cột Today).

**Marker "Today":** cột hôm nay tô hồng nhạt (#fce7f3); nếu row active
overlap ngày hôm nay → thêm inset box-shadow hồng đậm.

**Legend cuối section:**
- **Phân tích / Config** (xanh #3b82f6) — task_type "Phân tích".
- **Lập trình / Test** (cam #f59e0b) — task_type "Lập trình" / "Config+Test".
- **UAT** (tím #a855f7).
- **Golive / Milestone** (xanh lá #22c55e).
- **Tổng hợp (aggregate)** (đen #1f2937) — row group by module/process.
- **Chưa có ngày** (xám #94a3b8) — không có phase Start/End.
- **Today** (hồng #ec4899).

**Row category:**
- Function mode: category = category của phase đang active nhất
  (mapping từ `PhaseGroup.task_type`).
- Module/Process mode: category = "summary" (đen) vì gộp nhiều phase.

**Backend:** `GET /api/projects/<slug>/gantt-calendar` — trả JSON
`{columns, month_spans, week_spans, rows, today_col, legend}`. Áp
`_filtered_data_from_request()` để tôn trọng global filter.

**Export Excel:** `GET /api/projects/<slug>/export-gantt-calendar` —
openpyxl workbook: merge cell Month/Week, fill màu theo category, text
% ở cell giữa bar, cột Today fill hồng nhẹ, freeze pane ở cột đầu.

---

## 🆕 18. Compare Snapshot + Weekly Digest (V2 P2)

### Compare section (auto-show nếu ≥ 2 snapshots)

**Toolbar:**
- 2 dropdown chọn old/new snapshot
- Nút "So sánh"
- Nút "📥 Xuất Excel"
- Upload file cũ (không lưu snapshot, chỉ so sánh)

**4 Delta Cards:**
- Tiến độ chung: old → new + delta (▲ xanh, ▼ đỏ)
- Overdue: old → new + delta (▲ đỏ, ▼ xanh — vì overdue tăng là xấu)
- Function mới phát sinh (luôn hiển thị cam — cảnh báo scope creep)
- Tốc độ close + est ngày còn lại

**Module Delta Chart:** grouped bar 2 dataset (Trước = gray, Sau = blue).

**Status Transitions:** list `oldStatus → newStatus` với count, top 12.

**New Functions Table:** danh sách function mới phát sinh với Mã CN + Tên + Module + Priority.

### Weekly Digest (auto-show sau khi compare)

Format báo cáo có nút "🖨️ In / Xuất PDF":
- Header: `<old_date> → <new_date> (N ngày)`
- 3 cards lớn: Function Closed / Function mới / Est ngày còn lại
- Top 3 Module tiến bộ (xanh) + Top 3 Module cần chú ý (đỏ)
- 4 số nhỏ: forward / backward / removed / delta_total

**Print CSS:** ẩn header, sidebar, upload zone; giữ cards + tables.

---

## 19. Overdue Table (V1 giữ nguyên, có filter + export)

**Filters (dropdown):**
- Module: All / TMS / HR / ...
- PIC: All / SonHN6 / ...
- Phase: All / Analysis / Dev / ...

**Columns:** #, Mã CN, Tên CN, Module, Phase, Deadline, Ngày trễ, Status, PIC, Priority.

**Row styling:**
- >14 ngày: `bg-red-100 border-l-4 border-red-500`
- 7-14 ngày: `bg-orange-100 border-l-4 border-orange-500`
- 1-7 ngày: `bg-yellow-100 border-l-4 border-yellow-500`

**Sort:** mặc định theo ngày trễ giảm dần.

**Export button:** gọi `/api/export-overdue` với filter hiện tại.

---

## 🆕 UX Components (V2 P4)

### Sidebar Nav (fixed left)
Auto-hide đến khi upload file. Sau upload → hiện với 18 shortcut links.

### Search bar (header)
Auto-hide đến khi upload file. Sau upload → tìm trong overdue / unassigned / risk / duration / stalled bằng Mã CN / Tên / Module / PIC. Click result → scroll đến section tương ứng.

### Dark Mode toggle (header 🌙/☀️)
- Class `dark` trên `<html>`
- localStorage lưu preference `theme = "dark"` hoặc `"light"`
- Load early trong `<script>` header để tránh flash white
- Toggle icon 🌙 ↔ ☀️
- Chart auto re-render sau khi đổi

### Fullscreen Chart
- Nút `⛶` (opacity 0.5, hover đủ 1.0) trên mỗi chart card
- Click → modal fullscreen overlay `rgba(15,23,42,0.95)`
- Escape key hoặc nút "✕ Đóng" để thoát
- Re-render chart trong canvas mới với `maintainAspectRatio: false`

### Refresh Reminder banner
- Hiển thị sau khi upload nếu snapshot mới nhất > 24h trước
- Banner amber, có nút ✕ dismiss

### Threshold slider (Duration Analysis)
- Input number 1-30, mặc định 3
- Nút "Áp dụng" → nhắc user upload lại để backend recompute
- Client-side filter tạm thời cho bảng

## Responsive

- Grid 2 cột trên desktop (lg breakpoint 1024px), 1 cột mobile
- Summary 6 cards: 2 cột mobile / 6 cột desktop
- Sidebar nav ẩn trên mobile
- Chart cần overflow-x scroll nếu quá rộng

## 🆕 V3 UX Components

### Project Selector (header)
- Dropdown liệt kê tất cả project active (không hiện archived)
- Kèm số snapshot trong ngoặc `(N)` để user thấy nhanh
- Nút ⚙️ mở "Quản lý Project" modal (create/rename/archive/delete/import/export .zip)
- LocalStorage nhớ project đang chọn giữa các lần refresh (`current_project`)

### Global Filter (Module × Quy trình)
- Section riêng trên toolbar, 2 dropdown + nút "✕ Bỏ lọc"
- Backend recompute toàn bộ 18 metrics cho subset row (không phải filter client-side)
- Response có `applied_filter = {module, process, row_count}` → badge FE hiển thị:
  `🎯 Đang lọc → Module: TMS · Quy trình: X · 24 function`
- structureCache giữ `all_modules` / `all_processes` gốc để dropdown không mất option khi filter đang active

### Drill-Down Modal
Bấm vào:
- 1 cell trong Phase × Module matrix → filter `{module, phase}`
- 1 bar trong Phase Stacked → filter `{phase, status}`
- 1 bar trong PIC Workload → filter `{pic, status}` (`Overdue` → `status=overdue`)
- 1 segment Priority / Complexity doughnut → filter `{priority}` / `{complexity}`
- 1 bar FIT/GAP → filter `{module, fit_gap}`
- 1 bar Giai đoạn → filter `{giai_doan, phase}`
- 1 row Module Overview → filter `{module}` (V3.1 addition)

Modal có:
- Table 13 cột (Mã CN, Tên, Module, Phase, Status, PIC, Start, End, Trễ ngày, Priority, Complexity, FIT/GAP, ...)
- Search box lọc trong table
- Click header → sort asc/desc
- Row highlight: đỏ nhạt (overdue), xanh nhạt (Closed)
- Footer: `Tổng · Closed · Đang làm · Trễ`
- Nút "📥 Xuất Excel" POST đến `/api/projects/<slug>/drill-down/export`
  → file lưu trong `uploads/projects/<slug>/exports/`

### Chart Responsive
- `.chart-box` CSS class dùng `height: clamp(min, vh-based, max)` cho scale mượt
- Chart.js config force `responsive: true` + `maintainAspectRatio: false`
- Window resize handler debounced 150ms gọi `chart.resize()` cho tất cả instance
- Fullscreen mode dùng `maintainAspectRatio: false` để fill viewport

## Color palette

| Element        | Light                                   | Dark                          |
|----------------|-----------------------------------------|-------------------------------|
| Background     | `#f8fafc` (slate-50)                   | `#0f172a` (slate-900)         |
| Card           | `#ffffff`                               | `#1e293b` (slate-800)         |
| Text primary   | `#1e293b`                               | `#e2e8f0`                     |
| Text muted     | `#64748b`                               | `#94a3b8`                     |
| Border         | `#e2e8f0`                               | `#334155`                     |
| Header gradient| `blue-800 → blue-600`                   | `blue-900 → blue-800`         |
| Heatmap none   | `#f3f4f6`                               | `#334155`                     |

## V4 additions (T21–T29 + UX7)

### `section-dataquality` (T21)
- Summary strip: tổng issue, số high/medium/low.
- Filter theo severity + code; bảng issue paginated (30/page).
- Nút "📥 Xuất Excel" → sheet đơn với highlight theo severity.

### `section-aging-wip` (T22)
- Slider threshold 1-90 ngày, live-update (debounce 250ms), persist
  `localStorage` per-project.
- Summary card: Tổng WIP, Aging (>N ngày), Avg aging, Max aging.
- Bảng sort cột `aging_days` (asc/desc), phân trang 20/page.
- UX7: icon 👁 cột cuối mở function detail.

### `section-my-bookmarks` (T24)
- Card grid 1-2 cột. Mỗi card: Mã CN, Tên, Module · Quy trình, note
  (nếu có). Nút 👁 xem detail + ⭐ bỏ bookmark.
- Ẩn khi bookmarks rỗng để giảm noise.

### `section-my-digests` (T26)
- Badge lịch hiện tại (VD "Thứ 2 lúc 09:00" hoặc "Tắt").
- Nút "Sinh digest ngay" (POST endpoint).
- Bảng history: filename `YYYYMMDD.xlsx` | sinh lúc | size | Tải/Xoá.
- Ẩn khi không có file + schedule off.

### Presentation Mode (T25)
- Body class `presentation-mode` ẩn header, sidebar, `.no-print`.
- 1 section chọn: background trắng, shadow, min-height fill viewport,
  fadeIn 0.35s.
- HUD `<pos>/<total>` + tên section, hint `← → · Esc`.
- Key: `Arrow*`, `Space`, `PageUp/Down`, `Home/End`, `Esc`.

### Custom Dashboard drill-down modal (T27)
- Modal `#cdDrillModal` mở khi click bar/pie/segment chart có id (không
  áp dụng cho preview trong wizard).
- Bảng cột: Mã CN · Tên · Module · Quy trình · Priority · Status · Deadline
  · PIC · 👁 (mở function detail).
- Truncate 500 rows với note "(hiển thị 500/N)".

### Settings modal (T29)
- Nút "⚙️ Cài đặt" trong header sát nút Trình chiếu.
- 6 panel: `Ngưỡng % tiến độ` · `Ngưỡng Aging WIP` · `Nhắc upload định kỳ`
  · `Ngưỡng SLA (theo priority)` · `Lịch sinh Digest tự động` · `Hiển thị
  section dashboard`.
- Panel **Hiển thị** (Task Cấu hình ẩn/hiện, bổ sung sau T29):
  - Metadata `_VISIBILITY_GROUPS` gom section theo 5 nhóm: `📊 Tổng quan`,
    `📈 Tiến độ & Timeline`, `🔬 Phân tích chuyên sâu`, `🚨 Danh sách &
    Cảnh báo`, `🛠️ Tùy chỉnh & Lịch sử`. Mỗi item có `id`, `label`, mô tả
    ngắn — FE tự lọc theo section thực có trong DOM (auto-detect).
  - 3 action pills: `✔ Chọn tất cả` / `✖ Bỏ chọn tất cả` / `↺ Khôi phục
    mặc định` (default = tick tất cả).
  - Save: gọi `PUT /api/projects/<slug>/chart-config/visibility` với body
    `{visibility:{section_id:bool,…}}` — bulk cập nhật cờ `hidden` trong
    `chart_configs.json`. Chạy song song với `PUT /settings`.
  - Apply runtime: sau save, `_applyVisibilityMapping()` toggle `.hidden`
    class ngay lập tức — KHÔNG reload trang, KHÔNG mất filter/pagination
    /scroll position hiện tại.
  - Persist: reuse `chart_configs.<section_id>.hidden` → phiên sau load
    `loadChartConfigs()` → `applyChartConfigsToDom()` tự ẩn lại các
    section user đã bỏ tick.
- Sau khi lưu: auto refresh `loadDigests()` + section Aging WIP nếu đang mở.

### UX7 — Icon 👁 View trong bảng lưới
- Cột cuối mỗi bảng lưới có nút `.view-icon-btn` (26×26, rounded, hover
  blue). Click → `openFunctionDetailByMaCn(ma_cn)` mở function detail modal.
- Áp dụng cho: Overdue, Unassigned, Duration, Stalled, Risk, Effort open
  tasks, Aging WIP, Bookmark card, Custom drill result.
- Kanban card không đổi (giữ click card mở detail).

### T30 — Registry API modal + Sync dropdown

**Nút trong header:**
- `🔌 API Registry` mở modal `#integrationsModal`.
- `🔄 Đồng bộ ▾` mở dropdown `#syncQuickMenu` — list integrations với các
  endpoint clickable. Click 1 endpoint → gọi sync ngay, không cần vào modal.

**Modal 2 tab:**

*Tab "Danh sách":*
- Bảng cột `Tên · Base URL · #Endpoint · Sync gần nhất · Trạng thái · Hành động`.
- Cột hành động: `🔍 Test` · `<select endpoint>` + `🔄 Sync` · `✏️ Edit` · `🗑 Delete`.
- Status badge: xanh `✔ ok` / đỏ `✕ lỗi` với tooltip = `last_sync_message` để
  user hover thấy lý do fail (thiếu env, sai URL, response không phải Excel…).

*Tab "Thêm mới / Chỉnh sửa":*
- Form: `Tên` · `Base URL`.
- Fieldset **Cấu hình xác thực** (T30b — 4 method first-class, không disable):
  - Dropdown `Auth method`: `form_login` / `basic_auth` / `bearer_token` /
    `api_key` — với label tiếng Việt (VD "Form login (POST username/password)",
    "Bearer token"). Description hint hiển thị bên dưới sau khi chọn.
  - 4 block field group ẩn/hiện dynamic (`data-auth-fields="<method>"`) theo
    method đang chọn:
      * `form_login` → `Login path` · `Username field` · `Password field` ·
        `Prefix env (credential_env)`.
      * `basic_auth` → `Prefix env (credential_env)`.
      * `bearer_token` → `Prefix env (bearer_env)`.
      * `api_key` → `Prefix env (apikey_env)` · `Header/param name` ·
        `Vị trí (header|query)`.
- Fieldset **Danh sách Endpoint**: mỗi row = `Tên · Path · HTTP method ·
  Response type · Target action · Params (JSON)`. Có nút `➕ Thêm endpoint`
  / `🗑 Xoá` từng row. Template dùng `<template id="integEndpointTemplate">`
  để clone.
  - Khi user chọn `Response type = json` → hiện panel **🗺 Field Mapping**
    (T30b) với:
      * Input `data_path` — dot-notation trỏ đến list-of-records.
      * Textarea JSON `field_mapping` — `{"col_iHRP": "json.dot.path"}`.
      * Nút `🔮 Auto-suggest từ endpoint` → gọi `/preview-json`, nhận flat
        keys từ 1 record thực, dùng heuristic tên field để gợi ý mapping.
        User có thể sửa lại textarea trước khi Lưu.
- Nút `🔍 Test login` — bấm → POST `/integrations/<id>/test` → hiển thị
  message inline. Với các method non-form (basic/bearer/apikey) chỉ verify
  credential có trong `.env` (không hit server).
- Nút `💾 Lưu` — POST hoặc PUT tuỳ đang tạo mới hay edit.

**Sync flow FE (khi user bấm 🔄):**
1. Toast "Đang sync… có thể mất vài giây".
2. POST `/api/projects/<slug>/integrations/<id>/sync` với body `{endpoint_id}`.
3. Response `{status, message, rows_imported, snapshot_id, response_type}`.
4. Nếu ok → toast success + gọi `tryLoadDashboardForCurrent(true)` để dashboard
   tự refresh dữ liệu mới (giữ nguyên filter hiện tại).
5. Refresh list integrations để badge `last_synced_at` cập nhật.

**Security note:**
Credential (password/token/API key) chỉ được đọc từ `.env` phía backend khi
cần. FE KHÔNG bao giờ nhìn thấy hoặc gửi credential. Field nhập password/token
KHÔNG tồn tại trong UI — user chỉnh trực tiếp file `.env` ở gốc project.
Backend cũng KHÔNG log credential ra terminal (chỉ log tên biến khi thiếu).
