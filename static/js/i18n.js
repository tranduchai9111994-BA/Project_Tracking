/**
 * i18n client — VI/EN bilingual cho chrome UI + exports + toast chính.
 *
 * Persist: localStorage 'ihrp_lang' (+ sync project setting khi có API).
 * Coverage lần 1: header/nav/summary/filters/overdue/stalled/DQ/toasts chính.
 * String thiếu → fallback VI hoặc trả key.
 */
(function (global) {
    "use strict";

    const STORAGE_KEY = "ihrp_lang";
    const DEFAULT_LANG = "vi";

    const STRINGS = {
        vi: {
            "app.subtitle": "Dashboard theo dõi tiến độ dự án triển khai (multi-project · drill-down · global filter)",
            "nav.summary": "Summary",
            "nav.overdue": "Overdue",
            "nav.unassigned": "Chưa PIC",
            "nav.stalled": "Đình trệ",
            "nav.risk": "Risk Score",
            "nav.aging": "Aging WIP",
            "nav.sla": "SLA",
            "nav.dq": "Data Quality",
            "nav.anomaly": "Bất thường",
            "nav.rlog": "Rlog tuần",
            "section.rlog_title": "🧾 Rlog coded tuần này & kế hoạch tuần tới",
            "btn.settings": "⚙️ Cài đặt",
            "btn.settings_title": "Cài đặt: thứ tự Module, threshold, aging WIP, digest, reminder…",
            "btn.export_pdf": "📄 Xuất PDF",
            "btn.export_pdf_title": "Xuất PDF báo cáo tuần (client-side)",
            "btn.export_issues": "📊 Xuất vấn đề",
            "btn.export_issues_title": "Xuất Excel 1 file chứa mọi loại vấn đề",
            "btn.export_weekly_mom": "📋 Xuất MoM tuần",
            "btn.export_weekly_mom_title": "Xuất Excel báo cáo tuần MoM (Cover + Master plan + biên bản họp + PM Dashboard)",
            "btn.export_menu": "📤 Xuất ▾",
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
            "btn.upload_excel": "⬆ Upload Excel",
            "btn.upload_excel_title": "Hiện vùng kéo thả Function List (upload Excel tay)",
            "btn.upload_collapse": "▴ Thu gọn upload",
            "btn.upload_collapse_title": "Thu gọn vùng upload (ưu tiên Đồng bộ)",
            "btn.layout_edit": "🔧 Chỉnh thứ tự",
            "btn.layout_edit_title": "Bật/tắt drag-drop chỉnh thứ tự section",
            "btn.layout_reset": "↺ Mặc định",
            "btn.layout_reset_title": "Khôi phục thứ tự mặc định",
            "btn.custom_dash": "➕ Dashboard",
            "btn.custom_dash_title": "Tạo dashboard chart mới (wizard hoặc chat)",
            "btn.lang": "VI",
            "btn.lang_title": "Ngôn ngữ hiện tại: Tiếng Việt — bấm để chuyển sang English",
            "card.total": "Tổng chức năng",
            "card.progress": "Closed phase cuối",
            "card.overdue": "Function trễ deadline",
            "card.unassigned": "Function chưa PIC",
            "card.missing_deadline": "Chưa cập nhật deadline",
            "card.high_risk": "High-risk (≥50 điểm)",
            "card.modules": "Số Module",
            "card.anomaly": "Bất thường",
            "section.summary": "📋 Tổng quan dự án",
            "section.overdue": "⚠️ Overdue",
            "section.overdue_title": "⚠️ Danh sách trễ deadline",
            "section.unassigned": "👤 Chưa có PIC",
            "section.stalled": "🛑 Đình trệ",
            "section.dq": "🩺 Data Quality",
            "section.anomaly": "🚨 Bất thường",
            "filter.analyze_by": "🎯 Phân tích theo:",
            "filter.module": "Module",
            "filter.process": "Quy trình",
            "filter.pic": "PIC",
            "filter.project_code": "Mã dự án",
            "filter.all_module": "Tất cả module",
            "filter.all_process": "Tất cả quy trình",
            "filter.all_pic": "Tất cả PIC",
            "filter.all_project_code": "Tất cả mã dự án",
            "filter.module_order": "⚙ Thứ tự",
            "filter.module_order_title": "Cấu hình số thứ tự Module hiển thị trên toàn dashboard",
            "filter.clear_all": "✕ Bỏ tất cả",
            "filter.save_view": "💾 Lưu",
            "filter.save_view_title": "Lưu bộ lọc hiện tại",
            "filter.saved_views": "📂 View đã lưu…",
            "filter.n_selected": "{n} đã chọn",
            "filter.select_all": "☑ Chọn tất cả",
            "filter.deselect_all": "☐ Bỏ chọn",
            "filter.search": "🔍 Tìm...",
            "th.code": "Mã CN",
            "th.name": "Tên chức năng",
            "th.module": "Module",
            "th.phase": "Phase",
            "th.deadline": "Deadline",
            "th.days_late": "Ngày trễ",
            "th.status": "Status",
            "th.pic": "PIC",
            "th.priority": "Priority",
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
        },
        en: {
            "app.subtitle": "Implementation progress dashboard (multi-project · drill-down · global filter)",
            "nav.summary": "Summary",
            "nav.overdue": "Overdue",
            "nav.unassigned": "Unassigned",
            "nav.stalled": "Stalled",
            "nav.risk": "Risk Score",
            "nav.aging": "Aging WIP",
            "nav.sla": "SLA",
            "nav.dq": "Data Quality",
            "nav.anomaly": "Anomalies",
            "nav.rlog": "Rlog week",
            "section.rlog_title": "🧾 Rlog coded this week & next-week plan",
            "btn.settings": "⚙️ Settings",
            "btn.settings_title": "Settings: module order, thresholds, aging WIP, digest, reminder…",
            "btn.export_pdf": "📄 Export PDF",
            "btn.export_pdf_title": "Export weekly PDF report (client-side)",
            "btn.export_issues": "📊 Export issues",
            "btn.export_issues_title": "Export one Excel with all issue types",
            "btn.export_weekly_mom": "📋 Export weekly MoM",
            "btn.export_weekly_mom_title": "Export weekly MoM Excel (Cover + Master plan + meeting minutes + PM Dashboard)",
            "btn.export_menu": "📤 Export ▾",
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
            "section.anomaly": "🚨 Anomalies",
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
            "th.code": "Code",
            "th.name": "Function name",
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
        },
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
        STORAGE_KEY,
    };

    // Early init nếu DOM sẵn
    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", init);
    } else {
        init();
    }
})(typeof window !== "undefined" ? window : globalThis);
