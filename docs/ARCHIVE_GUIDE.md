# Archive Guide — Auto-archive snapshots (T-AA)

Hướng dẫn dùng tính năng **auto-archive** snapshot cũ để giải phóng dung lượng đĩa mà vẫn giữ data để so sánh / load.

## Mục đích

Mỗi lần upload/sync, app lưu snapshot (`.xlsx` + `.parsed.pkl`) trong
`uploads/projects/<slug>/snapshots/`. Theo thời gian thư mục này phình to.

**Archive** = gzip (level 6) + chuyển sang `snapshots/archive/` + đánh dấu
`archived=True` trong `snapshot_index.json`. Tiết kiệm khoảng **30–40%** dung lượng
(`.pkl` nén tốt ~60%, `.xlsx` đã zip sẵn nên chỉ ~15%).

## Cấu hình (per-project)

Settings → section **🗄️ Archive**:

| Field | Default | Ý nghĩa |
|-------|---------|---------|
| Bật auto-archive | ✅ | Master switch |
| Archive snapshot cũ hơn X ngày | 90 | `0` = không bao giờ auto |
| Tự động archive khi server start | ✅ | Chạy background thread lúc boot |
| Xóa vĩnh viễn archive cũ hơn Y ngày | 365 | `0` = không bao giờ purge (destructive) |

File lưu: `uploads/projects/<slug>/archive_settings.json`.

## Thao tác thủ công

- **▶ Archive ngay** — chạy theo ngưỡng ngày hiện tại + purge (nếu purge > 0).
- **📦 Archive** trên 1 dòng — archive đúng snapshot đó.
- **🔓 Rã đông** — extract lại về `snapshots/` (hot), bỏ flag archived.

## Transparent load

Khi snapshot đã archive, `SnapshotManager.load_snapshot()` vẫn đọc được:
decompress gzip pickle **trong memory**, không extract ra disk.

Compare mode: nếu chọn snapshot archived → FE tự gọi restore trước khi so sánh.

## API

```
GET  /api/projects/<slug>/archive-settings
PUT  /api/projects/<slug>/archive-settings
POST /api/projects/<slug>/archive-run          body: {days?, purge?, purge_days?}
POST /api/projects/<slug>/snapshots/<id>/archive
POST /api/projects/<slug>/snapshots/<id>/restore
```

## Startup behavior

Khi Flask start (và `auto_run_on_startup=True` + `enabled=True`):

1. Background daemon thread quét mọi project active.
2. `auto_archive_project(days=archive_after_days)`.
3. `purge_archive(days=purge_after_days)` nếu > 0.
4. Log stderr + 1 dòng vào `.project_store/access.log`.

## Checksum

Trước khi xóa bản hot, app verify SHA-256 của nội dung sau gzip khớp hash gốc.
Restore cũng verify lại trước khi xóa `.gz`.

## Lưu ý

- **Purge là destructive** — không khôi phục được. Chỉ bật khi chắc chắn không cần snapshot quá cũ.
- Entry cũ không có `archived`/`source` → default `archived=false`, `source=upload`.
- Không thêm dependency ngoài (stdlib `gzip` + `hashlib`).

## Verify nhanh

1. Upload 1 file → Settings → Archive → thấy 1 dòng 🔥 Hot.
2. Bấm 📦 Archive trên dòng đó → status đổi 📦 Archived, disk info cập nhật.
3. Bấm 🔓 Rã đông → trở lại Hot, file xuất hiện lại trong `snapshots/`.
4. Đặt slider = 0 ngày → ▶ Archive ngay → snapshot hôm nay bị archive (nếu days=0 thì **không** archive — dùng nút từng dòng để test).
5. `pytest tests/test_archive_manager.py -q` → pass.
