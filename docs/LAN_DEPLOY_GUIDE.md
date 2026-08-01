# LAN Deploy Guide — Chia sẻ dashboard trong công ty

> Kiến trúc tổng thể → [`ARCHITECTURE.md`](ARCHITECTURE.md) mục Auth & security.  
> Mục lục docs → [`README.md`](README.md).

**T34 Task 2** — App được thiết kế cho mô hình "1 máy chủ, nhiều máy view":
- Máy của bạn = server (chạy `start.bat`).
- Đồng nghiệp cùng LAN mở URL LAN → xem dashboard read-only.
- Máy bạn tắt = mọi người tự động offline (không cần server riêng).
- Bảo mật multi-layer: admin chỉ mở từ localhost, LAN chỉ được view + export.

---

## 1. Kiểm tra nhanh (5 phút setup)

### Bước 1 — Khởi động server (mặc định LOCAL-ONLY)

Chạy `start.bat`. **Mặc định bind `127.0.0.1`** — chỉ máy bạn truy cập được
(an toàn cho solo). Console:

```
============================================================
  Server: http://localhost:5000
  Bind: 127.0.0.1 (LOCAL-ONLY, mac dinh) — LAN khong truy cap.
  Mo LAN: set IHRP_LAN=1  (hoac IHRP_BIND_LOCAL_ONLY=0) roi chay lai.
============================================================
```

### Bước 1b — Mở LAN (khi cần chia sẻ trong công ty)

```bat
set IHRP_LAN=1
start.bat
```

(hoặc `set IHRP_BIND_LOCAL_ONLY=0`). Console sẽ in LAN URL + cảnh báo:

```
============================================================
  Server: http://localhost:5000
  Bind: 0.0.0.0 (LAN mode)
  LAN URL: http://192.168.1.5:5000  (đồng nghiệp cùng LAN dùng URL này)
  ADMIN MUTATIONS (upload, config) chỉ mở từ http://localhost:5000
  [CANH BAO] Dashboard GET mo tren LAN — KHONG dung WiFi cong cong.
============================================================
```

### Bước 2 — Cấu hình Firewall Windows (1 lần duy nhất, chỉ khi đã mở LAN)

Mặc định Windows Firewall block port 5000 từ máy khác. Chạy PowerShell
**as Administrator**:

```powershell
# Cho phép TCP port 5000 chỉ từ subnet nội bộ (192.168.0.0/16 + 10.0.0.0/8)
# → tránh mở ra internet.
netsh advfirewall firewall add rule ^
    name="iHRP Tracker LAN" ^
    dir=in action=allow protocol=TCP localport=5000 ^
    remoteip=192.168.0.0/16,10.0.0.0/8,172.16.0.0/12
```

Xoá rule khi không dùng nữa:

```powershell
netsh advfirewall firewall delete rule name="iHRP Tracker LAN"
```

### Bước 3 — Verify từ máy đồng nghiệp

Máy đồng nghiệp mở browser → `http://192.168.1.5:5000` (thay IP tương ứng).
Nếu:
- ✅ Thấy dashboard → xong.
- ❌ "Không truy cập được" → check firewall (bước 2) hoặc network subnet.

---

## 2. Kiến trúc bảo mật multi-layer

### Layer 1 — Bind interface

**Mặc định `127.0.0.1`** (solo-safe). App đọc ENV qua
`analyzer.lan_security.resolve_bind_host()`:

| ENV | Host |
|-----|------|
| (không set) | `127.0.0.1` |
| `IHRP_BIND_LOCAL_ONLY=1` | `127.0.0.1` (thắng cả `IHRP_LAN`) |
| `IHRP_BIND_LOCAL_ONLY=0` | `0.0.0.0` |
| `IHRP_LAN=1` | `0.0.0.0` |

Khi bind `0.0.0.0`, console in cảnh báo tiếng Việt: GET dashboard mở trên
LAN — không dùng WiFi công cộng.

### Layer 2 — Admin guard middleware (`@localhost_only`)

Mọi request **POST/PUT/DELETE** đến `/api/*` (trừ export routes) đều bị
`analyzer/lan_security.py::install_admin_guard()` chặn nếu `remote_addr`
không phải `127.0.0.1` / `::1`.

