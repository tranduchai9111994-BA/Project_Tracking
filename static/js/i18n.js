/**
 * i18n client — VI/EN bilingual cho chrome UI + exports + toast chính.
 *
 * Persist: localStorage 'ihrp_lang' (+ sync project setting khi có API).
 * Coverage: header/nav/summary/filters/overdue/risk/DQ/toasts chính.
 * String thiếu → fallback VI hoặc trả key.
 *
 * Quy ước: pack VI = tiếng Việt đầy đủ cho chrome; pack EN = English.
 * Giữ nguyên tên sản phẩm (iHRP), acronym (SLA/EVM/PIC/UAT) và Status enum
 * từ Function List khi là chuẩn dữ liệu.
 */
(function (global) {
    "use strict";

    const STORAGE_KEY = "ihrp_lang";
    const DEFAULT_LANG = "vi";

    const STRINGS = {
        vi: {
            "app.subtitle": "Dashboard theo dõi tiến độ dự án triển khai (đa dự án · drill-down · bộ lọc chung)",
            "hdr.file": "File:",
            "hdr.total_prefix": "Tổng:",
            "hdr.total_suffix": "chức năng",
            "hdr.upload": "Tải lên",

            "nav.summary": "Tổng quan",
            "nav.search_ph": "Tìm section… Ctrl+/",
            "nav.module_progress": "Tiến độ module",
            "nav.issues": "Issues",
            "nav.risk_hub": "Risk",
            "nav.timeline_hub": "Timeline",
            "nav.weekly": "Hoạt động tuần",
            "nav.plan": "Kế hoạch",
            "nav.manpower_hub": "Nhân lực",
            "nav.analysis_hub": "Phân tích",
            "nav.admin_hub": "Quản trị",
            "btn.import_menu": "⬆ Tải Excel",
            "issue_focus.label": "Nhóm vấn đề",
            "btn.view_menu": "👁 View ▾",
            "card.dq_high": "DQ High",
            "nav.module": "Phân hệ",
            "nav.tasktype": "Công việc",
            "nav.matrix": "Ma trận Phase",
            "nav.phase": "Phase xếp chồng",
            "nav.giaidoan": "Giai đoạn",
            "nav.gantt": "Timeline",
            "nav.forecast_gantt": "Dự báo UAT/Golive",
            "nav.forecast_manpower": "Dự báo nhân lực",
            "nav.estimate_ratio": "Ước lượng hệ số",
            "nav.gantt_calendar": "Lịch Gantt",
            "nav.burndown": "Burndown",
            "nav.rlog": "Rlog tuần",
            "nav.overdue": "Trễ hạn",
            "nav.unassigned": "Chưa PIC",
            "nav.stalled": "Đình trệ",
            "nav.risk": "Điểm rủi ro",
            "nav.aging": "WIP tồn đọng",
            "nav.sla": "SLA",
            "nav.dq": "Chất lượng dữ liệu",
            "nav.anomaly": "Bất thường",
            "nav.process": "Quy trình",
            "nav.capacity": "Năng lực",
            "nav.pic_overload": "PIC quá tải",
            "nav.pic_upcoming": "PIC tuần tới",
            "nav.baseline": "Baseline",
            "nav.evm": "EVM",
            "nav.exec": "Điều hành",
            "nav.scope_creep": "Phạm vi phình",
            "nav.uat_quality": "Chất lượng UAT",
            "nav.effort": "Effort MH",
            "nav.duration": "Thời lượng",
            "nav.slow": "PIC chậm",
            "nav.deps": "Phụ thuộc",
            "nav.kanban": "Kanban",
            "nav.pic": "PIC",
            "nav.priority": "Độ ưu tiên",
            "nav.fitgap": "FIT/GAP",
            "nav.diff": "Diff",
            "nav.bookmarks": "Đánh dấu",
            "nav.pm": "Chiều PM",
            "nav.compare": "So sánh",
            "nav.digest": "Digest tuần",
            "nav.my_digests": "Digest lưu trữ",
            "nav.custom_dash": "Dashboard tuỳ chỉnh",
            "nav.history": "Lịch sử upload",
            "section.custom_dash": "🎨 Dashboard tuỳ chỉnh",

            "section.forecast_gantt_title": "📆 Dự báo — UAT / Golive theo tháng",
            "section.forecast_gantt_sub": "Với hiện trạng Function List: tháng dự kiến UAT / Golive với KH (Gantt theo tháng). 1 dự án: thêm Phân tích / Dev / Cấu hình xong.",
            "fg.projects": "Dự án",
            "fg.row_project": "Hàng = Dự án",
            "fg.row_milestone": "Hàng = Milestone",
            "fg.col_project": "Dự án",
            "fg.col_milestone": "Milestone",
            "fg.meta_pct": "%",
            "fg.meta_sv": "SV",
            "fg.meta_remain": "Còn",
            "fg.meta_head_tip": "% hoàn thành · SV (ngày) · Số còn lại",
            "fg.tip_start": "Start",
            "fg.tip_forecast": "Forecast end",
            "fg.tip_closed": "Closed",
            "fg.tip_remain": "Còn lại",
            "fg.tip_baseline": "Baseline",
            "fg.tip_overdue": "Quá hạn — còn việc chưa Closed",
            "fg.legend_baseline": "Baseline (ghost)",
            "fg.legend_no_baseline": "Baseline: chưa gắn snapshot",
            "fg.legend_forecast": "Tháng forecast ◆",
            "fg.legend_overdue": "Quá hạn (chưa Closed)",
            "section.rlog_title": "🧾 Rlog coded tuần này & kế hoạch tuần tới",
            "section.pm_title": "📐 Chiều PM",
            "section.pm_sub": "Kế hoạch dự án (Excel) + báo cáo tuần (PPT) — milestone, lịch trình, rủi ro, tiến độ tuần.",
            "btn.export_pm": "📥 Xuất chiều PM",
            "btn.settings": "⚙️ Cài đặt",
            "btn.settings_title": "Cài đặt: thứ tự Phân hệ, ngưỡng, WIP tồn đọng, digest, nhắc nhở…",
            "btn.export_pdf": "📄 Xuất PDF",
            "btn.export_pdf_title": "Xuất PDF báo cáo tuần (client-side)",
            "btn.export_issues": "📊 Xuất vấn đề",
            "btn.export_issues_title": "Xuất Excel 1 file chứa mọi loại vấn đề",
            "btn.export_fl_reimport": "📥 Xuất FL chỉnh sửa",
            "btn.export_fl_reimport_title": "Xuất Function List chỉ CN dính issue — re-import được (tô vàng PIC/Status)",
            "btn.export_weekly_mom": "📋 Xuất MoM tuần",
            "btn.export_weekly_mom_title": "Xuất Excel báo cáo tuần MoM (Cover + Master plan + biên bản họp + PM Dashboard)",
            "toast.exporting_fl_reimport": "📥 Đang tạo FL re-import…",
            "toast.export_fl_reimport_fail": "❌ Lỗi khi xuất FL chỉnh sửa",
            "btn.export_menu": "📥 Xuất ▾",
            "btn.export_menu_title": "Xuất báo cáo (PDF, vấn đề, MoM tuần)",
            "btn.more_menu": "⋯ Thêm ▾",
            "btn.more_menu_title": "Thêm thao tác (dashboard, API, trợ giúp, cài đặt)",
            "btn.present": "🎬 Trình chiếu",
            "btn.present_title": "Chế độ trình chiếu (1 section/lần, ← → điều hướng, Esc thoát)",
            "btn.help": "❓ Trợ giúp",
            "btn.help_title": "Trợ giúp toàn hệ thống (Ctrl+/)",
            "btn.integrations": "🔌 API Registry",
            "btn.integrations_title": "Registry API: cấu hình + đồng bộ dữ liệu từ ứng dụng nguồn",
            "btn.sync": "🔄 Đồng bộ ▾",
            "btn.sync_title": "Đồng bộ nhanh từ 1 endpoint đã cấu hình",
            "btn.upload_excel": "⬆ Tải Excel",
            "btn.upload_excel_title": "Hiện vùng kéo thả Function List (tải Excel tay)",
            "btn.upload_collapse": "▴ Thu gọn tải file",
            "btn.upload_collapse_title": "Thu gọn vùng tải file (ưu tiên Đồng bộ)",
            "btn.layout_edit": "🔧 Chỉnh thứ tự",
            "btn.layout_edit_title": "Bật/tắt kéo thả chỉnh thứ tự section",
            "btn.layout_reset": "↺ Mặc định",
            "btn.layout_reset_title": "Khôi phục thứ tự mặc định",
            "btn.custom_dash": "➕ Dashboard",
            "btn.custom_dash_title": "Tạo dashboard biểu đồ mới (wizard hoặc chat)",
            "btn.lang": "VI",
            "btn.lang_title": "Ngôn ngữ hiện tại: Tiếng Việt — bấm để chuyển sang English",
            "card.total": "Tổng chức năng",
            "card.progress": "Đóng phase cuối",
            "card.overdue": "Chức năng trễ hạn",
            "card.unassigned": "Chức năng chưa PIC",
            "card.missing_deadline": "Chưa cập nhật hạn",
            "card.high_risk": "Rủi ro cao (≥50 điểm)",
            "card.modules": "Số phân hệ",
            "card.anomaly": "Bất thường",
            "section.summary": "📋 Tổng quan dự án",
            "section.overdue": "⚠️ Trễ hạn",
            "section.overdue_title": "⚠️ Danh sách trễ hạn",
            "section.unassigned": "👤 Chưa có PIC",
            "section.stalled": "🛑 Đình trệ",
            "section.dq": "🩺 Chất lượng dữ liệu",
            "section.dq_sub": "Phát hiện dữ liệu lỗi/thiếu (gồm WIP thiếu End/hạn) để clean trước khi báo cáo",
            "section.anomaly": "🚨 Bất thường",
            "section.risk_title": "⚡ Top chức năng có điểm rủi ro cao",
            "section.risk_sub": "Điểm 0–100 gồm yếu tố cũ + <b>PIC quá tải</b> (+15) + <b>cascade delay phân hệ</b> (+10). Chiều Nguồn lực / Phụ thuộc bên dưới phục vụ góc nhìn PM.",
            "section.aging_title": "⏳ WIP tồn đọng",
            "section.aging_sub": "Task In-progress quá lâu (kể từ Start) → cần push",

            "risk.cross_project": "Quá tải đa dự án",
            "risk.cross_project_title": "Gộp PIC quá tải đa dự án vào điểm rủi ro",
            "risk.detail": "Chi tiết",
            "risk.dim_high": "Rủi ro cao (≥50)",
            "risk.dim_resource": "Nguồn lực (PIC quá tải)",
            "risk.dim_resource_pic": "PIC",
            "risk.dim_dep": "Phụ thuộc (cascade)",
            "risk.dim_dep_sub": "phân hệ bị chặn",
            "risk.dim_lq": "CN LQ bị chặn",
            "risk.dim_lq_sub": "Must-have bị chặn",
            "risk.trend": "Xu hướng rủi ro (snapshot)",
            "risk.by_module": "Theo phân hệ · ghi chú công thức",
            "risk.th_score": "Điểm rủi ro",
            "risk.th_factors": "Yếu tố rủi ro",
            "risk.th_mitigation": "Biện pháp giảm thiểu",
            "risk.owner": "Người phụ trách",
            "risk.note": "Ghi chú giảm thiểu",
            "risk.empty": "Không có chức năng rủi ro",
            "risk.viewing": "Đang xem {start}–{end}/{total} chức năng rủi ro",
            "risk.toast_saved": "Đã lưu biện pháp giảm thiểu",
            "risk.toast_err": "Lỗi giảm thiểu: {msg}",
            "risk.cascade_title": "⚠ Cascade delay ({n})",
            "risk.cascade_more": "… và {n} cảnh báo khác",
            "risk.no_module": "Không có phân hệ.",
            "risk.mod_avg": "TB rủi ro",
            "risk.mod_max": "Max",
            "risk.mod_high": "Cao≥50",
            "risk.mod_resource": "Nguồn lực",
            "risk.mod_dep": "Phụ thuộc",
            "risk.chart_avg": "Điểm TB",
            "risk.chart_high": "Số rủi ro cao",
            "risk.factor.must_have": "Must-have",
            "risk.factor.should_have": "Should-have",
            "risk.factor.complexity_high": "Độ phức tạp cao",
            "risk.factor.phase_overdue": "Có phase trễ hạn",
            "risk.factor.days_late": "Trễ {n} ngày",
            "risk.factor.no_pic": "Không có PIC",
            "risk.factor.duration": "Thời lượng bất thường",
            "risk.factor.stalled": "Bị đình trệ",
            "risk.factor.risk_note": "Có ghi chú rủi ro",
            "risk.factor.pic_overload": "PIC quá tải",
            "risk.factor.cascade": "Cascade delay từ",

            "filter.analyze_by": "🎯 Phân tích theo:",
            "filter.module": "Phân hệ",
            "filter.process": "Quy trình",
            "filter.pic": "PIC",
            "filter.project_code": "Mã dự án",
            "filter.all_module": "Tất cả phân hệ",
            "filter.all_process": "Tất cả quy trình",
            "filter.all_pic": "Tất cả PIC",
            "filter.all_project_code": "Tất cả mã dự án",
            "filter.module_order": "⚙ Thứ tự",
            "filter.module_order_title": "Cấu hình số thứ tự Phân hệ hiển thị trên toàn dashboard",
            "filter.clear_all": "✕ Bỏ tất cả",
            "filter.save_view": "💾 Lưu",
            "filter.save_view_title": "Lưu bộ lọc hiện tại",
            "filter.saved_views": "📂 View đã lưu…",
            "filter.n_selected": "{n} đã chọn",
            "filter.select_all": "☑ Chọn tất cả",
            "filter.deselect_all": "☐ Bỏ chọn",
            "filter.search": "🔍 Tìm...",
            "gantt.week": "Tuần",
            "gantt.month": "Tháng",
            "gantt.quarter": "Quý",
            "gantt.compact_label": "⇔ Rút gọn nhãn",
            "gantt.filter_status": "Status",
            "gantt.all_status": "Tất cả Status",
            "gantt.filter_phase": "Phase",
            "gantt.all_phase": "Tất cả Phase",
            "gantt.filter_priority": "Độ ưu tiên",
            "gantt.all_priority": "Tất cả độ ưu tiên",
            "gantt.open_only": "Chỉ còn việc mở",
            "gantt.date_all": "Tất cả",
            "gantt.date_has": "Có ngày",
            "gantt.date_none": "Chưa có ngày",
            "chart.vm_pct": "%",
            "chart.vm_count": "SL",
            "chart.vm_title": "Hiển thị phần trăm (%) hoặc số lượng (SL)",
            "matrix.bottleneck": "Bottleneck (stuck)",
            "matrix.bottleneck_tip": "Module/QT còn phase ≠ Closed và (overdue hoặc stalled)",
            "th.code": "Mã CN",
            "th.name": "Tên chức năng",
            "th.name_short": "Tên CN",
            "th.module": "Phân hệ",
            "th.phase": "Phase",
            "th.deadline": "Hạn",
            "th.days_late": "Ngày trễ",
            "th.status": "Status",
            "th.pic": "PIC",
            "th.priority": "Độ ưu tiên",
            "btn.export_excel": "📥 Xuất Excel",
            "toast.exported": "Đã xuất file",
            "toast.exporting_issues": "📊 Đang tạo file Excel tổng hợp vấn đề…",
            "toast.export_fail": "❌ Lỗi khi xuất báo cáo tổng hợp",
            "toast.no_project": "⚠️ Chưa chọn project",
            "toast.lang_vi": "Ngôn ngữ: Tiếng Việt",
            "toast.lang_en": "Language: English",
            "settings.lang": "🌐 Ngôn ngữ giao diện",
            "settings.lang_hint": "Áp dụng cho UI + tên sheet/header khi xuất Excel/PDF.",
            "settings.retention": "🗄️ Số snapshot / lịch sử giữ",
            "settings.retention_hint": "Giữ N bản snapshot + N dòng upload history gần nhất (mặc định 10).",
            "history.cap_hint": "Giữ {n} lần gần nhất",
            "pdf.title": "Báo cáo tuần",
            "sg.all": "Tất cả",
            "sg.select_title": "Lọc theo nhóm dashboard",
            "sg.edit_title": "Hiệu chỉnh nhóm dashboard",
            "sg.modal_title": "Hiệu chỉnh nhóm dashboard",
            "sg.reset": "↺ Mặc định",
            "sg.add": "➕ Thêm nhóm",
            "sg.delete": "Xóa nhóm",
            "sg.save": "Lưu",
            "sg.cancel": "Hủy",
            "sg.name_vi": "Tên (VI)",
            "sg.name_en": "Tên (EN)",
            "sg.move": "Chuyển nhóm",
            "sg.sections": "Dashboard trong nhóm",
            "sg.empty": "Chưa có dashboard",
            "sg.toast_saved": "Đã lưu nhóm dashboard",
            "sg.toast_reset": "Đã khôi phục nhóm mặc định",
            "sg.confirm_delete": "Xóa nhóm này? Dashboard sẽ chuyển sang nhóm đầu tiên.",
            "sg.confirm_reset": "Khôi phục nhóm + phân bổ mặc định?",
            "sg.new_group": "Nhóm mới",
            "sg.new_group_en": "New group",
            "sg.add_more_short": "Thêm",
            "sg.add_more_title": "Thêm dashboard — bật/tắt nhóm Phân tích, Quản trị...",
            "sg.visible_on_dashboard": "Hiện trên dashboard",
            "matrix.bottleneck": "Bottleneck (stuck)",
            "matrix.bottleneck_tip": "Module/QT còn phase ≠ Closed và (overdue hoặc đình trệ)",
            "matrix.bottleneck_title": "Bottleneck (stuck) — Phase {phase}",
        },
        en: {
            "app.subtitle": "Implementation progress dashboard (multi-project · drill-down · global filter)",
            "hdr.file": "File:",
            "hdr.total_prefix": "Total:",
            "hdr.total_suffix": "functions",
            "hdr.upload": "Upload",

            "nav.summary": "Summary",
            "nav.search_ph": "Find section… Ctrl+/",
            "nav.module_progress": "Module progress",
            "nav.issues": "Issues",
            "nav.risk_hub": "Risk",
            "nav.timeline_hub": "Timeline",
            "nav.weekly": "Weekly activity",
            "nav.plan": "Plan",
            "nav.manpower_hub": "Manpower",
            "nav.analysis_hub": "Analysis",
            "nav.admin_hub": "Admin",
            "btn.import_menu": "⬆ Upload Excel",
            "btn.view_menu": "👁 View ▾",
            "card.dq_high": "DQ High",
            "issue_focus.label": "Issue group",
            "nav.module": "Module",
            "nav.tasktype": "Work type",
            "nav.matrix": "Phase Matrix",
            "nav.phase": "Phase Stack",
            "nav.giaidoan": "Stage",
            "nav.gantt": "Timeline",
            "nav.forecast_gantt": "Forecast UAT/Golive",
            "nav.forecast_manpower": "Forecast Manpower",
            "nav.estimate_ratio": "Estimate ratios",
            "nav.gantt_calendar": "Gantt Calendar",
            "nav.burndown": "Burndown",
            "nav.rlog": "Weekly Rlog",
            "nav.overdue": "Overdue",
            "nav.unassigned": "Unassigned",
            "nav.stalled": "Stalled",
            "nav.risk": "Risk Score",
            "nav.aging": "Aging WIP",
            "nav.sla": "SLA",
            "nav.dq": "Data Quality",
            "nav.anomaly": "Anomalies",
            "nav.process": "Process",
            "nav.capacity": "Capacity",
            "nav.pic_overload": "PIC Overload",
            "nav.pic_upcoming": "PIC upcoming",
            "nav.baseline": "Baseline",
            "nav.evm": "EVM",
            "nav.exec": "Executive",
            "nav.scope_creep": "Scope Creep",
            "nav.uat_quality": "UAT Quality",
            "nav.effort": "Effort MH",
            "nav.duration": "Duration",
            "nav.slow": "Slow PIC",
            "nav.deps": "Dependency",
            "nav.kanban": "Kanban",
            "nav.pic": "PIC",
            "nav.priority": "Priority",
            "nav.fitgap": "FIT/GAP",
            "nav.diff": "Diff",
            "nav.bookmarks": "Bookmarks",
            "nav.pm": "PM dimension",
            "nav.compare": "Compare",
            "nav.digest": "Weekly Digest",
            "nav.my_digests": "Saved digests",
            "nav.custom_dash": "Custom dashboards",
            "nav.history": "Upload history",
            "section.custom_dash": "🎨 Custom dashboards",

            "section.forecast_gantt_title": "📆 Forecast — UAT / Golive by month",
            "section.forecast_gantt_sub": "From current Function List: expected UAT / Golive month with client (month Gantt). Single project: also Analysis / Dev / Config done.",
            "fg.projects": "Projects",
            "fg.row_project": "Rows = Project",
            "fg.row_milestone": "Rows = Milestone",
            "fg.col_project": "Project",
            "fg.col_milestone": "Milestone",
            "fg.meta_pct": "%",
            "fg.meta_sv": "SV",
            "fg.meta_remain": "Left",
            "fg.meta_head_tip": "% complete · SV (days) · Remaining count",
            "fg.tip_start": "Start",
            "fg.tip_forecast": "Forecast end",
            "fg.tip_closed": "Closed",
            "fg.tip_remain": "Remaining",
            "fg.tip_baseline": "Baseline",
            "fg.tip_overdue": "Overdue — work still open",
            "fg.legend_baseline": "Baseline (ghost)",
            "fg.legend_no_baseline": "Baseline: no snapshot set",
            "fg.legend_forecast": "Forecast month ◆",
            "fg.legend_overdue": "Overdue (not Closed)",
            "section.rlog_title": "🧾 Rlog coded this week & next-week plan",
            "section.pm_title": "📐 PM dimension",
            "section.pm_sub": "Project plan (Excel) + weekly report (PPT) — milestones, schedule, risks, weekly progress.",
            "btn.export_pm": "📥 Export PM dimension",
            "btn.settings": "⚙️ Settings",
            "btn.settings_title": "Settings: module order, thresholds, aging WIP, digest, reminder…",
            "btn.export_pdf": "📄 Export PDF",
            "btn.export_pdf_title": "Export weekly PDF report (client-side)",
            "btn.export_issues": "📊 Export issues",
            "btn.export_issues_title": "Export one Excel with all issue types",
            "btn.export_fl_reimport": "📥 Export FL for re-import",
            "btn.export_fl_reimport_title": "Export Function List of issue rows only — yellow PIC/Status for fix",
            "btn.export_weekly_mom": "📋 Export weekly MoM",
            "btn.export_weekly_mom_title": "Export weekly MoM Excel (Cover + Master plan + meeting minutes + PM Dashboard)",
            "toast.exporting_fl_reimport": "📥 Building FL re-import…",
            "toast.export_fl_reimport_fail": "❌ Failed to export FL re-import",
            "btn.export_menu": "📥 Export ▾",
            "btn.export_menu_title": "Export reports (PDF, issues, weekly MoM)",
            "btn.more_menu": "⋯ More ▾",
            "btn.more_menu_title": "More actions (dashboard, API, help, settings)",
            "btn.present": "🎬 Present",
            "btn.present_title": "Presentation mode (1 section at a time, ← → navigate, Esc to exit)",
            "btn.help": "❓ Help",
            "btn.help_title": "Global help (Ctrl+/)",
            "btn.integrations": "🔌 API Registry",
            "btn.integrations_title": "API Registry: configure + sync from source apps",
            "btn.sync": "🔄 Sync ▾",
            "btn.sync_title": "Quick sync from a configured endpoint",
            "btn.upload_excel": "⬆ Upload Excel",
            "btn.upload_excel_title": "Show Function List drop zone (manual Excel upload)",
            "btn.upload_collapse": "▴ Collapse upload",
            "btn.upload_collapse_title": "Collapse upload zone (prefer Sync)",
            "btn.layout_edit": "🔧 Reorder",
            "btn.layout_edit_title": "Toggle drag-drop section reorder",
            "btn.layout_reset": "↺ Reset",
            "btn.layout_reset_title": "Restore default section order",
            "btn.custom_dash": "➕ Dashboard",
            "btn.custom_dash_title": "Create a custom chart dashboard",
            "btn.lang": "EN",
            "btn.lang_title": "Current language: English — click to switch to Tiếng Việt",
            "card.total": "Total functions",
            "card.progress": "Last phase Closed",
            "card.overdue": "Overdue functions",
            "card.unassigned": "Unassigned functions",
            "card.missing_deadline": "Missing deadline",
            "card.high_risk": "High-risk (≥50 pts)",
            "card.modules": "Modules",
            "card.anomaly": "Anomalies",
            "section.summary": "📋 Project overview",
            "section.overdue": "⚠️ Overdue",
            "section.overdue_title": "⚠️ Overdue list",
            "section.unassigned": "👤 Unassigned",
            "section.stalled": "🛑 Stalled",
            "section.dq": "🩺 Data Quality",
            "section.dq_sub": "Detect bad/missing data (incl. WIP missing End/deadline) before reporting",
            "section.anomaly": "🚨 Anomalies",
            "section.risk_title": "⚡ Top high-risk functions",
            "section.risk_sub": "Score 0–100 from prior factors + <b>PIC overload</b> (+15) + <b>module cascade delay</b> (+10). Resource / Dependency cards below for the PM view.",
            "section.aging_title": "⏳ Aging WIP",
            "section.aging_sub": "In-progress tasks open too long (from Start) → need push",

            "risk.cross_project": "Cross-project overload",
            "risk.cross_project_title": "Fold multi-project PIC overload into risk score",
            "risk.detail": "Details",
            "risk.dim_high": "High-risk (≥50)",
            "risk.dim_resource": "Resource (PIC overload)",
            "risk.dim_resource_pic": "PIC",
            "risk.dim_dep": "Dependency (cascade)",
            "risk.dim_dep_sub": "modules blocked",
            "risk.dim_lq": "LQ functions blocked",
            "risk.dim_lq_sub": "Must-have blocked",
            "risk.trend": "Risk trend (snapshots)",
            "risk.by_module": "By module · scoring notes",
            "risk.th_score": "Risk Score",
            "risk.th_factors": "Risk factors",
            "risk.th_mitigation": "Mitigation",
            "risk.owner": "Owner",
            "risk.note": "Mitigation note",
            "risk.empty": "No risky functions",
            "risk.viewing": "Showing {start}–{end}/{total} risky functions",
            "risk.toast_saved": "Mitigation saved",
            "risk.toast_err": "Mitigation error: {msg}",
            "risk.cascade_title": "⚠ Cascade delay ({n})",
            "risk.cascade_more": "… and {n} more warnings",
            "risk.no_module": "No modules.",
            "risk.mod_avg": "Avg risk",
            "risk.mod_max": "Max",
            "risk.mod_high": "High≥50",
            "risk.mod_resource": "Resource",
            "risk.mod_dep": "Dependency",
            "risk.chart_avg": "Avg score",
            "risk.chart_high": "High-risk count",
            "risk.factor.must_have": "Must-have",
            "risk.factor.should_have": "Should-have",
            "risk.factor.complexity_high": "High complexity",
            "risk.factor.phase_overdue": "Has overdue phase",
            "risk.factor.days_late": "{n} days late",
            "risk.factor.no_pic": "No PIC",
            "risk.factor.duration": "Unusual duration",
            "risk.factor.stalled": "Stalled",
            "risk.factor.risk_note": "Has risk note",
            "risk.factor.pic_overload": "PIC overload",
            "risk.factor.cascade": "Cascade delay from",

            "filter.analyze_by": "🎯 Analyze by:",
            "filter.module": "Module",
            "filter.process": "Process",
            "filter.pic": "PIC",
            "filter.project_code": "Project code",
            "filter.all_module": "All modules",
            "filter.all_process": "All processes",
            "filter.all_pic": "All PICs",
            "filter.all_project_code": "All project codes",
            "filter.module_order": "⚙ Order",
            "filter.module_order_title": "Configure Module display order across the dashboard",
            "filter.clear_all": "✕ Clear all",
            "filter.save_view": "💾 Save",
            "filter.save_view_title": "Save current filters",
            "filter.saved_views": "📂 Saved views…",
            "filter.n_selected": "{n} selected",
            "filter.select_all": "☑ Select all",
            "filter.deselect_all": "☐ Clear",
            "filter.search": "🔍 Search...",
            "gantt.week": "Week",
            "gantt.month": "Month",
            "gantt.quarter": "Quarter",
            "gantt.compact_label": "⇔ Compact labels",
            "gantt.filter_status": "Status",
            "gantt.all_status": "All Status",
            "gantt.filter_phase": "Phase",
            "gantt.all_phase": "All Phases",
            "gantt.filter_priority": "Priority",
            "gantt.all_priority": "All Priorities",
            "gantt.open_only": "Open work only",
            "gantt.date_all": "All",
            "gantt.date_has": "Has date",
            "gantt.date_none": "No date",
            "chart.vm_pct": "%",
            "chart.vm_count": "Qty",
            "chart.vm_title": "Show percentage (%) or quantity (Qty)",
            "matrix.bottleneck": "Bottleneck (stuck)",
            "matrix.bottleneck_tip": "Module/process still open on phase and (overdue or stalled)",
            "th.code": "Code",
            "th.name": "Function name",
            "th.name_short": "Name",
            "th.module": "Module",
            "th.phase": "Phase",
            "th.deadline": "Deadline",
            "th.days_late": "Days late",
            "th.status": "Status",
            "th.pic": "PIC",
            "th.priority": "Priority",
            "btn.export_excel": "📥 Export Excel",
            "toast.exported": "File exported",
            "toast.exporting_issues": "📊 Building all-issues Excel…",
            "toast.export_fail": "❌ Failed to export all-issues report",
            "toast.no_project": "⚠️ No project selected",
            "toast.lang_vi": "Ngôn ngữ: Tiếng Việt",
            "toast.lang_en": "Language: English",
            "settings.lang": "🌐 UI language",
            "settings.lang_hint": "Applies to UI + Excel/PDF sheet names and headers.",
            "settings.retention": "🗄️ Snapshot / history retention",
            "settings.retention_hint": "Keep N newest snapshots + N upload-history rows (default 10).",
            "history.cap_hint": "Keep last {n} uploads",
            "pdf.title": "Weekly report",
            "sg.all": "All",
            "sg.select_title": "Filter by dashboard group",
            "sg.edit_title": "Edit dashboard groups",
            "sg.modal_title": "Edit dashboard groups",
            "sg.reset": "↺ Defaults",
            "sg.add": "➕ Add group",
            "sg.delete": "Delete group",
            "sg.save": "Save",
            "sg.cancel": "Cancel",
            "sg.name_vi": "Name (VI)",
            "sg.name_en": "Name (EN)",
            "sg.move": "Move to group",
            "sg.sections": "Dashboards in group",
            "sg.empty": "No dashboards",
            "sg.toast_saved": "Dashboard groups saved",
            "sg.toast_reset": "Restored default groups",
            "sg.confirm_delete": "Delete this group? Dashboards move to the first group.",
            "sg.confirm_reset": "Reset groups and membership to defaults?",
            "sg.new_group": "Nhóm mới",
            "sg.new_group_en": "New group",
            "sg.add_more_short": "More",
            "sg.add_more_title": "Add more dashboards — toggle Analysis, Admin groups...",
            "sg.visible_on_dashboard": "Visible on dashboard",
            "matrix.bottleneck": "Bottleneck (stuck)",
            "matrix.bottleneck_tip": "Module/process still open on phase ≠ Closed and (overdue or stalled)",
            "matrix.bottleneck_title": "Bottleneck (stuck) — Phase {phase}",
        },
    };

    /** Map chuỗi factor từ backend → key i18n (hoặc pattern). */
    const RISK_FACTOR_EXACT = {
        "Must-have": "risk.factor.must_have",
        "Should-have": "risk.factor.should_have",
        "Complexity cao": "risk.factor.complexity_high",
        "Có phase overdue": "risk.factor.phase_overdue",
        "Không có PIC": "risk.factor.no_pic",
        "Duration bất thường": "risk.factor.duration",
        "Bị đình trệ": "risk.factor.stalled",
        "Có risk note": "risk.factor.risk_note",
    };

    let currentLang = DEFAULT_LANG;

    function normalize(lang) {
        const s = String(lang || "").trim().toLowerCase();
        return s.startsWith("en") ? "en" : "vi";
    }

    function getLang() {
        return currentLang;
    }

    function t(key, vars) {
        const pack = STRINGS[currentLang] || STRINGS.vi;
        let text = pack[key];
        if (text == null) text = STRINGS.vi[key];
        if (text == null) return key;
        if (vars && typeof vars === "object") {
            return text.replace(/\{(\w+)\}/g, (_, k) =>
                vars[k] != null ? String(vars[k]) : `{${k}}`
            );
        }
        return text;
    }

    /**
     * Localize nhãn risk factor từ backend (giữ nguyên dữ liệu gốc).
     * Must-have / Should-have giữ loanword (chuẩn Priority Excel).
     */
    function riskFactor(raw) {
        const s = String(raw || "");
        const exactKey = RISK_FACTOR_EXACT[s];
        if (exactKey) return t(exactKey);
        let m = /^Trễ (\d+) ngày$/.exec(s);
        if (m) return t("risk.factor.days_late", { n: m[1] });
        m = /^PIC overload:\s*(.+)$/.exec(s);
        if (m) return `${t("risk.factor.pic_overload")}: ${m[1]}`;
        m = /^Cascade delay từ\s*(.+)$/.exec(s);
        if (m) return `${t("risk.factor.cascade")} ${m[1]}`;
        return s;
    }

    function applyI18n(root) {
        const scope = root || document;
        scope.querySelectorAll("[data-i18n]").forEach((el) => {
            const key = el.getAttribute("data-i18n");
            if (!key) return;
            const attr = el.getAttribute("data-i18n-attr");
            const val = t(key);
            // Thiếu key → giữ text HTML fallback, không lộ key thô (vd btn.xxx)
            if (val === key) return;
            if (attr) {
                el.setAttribute(attr, val);
            } else {
                el.textContent = val;
            }
        });
        scope.querySelectorAll("[data-i18n-html]").forEach((el) => {
            const key = el.getAttribute("data-i18n-html");
            if (!key) return;
            const val = t(key);
            if (val === key) return;
            el.innerHTML = val;
        });
        // Title riêng (khi data-i18n đã dùng cho textContent)
        scope.querySelectorAll("[data-i18n-title]").forEach((el) => {
            const key = el.getAttribute("data-i18n-title");
            if (!key) return;
            const val = t(key);
            if (val === key) return;
            el.setAttribute("title", val);
        });
        // Placeholder
        scope.querySelectorAll("[data-i18n-placeholder]").forEach((el) => {
            const key = el.getAttribute("data-i18n-placeholder");
            if (!key) return;
            const val = t(key);
            if (val === key) return;
            el.setAttribute("placeholder", val);
        });
        // Toggle hiện ngôn ngữ ĐANG CHỌN (EN khi English, VI khi Tiếng Việt)
        const btn = document.getElementById("btnLangToggle");
        if (btn) {
            btn.textContent = t("btn.lang");
            btn.title = t("btn.lang_title");
            btn.setAttribute("aria-label", t("btn.lang_title"));
        }
        const langEl = document.getElementById("setUiLang");
        if (langEl && langEl.value !== currentLang) langEl.value = currentLang;
        document.documentElement.lang = currentLang;
    }

    function setLang(lang, opts) {
        const next = normalize(lang);
        currentLang = next;
        try {
            localStorage.setItem(STORAGE_KEY, next);
        } catch (_) { /* ignore */ }
        applyI18n();
        if (!(opts && opts.silent) && typeof global.showToast === "function") {
            global.showToast(t(next === "en" ? "toast.lang_en" : "toast.lang_vi"));
        }
        // Cho phép dashboard re-render labels động
        if (typeof global.onLangChanged === "function") {
            try { global.onLangChanged(next); } catch (_) { /* ignore */ }
        }
        return next;
    }

    function toggleLang() {
        return setLang(currentLang === "vi" ? "en" : "vi");
    }

    function init() {
        let saved = DEFAULT_LANG;
        try {
            saved = localStorage.getItem(STORAGE_KEY) || DEFAULT_LANG;
        } catch (_) { /* ignore */ }
        currentLang = normalize(saved);
        applyI18n();
    }

    global.I18n = {
        t,
        getLang,
        setLang,
        toggleLang,
        applyI18n,
        init,
        normalize,
        riskFactor,
        STORAGE_KEY,
    };

    // Early init nếu DOM sẵn
    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", init);
    } else {
        init();
    }
})(typeof window !== "undefined" ? window : globalThis);
