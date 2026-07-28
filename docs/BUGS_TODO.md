# 📋 Bug List — Session QA ngày 28/07/2026

**Trạng thái**: Session QA bị dừng giữa chừng (user tắt máy). Ngày mai tiếp tục từ đây.

**Test scenario chung**: Filter Module=**PR** + Quy trình=**[PRM.BP.03, PRM.BP.04]** → 45 function.

---

## 🔴 NHÓM A — CÙNG ROOT CAUSE: FE render trên filtered data trả 0

Backend verified TRẢ ĐÚNG (khi filter PR + 2 QT):
```
total_overdue: 1
unassigned_count: 44
high_risk_count: 2
overdue_list length: 1
unassigned_tasks length: 163
risk_scores length: 45
```

Nhưng FE hiện **0** ở các chỗ sau — nghi vấn cùng root cause (DOM duplicate id hoặc data binding lỗi):

### Bug 1 — Summary cards = 0
- `#cardOverdue` hiện 0 (backend: 1)
- `#cardUnassigned` hiện 0 (backend: 44)
- `#cardHighRisk` hiện 0 (backend: 2)
- Screenshot: `assets/image-b2178336-*.png`
- File: `static/js/dashboard.js` line ~1126 `renderSummaryCards()`

### Bug 10 — Bảng "Task chưa có PIC phụ trách" = 0
- `#unassignedTable` hiện "Không có task nào chưa được giao PIC"
- Backend trả 163 unassigned tasks
- Screenshot: `assets/image-721760cd-*.png`

### Bug 12 — Bảng "Danh sách trễ deadline" = 0
- Hiện "Không có task trễ"
- Backend trả 1 task overdue (PR.FR.57)
- Screenshot: `assets/image-1a4ec6e2-*.png`

### Bug 13 (chưa list) — Cột "Trễ" trong Module Overview = 0
- `#moduleTable` cột overdue_count hiện 0
- Backend trả `overdue_count=1` cho row PR

**Cách debug**:
- Grep các id trong `templates/` — nếu duplicate → dùng querySelector scoped
- Hoặc check `metricsData` bị overwrite race condition

---

## 🔴 NHÓM B — DRILL-DOWN CHART CLICKS

### Bug 5 — Task_type drill rỗng
- Chart "Tiến độ theo công việc" filter PR+2QT hiện UAT 18%
- Click UAT bar → drill trả 0 items
- Root cause có thể: `_filter_task_type` trong `analyzer/drill_down.py` có `if not pd.status: continue`
- 18% = 8/45 rows UAT Closed → drill phải ≥ 8 items

### Bug 7 — Workload PIC: Σ tổng ≠ drill chi tiết
- HoaTT81 chart hiện "Σ 9" nhưng click drill ra 10 dòng
- Screenshot: `assets/image-2a5c23a5-*.png`
- Kiểm tra `_pic_workload` (dashboard_engine.py) vs `_filter_pic_workload` (drill_down.py) count logic có consistent không (phase-record vs function unique)

### Bug 8 — Priority / Complexity donut: chi tiết ≠ tổng
- VD Must-have 7 (16%) nhưng click drill ≠ 7 items
- Screenshot: `assets/image-a81648de-*.png`
- Root cause tương tự Bug 7

### Bug 9 — "Tiến độ theo Giai đoạn"
- Chart hiện tất cả 100% dù không đúng
- Legend chồng chữ ("Giai đoạn 1" đè "Giai đoạn 2")
- Click chi tiết thấy phân hệ khác không thuộc bộ lọc → drill không inherit global filter
- Screenshot: `assets/image-2016a569-*.png`
- Fix:
  - Đổi denominator từ `total_with_status` → `len(rows)` (weighted_all pattern)
  - Sửa Chart.js legend layout (position, padding)
  - Đảm bảo dispatch drill có `_g_module/_g_process/_g_pic`

---

## 🔴 NHÓM C — RENDER BUGS

### Bug 6 — "Tiến độ theo Phase" chỉ hiện Closed
- Chart chỉ hiện Closed bars màu xanh
- Legend đủ (Closed, In-progress, Assigned, Resolved, Open, Pending, Cancelled) nhưng bars khác không hiện
- Screenshot: `assets/image-f77ca4c7-*.png`
- Có thể data `phase_progress_stacked` chỉ trả Closed sau filter, hoặc chart config dataset thiếu

---

## 🎨 NHÓM D — ENHANCEMENT

### Bug 11 — Số MM trên bar chart "Effort theo PIC"
- Hiện chỉ hover mới thấy số MM
- Cần datalabel trên từng segment (Đã Closed / Còn lại)
- Screenshot: `assets/image-f40c10ca-*.png`

---

## 🟡 NHÓM E — FEATURES MỚI

### Vấn đề 2 — Gantt 3 modes
- Hiện có 2 button `data-groupby="module"|"process"`
- User muốn 3 mode:
  - **Module**: mỗi module 1 row aggregate (min start → max end)
  - **Quy trình**: mỗi QT 1 row aggregate
  - **Function**: mỗi function 1 row với phase segments (mode hiện tại)
- Thêm button `data-groupby="function"` (mặc định = function)

### Vấn đề 3 — Excel export cho 4 section
Chưa có nút "📥 Xuất Excel" ở:
- SLA — vi phạm deadline theo Priority
- Capacity PIC — remaining MH vs công suất
- Ai đang chậm — Heatmap PIC × Phase
- Baseline vs Actual — variance ngày

Cần thêm:
- 4 endpoint POST `/api/projects/<slug>/export-{sla|capacity|slow|baseline}`
- 4 function trong `exporter/excel_exporter.py`
- 4 nút 📥 + handler FE gửi request kèm globalFilters

### Vấn đề 4 — Rule chung
> **"XEM THÌ PHÂN TRANG NHƯNG XUẤT LÀ XUẤT ALL RECORD"**

Verify tất cả export endpoints (drill-down, overdue, chart-data) đều xuất FULL không cắt theo pagination.

---

## ✅ ĐÃ FIX TRONG SESSION (không cần làm lại)

- Fix 12 vấn đề ban đầu (data % sai, filter cascade, pagination, help tips, Gantt compact mode)
- Fix drill-down inherit global filter (thêm `_g_module/_g_process/_g_pic`)
- Fix `_parse_drill_filters` valid_keys thiếu `task_type`, `ma_cn`, `level`
- Mở rộng drill modal `w-[98vw] h-[96vh]` + thêm filter panel (search, status multi, PIC, date, overdue, reset)
- Tất cả pushed lên `main` branch của GitHub

---

## 🚀 Instructions cho session tiếp theo

1. `git pull` để lấy state mới nhất
2. Đọc file này để nhớ context
3. Focus fix NHÓM A trước (impact cao nhất — dashboard sai lệch hoàn toàn khi filter)
4. Sau mỗi nhóm chạy `venv/Scripts/python -m pytest -q` verify không regression
5. Ctrl+Shift+R browser sau khi fix để reload JS/CSS
