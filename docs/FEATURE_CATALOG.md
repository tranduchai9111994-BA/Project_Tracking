# Feature Catalog — Checklist · UI · API · Module

> Cập nhật: **2026-08-04**. Dùng để tra cứu “đã ship gì / section nào / API nào”.  
> Rule chi tiết → [BUSINESS_LOGIC.md](BUSINESS_LOGIC.md).

---

## 0. Checklist trạng thái (cho review)

### Core

| Feature | Status | Module / UI |
|---------|--------|-------------|
| Auto-detect cột FL + phase `Name - Attr` | ✅ | `parser/excel_parser.py` |
| Status map Not Started theo PIC; Finished→Closed | ✅ | `_normalize_status(has_pic)` |
| Overdue / Status chuẩn / PIC multi | ✅ | `overdue.py`, parser |
| Multi-project | ✅ | `project_manager.py` |
| Snapshots (+ source Upload/Sync) | ✅ | `snapshot_manager.py` |
| Archive / restore / auto-archive | ✅ | `archive_manager.py` |
| Disk janitor (exports, snapshots, synced_*.xlsx, PPTX weekly trùng) | ✅ | `disk_janitor.py` (startup) |
| Column Mapping Wizard + sync integrations | ✅ | `column_mapping`, `integrations.py` |
| Public API + LAN + Help | ✅ | `public_api`, `lan_security`, `help_content.js` |

### Forecast / PM

| Feature | Status | Module |
|---------|--------|--------|
| Forecast Gantt UAT/Golive theo tháng | ✅ | `forecast_gantt.py` |
| Forecast Manpower MH/MD/MM + tuyển | ✅ | `forecast_manpower.py` |
| Ước lượng theo hệ số (ratio/parametric) | ✅ | `estimate_ratio.py` · `section-estimate-ratio` · `estimation_params.json` |
| PIC Overload đa dự án | ✅ | `pic_overload.py` |
| Rlog tuần | ✅ | `rlog_weekly.py` · `section-rlog` |
| Chiều PM (KeHoach + Weekly) | ✅ | `pm_store` + parsers |
| Capacity PIC (1 project) | ✅ | `advanced_metrics.compute_capacity_load` |

### Issues hub (2026-08)

| Feature | Status | Module / UI |
|---------|--------|-------------|
| Stalled nới (Closed→Open ngay; gate prev Closed) | ✅ | `stalled.py` · `section-stalled` |
| Thiếu / trùng FID (Dev Closed) | ✅ | `fid_check.py` · `section-fid-check` · `/fid-check` |
| ↳ Filter Module/Loại multi, bỏ module không dùng FID | ✅ | `modules_without_fid` · `fidModuleMS` / `fidTypeMS` |
| Checklist lấy source test Rlog (theo ngày Dev đến hạn — không cần Closed) | ✅ | `source_checklist.py` · `section-source-checklist` · `/source-checklist` · `/export-source-checklist` |
| Thời gian dài Start→End | ✅ | `duration_flag.py` · `section-duration-flag` · `/duration-flag` · `/export-duration-flag` |
| Báo cáo tuần GAP + Excel 2-sheet | ✅ | `weekly_gap_report` + `weekly_gap_exporter` · `section-weekly-gap` |
| Module risk theo % stalled/overdue | ✅ | `dashboard_engine` · `risk_reason` |
| Drill Còn lại / Tất cả | ✅ | `drill_down` `scope=remaining\|all` |

### Badge «Bản đang chạy» · Restart · Reset giao diện (2026-08e)

