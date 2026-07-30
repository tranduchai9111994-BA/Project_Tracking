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

### Default section order (UX — cảnh báo trước)

Thứ tự DOM + sidebar mặc định (khi project **chưa** có `section_order.json`).
Đã save order → giữ nguyên; nút **↺ Mặc định** xoá custom order và reload về layout này.

| Nhóm | Sections |
|------|----------|
| **A — Cảnh báo** | summary (+ global filter sticky) → overdue → unassigned → stalled → risk → aging-wip → sla → dataquality |
| **B — Tiến độ** | module + tasktype → matrix → phase → giaidoan → process → burndown → capacity → baseline → effort → duration → slow → deps |
| **C — Timeline / chi tiết** | gantt → gantt-calendar → kanban → pic → priority → fitgap-dashboard → function-diff → my-bookmarks |
| **D — Quản trị** | compare → digest → my-digests → custom-dashboards → history |

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

---

## 🆕 15. PDF Export (T7 → T28: comment per-chart + font fix Vietnamese)

**Nút mở:** `📄 Xuất PDF` trên header dashboard → mở modal `#pdfExportModal`.

### Layout modal (từ trên xuống)

1. **Preset nội dung** — 4 radio: 👔 PM view · 📊 BA view · 🔀 Cả 2 (Full) ·
   🎯 Custom (checkbox từng section).
2. **📝 Tóm tắt chung của báo cáo** — textarea 3 dòng, `maxlength=500`, hiển
   counter live `X/500`. Nội dung này in ở **trang cover** của PDF (block
   nền xanh nhạt, border-left xanh, prefix 💬).
3. **💬 Nhận xét từng chart** — khu vực scroll list các section đã chọn.
   Mỗi section:
   - Header nhỏ `📊 <tên section>` + counter `X/200` (font 10px).
   - Textarea 2 dòng, `maxlength=200`.
   - Input event → cập nhật in-memory cache `_pdfNotesCache.notes[<sid>]`.
4. **Ngày báo cáo** + **Chất lượng ảnh** (1x/1.5x/2x).
5. **Progress bar** — hiển khi đang generate.

### Nút footer

- `Huỷ` — đóng modal.
- `✓ Lưu nhận xét` — **KHÔNG xuất PDF**, chỉ PUT
  `/api/projects/<slug>/chart-notes` với `{summary, notes}`. Toast success.
- `📥 Xuất PDF` — silent-save trước (PUT notes), sau đó generate PDF.

### PDF layout

1. **Trang cover** — 1 image HTML render qua html2canvas:
   - Banner gradient xanh 22px title + date + `Project: X · Preset: Y`.
   - Card trắng dưới banner: filter subtitle (Module/Quy trình/PIC đang áp).
   - Nếu có Tóm tắt → box `#f1f5f9` border-left `#3b82f6`, prefix
     `💬 Tóm tắt báo cáo:` + text (white-space: pre-wrap).
2. **Mỗi section đã chọn** — image html2canvas của DOM section (giữ h3 title
   nội tại). Sau ảnh section, nếu có comment → block "💬 Nhận xét: <text>"
   italic, border-top nhạt, background xám nhạt. Comment rỗng → không thêm.
3. **Footer mỗi trang** — `pdf.text()` ASCII an toàn: "Trang X/Y" +
   "Generate: <timestamp>". (Không dùng diacritic vì Helvetica default
   không support.)

### Font fix (T28 — bug jsPDF mojibake)

**Vấn đề:** `pdf.text("📊 Báo cáo…")` với font Helvetica default → glyph
sai lệch "Ø=ÜÊ&Bào" vì Helvetica chỉ support Latin-1 basic.

**Fix (approach chọn — render toàn bộ qua html2canvas):**
- Helper `_pdfCaptureHtml(html, widthPx, scale)` inject 1 wrapper
  off-screen (`position:fixed; left:-20000px`) với font-family
  `"Inter", "Segoe UI", "Helvetica Neue", Arial, sans-serif` → browser
  tự chọn glyph có sẵn cho tiếng Việt + emoji → html2canvas snapshot
  ra ảnh → addImage vào PDF.
