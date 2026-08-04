# Prompt nâng cấp UX Dashboard — iHRP Function List Tracker

> Dùng prompt này trong Cursor để thực hiện toàn bộ đề xuất nâng cấp.
> Đọc ARCHITECTURE.md + FEATURE_CATALOG.md + DASHBOARD_SPEC.md trước khi bắt đầu.
> `pytest -q` trước và sau mỗi commit.

---

## PHẦN 1: SIDEBAR REDESIGN (ưu tiên cao nhất)

### 1A. Gom 30+ section thành 12 sidebar items bằng tab nội bộ

**Nguyên tắc:** mỗi sidebar item = 1 section trên DOM chứa nhiều tab con. Click sidebar = scroll đến section. Click tab = switch nội dung trong section đó (không reload, không scroll).

**Cấu trúc mới:**

```
TỔNG QUAN (luôn hiện, không collapse)
├── Summary          — giữ nguyên cards + insight strip + completion forecast
├── Tiến độ module   — TAB: Bảng A | Phase Matrix | Công việc | Giai đoạn
│                      (4 section cũ gom thành 1, dùng tab bar phía trên)

VẤN ĐỀ (vị trí #2 — ngay sau Tổng quan)
├── Issues           — TAB: Trễ hạn | Chưa PIC | Đình trệ | WIP tồn đọng | Data Quality
│                      Mỗi tab có badge count. Tab active có border-bottom accent.
│                      Data mỗi tab load lazy khi click (không fetch hết lúc đầu).
├── Risk             — TAB: Risk Score | UAT Quality

TIẾN ĐỘ
├── Timeline         — TAB: Phase Stack | Burndown | SLA
├── Hoạt động tuần   — TAB: Rlog | Function Diff | PIC tuần tới

DỰ BÁO & KẾ HOẠCH
├── Kế hoạch         — TAB: Gantt Calendar | Forecast UAT/Golive | Baseline SV
├── Nhân lực         — TAB: Manpower | EVM | PIC Overload | Capacity
│                      (Ước lượng hệ số gom vào tab Manpower dưới dạng expandable panel)

PHÂN TÍCH
├── Phân tích        — TAB: PIC | Priority | FIT/GAP | Effort | Scope Creep | Quy trình

QUẢN TRỊ
├── Quản trị         — TAB: Chiều PM | Compare | Custom Dashboard | History | Kanban | Bookmarks
```

**Implementation:**
- Mỗi section wrapper: `<section id="section-{name}" class="dashboard-card">` giữ nguyên.
- Tab bar dùng `<div class="section-tabs">` với `data-tab="tab-id"` per button.
- Tab content dùng `<div class="tab-pane" id="tab-{id}">`, show/hide bằng class `active`.
- Lưu active tab per section vào `localStorage` key `ihrp.tab.{section-id}`.
- `section_order.json` giữ nguyên cấu trúc — chỉ giảm số entry từ 30+ xuống 12.
- Sidebar scroll-to dùng `section-{name}`, không thay đổi logic hiện tại.
- Help `?` button: mỗi tab có `data-help-id` riêng (giữ nguyên help content cũ).
- Export mỗi tab: nút export nằm trong tab bar, chỉ xuất data của tab đang active.

### 1B. Sidebar visual redesign

**Thay thế hoàn toàn sidebar hiện tại:**

1. **Bỏ dropdown "Tất cả"** — thay bằng search bar nhỏ trên cùng:
   ```html
   <div class="sidebar-search">
     <i class="ti ti-search"></i>
     <input placeholder="Tìm section... Ctrl+/" />
   </div>
   ```
   Filter sidebar items theo keyword khi gõ. ESC clear.

2. **Nhóm bằng divider + label uppercase mờ:**
   ```html
   <div class="sidebar-group-label">
     <i class="ti ti-eye"></i> TỔNG QUAN
     <i class="ti ti-chevron-down sidebar-collapse-icon"></i>
   </div>
   ```
   Click label = collapse/expand nhóm. State lưu `localStorage` key `ihrp.sidebar.collapsed.{group}`.

3. **Icon Tabler cho mỗi item** (outline style, 15px):
   - Summary: `ti-layout-dashboard`
   - Tiến độ module: `ti-box`
   - Issues: `ti-alert-circle`
   - Risk: `ti-shield-exclamation`
   - Timeline: `ti-chart-area-line`
   - Hoạt động tuần: `ti-notebook`
   - Kế hoạch: `ti-calendar`
   - Nhân lực: `ti-users`
   - Phân tích: `ti-chart-pie`
   - Quản trị: `ti-settings`

4. **Badge count** trên sidebar items nhóm Vấn đề:
   ```html
   <span class="sidebar-badge sidebar-badge--danger">3</span>
   <span class="sidebar-badge sidebar-badge--warning">1</span>
   <span class="sidebar-badge sidebar-badge--muted">0</span>  <!-- muted khi = 0 -->
   ```
   Data lấy từ `summary.total_overdue`, `summary.unassigned_count`, stalled count — đã có sẵn.

5. **Active state:** item đang scroll-to có:
   - `border-left: 3px solid` accent color
   - Background accent nhạt
   - Font-weight 500
   - Transition 150ms

6. **Hover:** `background: var(--surface-0)` + `border-radius: 6px`.

7. **Mặc định collapse** nhóm Phân tích và Quản trị (ít dùng hàng ngày).

---

## PHẦN 2: FORECAST GANTT (section Forecast UAT/Golive)

