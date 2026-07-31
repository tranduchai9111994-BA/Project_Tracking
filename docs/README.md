# iHRP Function List Tracker — Docs

Dashboard local cho PM/BA triển khai **iHRP / HRIS**: upload hoặc sync Function List Excel → auto-detect cột → metrics đa chiều → export / Public API / LAN share.

## Cách chạy

```
start.bat          # Windows
./start.sh         # macOS/Linux
```

Mở `http://127.0.0.1:5000` (mặc định bind localhost). Credential: copy `.env.example` → `.env`.

---

## Đọc theo lớp (khuyến nghị)

| Lớp | File | Nội dung |
|-----|------|----------|
| **1. Tổng quan** | **[SYSTEM_OVERVIEW.md](SYSTEM_OVERVIEW.md)** | Big picture, data flow, nhóm dashboard, export matrix |
| **2. Logic nghiệp vụ** | **[BUSINESS_LOGIC.md](BUSINESS_LOGIC.md)** | Overdue, Unassigned, Stalled, DQ, Rlog, Forecast, FL re-import… |
| **3. Catalog feature** | **[FEATURE_CATALOG.md](FEATURE_CATALOG.md)** | Map section ↔ API ↔ module code |
| 4. Kiến trúc kỹ thuật | [ARCHITECTURE.md](ARCHITECTURE.md) | Stack, storage, security, module map, API surface |
| 5. Data schema | [DATA_MODEL.md](DATA_MODEL.md) | ParsedData + JSON stores |
| 6. Spec UI chi tiết | [DASHBOARD_SPEC.md](DASHBOARD_SPEC.md) | Từng chart / default section order |

---

## Guides chuyên đề

| File | Khi nào đọc |
|------|-------------|
| [INTEGRATIONS_GUIDE.md](INTEGRATIONS_GUIDE.md) | Registry API, auth, smart mapping, verify_ssl |
| [IHRP_TASKDAILY_API_SETUP.md](IHRP_TASKDAILY_API_SETUP.md) | Ví dụ sync iHRP Task Daily |
| [PUBLIC_API_GUIDE.md](PUBLIC_API_GUIDE.md) | REST + iframe + PNG + token |
| [LAN_DEPLOY_GUIDE.md](LAN_DEPLOY_GUIDE.md) | LAN, firewall, bind localhost |
| [ARCHIVE_GUIDE.md](ARCHIVE_GUIDE.md) | Archive / restore snapshot |
| [PM_DIMENSION_GUIDE.md](PM_DIMENSION_GUIDE.md) | KeHoachDuAn + Weekly PPT |
| [HELP_CONTENT_GUIDE.md](HELP_CONTENT_GUIDE.md) | Thêm topic help |
| [BUGS_TODO.md](BUGS_TODO.md) | Done / backlog |
| [UPGRADE_V2.md](UPGRADE_V2.md) / [UPGRADE_MULTIPROJECT.md](UPGRADE_MULTIPROJECT.md) | Historical |

---

## Feature highlights (tóm tắt)

- Multi-project + sync API + Column Mapping Wizard  
- Tracking: tiến độ tổng thể **trước**, vấn đề/trễ **sau**  
- Forecast: UAT/Golive theo tháng · **Manpower** MH/MD/MM + tuyển · PIC Overload đa dự án  
- Chiều PM + MoM tuần (Risk Analysis) + FL re-import tô màu  
- Export chart Tong_hop/Chi_tiet · nhóm sidebar VI/EN  
- Public API · LAN · Archive · Help unified  

Chi tiết → bắt đầu từ [SYSTEM_OVERVIEW.md](SYSTEM_OVERVIEW.md).

---

## Development

```bash
pytest -q
```
