# Feature Catalog — Map UI · API · Module

> Cập nhật: **2026-07-31**. Catalog để tra cứu “section này do đâu / API nào / rule nào”.

---

## 1. Shell ứng dụng

| Thành phần | Mô tả |
|------------|--------|
| `templates/index.html` | SPA: header, sidebar, sticky filter, mọi section |
| `static/js/dashboard.js` | Logic UI (~18k+ LOC) |
| `static/js/i18n.js` | VI/EN |
| `static/js/help_content.js` | Help `?` + Ctrl+/ |
| `static/css/style.css` | Sticky, toolbar, Gantt, treemap… |
| `app.py` | Toàn bộ HTTP routes |

**Header toolbar:** nhóm Import/Sync · Xuất ▾ · View · Thêm ▾ (không rainbow).  
**Sidebar:** dropdown nhóm + All; ⚙ chỉnh nhóm VI/EN + chuyển section.

---

## 2. Tracking — tiến độ & vấn đề

| Section ID | UI | Backend / metrics | Ghi chú |
|------------|----|--------------------|---------|
| `section-summary` | Cards tổng quan | `DashboardEngine` summary | Sticky compact |
| `section-globalfilter` | Module/Process/PIC/Project | `_filter_parsed_data` | Luôn hiện khi lọc nhóm |
| `section-module` | Bảng tiến độ module | module overview | Group Module/Process |
| `section-tasktype` | Bar % Closed theo công việc | task_type metrics | Export Chi_tiet status |
| `section-matrix` | Phase × Module heatmap | phase matrix | |
| `section-phase` | Stacked status × phase | phase stacked | |
| `section-giaidoan` | % Closed × giai đoạn | giai đoạn chart | Legend padding |
| `section-rlog` | Rlog coded / plan tuần | `rlog_weekly.py` | Đầu Tracking sau progress |
| `section-overdue` | Bảng trễ | `overdue.py` | Filter + cột picker |
| `section-unassigned` | Thiếu PIC | `unassigned.py` | Pred Closed + Start; Rlog ID |
| `section-stalled` | Đình trệ | `stalled.py` | End quá hạn; fully-closed exclude |
| `section-aging-wip` | WIP già | `advanced_metrics` | |
| `section-sla` | Vi phạm SLA | advanced | |

---

## 3. Forecast

| Section ID | UI | Backend | Export |
|------------|----|---------|--------|
| `section-gantt` | Timeline Gantt-style | timeline_data + FE filter | chart export |
| `section-forecast-gantt` | UAT/Golive theo tháng + nested MS | `forecast_gantt.py` | `forecast_gantt_exporter` |
| `section-forecast-manpower` | MH/MD/MM + tuyển | `forecast_manpower.py` | Tong_hop / Chi_tiet |
| `section-gantt-calendar` | Calendar Excel-style | `gantt_calendar.py` | |
| `section-burndown` | Burndown / velocity | advanced | |
| `section-capacity` | Remaining MH vs capacity | `compute_capacity_load` | |
| `section-pic-overload` | Overload đa dự án | `pic_overload.py` | + optional FL |
| `section-baseline` | Variance baseline | advanced | |
| `section-duration` | Duration analytics | advanced | |

### API Forecast Manpower

```
GET|POST /api/projects/<slug>/forecast-manpower
  ?basis=unit|duration
  &unit=manhour|manday|manmonth
  &default_mh=8&target_months=1
  &hc_dev=0&hc_impl_shared=0
  &module=&process=&pic=

GET|POST /api/projects/<slug>/export-forecast-manpower?mode=summary|detail|both
```

### API Forecast Gantt

```
GET|POST /api/forecast-gantt?slugs=a,b
GET|POST /api/forecast-gantt/export
```

### API PIC Overload

```
GET /api/pic-overload?grain=day|week|month&from=&to=
GET|PUT /api/pic-overload/settings
POST /api/pic-overload/export
```

---

## 4. Chất lượng

| Section | Module | Ghi chú |
|---------|--------|---------|
| Data Quality | `data_quality.py` | Filter Module/severityity/type; skip Config Local↔UAT overlap |
| Risk Score | `risk_scorer.py` | |
| Anomaly | data_quality / UI card | |

---

## 5. Phân tích

