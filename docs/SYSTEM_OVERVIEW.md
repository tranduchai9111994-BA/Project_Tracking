# Hệ thống iHRP Function List Tracker — Tổng quan cấu trúc & logic

> Cập nhật: **2026-07-31**. Tài liệu này là **lối vào** để hiểu toàn bộ hệ thống từ tổng quan → chi tiết.
> Chi tiết chuyên sâu vẫn nằm ở các guide cũ; bảng mục lục cuối file chỉ đường đi đọc tiếp.

---

## 1. Hệ thống này là gì?

Ứng dụng **dashboard local** (Flask) cho PM/BA dự án triển khai **HRIS iHRP**.

```
Function List Excel  ──parse──►  Metrics / Rules  ──►  Dashboard UI
         ▲                           │
    Sync API/DB                      ├── Export Excel / PDF / MoM / FL re-import
         │                           ├── Forecast (tháng UAT/Golive, Manpower)
Chiều PM (KeHoach + Weekly PPT)      └── Public API / LAN / Archive
```

**Người dùng chính:** 1 PM/BA (solo) trên máy local hoặc LAN tin cậy — không phải SaaS multi-tenant.

**Nguyên tắc gốc (`.cursorrules`):**

| # | Nguyên tắc |
|---|------------|
| 1 | **Không hardcode cột** — auto-detect header `Phase - Attribute` |
| 2 | **Overdue** = có End < today và Status ∉ {Closed, Cancelled} (+ ngoại lệ phase sau Closed) |
| 3 | **Status** chuẩn: Open, Assigned, In-progress, Resolved, Closed, Pending, Cancelled; số ở Status = lỗi lệch cột |
| 4 | **PIC** tách bởi `,` `;` `+` `\n` |

---

## 2. Bản đồ tài liệu (đọc theo thứ tự)

| Bước | File | Nội dung |
|------|------|----------|
| **1** | **[SYSTEM_OVERVIEW.md](SYSTEM_OVERVIEW.md)** (file này) | Big picture + data flow + nhóm dashboard |
| **2** | **[BUSINESS_LOGIC.md](BUSINESS_LOGIC.md)** | Toàn bộ rule nghiệp vụ (overdue, unassigned, stalled, DQ, forecast…) |
| **3** | **[FEATURE_CATALOG.md](FEATURE_CATALOG.md)** | Catalog từng section / API / export |
| 4 | [ARCHITECTURE.md](ARCHITECTURE.md) | Stack, folder, storage, security, module map kỹ thuật |
| 5 | [DATA_MODEL.md](DATA_MODEL.md) | Schema parse + JSON store |
| 6 | [DASHBOARD_SPEC.md](DASHBOARD_SPEC.md) | Spec UI từng chart (lịch sử + default order) |
| 7 | Guides chuyên đề | Integrations, Public API, LAN, Archive, PM dimension, Help |

---

## 3. Kiến trúc 3 lớp (rút gọn)

```
┌─────────────────────────────────────────────────────────────┐
│  templates/index.html + static/js/dashboard.js (SPA)         │
│  Chart.js · Tailwind · i18n VI/EN · sidebar nhóm · Help      │
└──────────────────────────▲──────────────────────────────────┘
                           │ fetch /api/projects/<slug>/…
┌──────────────────────────┴──────────────────────────────────┐
│  app.py (Flask) — routes admin + public + embed              │
└──────────────────────────▲──────────────────────────────────┘
                           │
     ┌─────────────────────┼─────────────────────┐
     ▼                     ▼                     ▼
 parser/              analyzer/              exporter/
 excel_parser         dashboard_engine       excel / MoM / FL
 column_mapping       overdue, stalled…      forecast / PM…
 pm_*_parser          forecast_*, rlog…      chart export
```

**Persistence:** `uploads/projects/<slug>/` — JSON + pickle + xlsx. **Không** dùng DB app.

Chi tiết folder/API → [ARCHITECTURE.md](ARCHITECTURE.md).

---

## 4. Data flow chính

### 4.1 Nạp dữ liệu Function List

```
Upload Excel ──► Column Mapping Wizard (optional)
              ──► parser.excel_parser (auto-detect)
              ──► SnapshotManager.add (source=upload|sync:…)
              ──► _state[slug] in-memory + current.xlsx
              ──► DashboardEngine.compute_all → metrics JSON
```

**Sync API:** Integrations registry → fetch JSON → field_mapping → snapshot (`source=sync:…`) → **eager-reload `_state`** → FE `_refreshAfterSync` (cache-bust).

### 4.2 Phase & task type

Header dạng `Analysis - Start|End|Status|PIC|Estimate MH` → `PhaseGroup`.

`PhaseGroup.task_type` map regex → tiếng Việt:

| Pattern phase | Công đoạn (task_type) |
|---------------|------------------------|
| analy* | Phân tích |
| \bdev\b | Lập trình |
| local\|test | Kiểm thử |
| config.*uat | Cấu hình UAT |
| ^uat$ | UAT |
| doc | Tài liệu |
| prod\|golive | Cấu hình Golive |

