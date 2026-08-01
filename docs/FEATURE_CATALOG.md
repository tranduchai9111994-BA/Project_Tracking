# Feature Catalog — Checklist · UI · API · Module

> Cập nhật: **2026-08-01**. Dùng để tra cứu “đã ship gì / section nào / API nào”.  
> Rule chi tiết → [BUSINESS_LOGIC.md](BUSINESS_LOGIC.md).

---

## 0. Checklist trạng thái (cho review)

### Core

| Feature | Status | Module / UI |
|---------|--------|-------------|
| Auto-detect cột FL + phase `Name - Attr` | ✅ | `parser/excel_parser.py` |
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
| 10 | Rlog visibility | 🔶 | Section + counts đầy đủ; không badge kiểu DQ khắp nơi |
| 11 | Module còn lại (count + MH) | ✅ | `module_overview.remaining` / `remaining_mh` |
| — | Insight strip collapse | ✅ | `ihrp.insightStrip.expanded` |
| — | DQ help topic | ✅ | `help_content.js` → `dataquality` |

---

## 1. Shell ứng dụng

| Thành phần | Mô tả |
|------------|--------|
| `templates/index.html` | SPA: header, sidebar, sticky filter, sections |
| `static/js/dashboard.js` | Logic UI |
| `static/js/i18n.js` | VI/EN |
| `static/js/help_content.js` | Help `?` + Ctrl+/ |
| `static/css/style.css` | Sticky, toolbar, Gantt… |
| `app.py` | ~100 HTTP routes |

**Header:** Import/Sync · Xuất ▾ · View · Thêm ▾ · Settings · Help.  
**Sidebar:** nhóm Tracking / Forecast / Chất lượng / Phân tích / Chiều PM / Quản trị + All.  
**Insight strip:** chip tóm tắt + toggle collapse.

---

## 2. Tracking

| Section ID | UI | Backend | Ghi chú |
|------------|----|---------|---------|
| `section-summary` | Cards tổng quan | `DashboardEngine` | Sticky compact |
| `section-globalfilter` | Module/Process/PIC/Project | `_filter_parsed_data` | Luôn hiện khi lọc nhóm |
| `section-module` | Bảng tiến độ module | module overview | Cột **còn lại** / MH còn lại |
| `section-tasktype` | % Closed theo công việc | task_type | |
| `section-matrix` | Phase × Module | phase matrix | DQ badge + bottleneck |
| `section-phase` | Stacked status × phase | | Bottleneck highlight |
| `section-giaidoan` | % Closed × giai đoạn | | |
| `section-rlog` | Rlog coded / plan tuần | `rlog_weekly.py` | |
| `section-overdue` | Bảng trễ | `overdue.py` | |
| `section-unassigned` | Thiếu PIC | `unassigned.py` | |
| `section-stalled` | Đình trệ | `stalled.py` | |
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
| `section-baseline` | Baseline SV | `baseline_sv.py` + advanced variance | `/baseline`, `/baseline-sv` |
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
| Chiều PM | `pm_store`, `pm_*_parser`, `pm_exporter` | `/api/projects/<slug>/pm*` |
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
