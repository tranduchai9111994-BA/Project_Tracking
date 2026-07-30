# iHRP Task Daily — Cấu hình API Sync

Hướng dẫn nhanh cho project **MPHG** (đã sẵn sàng, chỉ cần refresh trình duyệt).

## Trạng thái hiện tại

- **API**: `https://ihotel.fis.vn/ihrp-taskdaily/api/external/functions`
- **Auth**: `X-API-Key` header
- **Query bắt buộc**: `?project=<Mã dự án>` (VD `MPHG_IHRP_2025_PM`)
  - Thiếu / rỗng → HTTP **400** (`Thiếu tham số bắt buộc: project …`)
  - Mã sai → HTTP **200**, `data: []`, `count: 0`
  - Mã đúng → HTTP **200**, ~387 chức năng, 8 module (APP/ESS/HR/PIT/PR/SI/SYS/TMS)
- **Rate limit**: 120 request / 15 phút

### Config đã lưu
- `uploads/projects/mphg/integrations.json` — config integration
  - `params.project` = `MPHG_IHRP_2025_PM` (preview / project-codes / sync)
  - `project_code_field` = `project`, map → slug `mphg`
- `.env` (root) — chứa `IHRPTASKDAILY_KEY`
- Snapshot `2026-07-30_functionlist.xlsx` — data mới nhất đã kéo về

## Cách test nhanh

### Option A — Trong app (recommended)
1. Mở app (F5 refresh trang) → chọn project **MPHG**.
2. Bấm **⚙️ Cài đặt** → tab **🔌 API Registry**.
3. Thấy integration **"iHRP Task Daily (ihotel.fis.vn)"**.
4. Bấm **▶️ Đồng bộ** → modal chọn mã → tick `MPHG_IHRP_2025_PM` → map `mphg` → Đồng bộ.
5. App gọi API với `?project=<mã đã chọn>` (không tải full dump rồi filter client).
6. Kết quả: snapshot mới + dashboard cập nhật.

### Option B — Command line (khi debug)
```powershell
# Key lấy từ .env (IHRPTASKDAILY_KEY) — không hardcode
$key = (Get-Content .env | Where-Object { $_ -match '^IHRPTASKDAILY_KEY=' }) -replace '^IHRPTASKDAILY_KEY=',''
curl.exe -H "X-API-Key: $key" -k `
  "https://ihotel.fis.vn/ihrp-taskdaily/api/external/functions?project=MPHG_IHRP_2025_PM" `
  | ConvertFrom-Json | Select-Object count, project

# `-k` để bỏ qua SSL verify (cert của FIS chưa có trong certifi bundle)
```

### Option C — Python
```python
import os, requests, urllib3
urllib3.disable_warnings()
r = requests.get(
    "https://ihotel.fis.vn/ihrp-taskdaily/api/external/functions",
    params={"project": "MPHG_IHRP_2025_PM"},
    headers={"X-API-Key": os.environ["IHRPTASKDAILY_KEY"]},
    verify=False, timeout=30,
)
print(r.status_code, r.json()["count"])  # → 200, 387
```

## Ghi chú kỹ thuật

### SSL verify
- Server `ihotel.fis.vn` dùng certificate do FIS Root CA cấp — **không có** trong Python certifi bundle mặc định.
- Config đã set `auth.verify_ssl: false` để bỏ qua verify.
- Về lâu dài: (a) yêu cầu vendor đổi sang Let's Encrypt / DigiCert; hoặc (b) tự thêm CA FIS vào `%LOCALAPPDATA%\Python\certifi\cacert.pem`.

### `?project=` — bắt buộc từ phía vendor
Trước đây API trả full dump (~387 records) không cần query. Hiện tại **bắt buộc** `project`.

| Lợi ích | Impact app |
|---------|------------|
| Server-side filter — payload nhỏ hơn khi multi-tenant | Endpoint **phải** có `params.project` (hoặc chọn mã trong modal sync) |
| Modal Đồng bộ vẫn dùng `project_code_field` + map | Khi chọn 1 mã → request gắn `?project=<mã>`; nhiều mã → fetch lần lượt |
| Preview JSON / project-codes | Dùng `params.project` đã lưu; thiếu → HTTP 400 |

### Field mapping (JSON → iHRP columns)

65 Meta (18 cột) | Stages |
|---------------|--------|
| `functionCode` → Mã CN, `name`, `module`, `system`, `fid`, `process`, `requirementId` | 7 phase × 6 attr (+ Golive 5) qua `stages.*` |
| `project` → **Mã dự án** (VD `MPHG_IHRP_2025_PM`) | Analysis/Dev/Config Local/UAT/Document/Config Prod/UAT/Golive |
| `fitGap`, `phase`, `priority`, `complexity`, … | |

### Phân phối đa project (Mã dự án → folder local)

| Field | Ý nghĩa | Ví dụ MPHG |
|-------|---------|------------|
| `params.project` | Query API bắt buộc | `MPHG_IHRP_2025_PM` |
| `project_code_field` | JSON path chứa mã dự án | `project` |
| `project_code_map` | Map mã nguồn → slug local | `{"MPHG_IHRP_2025_PM": "mphg"}` |
| `project_code_filter` | (tuỳ chọn) chỉ giữ 1 mã | `MPHG_IHRP_2025_PM` |

**Hướng dẫn map MPHG:**

1. Mở project có integration Task Daily → **🔌 API Registry** → edit endpoint.
2. **Params** JSON: `{"project": "MPHG_IHRP_2025_PM"}` (bắt buộc để preview/project-codes chạy).
3. Field Mapping: `"Mã dự án": "project"`.
4. Panel **📁 Phân phối theo Mã dự án**: cột/JSON path = `project`.
5. Lưu → **Đồng bộ** → modal liệt kê mã → tick + chọn project local.
6. Map đã chọn được lưu (`project_code_map`) để lần sau prefill.

**Lưu ý:** mã nguồn thực tế là `MPHG_IHRP_2025_PM` (không phải `MPHG` ngắn).

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
