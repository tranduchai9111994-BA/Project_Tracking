# Prompt nâng cấp Header + Summary Cards — iHRP Function List Tracker

> Đọc ARCHITECTURE.md + DASHBOARD_SPEC.md § Summary Cards trước khi bắt đầu.
> `pytest -q` trước và sau mỗi commit. Ctrl+Shift+R sau khi đổi JS/CSS.

---

## 1. SUMMARY CARDS — GIẢM TỪ 8 XUỐNG 2 HÀNG

### Hàng chính (5 cards — kích thước lớn, giữ nguyên style hiện tại):

| # | Card | Giá trị | Border color | Ghi chú |
|---|------|---------|-------------|---------|
| 1 | Tổng chức năng | `summary.total_functions` | blue | Giữ subtitle "X module · Y PIC" |
| 2 | Tiến độ | `summary.overall_progress_pct` | green | Giữ subtitle Weighted + Golive % |
| 3 | Trễ hạn | `summary.total_overdue` | red | Giữ "(N phase)" subtitle |
| 4 | Chưa PIC | `summary.unassigned_count` | orange | Giữ subtitle |
| 5 | Rủi ro cao (≥50) | `summary.high_risk_count` | rose | Giữ subtitle |

### Hàng phụ (3 cards — nhỏ hơn ~60% height, font nhỏ hơn, nằm ngay dưới hàng chính):

| # | Card | Giá trị | Ghi chú |
|---|------|---------|---------|
| 6 | Chưa cập nhật hạn | `summary.missing_deadline_count` | Nếu = 0: hiện compact dạng inline `✓ Đã đủ hạn` thay vì card to |
| 7 | DQ (chỉ High) | Đếm DQ issues severity = High | **Không hiện total 2042** — total nằm trong tooltip hoặc subtitle "(tổng 2042 issue)" |
| 8 | Phân hệ / Quy trình | `summary.modules_count` / process count | Compact, ít actionable |

### CSS hàng phụ:
```css
.summary-cards-secondary {
  display: flex;
  gap: 8px;
  margin-top: 6px;
}
.summary-cards-secondary .summary-card {
  padding: 8px 14px;         /* nhỏ hơn hàng chính */
  min-height: auto;           /* không ép chiều cao */
  font-size: 13px;            /* số nhỏ hơn */
}
.summary-cards-secondary .summary-card .card-value {
  font-size: 20px;            /* thay vì 32-36px hàng chính */
}
```

### Zero-state card:
Khi giá trị = 0, card hàng phụ chuyển sang dạng inline nhỏ:
```html
<!-- Thay vì card to với số 0 lớn -->
<div class="summary-card summary-card--zero">
  <i class="ti ti-check"></i>
  <span>Đã đủ hạn</span>
</div>
```
Style: `background: var(--bg-success)`, `color: var(--text-success)`, `padding: 6px 12px`, `border-radius: var(--radius)`, `font-size: 12px`, inline-flex.

---

## 2. TREND INDICATOR TRÊN CARD

Mỗi card hàng chính (trừ Tổng và Phân hệ) thêm delta indicator góc trên phải:

```html
<div class="card-trend card-trend--down">  <!-- down = tốt cho overdue -->
  <i class="ti ti-trending-down"></i>
  <span>−2</span>
</div>
```

### Logic tính delta:
- So sánh giá trị hiện tại vs snapshot trước gần nhất (đã có trong `snapshot_index.json` hoặc tính từ `function_diff`).
- **Overdue / Chưa PIC / DQ**: giảm = xanh (↓ tốt), tăng = đỏ (↑ xấu).
- **Tiến độ %**: tăng = xanh (↑ tốt), giảm = đỏ (↓ xấu).
- **Risk cao**: giảm = xanh, tăng = đỏ.
- Delta = 0: không hiện indicator (ẩn hoàn toàn, không hiện "→0").
- Không có snapshot trước: không hiện indicator.

### Style:
```css
.card-trend {
  position: absolute;
  top: 8px;
  right: 10px;
  font-size: 12px;
  font-weight: 500;
  display: flex;
  align-items: center;
  gap: 2px;
}
.card-trend--up-bad   { color: var(--text-danger); }
.card-trend--down-good { color: var(--text-success); }
.card-trend--up-good  { color: var(--text-success); }
.card-trend--down-bad  { color: var(--text-danger); }
```

### Backend:
- Endpoint `GET /api/projects/<slug>/dashboard` response thêm field `summary.deltas`:
```json
{
  "deltas": {
    "total_overdue": -2,
    "unassigned_count": 0,
    "high_risk_count": 3,
    "overall_progress_pct": 1.2,
    "dq_high_count": -5
  }
}
```
- Tính trong `dashboard_engine.compute_all()`: load snapshot trước từ `snapshot_index.json` (entry trước current), tính diff.
- Nếu chỉ có 1 snapshot → `deltas = null` → FE ẩn indicator.

---

## 3. TOOLBAR GOM NÚT

### Hiện tại (11 nút):
`VI` `🌙` `Tải Excel` `Đồng bộ ▾` `Xuất ▾` `Trình chiếu` `Chỉnh thứ tự` `Mặc định` `Ẩn: ...` `Thêm ▾` `Đăng xuất`

