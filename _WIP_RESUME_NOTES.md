# WIP Resume Notes — 29/07/2026 lunch break

**Trạng thái**: Session bị STOP ngay khi vừa nhận batch mới. **KHÔNG có file dở nào** — working tree sạch, ahead origin 30 commits (chưa push).

## Nơi đang đứng

- Vừa hoàn thành xong 8 tasks (T12-T19) trong session trước, đã report + commit đủ (xem `git log --oneline -10`).
- Batch mới được giao ngay trước lunch break: **2 bugs P0 + T21-T29 (11 tasks)** — **CHƯA bắt đầu bất kỳ task nào**.
- Chỉ mới tạo TODO list trong đầu + gọi `git status`, `pytest -q` (verify state). Cả 3 tool call đầu đã bị user interrupt sau ~72s.

## 11 task pending session này

### P0 bugs (bắt đầu tại đây khi resume)

**BUG P0-A — Global Search bị "mất"**:
- Ô `#searchWrap` (placeholder "🔍 Tra cứu chức năng…") không hiện sau upload.
- Điều tra sơ bộ (từ prompt): HTML dòng 74 vẫn có `<div class="... hidden" id="searchWrap">`; JS dòng 272 có `_step("fileInfo", () => { ... searchWrap.classList.remove("hidden"); })`.
- Hướng debug:
  1. Verify bằng cách khởi app + upload file → DevTools console check error trong `_step("fileInfo", ...)`.
  2. Check `switchProject()` có gọi `applyDashboardResponse()` không — nếu không, `_step("fileInfo")` không chạy → search hidden vĩnh viễn.
  3. Sticky top block (T18) có `overflow: hidden` cắt search? Ít khả năng vì search nằm ngoài `#stickyTopBlock`.
  4. Z-index conflict với sticky element khác.
- Fix hướng: move `remove("hidden")` ra khỏi `_step("fileInfo")` block, hoặc gọi cả trong `loadProject/switchProject`.
- Commit: `fix: Function Traceability search hiển thị sau upload/switch project`

**BUG P0-B — Bảng Tổng quan mode "Quy trình" hiện ALL, không apply global filter**:
- Filter Module=[PR] + Quy trình=[PRM.BP.03, PRM.BP.04] → 45 function. Bấm toggle "Quy trình" bảng Tổng quan → list 10+ hàng quy trình của module khác (APP.BP.*, HR.HRM.*).
- Root cause: endpoint `/api/projects/<slug>/module-overview?group_by=process` (T17 vừa thêm ở `app.py`) KHÔNG merge global filter (`_g_module`, `_g_process`, `_g_pic`).
- Fix: endpoint phải dùng `_filtered_data_from_request()` (đã có sẵn ở app.py); `_overview_by_process` cần nhận filtered data; frontend `_fetchModuleOverview()` gửi kèm global filter params.
- Cùng lúc check chart "Tiến độ theo công việc" mode Quy trình có bug tương tự không.
- Commit: `fix(overview): mode Quy trình trong bảng Tổng quan + chart công việc apply global filter`

### Tier 2 — BA/PM Productivity

- **T21 — Data Quality panel**: module mới `analyzer/data_quality.py` với `compute_data_quality(rows, phase_groups)`; detect status invalid, End<Start, PIC blank ở phase quan trọng, Priority/Complexity/FIT-GAP blank, Phase Closed thiếu End date, duplicate Mã CN. Section mới, endpoint GET + export Excel.
- **T22 — Aging WIP**: detect task In-progress + (today - start) > threshold. Section `#section-aging-wip`, endpoint `/aging-wip?threshold=14`.
- **T23 — Command Palette Ctrl+K**: modal fuzzy search jump section/filter/action/function. Trigger `Ctrl+K` / `Cmd+K` / `/`.
- **T24 — Bookmark + Notes**: ⭐ 📝 icon cạnh row; store `bookmarked_functions[]`, `function_notes{}` trong project_store; section `#section-my-bookmarks`.

### Tier 4 — Meeting & Presentation

- **T25 — Presentation Mode**: nút "🎬 Trình chiếu" → full-screen 1-section-at-a-time, arrow keys ← →, Esc thoát, counter "3/15".
- **T26 — Weekly Digest auto-PDF**: cron-lite check on startup, auto-gen PDF (dùng logic T7 PDF preset PM) mỗi thứ 2 8AM, lưu `.project_store/<slug>/digests/YYYYMMDD_weekly.pdf`.

### Pending từ session cũ

- **T27 — Drill-down endpoint inline cho custom dashboard chart**: `GET /api/projects/<slug>/custom-dashboard/<id>/drill`.
- **T28 — Chart Config Phase B tab Filter multi-select dropdown**: nâng cấp text input → multi-select reuse `createMultiSelect`.
- **T29 — Settings modal cho progress_thresholds**: modal `⚙️ Cài đặt` cho thresholds palette + aging WIP + weekly digest + refresh reminder.

## Files ĐANG dở

**KHÔNG có**. Working tree hoàn toàn sạch. Chạy app sẽ không lỗi.

## Cách pickup (khi resume)

1. `git status` verify sạch. `git log --oneline -1` phải là `80c472f feat(palette)…`.
2. Đọc lại `.cursorrules` (auto-detect cột, comment tiếng Việt, không pandas/numpy).
3. Prompt gốc của batch này đã lưu trong `agent-transcripts/1907b0ac-c16e-476a-b875-018024db28eb/1907b0ac-c16e-476a-b875-018024db28eb.jsonl` — search cho keyword "BUG P0-A" hoặc "TIER 2" hoặc "T21 — Data Quality" để tìm prompt đầy đủ.
4. Bắt đầu bằng **BUG P0-A**, rồi P0-B, rồi tuần tự T21 → T29. Mỗi task commit riêng, không push.
5. Nếu overload lại → tạo lại `_WIP_RESUME_NOTES.md` với progress đã đạt.

## Ghi chú kỹ thuật quan trọng

- **`_filtered_data_from_request()`** đã có sẵn trong `app.py` — dùng để lấy `ParsedData` đã apply global filter từ query string. Đây là chìa khoá fix P0-B.
- `_parse_multi_arg("module")` trong `app.py` tách được comma-sep + repeat param.
- Meta key process là `"quy_trinh"` không phải `"process"` (đã fix ở kanban.py T13, cần check khi dùng ở data_quality.py T21).
- Palette API (`window.Palette` / `analyzer.palette`) đã sẵn cho T29 settings modal.
- SortableJS CDN đã load (T4b) → reuse cho drag ordering ở feature mới nếu cần.
- `createMultiSelect` component ở `static/js/dashboard.js` — reuse cho T28.
- Task 7 PDF Export logic đã ở `dashboard.js` (`doPdfExport`) — T26 gọi lại được từ backend? KHÔNG — logic là client-side html2canvas. **T26 cần backend PDF generation riêng** (VD dùng `weasyprint` / `xhtml2pdf` — nhưng đã bỏ pandas/matplotlib nên cần check dep light). Hoặc lưu URL để user manual gen — cần discuss với user khi resume.
- Auto-cleanup old digests: cần cân nhắc giữ 10-20 file gần nhất để tránh phình dung lượng.

## Config

- Flask app đã tắt, port 5000 free. Zip an toàn.
- Không có process nào giữ file lock.