Response 403 với message rõ:
```json
{
  "error": "Admin endpoint chỉ truy cập từ máy chủ (localhost).",
  "detail": "Request POST /api/upload từ '192.168.1.10' bị từ chối. …",
  "hint": "Muốn cho phép 1 máy khác dùng admin? Set ENV IHRP_LAN_ADMIN_ALLOW=192.168.1.X trước khi khởi động.",
  "code": "LOCALHOST_ONLY"
}
```

**Endpoint được bảo vệ (chỉ localhost gọi được):**
- `POST /api/upload`, `/api/upload-preview`, `/api/upload-confirm`
- `POST /api/projects/<slug>/upload`
- `POST/PUT/DELETE /api/projects` — CRUD project
- `POST /api/projects/<slug>/restore`
- `POST /api/projects/import-package` (import zip)
- `PUT/POST /api/projects/<slug>/{integrations, custom-dashboard, saved-views, section-order, mapping-presets, public-tokens, digests, chart-notes, chart-config/visibility, phase-aliases, capacity, pic-roles, bookmarks/toggle}`
- `POST /api/projects/<slug>/upload-compare`
- `DELETE /api/snapshots/*`
- `DELETE /api/projects/<slug>/{public-tokens/<id>, snapshots/<date>, mapping-presets/<name>}`

**Endpoint LAN được phép (read-only, có body POST):**
- Tất cả `GET /api/*`
- `POST /api/*/export-*` (overdue/all-issues/chart/audit/sla/…) — chỉ tạo file rồi return
- `POST /api/drill-down/export`, `/api/projects/*/chart-aggregate`
- `POST /api/portfolio/compare[/export]`
- Public API `/public/*` (token-guarded, không cần admin)
- `/embed/*` (iframe, token-guarded)

### Layer 3 — Access log

Middleware `install_access_log(app, log_path)` ghi mọi request vào
`.project_store/access.log` với format JSON-lines:

```json
{"ts": "2026-07-30T10:15:30", "ip": "192.168.1.5", "method": "GET",
 "path": "/api/projects/default/dashboard", "status": 200,
 "duration_ms": 12, "is_localhost": false}
```

- **Rotate** tự động khi log > 10 MB → `access.log.1` (giữ 1 backup).
- **Xem trong app**: Settings modal → section 🌐 LAN → bảng "📜 Access log".
  Chỉ máy chủ (localhost) xem được. Read-only.

### Layer 4 — Public API token (đã có)

Nếu muốn share cho **bên thứ 3 ngoài LAN** (partner, khách hàng,
Confluence, email), dùng Public API token (`/public/api/v1/*`) — xem
`docs/PUBLIC_API_GUIDE.md`.

---

## 3. Environment variables

| Biến | Giá trị | Ý nghĩa |
|------|---------|---------|
| `IHRP_LAN` | `1` | **Mở LAN** — bind `0.0.0.0:5000` (đồng nghiệp cùng mạng xem được). |
| `IHRP_BIND_LOCAL_ONLY` | `1` (mặc định hành vi) / `0` | `1` → luôn `127.0.0.1`. `0` → mở LAN. Không set = localhost. |
| `IHRP_LAN_ADMIN_ALLOW` | `192.168.1.10,10.0.0.5` | Whitelist IP cụ thể được admin ngoài localhost. **Không dùng `*` / subnet.** Mặc định rỗng. |
| `IHRP_DISABLE_ADMIN_GUARD` | `1` | Tắt admin guard hoàn toàn. **NGUY HIỂM trên LAN — chỉ debug local.** Mặc định không set (guard BẬT). |
| `IHRP_DISABLE_ACCESS_LOG` | `1` | Tắt access log (tiết kiệm disk). |
| `IHRP_ACCESS_LOG` | absolute path | Custom path cho log (default `.project_store/access.log`). |

---

## 4. HTTPS optional (mkcert)

Nếu công ty yêu cầu HTTPS cho traffic nội bộ (VD compliance / policy):

```powershell
# Cài mkcert (1 lần)
choco install mkcert
mkcert -install

# Sinh cert cho hostname/IP máy chủ
mkcert 192.168.1.5 localhost 127.0.0.1

# → sinh 2 file: 192.168.1.5+2.pem + 192.168.1.5+2-key.pem
```

Sửa `app.py::app.run(...)` (khi đã `IHRP_LAN=1`) thêm `ssl_context`:

```python
# host vẫn do resolve_bind_host() quyết định (0.0.0.0 khi IHRP_LAN=1)
app.run(
    host=bind_host,
    port=5000,
    ssl_context=("192.168.1.5+2.pem", "192.168.1.5+2-key.pem"),
)
```

