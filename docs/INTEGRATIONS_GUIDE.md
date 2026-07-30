# Registry API Integrations — Hướng dẫn cấu hình (T30 + T30b)

Tính năng "🔌 API Registry + Đồng bộ dữ liệu" cho phép PM/BA cấu hình 1 lần rồi
sau đó chỉ cần bấm 1 nút để tự động:

1. Xác thực với ứng dụng nguồn (form login / basic auth / bearer / API key).
2. Tải Excel HOẶC JSON về (JSON tự convert sang xlsx qua field mapping).
3. Parse và tạo snapshot mới trong project.

Không cần thao tác thủ công export → save → upload nữa.

**Auth methods hỗ trợ (T30b, tất cả first-class):**

| Method | Khi nào dùng | Env var đọc |
|--------|--------------|-------------|
| `form_login` | Web app có form HTML đăng nhập truyền thống (username/password) | `<PREFIX>_USERNAME`, `<PREFIX>_PASSWORD` |
| `basic_auth` | REST API dùng HTTP Basic (VD system dev tools nội bộ) | `<PREFIX>_USERNAME`, `<PREFIX>_PASSWORD` |
| `bearer_token` | REST API với JWT / OAuth PAT (VD API chính thức của team FIS) | `<PREFIX>_TOKEN` |
| `api_key` | REST API với `X-API-Key` header hoặc `?api_key=xxx` query | `<PREFIX>_KEY` |

**Response types hỗ trợ:**

| Type | Mô tả | Config bổ sung |
|------|-------|----------------|
| `excel` | Endpoint trả .xlsx/.xls trực tiếp | (không) |
| `json`  | Endpoint trả JSON — convert qua field mapping | `data_path` + `field_mapping` |
| `csv`   | (Reserve, chưa implement) | — |

---

## 1. Setup credentials (file `.env`)

**Tại sao dùng `.env`?** Vì username/password không nên nằm trong JSON của
project (JSON được backup/share/export .zip). Credential phải tách biệt.

### Bước 1: Copy template

```bash
# Từ thư mục gốc project
cp .env.example .env
```

`.env` đã có sẵn trong `.gitignore`, sẽ KHÔNG bị commit lên git.

### Bước 2: Điền credential

Mỗi integration trong app dùng 1 **prefix** (VD `IHRP_PROD`). Hệ thống tự
đọc 2 biến:

```
IHRP_PROD_USERNAME=your_username
IHRP_PROD_PASSWORD=your_password
```

Nếu bạn có nhiều môi trường (prod, UAT, staging), thêm nhiều prefix:

```env
IHRP_PROD_USERNAME=abc
IHRP_PROD_PASSWORD=xyz

IHRP_UAT_USERNAME=abc-uat
IHRP_UAT_PASSWORD=xyz-uat
```

**Rule tên prefix:** chỉ dùng `A-Z`, `0-9`, `_`. Hệ thống tự uppercase khi
resolve nên nhập chữ thường cũng OK.

Sau khi sửa `.env`, KHÔNG cần restart Flask — hệ thống đọc lại file mỗi lần
sync/test (biến `os.environ` process vẫn được ưu tiên nếu đã set).

---

## 2. Tạo integration trong UI

1. Mở dashboard → nhấn nút `🔌 API Registry` trong header.
2. Tab **Thêm mới** → điền form. Field hiển thị phụ thuộc **Auth method**:

### 2.1. Fields chung (mọi method)

| Field | Ví dụ | Ghi chú |
|-------|-------|---------|
| Tên | `iHRP Production` / `FIS REST API` | Chỉ để hiển thị |
| Base URL | `https://ihrp.company.com` | Không trailing slash, phải là http/https |
| Auth method | `form_login` / `basic_auth` / `bearer_token` / `api_key` | Cả 4 đều enabled — chọn theo API nguồn |

### 2.2. `form_login` — form HTML truyền thống

| Field | Ví dụ | Ghi chú |
|-------|-------|---------|
| Login path | `/login` | Path GET/POST form login |
| Username field name | `username` | Attribute `name=""` của input trong form |
| Password field name | `password` | Attribute `name=""` của input trong form |
| Prefix env (credential_env) | `IHRP_PROD` | Backend đọc `IHRP_PROD_USERNAME` + `IHRP_PROD_PASSWORD` |

### 2.3. `basic_auth` — HTTP Basic

| Field | Ví dụ | Ghi chú |
|-------|-------|---------|
| Prefix env (credential_env) | `FIS_UAT` | Backend đọc `FIS_UAT_USERNAME` + `FIS_UAT_PASSWORD`, tự encode base64 vào header `Authorization: Basic ...` |

### 2.4. `bearer_token` — REST API với JWT / PAT