- Cover + section title + comment box đều đi qua path này.
- Chỉ footer (Trang X/Y) còn dùng `pdf.text()` vì ASCII an toàn.
- Trade-off: text không search-able trong PDF → user care visual >
  searchable theo yêu cầu.

### Persist chart notes

- File: `.project_store/<slug>/chart_notes.json`
- Schema:
  ```json
  {
    "summary": "Tuần 30/2026 — overdue giảm 22%",
    "notes": {
      "section-overdue": "Push UAT CBLD",
      "section-module": "Module PR đã stable"
    }
  }
  ```
- Giới hạn: summary ≤ 500 ký tự, mỗi note ≤ 200 ký tự (backend auto-truncate).
- API `GET/PUT /api/projects/<slug>/chart-notes`:
  - GET → toàn bộ payload (nếu file chưa tồn tại → `{summary:"", notes:{}}`).
  - PUT body có thể chỉ chứa `summary` HOẶC chỉ `notes` — merge field-level:
    * `summary` in payload → replace (rỗng = clear).
    * `notes[k]` = "" → xoá key `k` khỏi map. `notes[k]` = "text" → set/update.
    * Field không truyền trong payload → giữ nguyên trong file.
- Modal mở → auto GET, pre-fill textarea (dùng tuần trước làm điểm khởi đầu
  → user chỉ sửa delta).


## 🆕 16. Column Mapping Wizard (T32 — upload flow mới)

### Vấn đề gốc
Auto-detect cột trong parser dựa vào keyword match với `META_KEYWORDS` +
pattern `Phase - Attr`. Với file có header lạ (VD "Function Code" thay vì
"Mã CN", "AnalysisStart" thay vì "Analysis - Start") → parser miss cột
→ phase_groups rỗng → dashboard rỗng. User cũ phải sửa Excel thủ công.

### Flow mới

1. User bấm **📁 Chọn file Excel** (hoặc kéo thả).
2. Default: JS gọi `POST /api/upload-preview` — file được lưu tạm vào
   `uploads/tmp/<uuid>.xlsx` (KHÔNG parse full). Response:
   ```json
   {
     "tmp_id": "abc123...",
     "filename": "Function List MPHG.xlsx",
     "sheet_name": "Function List",
     "headers": ["Function Code", "Function Name", ...],
     "preview_rows": [["PR.01", "Tính lương", ...], ...],   // 5 dòng đầu
     "ihrp_columns": ["Mã CN", "Tên chức năng", ...],       // list cột chuẩn
     "auto_suggest": {
       "Mã CN": [{"header": "Function Code", "score": 0.85}, ...],
       ...
     },
     "presets": [{"name": "MPHG Template", "mapping": {...}}, ...]
   }
   ```
3. FE mở modal `#uploadMappingModal` với:
   - **Header:** filename + sheet_name + counter "Đã map X/Y cột iHRP".
   - **Row Preset:** dropdown load preset đã lưu, nút 💾 Lưu, nút 🗑 Xoá.
   - **Preview table:** 5 dòng đầu (scroll ngang), header sticky.
   - **Mapping table:** mỗi row = 1 cột iHRP chuẩn + dropdown chọn header
     thực tế + score.
     * Auto-suggest score ≥ 0.7 → pre-fill và background emerald nhạt.
     * User có thể manual pick từ dropdown → hiện "manual" trong ô Score.
     * "(không có)" → row background xám (chưa map).
   - **Footer:** "→ Parse ngay" (skip mapping) / "Huỷ" / "✓ Xác nhận & Parse".
4. User confirm → `POST /api/upload-confirm`:
   ```json
   {
     "tmp_id": "abc123...",
     "project_slug": "mphg",
     "column_mapping": {"Mã CN": "Function Code", ...},
     "threshold": 3
   }
   ```