| Feature | Status | Module / UI |
|---------|--------|-------------|
| Phát hiện `.py`/template đổi sau khi server khởi động → «Cần restart» | ✅ | `analyzer/build_info.py` · `/api/build-info` |
| Phát hiện JS/CSS mới hơn **thời điểm trang nạp** → «Cần tải lại» | ✅ | `static_mtime` vs `PAGE_LOADED_AT` |
| Danh sách file theo dõi lấy từ `sys.modules`, không hardcode | ✅ | `loaded_source_files()` |
| Loại venv/site-packages (venv nằm trong project) | ✅ | `_dependency_roots()` |
| Kiểm chứa ổ đĩa không dùng `commonpath` (raise khi khác ổ) | ✅ | `_is_inside()` |
| Badge header + panel chi tiết từng file kèm nhãn restart/reload | ✅ | `#buildStatusBtn` · `#buildStatusModal` |
| Hiện interpreter đang phục vụ (venv hay Python hệ thống) | ✅ | `build_info()["python"]` |
| Restart qua launcher, không `os.execv` | ✅ | `analyzer/restart_service.py` · `restart_helper.bat` |
| Cắt cây process để `taskkill /T` không kill chính launcher | ✅ | `start ""` trong helper |
| Không truyền lệnh lồng vào `cmd /c` (`list2cmdline` escape MSVC) | ✅ | argv phẳng `["cmd","/c",helper]` |
| `CREATE_BREAKAWAY_FROM_JOB` + fallback khi job từ chối | ✅ | `spawn_restart()` |
| `IHRP_NO_BROWSER=1` — restart không mở tab mới | ✅ | `start.bat` |
| `IHRP_RESTART=1` — không treo `pause` kèm `[LOI]` sai lệch | ✅ | `start.bat` |
| Overlay chờ server, poll `/api/health` rồi tự reload | ✅ | `#restartOverlay` · `waitForServer()` |
| Restart: admin + localhost + chỉ Windows (501 kèm hướng dẫn) | ✅ | `can_restart()` · `install_admin_guard` |
| Git: chỉ báo ahead/behind + số file dirty, **không pull** | ✅ | `git_status()` · `/api/git-info` |
| Reset giao diện: xoá `localStorage` có xác nhận liệt kê | ✅ | `resetUiPrefs()` |
| Chốt `SEND_FILE_MAX_AGE_DEFAULT` không bị set | ✅ | `tests/test_build_info.py` |

### Cột meta sheet Chi_tiet — export chart (2026-08d)

| Feature | Status | Module |
|---------|--------|--------|
| Cột `FID` trong mọi sheet Chi_tiet (sau `Mã CN`) | ✅ | `DETAIL_META_COLUMNS` · `_func_meta` |
| `Rlog ID` tự ẩn khi FL không khai cột | ✅ | `_detail_meta()` · `_file_has_rlog_column` |
| Ẩn theo *có khai cột*, không theo *có giá trị* | ✅ | `_detail_meta()` |
| Cặp (columns, values_fn) chống lệch cột | ✅ | `_detail_meta()` |
| `pic_workload` dùng chung bộ meta | ✅ | `export_chart` |

### Hai chế độ xuất cho tab issue (2026-08d)

| Feature | Status | Module / UI |
|---------|--------|-------------|
| Menu 2 nhóm «Danh sách lỗi» / «FL để import» | ✅ | `openExportModePicker(event, key, fn, {flKinds})` |
| `kinds` giới hạn union về 1 loại issue | ✅ | `FL_REIMPORT_KINDS` · `/export-fl-reimport?kinds=` |
| Không truyền `kinds` → union như cũ (Archive không đổi) | ✅ | `want()` fallback |
| Danh sách lỗi FID: 7 cột như lưới + cột trống điền tay | ✅ | `export_fid_issues_report` · `/export-fid-issues` |
| Sheet `Loi_FID` (không phải `Function List`) chống import nhầm | ✅ | `export_fid_issues_report` |
| Forward filter cục bộ sang FL-import | ✅ | `l_module` · `l_phase` · `l_pic` · `l_waiting_phase` |
| Khớp field dạng list (`overdue[].pic`) | ✅ | `_narrow()` |
| Cảnh báo `row_count_drop` khi upload file ít dòng | ✅ | `_row_count_drop_warning` · `ROW_DROP_WARN_RATIO` |
| Banner cố định cho warning critical (thay toast) | ✅ | `#uploadCriticalWarn` · `_showUploadWarnings` |

### Nút 📥 trên thanh tab + xuất gộp nhiều tab (2026-08d)

| Feature | Status | Module / UI |
|---------|--------|-------------|
| Config tab nhận `exportFn` (hàm global) ngoài `export` (chart key) | ✅ | `_openTabExport()` · `SIDEBAR_NAV_TREE` |
| 9 tab Issues nối đúng hàm xuất của mình | ✅ | `exportFn` từng tab |
| Forward filter cục bộ của section qua thanh tab | ✅ | `extraParamsFn` |
| Option «Tất cả tab (1 file nhiều sheet)» | ✅ | `data-all-group` · `exportAllFn` |
| `forceFull` bỏ qua nhóm vấn đề đang focus | ✅ | `exportAllIssues({forceFull})` |
| File tổng hợp 8 → 12 sheet (đủ 9 tab Issues) | ✅ | `export_all_issues(fid_issues=…, …)` |
| `None` = bỏ sheet · `[]` = sheet rỗng | ✅ | `export_all_issues()` |
| Thứ tự sheet khớp thứ tự tab (Risk/Bookmark về cuối) | ✅ | `export_all_issues()` |
| Xuất riêng «Lấy source test» + «Thời gian dài» | ✅ | `/export-source-checklist` · `/export-duration-flag` |
| Sheet rời dùng lại writer của file gộp (chống lệch cột) | ✅ | `_send_single_issue_sheet()` |
| Tab lazy chưa mở → toast hướng dẫn, không báo thiếu tính năng | ✅ | `_openTabExport()` |
| Kiểm tên hàm trong config tồn tại thật | ✅ | `tests/test_tab_bar_export.py` |

