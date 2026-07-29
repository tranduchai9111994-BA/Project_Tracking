# Bug Tracker + TODO — cập nhật 29/07/2026 (sau batch T21–T29)

**Trạng thái**: Batch productivity + presentation (T21–T29, UX7, b8–b15)
đã hoàn thành. Các bug lịch sử từ QA 28/07 đã được fix trong wave trước.
File này giữ để track bug đang open + backlog nhỏ.

Test suite: `pytest -q` → **355 passed** (~172s trên Win10, Python 3.11).

---

## ✅ Đã fix trong batch mới nhất (29/07/2026)

| Bug ID | Mô tả ngắn                                                            | Commit           |
|--------|-----------------------------------------------------------------------|------------------|
| b8     | Help tooltip "?" không click được trong section Stalled + đổi Stalled → **Đình trệ** | `2336ef8`        |
| b9     | Matrix Phase × Module toggle **Module / Quy trình** + apply global filter | `aa8904e`        |
| b10    | Chart Tiến độ theo Phase: header wrap 3 dòng + thêm bucket **(Blank)** để tổng bằng total | `c0667ca`        |
| b11    | Heatmap Quy trình: badge tổng + apply global filter                    | `ce0f0d7`        |
| b12    | Burndown & Velocity: scope badge + toggle phạm vi theo Phase + global filter | `3b76390`        |
| b13    | Unassigned drill mismatch — logic `_is_phase_active` không khớp `dashboard_engine._is_overdue` | `6706e89`        |
| b14    | Data label toàn app (FIT/GAP aging, Burndown, Module delta…)          | `e70c077`        |
| b15    | Custom Dashboard `pct_overdue` 100% sai + label tiếng Việt + format measure | `82262a3`        |
| UX7    | Icon 👁 View column trong bảng lưới thay click-any-row                 | `539dad5`        |

## ✅ Tính năng mới (batch cùng session)

| Task | Mô tả                                                          | Commit           |
|------|-----------------------------------------------------------------|------------------|
| T21  | Data Quality panel + Excel export                              | `40e8b7a`        |
| T22  | Aging WIP tracking + slider threshold                          | `2ef6dec`        |
| T23  | Command Palette (Ctrl+K / Cmd+K / `/`)                         | `79777fe`        |
| T24  | Bookmark + Notes per-function (⭐ 📝)                          | `e182ff3`        |
| T25  | Presentation Mode (🎬 header, ← → điều hướng, Esc thoát)       | `af200b3`        |
| T26  | Weekly Digest cron-lite (Excel, không PDF backend)             | `962ae66`        |
| T27  | Drill-down inline cho custom dashboard chart                   | `b8330a7`        |
| T28  | Chart Config filter multi-select + preview live                | `6b104a5`        |
| T29  | Settings modal (thresholds / digest / SLA / reminder)          | `5fa7a0a`        |

---

## 🟢 Backlog nhỏ (nice-to-have, không blocker)

### Effort export chart 4 section
Chưa có nút "📥 Xuất Excel" cho: SLA, Capacity PIC, PIC chậm heatmap, Baseline
variance. Có thể tận dụng `export_chart_data` generic hoặc thêm 4 endpoint
riêng nếu cần format đặc thù.

### Gantt 3 modes (Function/Module/Process)
Hiện có 2 mode (Module/Process). Có thể thêm chế độ per-function với phase
segments. Ước lượng ~2h — chưa ưu tiên.

### Auto-cleanup old digests
`digests/YYYYMMDD.xlsx` không tự dọn. Nếu tệp tin phình to cần bổ sung
`purge_old_digests(keep=10)` vào `analyzer/disk_janitor.py`.

### Data Quality: rule mới
Cân nhắc thêm rule mới nếu user gặp trường hợp thực tế:
- Overlap giữa 2 phase cùng function (Start-End trùng)
- Estimate MH quá lệch so với duration thực tế (>2× hoặc <0.3×)

### Presentation Mode enhancements
- Nút Prev/Next trong HUD (hiện chỉ dùng key)
- Auto-advance mỗi N giây (dùng cho standup review)

---

## 🚀 Instructions cho session tiếp theo

1. `git status` verify sạch.
2. `pytest -q` chạy full suite (355 test).
3. Đọc `docs/ARCHITECTURE.md` mục **V4 Wave — Productivity + Presentation**
   để nhớ các API mới.
4. Ctrl+Shift+R browser sau khi pull code mới để reload JS/CSS.