5. Backend copy tmp → project's current.xlsx → `FunctionListParser.parse(
   filepath, column_mapping=...)` → snapshot + dashboard response.

### Bỏ qua wizard

Checkbox trong upload zone: "Bỏ qua Column Mapping wizard (file chuẩn
iHRP → auto-detect ngay)". Persist trong localStorage
(`ihrp_upload_skip_wizard`). Khi tick → `handleFile` gọi thẳng
`/api/projects/<slug>/upload` giống flow cũ, không mở wizard.

Trong modal wizard cũng có nút "→ Parse ngay (bỏ qua mapping — auto-detect)"
để user mid-flow đổi ý.

### Fuzzy match

`parser/column_mapping.py::_fuzzy_score(a, b)` kết hợp 4 signal:
1. `SequenceMatcher.ratio()` trên bản normalized (lowercase, strip
   `[\s\-_/.]`).
2. Substring bonus (+0.15 nếu 1 chuỗi chứa toàn bộ chuỗi kia).
3. Token overlap bonus (up to +0.1 nếu split by whitespace/`-_/.` có
   token trùng).
4. **Alias bilingual bonus** (+0.5 nếu match trong bảng `_ALIAS_HINTS`):
   - `Mã CN` ↔ `Function Code`, `Module` ↔ `Phân hệ`, ...
   - Cover case pure string matcher không giải quyết được.

Suggestion trả top-3 candidate mỗi cột iHRP, filter score ≥ 0.35.

### Preset

File: `.project_store/<slug>/excel_mapping_presets.json`.
Schema: `{"presets": [{"name": str, "mapping": {ihrp: actual}, "updated_at": iso}, ...]}`

- Cap 30 preset per project (auto drop cũ nhất khi vượt).
- Save cùng name → OVERWRITE (upsert).
- API:
  * `GET /api/projects/<slug>/mapping-presets` → list.
  * `POST /api/projects/<slug>/mapping-presets {name, mapping}` → upsert.
  * `DELETE /api/projects/<slug>/mapping-presets/<name>` → xoá.

### Parser behavior

`FunctionListParser.parse(filepath, column_mapping=None)`:
- `column_mapping=None` → hoạt động như cũ (backward compat 100%).
- `column_mapping={"Mã CN": "Function Code", ...}` → `_apply_column_mapping`
  ADD alias vào `headers` dict (header gốc GIỮ nguyên, chỉ thêm alias):
  → `headers["Mã CN"] = headers["Function Code"]` với cùng col_index.
- Sau đó `_detect_meta_columns` và `_detect_phase_groups` chạy như thường
  — bây giờ match được cả header gốc lẫn iHRP standard name.
- Mapping missing actual header → skip thầm lặng.

### Cleanup

`_prune_old_tmp_uploads(max_age_hours=24)` xoá tự động file trong
`uploads/tmp/` cũ hơn 24h mỗi lần có upload-preview mới. Không cần cron.

### Security

- Path traversal guard trong `/upload-confirm`: `tmp_id` chỉ chấp nhận
  ký tự hex `[a-f0-9]` (uuid4 hex slice). Reject `../../../etc/passwd`.
- `MAX_CONTENT_LENGTH = 50MB` (config Flask có sẵn).
- Preset name/mapping trim + cap ký tự để không crash JSON store.

### 🆕 Smart mapping (T34 Task 3 — A+B+C+E)

Wizard nâng cấp 4 cơ chế smart, xem `docs/INTEGRATIONS_GUIDE.md` mục 8 để
đầy đủ. Tóm tắt UI:

- **A. Sample preview** — mỗi header hiển thị 3 giá trị mẫu từ 3 record
  đầu tiên (italic monospace) ngay dưới dropdown.
- **B. Type badge + filter** — cột "Kiểu suy đoán" hiển badge 📅 date /
  👥 PIC / 🏷 status / 🔢 number / 📝 text. Dropdown mapping chỉ hiển
  header có type tương thích với iHRP col — checkbox "Hiện tất cả (bỏ
  filter kiểu)" để bypass khi cần map manual.
- **C. Preset per source** — Excel giữ cấu trúc cũ. JSON API mới có
  preset per integration_id (schema `{integration_id: [presets]}`),
  CRUD endpoints `/api/projects/<slug>/integrations/<id>/mapping-presets`.
- **E. Test parse dry-run** — nút 🔍 "Test parse 5 record đầu" chạy
  parser thử, hiện bảng preview data iHRP + errors/warnings. Row lỗi
  highlight nền đỏ nhạt. Không lưu → chỉ để user verify trước confirm.


## 🆕 17. Public API — REST + iframe + PNG snapshot (T33)

Cho phép bên thứ 3 (partner/khách/Confluence/Word) truy cập dữ liệu dashboard
mà không cần login app chính. Xem đầy đủ ở `docs/PUBLIC_API_GUIDE.md`.

### Task 2A (bản này) — REST + Token CRUD

- **Storage**: `.project_store/<slug>/public_tokens.json` — lưu SHA-256 hash
  (không plaintext). Token format `pub_<40 hex>`. Xem schema chi tiết ở
  `docs/DATA_MODEL.md::T33`.

- **Admin endpoints** (chưa auth layer riêng — local single-user, dùng luôn
  session Flask):
  - `GET  /api/projects/<slug>/public-tokens` — list masked entries.
  - `POST /api/projects/<slug>/public-tokens` — create, trả plaintext **1
    lần duy nhất** (`{token, entry, warning}`).
  - `DELETE /api/projects/<slug>/public-tokens/<id>` — revoke (idempotent,
    giữ entry để audit).
  - `GET  /api/projects/<slug>/public-scopes` — metadata multi-select FE.

- **Public read endpoints** (header `X-API-Key` hoặc `?token=`):
  - `GET /public/api/v1/projects/<slug>/summary` (scope `summary`).
  - `GET /public/api/v1/projects/<slug>/charts/<chart_id>` (scope
    `<chart_id>` dynamic; wildcard `*` bypass).
  - `GET /public/api/v1/projects/<slug>/functions?page=&size=` (scope
    `functions`, max size 200).

- **Scope key**: 15 scope + wildcard `*` — xem `PUBLIC_SCOPES` trong
  `analyzer/public_api.py`. Normalize `_` → `-` để user copy từ code Python
  không lo case.

- **Rate limit**: 60 req / 60s / token — sliding window in-memory (deque).
  Vượt → HTTP 429 + `Retry-After: <s>` + body `{"retry_after": <s>}`.

- **CORS**: allow-all origin, method GET/OPTIONS, header `X-API-Key`.
  Preflight OPTIONS trả 204 no-content, không cần token.

- **Security**:
  - Plaintext token chỉ trả 1 lần (POST create response). Sau đó server chỉ
    còn hash.
  - Verify: `secrets.compare_digest(hash(input), stored_hash)` — constant-time
    compare chống timing attack.
  - Revoke = mark flag; verify luôn fail. Không xoá entry (audit trail).
  - Cap 50 token active/project (chống abuse).

- **Backward compat**: 100% additive — dashboard nội bộ (localhost) không
  đụng gì. Route `/api/...` cũ giữ nguyên hành vi. Public route ở prefix
  riêng `/public/api/v1/...`.

### Task 2B — iframe + PNG (đã ship)

- **iframe route**: `GET /embed/<slug>/<chart_id>?token=&bg=`
  - Render `templates/embed.html` — trang tối giản Chart.js chỉ 1 chart,
    fetch data qua public API bằng JS + token trong query.
  - Header `X-Frame-Options: ALLOWALL` + `CSP frame-ancestors *` — nhúng
    được vào bất kỳ site (Confluence, Notion, portal partner).
  - `bg=transparent` → nền trong suốt (blend vào UI host).
  - **Không** verify token server-side — token verify khi JS gọi API.
    Token sai → iframe hiển "⚠️ Token không hợp lệ".
  - 15 chart_id hỗ trợ: chart-type (bar/doughnut/stacked bar/horizontal bar)
    + list-based (table 50 dòng đầu — full list dùng REST `/functions`).

- **PNG snapshot route**: `GET /public/api/v1/projects/<slug>/charts/<id>/image?w=&h=&bg=&token=`
  - Verify token + scope + rate limit (giống REST).
  - Cache: `.project_store/<slug>/public_cache/<chart>_<WxH>_<bg>.png`,
    TTL 300s. Response header `X-Cache: HIT/MISS`.
  - Miss → dùng Playwright headless chromium: mở `/embed/<slug>/<chart_id>?token=`
    trong viewport `w×h`, wait `body[data-chart-ready]` selector, screenshot.
  - `w/h` clamp [200, 1920] × [150, 1200] — tránh abuse chụp size khổng lồ.
  - Playwright là **optional dep**: `pip install playwright + python -m
    playwright install chromium` (~200MB). Chưa cài → HTTP 503 + message.
  - Cache là **public per-project** (không hash token) — mọi token cùng
    scope xem ảnh cached giống nhau; verify vẫn chạy trước khi serve nên
    revoke token vẫn hoạt động.

### Task 2C — Settings tab "🌐 Public API" (đã ship)

Section mới trong `#settingsModal` (giữa "🎯 SLA" và "🎛️ Hiển thị section"):