### Filter Module/Loại — section Thiếu / Trùng FID (2026-08d)

| Feature | Status | Module / UI |
|---------|--------|-------------|
| Multi-select Module + Loại issue | ✅ | `#fidModuleMS` · `#fidTypeMS` |
| Mặc định bỏ module không dùng FID (suy từ dữ liệu, không hardcode "APP") | ✅ | `modules_without_fid` · `_fidDefaultModules()` |
| Fallback check hết khi mọi module đều không có FID | ✅ | `_fidDefaultModules()` |
| Nhớ lựa chọn theo project + module mới tự check | ✅ | localStorage `fidModuleSel:<slug>` |
| Nút trả về mặc định | ✅ | `resetFidFilters()` |
| 4 card chạy theo filter + ghi chú `toàn bộ: N` | ✅ | `_fidRenderSummaryCards()` · `module_stats` |
| Banner phân biệt "ẩn vì không dùng FID" vs "user bỏ chọn" | ✅ | `_fidUpdateScopeBanner()` |
| Export FL nhận `fid_module` / `fid_type` | ✅ | `/export-fl-reimport` |
| Module rỗng vẫn lọc được (token `__no_module__`) | ✅ | `_fidModKey()` · `_fidModWire()` |

Badge Thiếu FID ở sidebar **cố ý không lọc** — xem `BUSINESS_LOGIC.md` mục 5b.

### Filter Phase chờ — section Đình trệ (2026-08c)

| Feature | Status | Module / UI |
|---------|--------|-------------|
| Multi-select Phase chờ, mặc định bỏ Document | ✅ | `#stalledPhaseMS` · `_stalledDefaultPhases()` |
| Nhận diện phase Document theo keyword bỏ dấu (không hardcode) | ✅ | `_stalledIsDocPhase()` |
| Nhớ lựa chọn theo project + phase mới tự check | ✅ | localStorage `stalledPhaseSel:<slug>` |
| Nút trả về mặc định | ✅ | `resetStalledPhaseFilter()` |
| Drill + Excel nhận `waiting_phase` | ✅ | `drill_down` · `/export-stalled?waiting_phase=` |
| Banner ghi tỷ lệ hiện/tổng + phase đang ẩn | ✅ | `_updateStalledScopeBanner()` |
| Fix drill Đình trệ khi chọn nhiều Module | ✅ | `_filter_stalled` tách `module` theo dấu phẩy |

Funnel Closed/Phase và badge Đình trệ ở sidebar **cố ý không lọc** — xem `DASHBOARD_SPEC.md` mục 13.

### Baseline chain & delta bảng Module (2026-08b)

| Feature | Status | Module / UI |
|---------|--------|-------------|
| Chuỗi baseline bất biến có version (v1, v2, v3…) | ✅ | `baseline_manager.py` · `baselines/` · `/baselines` |
| Cảnh báo snapshot gốc của baseline bị ghi đè | ✅ | `source_drifted` · bảng baseline trong `section-baseline` |
| Chọn mốc so sánh: Baseline / Tuần trước / Bản trước / Bản cụ thể | ✅ | `compare_base.py` · dropdown `#moCompareBase` |
| Cột tăng/giảm SL · Tiến độ · Trễ · Còn lại (số lượng + %) | ✅ | `module_delta.py` · `/module-overview?compare=` |
| Chốt baseline ngay từ bảng A | ✅ | `pinBaselineFromModule()` |
| Export bảng A kèm delta + Còn lại/Đánh giá + `group_by` | ✅ | `excel_exporter` `module_overview` |

### PMO Phase A–F