### Đề xuất (6 nút):

| Nút | Chứa | Icon |
|-----|-------|------|
| **Import ▾** | Tải Excel · Đồng bộ (dropdown giữ nguyên sub-items) | `ti-upload` |
| **Xuất ▾** | Giữ nguyên (đã là dropdown) — thêm Trình chiếu vào cuối dropdown | `ti-download` |
| **View ▾** | Chỉnh thứ tự · Mặc định · Ẩn/Hiện section (dropdown) | `ti-eye` |
| **Thêm ▾** | Giữ nguyên | `ti-plus` |
| **⚙️** | Cài đặt (icon only, không text) | `ti-settings` |
| **VI / 🌙** | Gom thành 2 icon nhỏ cạnh nhau, không cần label text | `ti-language` · `ti-moon` |

### Layout:
```html
<div class="toolbar">
  <div class="toolbar-left">
    <!-- Import + Xuất: nút chính thao tác data -->
    <div class="toolbar-dropdown" data-dropdown="import">
      <button><i class="ti ti-upload"></i> Import <i class="ti ti-chevron-down"></i></button>
      <!-- dropdown: Tải Excel | Đồng bộ -->
    </div>
    <div class="toolbar-dropdown" data-dropdown="export">
      <button><i class="ti ti-download"></i> Xuất <i class="ti ti-chevron-down"></i></button>
      <!-- dropdown: items hiện tại + Trình chiếu -->
    </div>
  </div>
  <div class="toolbar-right">
    <!-- View + Thêm + Settings + Language/Dark -->
    <div class="toolbar-dropdown" data-dropdown="view">
      <button><i class="ti ti-eye"></i> View <i class="ti ti-chevron-down"></i></button>
      <!-- dropdown: Chỉnh thứ tự | Mặc định | Ẩn section toggle -->
    </div>
    <div class="toolbar-dropdown" data-dropdown="more">
      <button><i class="ti ti-plus"></i> Thêm <i class="ti ti-chevron-down"></i></button>
    </div>
    <button class="toolbar-icon-btn" onclick="openSettingsModal()">
      <i class="ti ti-settings"></i>
    </button>
    <button class="toolbar-icon-btn" onclick="toggleLanguage()">
      <i class="ti ti-language"></i>
    </button>
    <button class="toolbar-icon-btn" onclick="toggleDarkMode()">
      <i class="ti ti-moon"></i>
    </button>
  </div>
</div>
```

### Style nút:
```css
.toolbar-dropdown button,
.toolbar-icon-btn {
  background: white;
  border: 0.5px solid var(--border);
  border-radius: var(--radius);
  padding: 6px 12px;
  font-size: 13px;
  cursor: pointer;
  display: flex;
  align-items: center;
  gap: 4px;
}
.toolbar-icon-btn {
  padding: 6px 8px;   /* icon-only nhỏ hơn */
}
.toolbar-dropdown button:hover,
.toolbar-icon-btn:hover {
  background: var(--surface-0);
}
```

---

## 4. VÙNG UPLOAD THU GỌN — GIẢM CHIỀU CAO

Vùng "Vùng tải Function List đã thu gọn" hiện chiếm ~50px height + border dashed to.

### Đề xuất: thu thành 1 dòng inline nhỏ:
```html
<div class="upload-collapsed-bar">
  <i class="ti ti-file-upload" style="font-size: 14px;"></i>
  <span>Kéo thả file hoặc</span>
  <button class="upload-expand-btn">Tải lên</button>
  <span class="upload-project-tag">MPHG</span>
</div>
```

### Style:
```css
.upload-collapsed-bar {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 14px;
  background: var(--surface-1);
  border: 0.5px dashed var(--border);
  border-radius: var(--radius);
  font-size: 12px;
  color: var(--text-secondary);
  margin-bottom: 12px;
}
.upload-expand-btn {
  background: var(--fill-accent);
  color: white;
  border: none;
  border-radius: var(--radius);
  padding: 3px 10px;
  font-size: 12px;
  cursor: pointer;
}
.upload-project-tag {
  background: var(--bg-accent);
  color: var(--text-accent);
  padding: 1px 6px;
  border-radius: 4px;
  font-size: 11px;
  font-weight: 500;
}
```

Chiều cao giảm từ ~50px xuống ~32px — tiết kiệm vertical space cho cards.

---

## QUY TẮC

1. **Không break API** — chỉ thêm `deltas` field vào response dashboard.
2. **Giữ nguyên click behavior** trên cards (click → scroll đến section tương ứng).
3. **Responsive**: hàng chính 5 cards wrap thành 3+2 trên tablet, 2+2+1 trên mobile. Hàng phụ wrap tự do.
4. **Dark mode**: dùng CSS variable, không hardcode màu.
5. **Backward compat**: `section_order.json` cũ, `chart_configs.json` không bị ảnh hưởng.
6. **`pytest -q`** trước và sau. Ctrl+Shift+R sau khi đổi JS/CSS.