### 4.3 Filters

- **Global:** Module × Quy trình × PIC × Mã dự án (AND giữa chiều).
- **Local:** từng section (Kanban AND với global; Timeline Status/Phase/Priority…).
- Export chart: `mode=summary|detail|both` → sheet `Tong_hop` / `Chi_tiet`.

---

## 5. Nhóm dashboard (IA)

Sidebar lọc theo nhóm; **All** = hiện hết. Có thể sửa tên VI/EN + chuyển section giữa nhóm (`localStorage` `ihrp_sidebar_groups_v2`).

| Nhóm | Mục đích | Section tiêu biểu |
|------|----------|-------------------|
| **Tracking** | Tiến độ tổng → rồi vấn đề | Summary, Module, Công việc, Phase, Matrix, Rlog, Overdue, Unassigned, Đình trệ |
| **Forecast** | Dự báo thời gian & lực lượng | Timeline Gantt, Forecast UAT/Golive, **Forecast Manpower**, Capacity, PIC Overload |
| **Chất lượng** | DQ / anomaly / risk | Data Quality, Risk Score |
| **Phân tích** | Sâu hơn | Quy trình, PIC, Effort, Kanban… |
| **Chiều PM** | Kế hoạch dự án + weekly PPT | Chiều PM, Digest |
| **Quản trị** | Settings-adjacent | So sánh, Custom dash, History |

### Thứ tự mặc định (DOM) — **tiến độ trước, vấn đề sau**

1. Summary + filter global  
2. Module / Công việc / Matrix / Phase / Giai đoạn  
3. Timeline + Forecast (UAT/Golive, Manpower) + Burndown + Rlog  
4. Overdue → Unassigned → Stalled → Risk / DQ…  
5. Phân tích sâu → Chiều PM → Admin  

Nút **↺ Mặc định** áp `DEFAULT_SECTION_DOM_ORDER` (không cần F5). Nếu đã lưu `section_order.json` cũ → phải reset một lần.

Chi tiết từng section → [FEATURE_CATALOG.md](FEATURE_CATALOG.md).

---

## 6. Các “chiều” dữ liệu ngoài Function List

| Chiều | Nguồn | Lưu | UI / Export |
|-------|--------|-----|-------------|
| Function List | Excel / API sync | snapshots + current | Toàn dashboard |
| **Chiều PM** | KeHoachDuAn.xlsx + Weekly.pptx | `pm/plan.json`, `weekly.json` | Section Chiều PM; MoM sheet PM Lịch trình |
| **Mẫu FL re-import** | Upload template | `fl_export_schema.json` | Xuất FL chỉnh sửa (tô màu) |
| Capacity PIC | Settings | `capacity.json` | Capacity load |
| PIC Overload | Aggregate mọi project | settings thresholds | Cross-project |

---

## 7. Export — ma trận nhanh

| Nút / API | Đầu ra |
|-----------|--------|
| Chart 📥 | Tong_hop + Chi_tiet (+ Theo_nhom nếu task_type) |
| Xuất MoM tuần | Cover, Master, Gantt, MoM_Wxx, Risk Analysis, PM Dashboard, PM Lịch trình |
| Xuất FL chỉnh sửa | 1 sheet Function List — vàng PIC/Status, xanh date-chain; **không** sheet hướng dẫn |
| Forecast Gantt / Manpower | Excel riêng |
| PIC Overload | Summary + detail (+ optional FL) |
| Chiều PM | Workbook lịch trình / WBS / weekly |
| PDF | Client html2canvas + ghi chú chart |

---

## 8. Bảo mật (solo / LAN)

| Chế độ | Hành vi |
|--------|---------|
| Mặc định | Bind **`127.0.0.1`** |
| `IHRP_LAN=1` | Bind `0.0.0.0` + cảnh báo console |
| Admin mutation | Chỉ localhost (trừ override env) |
| Public API | Token SHA-256, scope, expiry, rate limit |

→ [LAN_DEPLOY_GUIDE.md](LAN_DEPLOY_GUIDE.md), [ARCHITECTURE.md § Auth](ARCHITECTURE.md).

---

## 9. Cách chạy & kiểm thử

```bat
start.bat
```

```bash
pytest -q
```

Mở `http://127.0.0.1:5000` → chọn project → upload/sync.

---

## 10. File liên quan tiếp theo

- **Rule nghiệp vụ đầy đủ:** [BUSINESS_LOGIC.md](BUSINESS_LOGIC.md)  
- **Catalog feature:** [FEATURE_CATALOG.md](FEATURE_CATALOG.md)  
- **Kiến trúc kỹ thuật:** [ARCHITECTURE.md](ARCHITECTURE.md)  
- **Schema parse:** [DATA_MODEL.md](DATA_MODEL.md)  
- **Chiều PM:** [PM_DIMENSION_GUIDE.md](PM_DIMENSION_GUIDE.md)  
- **Integrations / Public / Archive / Help:** xem [README.md](README.md)