| Phase | Feature | Status | Module / API |
|-------|---------|--------|--------------|
| A | Baseline mark + SV cross-snapshot | ✅ | `baseline_sv.py` · `/baseline`, `/baseline-sv` |
| B | Completion forecast (velocity) | ✅ | `completion_forecast.py` · `/completion-forecast` |
| C | EVM EV/PV/AC/SPI/CPI | ✅ | `earned_value.py` · `/earned-value` · `section-evm` |
| C | Scope creep / CR | ✅ | `scope_creep.py` · `/scope-creep` · `section-scope-creep` |
| D | PMO risk + cascade + overload | ✅ | `risk_scorer.compute_pmo_risk`, `module_dependency` · `/pmo-risk` |
| E | UAT Quality | ✅ | `uat_quality.py` · `/uat-quality` · `section-uat-quality` |
| F | SQLite `meta.db` dual-write | 🔶 partial | `sqlite_store.py` — chỉ settings/bookmarks/tags |

### BA UX 1–11 + polish

| # | Feature | Status | Ghi chú |
|---|---------|--------|---------|
| 1 | Auto-diff vs snapshot trước | ✅ | `function_diff.py` · `section-function-diff` |
| 2 | Saved filters / views | ✅ | `saved_views.json` · `/saved-views` |
| 3 | Trends (insight chips) | 🔶 | Delta OD/UA/ST trên insight strip — không API trend riêng |
| 4 | DQ highlights trên Module/Matrix | ✅ | FE + `data_quality.py` |
| 5 | Bulk tags | ✅ | `/tags`, `/tags/bulk` (+ SQLite dual-write) |
| 6 | Critical path | 🔶 | Heuristic trên Gantt Calendar |
| 7 | FL re-import verify | 🔶 | Chỉ yellow-hit PIC/Status trước đó |
| 8 | Bottleneck phase | ✅ | `phase_status_matrix.bottleneck` |
| 9 | PIC upcoming (tuần tới) | ✅ | `pic_upcoming.py` · `section-pic-upcoming` |
| 10 | Rlog visibility | 🔶 | Ẩn cột RlogID khi file không có `* - RlogID` |
| 11 | Module còn lại (count + MH) | ✅ | + drill `scope=remaining` khớp số |
| — | Insight strip collapse | ✅ | `ihrp.insightStrip.expanded` |
| — | DQ help topic | ✅ | `help_content.js` → `dataquality` |

---

## 1. Shell ứng dụng

| Thành phần | Mô tả |
|------------|--------|
| `templates/index.html` | SPA: header, sidebar hubs, sticky filter, sections |
| `static/js/dashboard.js` | Logic UI |
| `static/js/sidebar_hubs.js` | Hub/tab IA (Tổng quan / Issues / Tiến độ…) |
| `static/js/i18n.js` | VI/EN |
| `static/js/help_content.js` | Help `?` + Ctrl+/ |
| `static/css/style.css` | Sticky, toolbar, Gantt… |
| `app.py` | ~100+ HTTP routes |

**Header:** Import/Sync · Xuất ▾ · View · Thêm ▾ · Settings · Help.  
**Sidebar:** hubs Tổng quan / **VẤN ĐỀ (Issues)** / Tiến độ / Forecast / … + All.  
**Insight strip:** chip tóm tắt + toggle collapse.

---

## 2. Tracking

| Section ID | UI | Backend | Ghi chú |
|------------|----|---------|---------|
| `section-summary` | Cards tổng quan | `DashboardEngine` | Sticky compact |
| `section-globalfilter` | Module/Process/PIC/Project | `_filter_parsed_data` | Luôn hiện khi lọc nhóm |
| `section-module` | Bảng tiến độ module | module overview | Cột **còn lại** / MH; risk %; drill `scope` |
| `section-tasktype` | % Closed theo công việc | task_type | |
| `section-matrix` | Phase × Module | phase matrix | DQ badge + bottleneck; click → drill (không redirect DQ) |
| `section-phase` | Stacked status × phase | | Bottleneck highlight |
| `section-giaidoan` | % Closed × giai đoạn | | |
| `section-rlog` | Rlog coded / plan tuần | `rlog_weekly.py` | Ẩn cột RlogID nếu file không có |
| `section-overdue` | Bảng trễ | `overdue.py` | |
| `section-unassigned` | Thiếu PIC | `unassigned.py` | |
| `section-stalled` | Đình trệ | `stalled.py` | Nới rule + prev Closed |
| `section-fid-check` | Dev Closed thiếu/trùng FID | `fid_check.py` | Issues hub |
| `section-source-checklist` | Checklist lấy source test theo ngày Dev đến hạn (End trong lookback, không cần Closed) | `source_checklist.py` | Người lấy = PIC Config Local; lookback 14 ngày; loại Dev.Cancelled |
| `section-duration-flag` | Start→End dài | `duration_flag.py` | Ngưỡng ngày chỉnh được |
| `section-weekly-gap` | Báo cáo tuần GAP | `weekly_gap_report.py` | Export Excel 2-sheet |
| `section-aging-wip` | WIP già | advanced | |
| `section-sla` | SLA | advanced | |
| `section-pic-upcoming` | PIC × tuần tới | `pic_upcoming.py` | |

