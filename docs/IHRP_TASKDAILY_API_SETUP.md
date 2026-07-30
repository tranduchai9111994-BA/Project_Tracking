# iHRP Task Daily — Cấu hình API Sync

Hướng dẫn nhanh cho project **MPHG** (đã sẵn sàng, chỉ cần refresh trình duyệt).

## Trạng thái hiện tại

- **API**: `https://ihotel.fis.vn/ihrp-taskdaily/api/external/functions`
- **Auth**: `X-API-Key` header
- **Response**: JSON 522 KB, 387 chức năng, 8 module (APP/ESS/HR/PIT/PR/SI/SYS/TMS)
- **Rate limit**: 120 request / 15 phút

### Config đã lưu
- `uploads/projects/mphg/integrations.json` — config integration
- `.env` (root) — chứa `IHRPTASKDAILY_KEY`
- Snapshot `2026-07-30_functionlist.xlsx` — data mới nhất đã kéo về

## Cách test nhanh

### Option A — Trong app (recommended)
1. Mở app (F5 refresh trang) → chọn project **MPHG**.
2. Bấm **⚙️ Cài đặt** → tab **🔌 API Registry**.
3. Thấy integration **"iHRP Task Daily (ihotel.fis.vn)"** với status **✓ Đã sync 2026-07-30**.
4. Bấm **▶️ Đồng bộ** để kéo dữ liệu mới nhất từ vendor.
5. Kết quả: snapshot mới + tất cả dashboard tự cập nhật.

### Option B — Command line (khi debug)
```powershell
# Kiểm tra API còn sống
curl.exe -H "X-API-Key: 2a0d010b88a9023ef06cf2598a985e52e44a717a2a9c8361bd2ee2feb813598b" `
  -k https://ihotel.fis.vn/ihrp-taskdaily/api/external/functions | ConvertFrom-Json | Select-Object -ExpandProperty data | Measure-Object

# `-k` để bỏ qua SSL verify (cert của FIS chưa có trong certifi bundle)
```

### Option C — Python
```python
import requests, urllib3
urllib3.disable_warnings()
r = requests.get(
    "https://ihotel.fis.vn/ihrp-taskdaily/api/external/functions",
    headers={"X-API-Key": os.environ["IHRPTASKDAILY_KEY"]},
    verify=False, timeout=30,
)
print(len(r.json()["data"]))  # → 387
```

## Ghi chú kỹ thuật

### SSL verify
- Server `ihotel.fis.vn` dùng certificate do FIS Root CA cấp — **không có** trong Python certifi bundle mặc định.
- Config đã set `auth.verify_ssl: false` để bỏ qua verify.
- Về lâu dài: (a) yêu cầu vendor đổi sang Let's Encrypt / DigiCert; hoặc (b) tự thêm CA FIS vào `%LOCALAPPDATA%\Python\certifi\cacert.pem`.

### Field mapping (JSON → iHRP columns)

65 cột được map từ JSON response, gồm:

**Meta (18 cột):**
- `functionCode` → Mã CN
- `name` → Tên chức năng
- `module`, `system`, `fid`, `process`, `requirementId`
- `project` → **Mã dự án** (JSON key thật: `project`, VD `MPHG_IHRP_2025_PM`)
- `fitGap` → FIT/GAP
- `phase` → Giai đoạn
- `priority`, `complexity`, `description`, `dependencies`, `riskBlocker`, `lastUpdatedDate`, `remark`, `id` → STT

**Stages (7 phase × 6 attr = 42 cột + Golive 5):**
- `stages.analysis.{startDate,endDate,status,estimateMh,pic,note}` → `Analysis - Start/End/Status/Estimate MH/PIC/Note`
- Tương tự cho `dev`, `configLocal`, `configUat`, `document`, `configProd`, `uat`
- `stages.golive.{plannedDate,actualDate,status,pic,note}` → `Golive - Planned/Actual/Status/PIC/Note`

### Phân phối đa project (Mã dự án → folder local)

Khi API trả nhiều mã dự án trong 1 response, cấu hình trên endpoint:

| Field | Ý nghĩa | Ví dụ MPHG |
|-------|---------|------------|
| `project_code_field` | JSON path (hoặc tên cột Excel) chứa mã dự án | `project` |
| `project_code_map` | Map mã nguồn → slug local | `{"MPHG_IHRP_2025_PM": "mphg"}` |
| `project_code_filter` | (tuỳ chọn) chỉ giữ 1 mã; nếu không có map → ghi vào project đang sync | `MPHG_IHRP_2025_PM` |

**Hướng dẫn map MPHG:**

1. Mở project bất kỳ có integration Task Daily → **🔌 API Registry** → edit endpoint.
2. Field Mapping: thêm `"Mã dự án": "project"` (đã có sẵn nếu dùng config mẫu).
3. Panel **📁 Phân phối theo Mã dự án**:
   - Cột/JSON path = `project`
   - (Tuỳ chọn) Thêm dòng map sẵn; hoặc để trống — modal Đồng bộ sẽ hỏi.
4. Lưu → **Đồng bộ** → modal liệt kê mã từ API → tick mã + chọn project local → **Đồng bộ các mục đã chọn**.
5. Map đã chọn được lưu lại (`project_code_map`) để lần sau prefill.
6. Không cấu hình `project_code_field` → behavior cũ (toàn bộ vào project đang mở, không hỏi modal).

**Lưu ý:** mã nguồn thực tế hiện tại là `MPHG_IHRP_2025_PM` (không phải `MPHG` ngắn). Kiểm tra bằng Auto-suggest hoặc sample record.

### Env variables (`.env` gốc project)
```
IHRPTASKDAILY_KEY=<key>
```

Nếu vendor gia hạn/đổi key → chỉ cần sửa file `.env`, không cần restart server (mỗi lần sync tự nạp `.env`).

### Log & audit
- Kết quả mỗi lần sync ghi vào `integrations.json` (`last_synced_at`, `last_sync_status`, `last_sync_message`).
- HTTP access log ghi vào `.project_store/access.log` (feature LAN — đã bật).
- Chi tiết warning parse Excel hiển thị trong toast + F12 console.

## Rollback (nếu cần xóa)
1. UI: **⚙️ Cài đặt** → **🔌 API Registry** → click `🗑️` bên cạnh integration.
2. Hoặc: xóa file `uploads/projects/mphg/integrations.json`.
3. Xóa `IHRPTASKDAILY_KEY=` trong `.env`.