- **Bảng token**: cột Name | Prefix (`pub_xxxxxxxx…`) | Scope (compact
  `a, b, c + N…`) | Ngày tạo | Dùng cuối | Actions (🔗 Xem snippet /
  🚫 Revoke). Badge Active/Revoked ngay cạnh name. Empty state message
  "Chưa có token nào".

- **Form create** (toggle inline): input name + grid multi-select scope
  với 3 quick-action (✔ Tất cả / ✖ Bỏ hết / 🌟 Wildcard `*`). Grid render
  từ metadata `/api/projects/<slug>/public-scopes`.

- **New-token modal (`#pubTokNewModal`)** — auto mở sau khi tạo:
  - Warning "Token chỉ hiển thị 1 lần" (yellow banner).
  - Input readonly + nút 📋 Copy (dùng `navigator.clipboard`, fallback
    `document.execCommand("copy")`).
  - 3 tab snippet: **🌐 REST** (curl + PowerShell + chart/functions),
    **🖼 iframe** (`<iframe src=".../embed/..."`), **🖼 PNG**
    (`<img src=".../image?w=&h=&token="`). Snippet build runtime dùng
    `window.location.origin` + `currentProjectSlug` + token vừa tạo.
  - Chart selector (chỉ hiện với iframe/PNG) — populate từ scope metadata
    filter `key != '*'/summary/functions`.
  - Nút "✔ Đã lưu — Đóng" clear plaintext khỏi RAM state.

