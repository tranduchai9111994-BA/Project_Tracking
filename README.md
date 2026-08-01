# iHRP Function List Tracker

Dashboard **local** cho PM/BA triển khai iHRP / HRIS: upload hoặc sync Function List Excel → auto-detect cột → tracking / forecast / PMO / BA UX → export · Public API · LAN.

## Chạy nhanh

```
start.bat          # Windows
./start.sh         # macOS/Linux
```

Mở `http://127.0.0.1:5000` → đăng nhập. Lần đầu: **`admin` / `admin`** (đổi mật khẩu ngay trong ⋯ Thêm → Tài khoản). Copy `.env.example` → `.env` nếu dùng sync API.

```bash
pytest -q
```

## Tài liệu

**Bắt đầu tại [`docs/README.md`](docs/README.md)** (mục lục + thứ tự đọc cho review ngoài).

| File | Nội dung |
|------|----------|
| [docs/SYSTEM_OVERVIEW.md](docs/SYSTEM_OVERVIEW.md) | Tổng quan sản phẩm + gaps |
| [docs/FEATURE_CATALOG.md](docs/FEATURE_CATALOG.md) | Checklist feature đã ship |
| [docs/BUSINESS_LOGIC.md](docs/BUSINESS_LOGIC.md) | Rule / công thức |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | Kiến trúc kỹ thuật |
| [docs/CHANGELOG_PMO_BA.md](docs/CHANGELOG_PMO_BA.md) | PMO A–F + BA UX |

Nguyên tắc parse / overdue / PIC: [`.cursorrules`](.cursorrules).