### 2A. % Complete fill trên bar
- Mỗi milestone bar (Phân tích xong, Dev xong, Cấu hình xong, UAT, Golive): tô phần đã Closed đậm, phần chưa xong nhạt hơn (opacity 0.3).
- Hiện con số % ngay trên bar (font 11px, trắng trên nền đậm, đen trên nền nhạt).
- Data: đã có `closed_count / total_count` per milestone trong `forecast_gantt.py`.

### 2B. Baseline ghost bar
- Khi project đã chọn `baseline_snapshot_id`: vẽ bar mờ (opacity 0.15, cùng màu) phía sau mỗi milestone bar.
- Ghost bar thể hiện baseline Start→End.
- Data: tính từ `baseline_sv.py` — đã có `end_baseline` per function.

### 2C. Overdue visual trên bar
- Phần bar vượt qua đường Today mà chưa Closed: tô sọc đỏ chéo (`repeating-linear-gradient 45deg, red 0 4px, transparent 4px 8px`).
- Today line: `border-left: 2px dashed red` vertical xuyên toàn bộ chart.

### 2D. Summary column bên phải bar
- Sau mỗi bar milestone, thêm 3 cột nhỏ text (font 11px):
  - `% done` (e.g. "78%")
  - `SV` (e.g. "+12d" đỏ hoặc "−3d" xanh)
  - `Còn` (e.g. "42 fn")
- Chiều rộng cố định 180px bên phải vùng chart.

### 2E. Milestone diamond marker
- Tách biệt: bar = duration (min Start → max End), diamond ◆ = forecast month.
- Diamond đặt trên trục thời gian tại vị trí tháng forecast, cùng hàng với bar.
- Diamond: SVG `<polygon>` 10×10px, cùng màu milestone, có tooltip "Forecast: MM/YYYY".

---

## PHẦN 3: FORECAST MANPOWER — FIX SỐ LIỆU

### 3A. Target mặc định = remaining duration
- Thay `target_months` default từ `1` thành: `ceil((max_forecast_end - today) / 30)`.
- `max_forecast_end` lấy từ `forecast_gantt.py` (Golive forecast month cuối cùng).
- Nếu không có forecast → fallback 3 tháng (thay vì 1).
- User vẫn override bằng input, nhưng input pre-fill số tháng đã tính.

### 3B. Cảnh báo seed ratio nổi bật hơn
- Khi seed % > 50%: bảng kết quả bọc trong `border: 2px solid orange` + banner trên cùng:
  ```
  ⚠️ {seed_pct}% function dùng estimate mặc định — kết quả mang tính THAM KHẢO.
  Nhập Estimate MH thực tế trên Function List để có số liệu chính xác.
  ```
- Banner dùng `background: var(--bg-warning)`, font-weight 500.

### 3C. Cho nhập tổng effort hợp đồng (optional)
- Thêm input "Tổng effort dự án (MD)" trong phần Ước lượng hệ số.
- Nếu nhập (e.g. 500 MD): auto-scale tất cả ratio seed sao cho tổng MH khớp `500 × 8 = 4000 MH`.
- Hiện scale factor: "Hệ số đã điều chỉnh ×0.47 để khớp tổng effort hợp đồng 500 MD."
- Lưu vào `project_settings.json` field `contract_effort_md`.

---

## PHẦN 4: CÁC CẢI TIẾN NHỎ KHÁC

### 4A. Snapshot diff tự động sau upload/sync
- Sau mỗi upload/sync thành công, tự chạy `function_diff` so với snapshot trước.
- Hiện kết quả trên Insight strip dạng chip:
  ```
  Diff: +5 mới · 3 sửa status · 2 đổi PIC
  ```
- Click chip → scroll đến tab Function Diff.

### 4B. Trend sparkline trên summary cards
- Cards Overdue, Chưa PIC, Đình trệ: thêm sparkline nhỏ (30×16px) góc phải.
- Data: count per snapshot (lấy từ `snapshot_index.json` metrics hoặc tính lại từ 5 snapshot gần nhất).
- Dùng inline SVG `<polyline>` — không cần Chart.js cho sparkline.
- Màu: xanh nếu trending down (tốt), đỏ nếu trending up (xấu).

### 4C. DQ badge trên tab Module/Matrix
- Trong tab "Bảng A" (Module overview): cột mới "DQ" hiện số issue per module.
- Trong tab "Phase Matrix": cell có DQ issue hiện dot nhỏ góc trên phải (đỏ nếu High, cam nếu Medium).
- Data: đã có từ `data_quality.py`, chỉ cần join theo module.

### 4D. Drill-down: bulk tag/bookmark
- Trong drill-down modal: thêm checkbox mỗi row + nút "Tag đã chọn" / "Bookmark đã chọn".
- Gọi `/tags/bulk` API đã có.
- Sau khi tag: hiện toast "Đã tag 5 function → CR" (hoặc bookmark icon).

---

## QUY TẮC CHUNG

1. **Không break existing API** — tất cả route hiện tại giữ nguyên. Chỉ thêm logic FE grouping.
2. **Tab state lưu localStorage** — key pattern `ihrp.tab.{section-id}`.
3. **Sidebar state lưu localStorage** — key pattern `ihrp.sidebar.collapsed.{group}`.
4. **Help content giữ nguyên** — mỗi tab kế thừa `data-help-id` từ section cũ tương ứng.
5. **Section order migration**: khi load `section_order.json` cũ (30+ entries) → auto-map sang 12 entries mới. Giữ backward compat.
6. **Mobile**: tab bar horizontal scroll trên viewport nhỏ (overflow-x auto, no wrap).
7. **`pytest -q` phải pass** trước và sau mỗi commit.
8. **Ctrl+Shift+R** sau khi đổi JS/CSS.
9. **Không push** trừ khi user yêu cầu.