| Field | Ví dụ | Ghi chú |
|-------|-------|---------|
| Prefix env (bearer_env) | `FIS_API` | Backend đọc `FIS_API_TOKEN` → gửi `Authorization: Bearer <token>` |

Dùng khi team FIS release API chính thức và cấp token dài hạn.

### 2.5. `api_key` — Header hoặc Query param

| Field | Ví dụ | Ghi chú |
|-------|-------|---------|
| Prefix env (apikey_env) | `FIS_API` | Backend đọc `FIS_API_KEY` |
| Header/param name | `X-API-Key` / `X-Api-Token` / `api_key` | Tuỳ convention của app source |
| Vị trí | `header` hoặc `query` | Chọn `query` nếu app yêu cầu `?api_key=xxx` |

### 2.6. Thêm ít nhất 1 endpoint

| Field | Ví dụ | Ghi chú |
|-------|-------|---------|
| Tên endpoint | `Function List Export` | Chỉ để hiển thị |
| Path | `/api/functions/export` hoặc `/v1/functions` | Prefix `base_url`. Có thể dùng absolute URL. |
| HTTP method | `GET` | `GET` (thường dùng cho download/list) hoặc `POST` |
| Response type | `excel` / `json` | Chọn theo format API trả về |
| Target action | `snapshot` / `replace` / `append` | `replace` = đè current.xlsx để dashboard load ngay |
| Params | `{"module":"all"}` | JSON object → query string cho GET hoặc form body cho POST |

Khi chọn **Response type = json** → hiện panel **🗺 Field Mapping** (xem mục 3).

3. Bấm **💾 Lưu** — integration được tạo với `id` random.
4. Quay lại tab **Danh sách** → bấm `🔍 Test` để verify auth → nếu OK
   status badge sẽ xanh.
   - Với `form_login`: test thực sự đăng nhập → verify creds đúng.
   - Với `basic_auth` / `bearer_token` / `api_key`: chỉ verify credential nạp
     được từ `.env` (không hit server, vì các method này không có "login" tách
     biệt). Muốn verify server chấp nhận creds → bấm Sync 1 endpoint.

---

## 3. Cấu hình JSON API response mapping

Khi API nguồn trả **JSON** thay vì Excel, hệ thống cần biết:
1. Cấu trúc JSON như thế nào (`data_path`).
2. Field nào map sang cột iHRP Tracker nào (`field_mapping`).

### 3.1. `data_path` — dot-notation trỏ đến list

Ví dụ response API:

```json
{
  "status": "success",
  "data": {
    "items": [
      { "code": "F001", "name": "Chức năng 1", ...},
      { "code": "F002", "name": "Chức năng 2", ...}
    ],
    "total": 2
  }
}
```

→ `data_path = "data.items"` để trích list.

Trường hợp response là **array top-level** (`[{...}, {...}]`) → để `data_path` **trống**.

Trường hợp lồng sâu hơn: `"result.functions.list"`, `"payload.data.rows"`…

### 3.2. `field_mapping` — JSON `{cột_iHRP: json_path}`

Value là dot-notation path trong 1 record. Ví dụ:

```json
{
  "Mã CN": "code",
  "Tên chức năng": "name",
  "Module": "module_code",
  "Priority": "priority",
  "FIT/GAP": "fit_gap",
  "Giai đoạn": "phase",
  "Analysis - Start": "phases.analysis.start",
  "Analysis - End": "phases.analysis.end",
  "Analysis - Status": "phases.analysis.status",
  "Analysis - PIC": "phases.analysis.pic",
  "Dev - Start": "phases.dev.start",
  "Dev - Status": "phases.dev.status"
}
```

Với record JSON:

```json
{
  "code": "F001",
  "name": "Đăng ký nhân viên",
  "module_code": "HR",
  "priority": "Must-have",
  "fit_gap": "FIT",
  "phase": "P1",
  "phases": {
    "analysis": {
      "start": "2026-01-01",
      "end": "2026-01-05",
      "status": "Closed",
      "pic": "SonHN6"
    },
    "dev": { "start": "2026-01-06", "status": "In-progress" }
  }
}
```

→ Excel sinh ra sẽ có row:

| Mã CN | Tên chức năng | Module | Priority | FIT/GAP | Giai đoạn | Analysis - Start | ... |
|-------|---------------|--------|----------|---------|-----------|------------------|-----|
| F001 | Đăng ký nhân viên | HR | Must-have | FIT | P1 | 2026-01-01 | ... |

**Quy tắc quan trọng:**
- Tên cột iHRP (key) phải theo format phase group đã biết (VD `"Analysis - Start"`,
  `"Dev - PIC"`) để parser auto-detect được phase Analysis, Dev với 4 attribute
  Start/End/Status/PIC. Nếu tự đặt tên khác → parser vẫn giữ cột nhưng không
  hiểu là phase.