---

## 3. Forecast + PMO lịch/effort

| Section ID | UI | Backend | Export / API |
|------------|----|---------|--------------|
| `section-gantt` | Timeline | timeline_data | chart export |
| `section-forecast-gantt` | UAT/Golive tháng | `forecast_gantt.py` | `/api/forecast-gantt` |
| `section-forecast-manpower` | MH/MD/MM + tuyển | `forecast_manpower.py` | `/forecast-manpower` |
| `section-estimate-ratio` | Ước lượng theo hệ số | `estimate_ratio.py` | `/estimate-ratio` · params JSON |
| `section-gantt-calendar` | Calendar Excel-style | `gantt_calendar.py` | Critical path flag |
| `section-burndown` | Velocity | advanced | Dùng cho completion forecast |
| `section-capacity` | Remaining vs capacity | advanced | |
| `section-pic-overload` | Overload đa dự án | `pic_overload.py` | `/api/pic-overload` |
| `section-baseline` | Baseline SV + quản lý chuỗi baseline | `baseline_sv.py` · `baseline_manager.py` | `/baseline`, `/baseline-sv`, `/baselines` |
| `section-evm` | SPI/CPI | `earned_value.py` | `/earned-value` |
| `section-scope-creep` | CR vs baseline scope | `scope_creep.py` | `/scope-creep` |
| `section-duration` | Duration analytics | advanced | |

### API nhanh

```
GET|POST /api/forecast-gantt?slugs=
GET|POST /api/projects/<slug>/forecast-manpower
GET|POST /api/projects/<slug>/estimate-ratio
GET|PUT  /api/projects/<slug>/estimation-params
GET     /api/pic-overload?grain=day|week|month
GET|PUT /api/projects/<slug>/baseline
GET     /api/projects/<slug>/baseline-sv
GET     /api/projects/<slug>/completion-forecast
GET     /api/projects/<slug>/earned-value
GET     /api/projects/<slug>/scope-creep
GET     /api/projects/<slug>/pmo-risk
GET     /api/projects/<slug>/uat-quality
GET     /api/projects/<slug>/pic-upcoming
POST    /api/projects/<slug>/fl-reimport-verify
GET     /api/projects/<slug>/function-diff
GET     /api/projects/<slug>/fid-check
GET     /api/projects/<slug>/duration-flag?threshold=&phase=
GET     /api/projects/<slug>/weekly-gap-report?week_offset=&fitgap=
GET     /api/projects/<slug>/export-weekly-gap
GET     /api/projects/<slug>/export-duration-flag?threshold=&phase=
GET     /api/projects/<slug>/export-source-checklist?lookback=
GET|POST|DELETE /api/projects/<slug>/saved-views
GET|PUT /api/projects/<slug>/tags
POST    /api/projects/<slug>/tags/bulk
```

---

## 4. Chất lượng

| Section | Module | Ghi chú |
|---------|--------|---------|
| Data Quality | `data_quality.py` | Filter Module/severity; help `dataquality` |
| Risk Score | `risk_scorer.py` | + PMO rollup `/pmo-risk` |
| Anomaly | DQ / UI | |
| UAT Quality | `uat_quality.py` | Cột Defect/Feedback/Reopen/Cycle hoặc tag |

---

## 5. Phân tích

| Section | Module |
|---------|--------|
| Quy trình / treemap | process + generic |
| PIC workload | dashboard_engine |
| Priority / Complexity / FIT-GAP | pies + `fitgap_analytics` |
| Effort MH | effort heatmap |
| PIC chậm / Dependency | advanced |
| Kanban tuần | `kanban.py` |
| Function Diff | `function_diff.py` |
| Bookmarks / Tags | `project_store` + `sqlite_store` |

---

