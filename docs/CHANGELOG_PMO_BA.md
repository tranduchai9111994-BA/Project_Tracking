# Changelog — PMO Phase A–F + BA UX (đã ship)

> Cập nhật: **2026-08-01**. Tài liệu ngắn cho reviewer: phạm vi đã giao, file chính, hạn chế.  
> Không liệt kê commit hash trừ khi cần; verify trong code / `tests/test_*pmo*` · `test_ba_ux*` · `test_sqlite*` · `test_baseline*` · `test_earned*` · `test_scope*` · `test_uat*`.

---

## PMO Phase A–F

| Phase | Deliverable | Module | API / UI chính |
|-------|-------------|--------|----------------|
| **A** | Đánh dấu snapshot baseline + Schedule Variance (ngày) theo function/milestone | `analyzer/baseline_sv.py` | `/baseline`, `/baseline-sv` · `section-baseline` |
| **B** | Dự báo ngày xong từ velocity Closed/tuần (4 tuần) | `analyzer/completion_forecast.py` | `/completion-forecast` (thường gắn Summary / Forecast) |
| **C** | EVM: BAC, EV, PV, AC → SPI, CPI (MH) | `analyzer/earned_value.py` | `/earned-value` · `section-evm` |
| **C** | Scope creep / CR (cột Excel hoặc tag/`cr_function_codes`) | `analyzer/scope_creep.py` | `/scope-creep` · `section-scope-creep` |
| **D** | Risk score + PIC overload + module cascade delay | `risk_scorer.compute_pmo_risk`, `module_dependency.py` | `/pmo-risk` · Risk section |
| **E** | UAT Quality: defect / feedback / reopen / cycle | `analyzer/uat_quality.py` | `/uat-quality` · `section-uat-quality` |
| **F** | SQLite WAL `meta.db` dual-write settings/bookmarks/tags | `analyzer/sqlite_store.py` + `project_store.py` | Transparent qua store helpers |

**Vẫn file-based sau Phase F:** ParsedData pickle, snapshots, capacity, saved_views, section/module order, chart configs/notes, integrations, PM plan/weekly, archive settings, upload history, custom dashboards…

---

## BA UX 1–11 (+ polish)

| # | Deliverable | Module / FE |
|---|-------------|-------------|
| 1 | Auto-diff FL hiện tại vs snapshot trước | `function_diff.py` · `section-function-diff` |
| 2 | Saved filter views | `saved_views` API + FE |
| 3 | Trend chips OD/UA/ST trên insight strip | FE `updateInsightStripChips` |
| 4 | DQ highlight Module / Matrix | FE + `data_quality.py` |
| 5 | Bulk tags | `/tags/bulk` |
| 6 | Critical path trên Gantt Calendar | `gantt_calendar._annotate_critical_path` (heuristic) |
| 7 | FL re-import verify sau sửa yellow cells | `fl_reimport_verify.py` |
| 8 | Bottleneck phase trong matrix/phase | `dashboard_engine` |
| 9 | PIC × tuần sắp tới | `pic_upcoming.py` · `section-pic-upcoming` |
| 10 | Rlog tuần (section + counts) | `rlog_weekly.py` |
| 11 | Module còn lại (SL + MH) | module overview fields |
| Polish | Insight strip collapse | `toggleInsightStrip` · LS key |
| Polish | Help topic Data Quality | `help_content.js` → `dataquality` |

---

## Ops liên quan (cùng giai đoạn sản phẩm)

- **Disk janitor** startup: `purge_old_exports`, `purge_excess_snapshots`, `purge_excess_synced_*`, `purge_duplicate_pm_weekly_*`.
- Archive T-AA vẫn dùng (xem [ARCHIVE_GUIDE.md](ARCHIVE_GUIDE.md)).

---

## Đã bổ sung sau review

- **Ước lượng theo hệ số** (`estimate_ratio.py`, `section-estimate-ratio`, `estimation_params.json`) — parametric BA/Dev + ratios; không thay Forecast Manpower.

## Chưa ship / cố ý hạn chế

1. **SQLite cutover full** — chưa; chỉ meta slice.  
2. **Critical path** — không phải CPM trên dependency graph.  
3. **FL verify** — không phải cell-diff tổng quát.  
4. **P2:** API Registry Catalog (T-B), form_login wizard đầy đủ (T-C) — [BUGS_TODO.md](BUGS_TODO.md).

---

## Gợi ý kiểm thử nhanh

```bash
pytest tests/test_baseline_sv_forecast.py tests/test_earned_value.py tests/test_scope_creep.py tests/test_pmo_risk_phase_d.py tests/test_uat_quality.py tests/test_sqlite_store.py tests/test_ba_ux_backlog.py -q
```