- Nếu value trong record là `null` → cell Excel để trống → parser sẽ hiểu là
  "chưa có date" (không tính overdue).
- Nếu key JSON không tồn tại (dot-path sai) → cell cũng để trống, không lỗi.
- Nếu value là dict/list (phức tạp) → tự stringify thành JSON string vào cell,
  giữ nguyên thông tin gốc (không lý tưởng để parse, nên tránh mapping vào
  cột nested).

### 3.3. Auto-suggest mapping

Trong editor endpoint, khi chọn **response_type = json**, panel Field Mapping
xuất hiện. Bấm **🔮 Auto-suggest từ endpoint**:

1. Backend gọi endpoint (dùng auth đã config) → nhận 1 sample record.
2. Trả về flat keys `{"dot.path": "sample_value"}` — VD `"phases.analysis.status": "Closed"`.
3. Frontend suggest mapping dựa trên **heuristic tên field**:
    - `code`, `ma_cn`, `function_code` → `Mã CN`
    - `name`, `function_name` → `Tên chức năng`
    - `phases.<phase>.<attr>` → `<Phase> - <Attr>` (VD `phases.dev.status` → `Dev - Status`)
    - `module_code`, `phan_he` → `Module`
    - `priority`, `complexity`, `fit_gap`, `phase` → `Priority`, `Complexity`, `FIT/GAP`, `Giai đoạn`
4. Kết quả được merge vào textarea → user **có thể sửa lại** trước khi Lưu.
   Mapping user tự thêm sẽ được giữ nguyên (không bị suggest ghi đè).

**Yêu cầu**: integration đã được **Lưu** ít nhất 1 lần → endpoint có `id`.
Nếu chưa lưu, nút Auto-suggest sẽ báo lỗi.

### 3.4. Full example — Bearer token + JSON API (mô phỏng REST API team FIS)

Integration:
```
name = "FIS REST API"
base_url = "https://fis-api.company.com"
auth.method = "bearer_token"
auth.bearer_env = "FIS_API"
```

`.env`:
```
FIS_API_TOKEN=eyJhbGciOiJIUzI1NiIs...
```

Endpoint:
```
name = "Functions Export"
path = "/v1/projects/ihrp/functions"
http_method = "GET"
response_type = "json"
target_action = "snapshot"
data_path = "data.items"
field_mapping = {
  "Mã CN": "code",
  "Tên chức năng": "name",
  "Module": "module_code",
  "Priority": "priority",
  "FIT/GAP": "fit_gap",
  "Analysis - Start": "phases.analysis.start",
  "Analysis - End": "phases.analysis.end",
  "Analysis - Status": "phases.analysis.status",
  "Analysis - PIC": "phases.analysis.pic",
  "Dev - Start": "phases.dev.start",
  "Dev - End": "phases.dev.end",
  "Dev - Status": "phases.dev.status",
  "Dev - PIC": "phases.dev.pic"
}
```

→ Bấm Sync → backend `GET https://fis-api.company.com/v1/projects/ihrp/functions`
với header `Authorization: Bearer eyJ...` → parse JSON → convert xlsx →
snapshot mới với đầy đủ phase Analysis + Dev.

---

## 4. Sync 1 endpoint

**Cách 1 — Trong modal:**
- Tab Danh sách → chọn endpoint từ dropdown ở cột "Hành động" → bấm `🔄`.

**Cách 2 — Dropdown quick trong header (tiện hơn):**
- Bấm `🔄 Đồng bộ ▾` bên phải nút `🔌 API Registry` → chọn endpoint bất kỳ
  → sync ngay.

Sau khi sync ok, dashboard tự động refresh dữ liệu mới. Snapshot được lưu vào
`uploads/projects/<slug>/snapshots/YYYY-MM-DD_functionlist.xlsx` (kể cả khi
response gốc là JSON — hệ thống convert sang xlsx trong bộ nhớ trước khi lưu).

---

## 5. Reverse-engineer form login (nếu chưa biết login_path / field name)

Nhiều web app dùng form login đơn giản nhưng đặt tên field khác nhau. Cách
tìm chính xác:

### Bước 1: Mở DevTools tab Network

- Chrome/Edge/Firefox: `F12` → tab **Network** → tick **Preserve log**.

### Bước 2: Login thủ công vào web app

- Điền username/password sai → bấm Đăng nhập → xem request.
- Filter tab Network chỉ hiện `Doc` hoặc `XHR`.

### Bước 3: Đọc request POST login

Click vào request đầu tiên POST tới server. Trong panel **Headers**:

```
Request URL: https://ihrp.company.com/auth/signin       ← đây là login_path
Request Method: POST
```

Trong panel **Payload** hoặc **Form Data**:

