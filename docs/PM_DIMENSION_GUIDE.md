# Chiều PM — Kế hoạch dự án + Weekly Report

> Cập nhật nhỏ: **2026-08-01**. Disk janitor có thể xóa PPTX `*weekly*` trùng khi đã có `pm/weekly.pptx` (xem [ARCHIVE_GUIDE.md](ARCHIVE_GUIDE.md) § Disk janitor).

Import **2 loại file PM** vào từng project (không thay Function List):

| Loại | Định dạng | Ví dụ |
|------|-----------|--------|
| Kế hoạch dự án | `.xlsx` | `*_PM_KeHoachDuAn_*.xlsx` |
| Báo cáo tuần | `.pptx` | `*_PM_Weekly_Report_*.pptx` |

## Cách dùng trên UI

1. Chọn project → mở section **「Chiều PM」** (sidebar).
2. **Kế hoạch (.xlsx)** → app đề xuất ánh xạ sheet (Gantt / Lịch trình / Deliverable / Đội FPT / Đội KH) → chỉnh nếu cần → **Chấp nhận & lưu**.
3. **Weekly (.pptx)** → xem tóm tắt slides → **Parse & lưu**.
4. **Xuất chiều PM** → Excel tổng hợp (WBS, lịch trình, deliverable, đội, weekly done/next/risk, FL links nếu có).

Xuất **MoM tuần** (nếu đã import kế hoạch) sẽ thêm sheet `PM Lịch trình` từ KeHoachDuAn — không ghi đè Master plan từ Function List.

## Lưu trữ

```
uploads/projects/<slug>/pm/
  plan.json + plan.xlsx
  weekly.json + weekly.pptx
  mapping.json
```

**Auto-hydrate:** Nếu có `plan.xlsx` / `weekly.pptx` (hoặc file tên `*KeHoachDuAn*.xlsx` / `*Weekly*.pptx`) trong `pm/` nhưng chưa có JSON → `GET /api/projects/<slug>/pm` sẽ tự parse + ghi `plan.json` / `weekly.json` (mapping auto-propose).

## API

```
GET  /api/projects/<slug>/pm
POST /api/projects/<slug>/pm/plan/preview    # multipart file
POST /api/projects/<slug>/pm/plan/confirm    # {tmp_id, sheet_mapping, filename}
POST /api/projects/<slug>/pm/weekly/preview
POST /api/projects/<slug>/pm/weekly/confirm  # {tmp_id, filename}
GET  /api/projects/<slug>/pm/export
```

## Parse — khối chính

**KeHoachDuAn:** Gantt WBS (tên milestone + trục tuần), Lịch trình UAT/Golive (ngày + PIC FPT/KH), Sản phẩm bàn giao, Đội FPT / Đội KH. Thanh Gantt dạng shape → không lấy được week fill; ngày chi tiết lấy từ sheet lịch trình.

**Weekly PPT:** cover (kỳ báo cáo), bảng done tuần này, bảng tuần tới, issues/risk (text hoặc N/A). Không pixel-perfect slide layout.

## Join Function List (optional)

Khi project đã có FL: khớp **module / phase / PIC** xuất hiện trong tên công việc hoặc PIC lịch trình → hiện ở bảng «Liên kết Function List» và sheet `FL Links` khi xuất.