- **Snippet-view modal (`#pubTokSnipModal`)** — cho token cũ (đã revoke
  hoặc không có plaintext):
  - Placeholder `pub_YOUR_TOKEN` trong snippet — user tự thay bằng token
    đã lưu.
  - Cùng 3 tab REST/iframe/PNG.
  - Message rõ "Token thực đã ẩn (server chỉ giữ hash)".

- **State cục bộ** (`_pubTokState`):
  - `scopes`, `tokens` — cache metadata.
  - `selected` — Set scope key user chọn trong form.
  - `lastNewToken` — plaintext vừa tạo (RAM only, xoá khi đóng modal).
  - `snipTab` + `snipChart` (new-token) & `snipViewTab` + `snipViewChart`
    (view modal) — separate state 2 modal.

- **Hook**: `openSettingsModal` gọi `_pubTokRefresh()` best-effort
  (không block modal, log warn nếu fail).

- **Bảo mật FE**:
  - Plaintext token KHÔNG được lưu vào localStorage / cookie / URL log.
  - Modal đóng → `lastNewToken` = "" + input value = "".
  - Snippet-view chỉ hiện placeholder — không expose token thật.

---

## 18. Xuất "Toàn bộ vấn đề" — Excel multi-sheet (T34 — Task 1)

### Mục đích
1 nút xuất Excel workbook duy nhất chứa mọi loại vấn đề gộp lại, mỗi loại 1
sheet. Tiện cho tuần báo cáo / họp escalation — thay vì bấm 7 nút "Xuất
Excel" ở 7 section, chỉ cần 1 click.