## 6. Chiều PM & báo cáo tuần

| Feature | Module | API |
|---------|--------|-----|
| Chiều PM | `pm_store`, `pm_*_parser`, `pm_exporter` | `/api/projects/<slug>/pm*` — Gantt lịch trình UI từ `plan.schedule` (Phase A) |
| MoM tuần | `weekly_mom.py` | `export-weekly-mom` |
| Digest | `digest.py` | Weekly digest |

→ [PM_DIMENSION_GUIDE.md](PM_DIMENSION_GUIDE.md).

---

## 7. Import / Sync / FL round-trip

| Feature | Module | Ghi chú |
|---------|--------|---------|
| Excel upload | `excel_parser` | |
| Mapping Wizard | `column_mapping`, `type_infer` | |
| Integrations sync | `integrations.py` | `verify_ssl`, eager reload |
| FL export template | `fl_export_schema` | |
| FL re-import export | `fl_reimport_export` | Tô vàng/xanh |
| FL re-import verify | `fl_reimport_verify` | So yellow-hit trước/sau |

```
GET  /api/projects/<slug>/export-fl-reimport
POST /api/projects/<slug>/fl-reimport-verify
GET|POST|DELETE /api/projects/<slug>/fl-export-template
```

---

## 8. Export chart thống nhất

**Module:** `exporter/excel_exporter.py` (`export_chart`)

Charts: module_overview, task_type, phase_matrix, phase_stacked, giai_doan, process, burndown, effort_*, duration, pic_workload, priority, complexity, fit_gap, unassigned, risk, overdue, stalled, …

UI: 📥 → **Tổng hợp | Chi tiết | Cả hai** (`mode`).

---

## 9. Multi-project & portfolio

| Feature | Module / API |
|---------|----------------|
| Project CRUD | `project_manager.py` |
| Compare 2–4 project | `portfolio.py` |
| Global search / rollup | `/api/portfolio/*` |
| PIC Overload / Forecast Gantt | cross-slug |

---

## 10. Settings / vận hành / persistence

| Tính năng | Store |
|-----------|--------|
| Capacity, aliases, visibility | JSON (+ settings blob trong `meta.db`) |
| Estimation ratios (BA/Dev seed + hệ số) | `estimation_params.json` (project + optional global) |
| Baseline snapshot id | trong project settings |
| Section / module order | `section_order.json`, `module_order.json` |
| Saved views | `saved_views.json` |
| Bookmarks / tags | JSON **+** `meta.db` dual-write |
| Archive | `archive_settings.json` |
| Public tokens | `.project_store/...` |
| Disk janitor | startup (không UI riêng) |

---

## 11. Sơ đồ phụ thuộc rule (rút gọn)

```
ParsedData
   ├── overdue / unassigned / stalled / data_quality
   ├── rlog_weekly · pic_upcoming · function_diff
   ├── forecast_gantt · forecast_manpower · estimate_ratio · pic_overload
   ├── baseline_sv · completion_forecast · earned_value · scope_creep
   ├── risk_scorer (+ module_dependency cascade) · uat_quality
   ├── gantt_calendar (+ critical path heuristic)
   └── dashboard_engine (module remaining, bottleneck, charts…)
```

---

## 12. Điểm vào khi sửa code

| Muốn sửa… | Mở trước |
|-----------|----------|
| Rule overdue/unassigned/stalled | `analyzer/{overdue,unassigned,stalled}.py` |
| PMO A–F | `baseline_sv`, `completion_forecast`, `earned_value`, `scope_creep`, `risk_scorer`, `uat_quality`, `sqlite_store` |
| BA UX | `function_diff`, `pic_upcoming`, `fl_reimport_verify`, `gantt_calendar`, `dashboard_engine`, FE insight strip |
| Chart metrics chung | `dashboard_engine.py` |
| Parse cột mới | `parser/excel_parser.py` |
| UI section | `templates/index.html` + `dashboard.js` + sidebar group |
| Thứ tự mặc định | `DEFAULT_SECTION_DOM_ORDER` / `DEFAULT_SIDEBAR_GROUP_DEFS` |

---

## Xem thêm

- [SYSTEM_OVERVIEW.md](SYSTEM_OVERVIEW.md)  
- [BUSINESS_LOGIC.md](BUSINESS_LOGIC.md)  
- [CHANGELOG_PMO_BA.md](CHANGELOG_PMO_BA.md)  
- [ARCHITECTURE.md](ARCHITECTURE.md)  
