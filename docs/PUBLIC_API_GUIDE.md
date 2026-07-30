# Public API Guide (T33)

> **Mục đích:** cho phép PM/BA/khách hàng nhúng biểu đồ hoặc lấy dữ liệu iHRP
> Tracker từ bên ngoài (Confluence, Word, email, portal riêng, dashboard 3rd-party)
> mà **không cần đăng nhập app chính**.

Có 3 kiểu tiêu thụ:

| Kiểu | Endpoint | Trả về | Dùng khi |
|------|----------|--------|----------|
| **REST** | `/public/api/v1/projects/<slug>/...` | JSON | Backend script / Power BI / Excel Power Query / bất cứ tool nào gọi HTTP được |
| **iframe** | `/embed/<slug>/<chart_id>?token=...` | HTML chart (Chart.js) | Confluence / Notion / trang web / Wordpress |
| **PNG snapshot** | `/public/api/v1/projects/<slug>/charts/<chart_id>/image?...` | Ảnh PNG | Word document / email / báo cáo tĩnh |

> Task 2A (bản này) mới ship **REST** + **Token CRUD**. Iframe + PNG snapshot
> ship trong Task 2B (Playwright), tab UI ship trong Task 2C.

---

## 1. Cấp phát token

### Bước 1 — Tạo token
UI (Task 2C) sẽ có form; hiện dev có thể dùng `curl`:

```bash
curl -X POST http://localhost:5000/api/projects/<slug>/public-tokens \
  -H "Content-Type: application/json" \
  -d '{"name": "Confluence embed", "scope": ["summary", "module-overview"]}'
```

Response:

```json
{
  "token": "pub_a1b2c3d4e5f60718293a4b5c6d7e8f9012345678",
  "entry": {
    "id": "abc123...",
    "name": "Confluence embed",
    "token_prefix": "pub_a1b2c3d4",
    "scope": ["module-overview", "summary"],
    "created_at": "2026-07-30T03:15:22Z",
    "last_used_at": null,
    "revoked": false
  },
  "warning": "Token này chỉ hiển thị 1 lần — copy ngay và lưu chỗ an toàn."
}
```

> ⚠️ **QUAN TRỌNG**: field `token` chỉ trả **1 lần** — server chỉ lưu SHA-256
> hash. Copy ngay vào password manager. Nếu quên → revoke + tạo mới.

### Bước 2 — Lưu token vào bên tiêu thụ
- Confluence / Notion: paste vào iframe URL (`?token=pub_...`).
- Backend script: lưu trong biến môi trường `IHRP_PUBLIC_TOKEN` (không commit).

### Bước 3 — Quản lý token
```bash
# List (không expose full token/hash, chỉ prefix)
curl http://localhost:5000/api/projects/<slug>/public-tokens

# Revoke
curl -X DELETE http://localhost:5000/api/projects/<slug>/public-tokens/<token_id>
```

Token bị revoke sẽ luôn trả `401 Unauthorized` — entry vẫn giữ để audit trail.

---

## 2. Scope (phân quyền chi tiết)

Token gắn với 1 danh sách **scope** — control chart_id / endpoint mà token được
phép truy cập. Không cho phép "one-size-fits-all" — theo nguyên tắc least
privilege.

| Scope | Endpoint được phép |
|-------|--------------------|
| `*` | Tất cả (wildcard — chỉ nên cấp cho admin partner đáng tin cậy) |
| `summary` | `GET /public/api/v1/projects/<slug>/summary` |
| `functions` | `GET /public/api/v1/projects/<slug>/functions?page=&size=` |
| `module-overview` | `GET /public/api/v1/projects/<slug>/charts/module-overview` |
| `phase-matrix` | `GET .../charts/phase-matrix` |
| `phase-stacked` | Phase progress stacked bar |
| `progress-task-type` | Progress theo Task type |
| `pic-workload` | PIC workload |
| `priority` | Priority breakdown |
| `complexity` | Complexity breakdown |
| `fit-gap` | FIT/GAP analysis |
| `giai-doan` | Progress theo Giai đoạn |
| `overdue` | Danh sách trễ deadline |
| `unassigned` | Task chưa có PIC |
| `stalled` | Task đình trệ |
| `risk` | Risk scores |
| `effort-heatmap` | Effort heatmap |
| `process` | Process analysis |

- Truyền scope dưới dạng list JSON: `"scope": ["summary", "overdue"]`.
- Hoặc CSV string: `"scope": "summary,overdue,module-overview"`.
- Underscore (`module_overview`) được tự động normalize thành dash
  (`module-overview`) — copy từ code không lo case.

---

## 3. Xác thực

Gửi token theo 1 trong 2 cách:

**Header (khuyến nghị cho backend script):**
```
X-API-Key: pub_a1b2c3d4e5f60718293a4b5c6d7e8f9012345678
```

**Query param (bắt buộc cho iframe / img):**
```
?token=pub_a1b2c3d4e5f60718293a4b5c6d7e8f9012345678
```