```
username: my_user           ← tên username field
password: my_pass           ← tên password field
csrf_token: abc123def456    ← nếu có CSRF, hệ thống tự parse
remember_me: 1              ← extra_fields, có thể bỏ qua nếu optional
```

→ Cấu hình vào integration:
- `login_path` = `/auth/signin`
- `username_field` = `username`
- `password_field` = `password`
- **Không cần** điền CSRF: backend tự parse HTML trang GET login trước.

### Bước 4: Xử lý CSRF

Nếu web app có CSRF, khi bạn xem HTML nguồn trang login sẽ thấy:

```html
<form method="POST" action="/login">
    <input type="hidden" name="csrf_token" value="abc123def456">
    <input name="username" placeholder="Tài khoản">
    <input name="password" type="password">
    <button>Đăng nhập</button>
</form>
```

Hệ thống scan tất cả `<input>` có tên nằm trong whitelist:
- `csrf_token`, `csrfmiddlewaretoken` (Django), `_csrf`, `authenticity_token`
  (Rails), `__requestverificationtoken` (ASP.NET), `_token` (Laravel).

Nếu web app dùng tên khác (VD `SecureToken`), hiện tại KHÔNG tự parse được —
mở issue cho dev thêm vào whitelist.

### Bước 5: Test URL download Excel

Trong DevTools Network, filter request khi bạn click nút "Export" trong web app:

- Tìm request có `Content-Type: application/vnd.openxmlformats-officedocument.spreadsheetml.sheet`
  hoặc URL kết thúc bằng `.xlsx`.
- Copy URL → tách phần path + query params:
  - URL: `https://ihrp.company.com/api/functions/export?module=HR&year=2026`
  - `path` = `/api/functions/export`
  - `params` = `{"module":"HR","year":"2026"}`

### Bước 6: Verify

Sau khi cấu hình xong:
1. Bấm `🔍 Test login` — nếu OK → creds/URL đúng.
2. Bấm `🔄 Sync` — nếu OK → toast báo số dòng đã import.
3. Nếu fail, đọc message trong toast/tooltip — thường là:
   - `Thiếu biến môi trường: IHRP_PROD_USERNAME` → sửa `.env`.
   - `HTTP 401 — sai username hoặc password` → kiểm tra credential.
   - `Response không phải Excel (Content-Type: text/html)` → sai path hoặc
     tài khoản không có quyền export.

---

## 6. Troubleshooting

| Triệu chứng | Nguyên nhân | Cách fix |
|-------------|-------------|----------|
| `Thiếu biến môi trường: X_USERNAME` | Chưa set trong `.env` hoặc prefix sai | Kiểm tra chính tả prefix trong UI vs `.env` |
| `Thiếu biến môi trường: X_TOKEN` | Auth = bearer_token nhưng chưa set `X_TOKEN=...` | Thêm vào `.env`, refresh page rồi thử lại |
| `Thiếu biến môi trường: X_KEY` | Auth = api_key nhưng chưa set `X_KEY=...` | Thêm vào `.env`, refresh page rồi thử lại |
| `HTTP 401 / 403` sau login | Sai creds, token hết hạn, account bị lock | Login thử thủ công web/API trước |
| `Server trả về trang login sau khi POST` | CSRF hoặc redirect logic đặc biệt (form_login) | Verify field name qua F12 Network |
| `Response không phải Excel` | Endpoint trả HTML (error page) hoặc JSON | Đổi response_type sang `json` HOẶC kiểm tra path/params |
| `Response không phải JSON hợp lệ` | Backend trả HTML/text nhưng UI chọn `json` | Đổi response_type hoặc kiểm tra endpoint đúng chưa |
| `Không trích được record nào từ JSON` | Sai `data_path` (dot-notation) | Bấm 🔮 Auto-suggest để xem structure thực |
| `Response JSON nhưng chưa cấu hình field_mapping` | Chọn `json` mà chưa map | Điền textarea Field Mapping — có thể dùng Auto-suggest |
| `Parse file lỗi` | File Excel không đúng cấu trúc, hoặc field_mapping tạo header sai | Verify bằng cách xuất thủ công / xem lại tên cột trong mapping |
| `Không kết nối được` | Firewall/VPN | Ping thử `base_url` từ terminal |

---

## 7. Roadmap (còn lại chưa support)

- `response_type = csv` — Parse CSV (reserve, priority thấp).
- OAuth 2.0 flow đầy đủ (authorize/refresh) — chưa có kế hoạch. Bearer PAT tĩnh
  đã đủ cho case nội bộ.
- MFA — chưa có kế hoạch (blocker: cần user tương tác OTP).
- Body-JSON cho POST endpoint (hiện dùng form-data). Nếu API yêu cầu POST + JSON
  body → gõ backdoor qua `endpoint.params` sẽ không hoạt động, cần mở rộng
  thêm `body_json` field.

Feedback + feature request: liên hệ dev team.