### Nút truy cập

- **Header dashboard**: nút đỏ `📊 Xuất vấn đề` cạnh `📄 Xuất PDF` và
  `🎬 Trình chiếu`.
- **Command Palette** (`Ctrl+K`): entry `📊 Xuất toàn bộ vấn đề (Excel
  multi-sheet)`.

### File output

Tên: `iHRP_Van_De_Tong_Hop_<slug>_YYYYMMDD.xlsx` → 8 sheet:

| # | Sheet | Nội dung | Banner màu |
|---|-------|----------|------------|
| 0 | Cover | Project name, filter info (module/process/pic), timestamp, count mỗi loại + hyperlink đến sheet | Xanh navy `1F4E79` |
| 1 | Overdue | Function trễ deadline (**dedup theo Mã CN, phase merged**) | Đỏ `C00000` |
| 2 | Chua_Co_PIC | Function chưa assign PIC | Cam `ED7D31` |
| 3 | Dinh_Tre | Function stalled giữa 2 phase | Vàng đậm `BF8F00` |
| 4 | High_Risk | Risk score ≥30 | Đỏ tươi `E60000` |
| 5 | Aging_WIP | In-progress quá threshold (default 14 ngày) | Vàng nhạt `FFC000` |
| 6 | Data_Quality | Row có lỗi data (dup, missing, invalid) | Xám `595959` |
| 7 | Bookmark | Function đã star (fetch từ `bookmarks.json` — cross-check với filtered data) | Tím `7030A0` |

### Layout chuẩn mỗi sheet

- **Row 1**: banner merge A1:...1 với fill màu category + text trắng đậm,
  format `<icon> <TÊN SHEET> — Tổng: N record`.
- **Row 2**: header bold + fill xanh nhạt `DEEBF7`.
- **Row 3+**: data rows. Fill màu theo mức trễ / risk (RED ≥30d/≥80,
  ORANGE ≥14d/≥50, YELLOW ≥7d/≥30).
- **Freeze pane**: `A3` — luôn thấy banner + header khi scroll.
- **Auto-filter**: enable ở row 2.
- **Empty state**: nếu 0 record → row 3 merge cell với message "✓ Không có
  record nào trong nhóm này (đã áp dụng filter global)."

### Dedup Overdue

Sheet Overdue: gom nhiều phase-record của cùng 1 Mã CN thành 1 row:
- Cột **Phase trễ (gộp)**: `"Analysis, UAT"` — giữ order first-seen.
- Cột **Số ngày trễ (max)**: `MAX(days_overdue của các phase)`.
- Cột **PIC**: dedup + giữ order first-seen (union tất cả PIC của các phase).
- Sort DESC theo `days_overdue`.

### Global filter

**Query params** (`GET /api/projects/<slug>/export-all-issues`):
- `g_module=HR,SI,PR` (comma-sep, hoặc lặp nhiều lần)
- `g_process=BP.01,BP.02`
- `g_pic=SonHN6`
- `threshold=14` (aging WIP ngưỡng — default 14).

**POST body** (JSON): `{ "g_module": [...], "g_process": [...],
"g_pic": [...], "threshold": 14 }`.

Filter apply **1 lần** tại `_filter_parsed_data(state["data"], ...)`, sau
đó recompute mọi loại vấn đề trên filtered data. Tránh tính lại 8 lần.

### Cover sheet — hyperlink

Cột **Link** dùng `openpyxl.Hyperlink(location=f"'<sheet>'!A1")` — click
→ nhảy trực tiếp đến sheet tương ứng trong Excel.

### File chính

- `exporter/export_all_issues.py` (~500 LOC) — main entry
  `export_all_issues(project_name, slug, overdue_list, ...)` + 7 per-sheet
  writer + helper `_dedup_by_ma_cn`.
- `app.py::project_export_all_issues` — endpoint (GET/POST hỗ trợ).
- `templates/index.html` — nút `📊 Xuất vấn đề` ở header (red-500).
- `static/js/dashboard.js` — `exportAllIssues()` + Command Palette entry
  `act.export-all-issues`.