Server verify:
1. Token đúng format (bắt đầu `pub_`).
2. SHA-256 hash khớp với 1 entry trong `.project_store/<slug>/public_tokens.json`.
3. `revoked = false`.
4. Scope required nằm trong `scope[]` hoặc token có `*`.

Sai mỗi bước → HTTP status tương ứng:
- `401 Unauthorized`: sai/thiếu/revoked token.
- `403 Forbidden`: token OK nhưng thiếu scope cần thiết.
- `429 Too Many Requests`: vượt rate limit (kèm header `Retry-After`).

---

## 4. Rate limit

- **60 request / 60 giây / token** (sliding window).
- Vượt: HTTP 429 kèm header `Retry-After: <seconds>`.
- Giữ trong bộ nhớ Flask process — reset khi restart. Production đa worker
  nên chuyển sang Redis (chưa impl trong bản v1).

---

## 5. Endpoints

### 5.1 `GET /public/api/v1/projects/<slug>/summary`
Scope: `summary`.

Response:
```json
{
  "project": {"slug": "mphg", "name": "Minh Phú HRM"},
  "summary": {
    "total_functions": 285,
    "closed": 179,
    "in_progress": 82,
    "overdue": 47,
    "overall_progress_pct": 62.8,
    "...": "..."
  },
  "generated_at": "2026-07-30T03:20:00Z"
}
```

### 5.2 `GET /public/api/v1/projects/<slug>/charts/<chart_id>`
Scope: `<chart_id>` (VD `module-overview` yêu cầu scope `module-overview`).

Response:
```json
{
  "chart_id": "module-overview",
  "data": { "...": "..." },
  "generated_at": "2026-07-30T03:20:00Z"
}
```

`data` shape khác nhau tùy chart — xem `docs/DATA_MODEL.md` cho detail.

### 5.3 `GET /public/api/v1/projects/<slug>/functions?page=1&size=50`
Scope: `functions`. Max size = 200.

Response:
```json
{
  "items": [
    {
      "ma_cn": "HR.01",
      "ten_cn": "Quản lý nhân sự",
      "module": "HR",
      "process": "HR.BP.01",
      "priority": "Must-have",
      "complexity": "Medium",
      "fit_gap": "FIT",
      "giai_doan": "1",
      "phase_stats": {"total": 4, "closed": 3, "open": 0}
    }
  ],
  "page": 1,
  "size": 50,
  "total": 285,
  "total_pages": 6
}
```

---

## 6. CORS

Public API cho phép mọi origin (mission: embed vào bất kỳ đâu):
- `Access-Control-Allow-Origin: *`
- `Access-Control-Allow-Methods: GET, OPTIONS`
- `Access-Control-Allow-Headers: X-API-Key, Content-Type`
- **Không** cho phép cookies (`credentials: false`).

---

## 7. Security best practices

1. **Scope tối thiểu** — cấp scope hẹp nhất có thể. Ưu tiên chart_id cụ thể
   hơn `*`.
2. **Rotate định kỳ** — revoke + tạo mới mỗi quý, hoặc khi nghi ngờ lộ.
3. **Không hardcode token trong repo public** — dùng env var / secret store.
4. **Không expose token qua GET trong URL log** — ưu tiên header `X-API-Key`
   khi có thể (log server thường lưu URL nhưng bỏ header nhạy cảm).
5. **Revoke ngay khi partner dừng hợp tác** — endpoint DELETE là idempotent
   và giữ audit trail.
6. **Storage plaintext = KHÔNG** — server chỉ lưu SHA-256 hash; kể cả admin
   cũng không xem lại được token đã cấp (buộc phải tạo mới nếu quên).

---

## 8. Ví dụ nhanh — chuyển dữ liệu vào Power BI

```powershell
# PowerShell script — refresh dashboard hàng ngày
$token = $env:IHRP_PUBLIC_TOKEN
$url = "http://ihrp-tracker.company.local/public/api/v1/projects/mphg/charts/module-overview"
$resp = Invoke-RestMethod -Uri $url -Headers @{"X-API-Key" = $token}
$resp.data | ConvertTo-Json | Out-File -Encoding UTF8 "module_overview.json"
```

Sau đó Power BI Data Source → JSON File → point tới `module_overview.json`.

---

## 9. Troubleshooting

| Triệu chứng | Nguyên nhân | Cách khắc |
|-------------|-------------|-----------|
| HTTP 401 `Thiếu / sai format token` | Header/query chưa có, hoặc quên prefix `pub_` | Kiểm tra header `X-API-Key` |
| HTTP 401 `Token đã bị revoke` | Ai đó (kể cả bạn) đã DELETE token | Tạo token mới |
| HTTP 403 `Token không có quyền 'X'` | Scope thiếu `X` | Tạo token khác với scope rộng hơn hoặc thêm `*` |
| HTTP 429 `Retry-After: 60` | Client polling quá dày | Giảm tần suất hoặc cache local |
| HTTP 404 `Project chưa có data` | Project chưa upload lần nào | Upload Function List trước |
| iframe không hiện gì | Task 2B chưa ship / thiếu `?token=` | Chờ Task 2B hoặc dùng REST tạm thời |

---

