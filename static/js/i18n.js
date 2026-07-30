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
            "btn.settings": "⚙️ Cài đặt",
            "btn.export_pdf": "📄 Xuất PDF",
            "btn.export_issues": "📊 Xuất vấn đề",
            "btn.lang": "EN",
            "btn.lang_title": "Switch to English",
            "card.total": "Tổng chức năng",
            "card.progress": "Closed phase cuối",
            "card.overdue": "Function trễ deadline",
            "card.unassigned": "Function chưa PIC",
            "card.missing_deadline": "Chưa cập nhật deadline",
            "card.high_risk": "High Risk",
            "card.modules": "Modules",
            "card.anomaly": "Bất thường",
            "section.overdue": "⚠️ Overdue",
            "section.unassigned": "👤 Chưa có PIC",
            "section.stalled": "🛑 Đình trệ",
            "section.dq": "🩺 Data Quality",
            "section.anomaly": "🚨 Bất thường",
            "filter.module": "Module",
            "filter.process": "Quy trình",
            "filter.pic": "PIC",
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
            "btn.settings": "⚙️ Settings",
            "btn.export_pdf": "📄 Export PDF",
            "btn.export_issues": "📊 Export issues",
            "btn.lang": "VI",
            "btn.lang_title": "Chuyển sang Tiếng Việt",
            "card.total": "Total functions",
            "card.progress": "Last phase Closed",
            "card.overdue": "Overdue functions",
            "card.unassigned": "Unassigned functions",
            "card.missing_deadline": "Missing deadline",
            "card.high_risk": "High Risk",
            "card.modules": "Modules",
            "card.anomaly": "Anomalies",
            "section.overdue": "⚠️ Overdue",
            "section.unassigned": "👤 Unassigned",
            "section.stalled": "🛑 Stalled",
            "section.dq": "🩺 Data Quality",
            "section.anomaly": "🚨 Anomalies",
            "filter.module": "Module",
            "filter.process": "Process",
            "filter.pic": "PIC",
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
            if (attr) {
                el.setAttribute(attr, val);
            } else {
                el.textContent = val;
            }
        });
        scope.querySelectorAll("[data-i18n-html]").forEach((el) => {
            const key = el.getAttribute("data-i18n-html");
            if (key) el.innerHTML = t(key);
        });
        // Toggle button label shows the OTHER language
        const btn = document.getElementById("btnLangToggle");
        if (btn) {
            btn.textContent = t("btn.lang");
            btn.title = t("btn.lang_title");
        }
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