| Section | Module |
|---------|--------|
| Quy trình | process analysis + treemap contrast |
| PIC workload | dashboard_engine |
| Priority / Complexity / FIT-GAP | pies + `fitgap_analytics` |
| Effort MH | effort heatmap |
| PIC chậm / Dependency | advanced |
| Kanban tuần | `kanban.py` — local filter **AND** global |
| Function Diff | `function_diff.py` |
| Bookmarks | project_store |

---

## 6. Chiều PM & báo cáo tuần

| Feature | Module | API / UI |
|---------|--------|----------|
| Chiều PM | `pm_store`, `pm_*_parser`, `pm_exporter` | `/api/projects/<slug>/pm*` |
| MoM tuần | `weekly_mom.py` | `export-weekly-mom` + nút Xuất MoM |
| Digest | `digest.py` | Weekly digest section |

---

## 7. Import / Sync / Mapping

| Feature | Module | Ghi chú |
|---------|--------|---------|
| Excel upload | `excel_parser` | |
| Column Mapping Wizard | `column_mapping`, `type_infer` | |
| Integrations sync | `integrations.py` | auth + verify_ssl + project param |
| FL export template | `fl_export_schema` | Settings upload + DnD review |
| FL re-import export | `fl_reimport_export` | Issues → FL tô màu |

```
GET  /api/projects/<slug>/export-fl-reimport
GET|POST|DELETE /api/projects/<slug>/fl-export-template
```

---

## 8. Export chart thống nhất

**Module:** `exporter/excel_exporter.py` (`export_chart`)

Charts: `module_overview`, `task_type`, `phase_matrix`, `phase_stacked`, `giai_doan`, `process`, `burndown`, `effort_*`, `duration`, `pic_workload`, `priority`, `complexity`, `fit_gap`, `unassigned`, `risk`, `overdue`, `stalled`, …

UI: 📥 → **Tổng hợp | Chi tiết | Cả hai** (`mode`).

---

## 9. Multi-project & portfolio

| Feature | Module / API |
|---------|----------------|
| Project CRUD | `project_manager.py` |
| Compare 2–4 project | `portfolio.py` |
| Global search | `/api/portfolio/search` |
| Rollup | `/api/portfolio/rollup` |
| PIC Overload / Forecast Gantt | cross-slug |

---

## 10. Settings / vận hành

| Tab / tính năng | Store / module |
|-----------------|----------------|
| Capacity, aliases, visibility | `project_store` |
| Section order | `section_order.json` + `DEFAULT_SECTION_DOM_ORDER` |
| Module order | `module_order.json` |
| Archive | `archive_manager` |
| Public tokens | `public_api` |
| LAN bind | `lan_security.resolve_bind_host` |
| Snapshot history + Nguồn | `snapshot_manager` |

---

## 11. Sơ đồ phụ thuộc rule (rút gọn)

```
ParsedData
   ├── overdue ──────────────► summary card + bảng + MoM Risk
   ├── unassigned ───────────► card + DQ gate + MoM Risk + FL reimport
   ├── stalled ──────────────► funnel/table + MoM Risk + FL reimport
   ├── data_quality ─────────► DQ UI + MoM Risk
   ├── rlog_weekly ──────────► Rlog section + export
   ├── forecast_gantt ───────► Forecast UAT/Golive
   ├── forecast_manpower ────► Forecast Manpower
   ├── pic_overload ─────────► cross-project (nhiều ParsedData)
   └── dashboard_engine ─────► hầu hết chart còn lại
```

---

## 12. File code “điểm vào” khi sửa

| Muốn sửa… | Mở trước |
|-----------|----------|
| Rule overdue/unassigned/stalled | `analyzer/{overdue,unassigned,stalled}.py` |
| Chart metrics chung | `analyzer/dashboard_engine.py` |
| Parse cột mới | `parser/excel_parser.py` |
| Export MoM / FL / Manpower | `exporter/weekly_mom.py`, `fl_reimport_export.py`, `forecast_manpower_exporter.py` |
| UI section mới | `templates/index.html` + `dashboard.js` + sidebar group |
| Thứ tự mặc định | `DEFAULT_SECTION_DOM_ORDER` trong `dashboard.js` |
| Bind/LAN | `analyzer/lan_security.py`, `app.py` |

---

## Xem thêm

- [SYSTEM_OVERVIEW.md](SYSTEM_OVERVIEW.md)  
- [BUSINESS_LOGIC.md](BUSINESS_LOGIC.md)  
- [ARCHITECTURE.md](ARCHITECTURE.md)  
- [DASHBOARD_SPEC.md](DASHBOARD_SPEC.md)  
