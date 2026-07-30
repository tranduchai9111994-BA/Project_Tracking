# Registry API Integrations — Hướng dẫn cấu hình (T30)

Tính năng "🔌 API Registry + Đồng bộ dữ liệu" cho phép PM/BA cấu hình 1 lần rồi
sau đó chỉ cần bấm 1 nút để tự động:

1. Đăng nhập vào web app nguồn (VD iHRP production).
2. Tải file Excel Function List về.
3. Parse và tạo snapshot mới trong project.

Không cần thao tác thủ công export → save → upload nữa.

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
2. Tab **Thêm mới** → điền form:

| Field | Ví dụ | Ghi chú |
|-------|-------|---------|
| Tên | `iHRP Production` | Chỉ để hiển thị |
| Base URL | `https://ihrp.company.com` | Không có trailing slash, phải là http/https |
| Auth method | `form_login` | MVP chỉ hỗ trợ form login. Các option khác đang phát triển. |
| Login path | `/login` | Path GET/POST form login |
| Username field | `username` | Tên attribute `name=""` của input trong form |
| Password field | `password` | Tên attribute `name=""` của input trong form |
| Credential env | `IHRP_PROD` | Prefix của biến `.env` (viết HOA) |

3. Thêm ít nhất 1 endpoint:

| Field | Ví dụ | Ghi chú |
|-------|-------|---------|
| Tên endpoint | `Function List Export` | Chỉ để hiển thị |
| Path | `/api/functions/export` | Prefix `base_url`. Có thể dùng absolute URL. |
| HTTP method | `GET` | `GET` (thường dùng cho download) hoặc `POST` |
| Params | `{"module":"all"}` | JSON object, thành query string cho GET hoặc form body cho POST |
| Response type | `excel` | MVP chỉ excel. Reserve: json/csv (chưa support) |
| Target action | `snapshot` | `snapshot` = chỉ thêm snapshot (KHÔNG đổi current.xlsx). `replace` = cũng copy đè current.xlsx để dashboard load ngay dữ liệu mới. `append` giống snapshot. |

4. Bấm **💾 Lưu** — integration được tạo với `id` random.
5. Quay lại tab **Danh sách** → bấm `🔍 Test` để verify login → nếu OK
   status badge sẽ xanh.

---

## 3. Sync 1 endpoint

**Cách 1 — Trong modal:**
- Tab Danh sách → chọn endpoint từ dropdown ở cột "Hành động" → bấm `🔄`.

**Cách 2 — Dropdown quick trong header (tiện hơn):**
- Bấm `🔄 Đồng bộ ▾` bên phải nút `🔌 API Registry` → chọn endpoint bất kỳ
  → sync ngay.

Sau khi sync ok, dashboard tự động refresh dữ liệu mới. Snapshot được lưu vào
`uploads/projects/<slug>/snapshots/YYYY-MM-DD_functionlist.xlsx`.

---

## 4. Reverse-engineer form login (nếu chưa biết login_path / field name)

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

## 5. Troubleshooting

| Triệu chứng | Nguyên nhân | Cách fix |
|-------------|-------------|----------|
| `Thiếu biến môi trường: X_USERNAME` | Chưa set trong `.env` hoặc prefix sai | Kiểm tra chính tả prefix trong UI vs `.env` |
| `HTTP 401 / 403` sau login | Sai user/pass, hoặc account bị lock | Login thử thủ công web trước |
| `Server trả về trang login sau khi POST` | Có thể do CSRF hoặc redirect logic đặc biệt | Verify field name qua F12 Network |
| `Response không phải Excel` | Endpoint trả HTML (error page) hoặc JSON | Kiểm tra path/params + quyền tài khoản |
| `Parse file lỗi` | File tải về không đúng cấu trúc Function List | Verify bằng cách xuất thủ công trước |
| `Không kết nối được` | Firewall/VPN | Ping thử `base_url` từ terminal |

---

## 6. Roadmap (chưa support ở MVP)

- `basic_auth` — HTTP Basic Auth với `Authorization: Basic ...`.
- `bearer_token` — API token cố định.
- `api_key` — Query param hoặc header key riêng.
- `response_type = json` — Parse JSON → convert sang function list.
- `response_type = csv` — Parse CSV.
- OAuth 2.0 / MFA — chưa có kế hoạch (complexity cao cho use case nội bộ).

Feedback + feature request: liên hệ dev team.
