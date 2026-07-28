# WIP Resume Notes — Task 4a interrupted (29/07/2026)

## Trạng thái session pause

- **Task 1** ✅ committed `d086902` (Function Traceability search)
- **Task 2** ✅ committed `d8f012f` (FIT/GAP Dashboard)
- **Task 3** ✅ committed `ed1791a` (Function Diff)
- **Task 4a** 🚧 **DANG DỞ** — mới bắt đầu, chỉ có script Python chuẩn bị,
  chưa chạy được. Template `templates/index.html` **CHƯA BỊ CHỈNH SỬA** — vẫn
  y hệt commit Task 3.
- **Task 4b** ⏸ chưa bắt đầu (drag-drop customize)

## File dang dở

- `_dbg_reorder.py` — **có syntax error** (dùng pipe operator `|>` không hợp lệ
  trong Python 3.11). Đã có cả 2 định nghĩa `extract_grid_containing`; cái đầu
  cần XOÁ HOÀN TOÀN, cái thứ 2 (dưới comment "Fallback...") là bản chạy được.
  → Sửa xong chạy `python _dbg_reorder.py` là reorder xong Task 4a.

## Files có thể xóa an toàn (test artifact)

`_dbg_*.json`, `_dbg_*.xlsx`, `_dbg_*.png`, `_dbg_t1_e2e.js`, `_dbg_t1_overdue.js`,
`_dbg_t2_e2e.js`, `_dbg_t3_e2e.js`, `_dbg_setup_snapshot.py`, `_dbg_inspect.py`,
`_dbg_gen_upload.py`, `_dbg_broken.js`, `_dbg_drill.js`.

## Snapshot test đã set up

Trong `uploads/projects/default/snapshots/` có 2 snapshot:
- Hôm nay (29/07): current.xlsx đã upload = `_dbg_sample_modified.xlsx`
- Hôm qua (28/07): snapshot manual = `_dbg_sample.xlsx`

Diff sẽ hiển thị: 1 added + 1 deleted + 1 PIC change + 1 Priority change +
1 FIT/GAP change + 1 Status change.

## Cách pickup Task 4a

1. Fix syntax error trong `_dbg_reorder.py` (xoá cái `extract_grid_containing`
   đầu tiên có `|>`).
2. Chạy `python _dbg_reorder.py` → rewrite `templates/index.html`.
3. Verify: mở app, xem sidebar nav + section order khớp 8 nhóm.
4. Chạy `pytest -q` để đảm bảo không regression.
5. Commit: `refactor(ux): reorder sections theo 8 nhóm - kéo Overdue/Unassigned/Risk/Stalled lên sau summary`.

## Task 4b (chưa bắt đầu)

Sau Task 4a xong:
- SortableJS CDN: `https://cdn.jsdelivr.net/npm/sortablejs@1.15.2/Sortable.min.js`
- Toggle "🔧 Chỉnh thứ tự" ở header
- Endpoint `POST /api/projects/<slug>/section-order` + `.../reset`
- Extend `project_store.py`: `section_order: [id1, id2, ...]`
- Save vào saved views (view definition có optional section_order)
- Load order khi mở dashboard (apply DOM reorder trước renderDashboard).
- Commit: `feat(ux): drag-drop reorder section + lưu vào project_store & saved views`

## Lưu ý khi pickup

- Flask server đã kill, port 5000 free — restart bằng `start.bat` hoặc
  `venv\Scripts\python.exe app.py`.
- `venv/` đã sẵn sàng, `node_modules/playwright-core` đã install.
- `.cursorrules` vẫn nguyên: auto-detect cột, không hardcode, comment tiếng Việt.