Máy client cần cài root CA của mkcert: `mkcert -CAROOT` → import file
`rootCA.pem` vào trust store của browser/OS.

---

## 5. Danh sách URL mẫu cho từng consumer

Sau khi setup, gửi các URL này cho từng nhóm dùng:

| Consumer | URL mẫu | Note |
|----------|---------|------|
| Bạn (admin) | `http://localhost:5000` | Full quyền — upload/config/manage |
| Đồng nghiệp cùng LAN | `http://192.168.1.5:5000` | Read-only + export Excel — không upload được |
| Confluence/Word nhúng | `<iframe src="http://192.168.1.5:5000/embed/mphg/module-overview?token=pub_xxx" width="800" height="400"></iframe>` | Cần Public API token |
| Email/Slack | `<img src="http://192.168.1.5:5000/public/api/v1/projects/mphg/charts/module-overview/image?w=800&h=400&token=pub_xxx">` | PNG snapshot |

---

## 6. Troubleshooting

### "Không truy cập được từ máy khác dù cùng LAN"

Check theo thứ tự:
1. Đã bật LAN chưa? Cần `set IHRP_LAN=1` (hoặc `IHRP_BIND_LOCAL_ONLY=0`) rồi restart — mặc định chỉ listen `127.0.0.1`.
2. `netstat -an | findstr :5000` — verify server đang LISTEN trên `0.0.0.0:5000` (không phải `127.0.0.1:5000`).
3. `ping <IP_may_chu>` từ máy client — verify network reachable.
4. Firewall Windows máy chủ — chạy lệnh section 1 bước 2 hoặc tạm tắt firewall để test.
5. Router/switch có isolate client không? (VD Guest WiFi thường block LAN-to-LAN).

### "Máy chủ mất kết nối liên tục"

App design: máy chủ tắt = dashboard offline. Muốn 24/7:
- Chạy `start.bat` on-startup Windows (Task Scheduler).
- Hoặc deploy production dùng systemd/nginx/gunicorn (ngoài scope guide này).

### "Tôi muốn admin từ máy khác, không phải máy chủ"

Set env `IHRP_LAN_ADMIN_ALLOW=192.168.1.10` (thay IP của máy được phép)
trước khi chạy `start.bat`. **Cẩn thận** — máy đó cần bảo mật tương đương
máy chủ.

### "Access log quá to, chiếm disk"

Log tự rotate ở 10 MB. Backup `access.log.1` sẽ bị ghi đè khi rotate lần
sau. Muốn tắt hẳn: `set IHRP_DISABLE_ACCESS_LOG=1`.

### "IP LAN của máy chủ hay đổi (DHCP)"

- Ngắn hạn: reserve IP trong router DHCP.
- Trung hạn: gán static IP cho máy chủ.
- Dài hạn: dùng hostname nội bộ + DNS (VD `\\pc-huy\dashboard`).

---

## 7. Checklist deploy production nội bộ

- [ ] Windows Firewall inbound rule port 5000 (subnet nội bộ, không internet)
- [ ] `start.bat` chạy on-startup (Task Scheduler)
- [ ] Backup thư mục `.project_store/` định kỳ (chứa data)
- [ ] Static IP hoặc DHCP reservation cho máy chủ
- [ ] Verify `/api/lan/info` từ máy client trả `is_localhost_request: false`
- [ ] Verify POST `/api/upload` từ máy client trả 403 `LOCALHOST_ONLY`
- [ ] (Optional) HTTPS với mkcert nếu policy yêu cầu
- [ ] (Optional) Public API token cho bên thứ 3 ngoài LAN

---

## Files chính (impl)

- `analyzer/lan_security.py` — `is_localhost_request`, `is_admin_mutation_request`,
  `@localhost_only`, `install_admin_guard`, `install_access_log`,
  `read_access_log_tail`, `detect_lan_ips`.
- `app.py` — install ngay khi startup (dòng ~110–130).
  Endpoints `/api/lan/info` (public) + `/api/lan/access-log` (localhost-only).
- `start.bat` — in URL LAN auto-detect.
- `templates/index.html` — section 🌐 LAN trong Settings modal.
- `static/js/dashboard.js` — `_lanRefresh`, `_lanRenderInfo`,
  `_lanRenderAccessLog`, `_lanCopyUrl`.
- `tests/test_lan_security.py` — 50 test (unit + HTTP end-to-end).