## 10. iframe embed (Task 2B)

Nhúng chart trực tiếp vào Confluence / Notion / trang web:

```html
<iframe
  src="http://ihrp-tracker.company.local/embed/mphg/module-overview?token=pub_xxx"
  width="800" height="400"
  frameborder="0"></iframe>
```

- **URL pattern**: `/embed/<slug>/<chart_id>?token=pub_...&bg=transparent`
- **Query params**:
  - `token` (bắt buộc) — như REST.
  - `bg=transparent` (optional) — nền trong suốt để blend với UI host.
- **Chart hỗ trợ embed** (Task 2B v1): xem `analyzer/public_api.py::PUBLIC_SCOPES`
  — 15 loại (module-overview, phase-stacked, pic-workload, priority,
  complexity, fit-gap, giai-doan, overdue, unassigned, stalled, risk...).
  Các chart list-based (overdue/unassigned/stalled/risk) hiển thị table
  50 dòng đầu (dùng REST /functions cho full list).
- **Headers**:
  - `X-Frame-Options: ALLOWALL` — override reverse-proxy default block.
  - `Content-Security-Policy: frame-ancestors *` — nhúng vào bất kỳ site nào.
- **Auth flow**: server render HTML KHÔNG verify token — JS trong iframe gọi
  `/public/api/v1/.../charts/<id>` với `X-API-Key` để lấy data → verify.
  Token sai → iframe hiển "⚠️ Token không hợp lệ".

---

## 11. PNG snapshot (Task 2B)

Ảnh tĩnh cho Word / email / báo cáo PDF:

```html
<img src="http://ihrp-tracker.company.local/public/api/v1/projects/mphg/charts/module-overview/image?w=800&h=400&token=pub_xxx"
     alt="Module Overview" />
```

- **URL pattern**: `/public/api/v1/projects/<slug>/charts/<chart_id>/image?w=&h=&bg=&token=`
- **Query params**:
  - `token` (bắt buộc, scope `<chart_id>`).
  - `w` (default 800, min 200, max 1920).
  - `h` (default 400, min 150, max 1200).
  - `bg=transparent` (optional).
- **Caching**: file PNG lưu ở `.project_store/<slug>/public_cache/<chart>_<WxH>_<bg>.png`.
  TTL 5 phút — sau đó regenerate. Header:
  - `X-Cache: HIT` = serve từ disk (nhanh, ~ms).
  - `X-Cache: MISS` = mới generate (~2-5s, tuỳ Chart.js render).
  - `X-Cache-Age: <s>` = tuổi cache khi HIT.

### Cài Playwright

PNG endpoint dùng Playwright headless Chromium để render iframe → screenshot.
Nếu chưa cài → HTTP 503 với message hướng dẫn.

```bash
pip install playwright>=1.40.0
python -m playwright install chromium         # tải ~200MB browser binary
```

Sau đó restart Flask. Endpoint /image sẽ hoạt động ngay.

### Lỗi thường gặp

| Lỗi | Nguyên nhân |
|-----|-------------|
| 503 `Playwright chưa cài` | Chưa `pip install playwright && python -m playwright install chromium` |
| 500 `Playwright chụp ảnh lỗi: Timeout` | Iframe không set `data-chart-ready` — chart_id không hỗ trợ hoặc data rỗng |
| Ảnh trắng | Chart data empty → JS render error → screenshot lấy khung trống. Kiểm tra REST API cùng chart_id có data không |
| Chậm 10s+ mỗi request | Chưa cache — miss lần đầu. Sau 5 phút TTL, cùng request rất nhanh |

---

## 12. Settings tab "Public API" (Task 2C)

Không cần dùng `curl` — mở app → nút ⚙️ **Cài đặt** → cuộn xuống section
🌐 **Public API**:

- Bảng token đã tạo (Name / Prefix / Scope / Ngày tạo / Dùng cuối).
- Nút **➕ Tạo token mới**: nhập Name + tick scope (hoặc bấm 🌟 Wildcard `*`).
- Sau khi tạo, modal hiện token **1 lần** với:
  - Nút 📋 Copy token
  - 3 tab snippet copy-ready: **REST** (curl + PowerShell), **iframe**
    (HTML tag), **PNG** (img tag).
  - Chart selector cho iframe/PNG snippet.
- Nút 🔗 mỗi row: xem lại snippet cho token cũ (dùng placeholder
  `pub_YOUR_TOKEN` — thay bằng token bạn đã lưu).
- Nút 🚫 mỗi row: revoke token (idempotent, giữ audit trail).

Toàn bộ non-tech friendly — không cần vào terminal.

---

## 13. Roadmap

- ✅ **Task 2A** — REST API + token CRUD + rate limit.
- ✅ **Task 2B** — iframe embed + PNG snapshot (Playwright).
- ✅ **Task 2C** — Settings tab "Public API" với snippet copy UI.
- 💭 Redis-backed rate limit cho multi-worker.
- 💭 IP whitelist per-token.
- 💭 Signed URL (JWT) cho time-limited access.
- 💭 Token expiry date (tự động revoke sau N ngày).
