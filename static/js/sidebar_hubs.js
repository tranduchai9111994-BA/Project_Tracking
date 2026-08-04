/**
 * Sidebar Hub UX — gom 30+ section → ~12 hub + tab nội bộ.
 * localStorage: ihrp.tab.{hubId}, ihrp.sidebar.collapsed.{group}
 * Không phá auth; giữ id section-* cũ bên trong tab-pane.
 */
(function (global) {
    "use strict";

    const TAB_KEY = (hubId) => `ihrp.tab.${hubId}`;
    const COLLAPSE_KEY = (gid) => `ihrp.sidebar.collapsed.${gid}`;

    /** Hub definitions — thứ tự sidebar + tabs */
    const SIDEBAR_NAV_TREE = [
        {
            group: "overview",
            label_vi: "TỔNG QUAN",
            label_en: "OVERVIEW",
            icon: "ti-eye",
            defaultCollapsed: false,
            noCollapse: true,
            items: [
                {
                    id: "section-summary",
                    label_vi: "Summary",
                    label_en: "Summary",
                    icon: "ti-layout-dashboard",
                    hub: false,
                },
                {
                    id: "section-module-progress",
                    label_vi: "Tiến độ module",
                    label_en: "Module progress",
                    icon: "ti-box",
                    tabs: [
                        { section: "section-module", label_vi: "Bảng A", label_en: "Table A", help: "module", export: "module_overview" },
                        { section: "section-matrix", label_vi: "Phase Matrix", label_en: "Phase Matrix", help: "matrix", export: "phase_matrix" },
                        { section: "section-tasktype", label_vi: "Công việc", label_en: "Work type", help: "tasktype", export: "task_type" },
                        { section: "section-giaidoan", label_vi: "Giai đoạn", label_en: "Stage", help: "giaidoan", export: "giai_doan" },
                    ],
                },
            ],
        },
        {
            group: "issues",
            label_vi: "VẤN ĐỀ",
            label_en: "ISSUES",
            icon: "ti-alert-triangle",
            defaultCollapsed: false,
            items: [
                {
                    id: "section-issues",
                    label_vi: "Issues",
                    label_en: "Issues",
                    icon: "ti-alert-circle",
                    badges: true,
                    lazy: true,
                    tabs: [
                        { section: "section-overdue", label_vi: "Trễ hạn", label_en: "Overdue", help: "overdue", badge: "overdue" },
                        { section: "section-unassigned", label_vi: "Chưa PIC", label_en: "Unassigned", help: "unassigned", badge: "unassigned" },
                        { section: "section-stalled", label_vi: "Đình trệ", label_en: "Stalled", help: "stalled", badge: "stalled" },
                        { section: "section-aging-wip", label_vi: "WIP tồn đọng", label_en: "Aging WIP", help: "aging", lazy: "loadAgingWip" },
                        { section: "section-dataquality", label_vi: "Data Quality", label_en: "Data Quality", help: "dataquality", lazy: "loadDataQuality" },
                        { section: "section-fid-check", label_vi: "Thiếu FID", label_en: "FID Check", help: "fid-check", badge: "fid_issues", lazy: "loadFidCheck" },
                        { section: "section-duration-flag", label_vi: "Thời gian dài", label_en: "Long Duration", help: "duration-flag", lazy: "loadDurationFlag" },
                        { section: "section-weekly-gap", label_vi: "Báo cáo tuần", label_en: "Weekly Report", help: "weekly-gap", lazy: "loadWeeklyGap" },
                    ],
                },
                {
                    id: "section-risk-hub",
                    label_vi: "Risk",
                    label_en: "Risk",
                    icon: "ti-shield-exclamation",
                    tabs: [
                        { section: "section-risk", label_vi: "Risk Score", label_en: "Risk Score", help: "risk", lazy: "loadPmoRisk" },
                        { section: "section-uat-quality", label_vi: "UAT Quality", label_en: "UAT Quality", help: "uat-quality" },
                        { section: "section-anomaly", label_vi: "Bất thường", label_en: "Anomaly", help: "anomaly", lazy: "loadAnomalySection" },
                    ],
                },
            ],
        },
        {
            group: "progress",
            label_vi: "TIẾN ĐỘ",
            label_en: "PROGRESS",
            icon: "ti-chart-line",
            defaultCollapsed: false,
            items: [
                {
                    id: "section-timeline",
                    label_vi: "Timeline",
                    label_en: "Timeline",
                    icon: "ti-chart-area-line",
                    tabs: [
                        { section: "section-phase", label_vi: "Phase Stack", label_en: "Phase Stack", help: "phase", export: "phase_stacked" },
                        { section: "section-gantt", label_vi: "Gantt", label_en: "Gantt", help: "gantt" },
                        { section: "section-burndown", label_vi: "Burndown", label_en: "Burndown", help: "burndown", lazy: "loadBurndownAndSLA" },
                        { section: "section-sla", label_vi: "SLA", label_en: "SLA", help: "sla", lazy: "loadBurndownAndSLA" },
                    ],
                },
                {
                    id: "section-weekly",
                    label_vi: "Hoạt động tuần",
                    label_en: "Weekly activity",
                    icon: "ti-notebook",
                    tabs: [
                        { section: "section-rlog", label_vi: "Rlog", label_en: "Rlog", help: "rlog" },
                        { section: "section-function-diff", label_vi: "Function Diff", label_en: "Function Diff", help: "function-diff", lazy: "loadFunctionDiff" },
                        { section: "section-pic-upcoming", label_vi: "PIC tuần tới", label_en: "PIC upcoming", help: "pic-upcoming" },
                    ],
                },
            ],
        },
        {
            group: "ba_tasks",
            label_vi: "BA TASKS",
            label_en: "BA TASKS",
            icon: "ti-clipboard-list",
            defaultCollapsed: false,
            items: [
                {
                    id: "section-ba-tasks",
                    label_vi: "Đầu việc BA",
                    label_en: "BA Tasks",
                    icon: "ti-clipboard-list",
                    hub: false,
                },
            ],
        },
        {
            group: "forecast",
            label_vi: "DỰ BÁO & KẾ HOẠCH",
            label_en: "FORECAST & PLAN",
            icon: "ti-calendar-event",
            defaultCollapsed: false,
            items: [
                {
                    id: "section-plan",
                    label_vi: "Kế hoạch",
                    label_en: "Plan",
                    icon: "ti-calendar",
                    tabs: [
                        { section: "section-gantt-calendar", label_vi: "Gantt Calendar", label_en: "Gantt Calendar", help: "gantt-calendar", lazy: "loadGanttCalendar" },
                        { section: "section-forecast-gantt", label_vi: "Forecast UAT/Golive", label_en: "Forecast UAT/Golive", help: "forecast-gantt", lazy: "loadForecastGantt" },
                        { section: "section-baseline", label_vi: "Baseline SV", label_en: "Baseline SV", help: "baseline" },
                    ],
                },
                {
                    id: "section-manpower",
                    label_vi: "Nhân lực",
                    label_en: "Manpower",
                    icon: "ti-users",
                    tabs: [
                        {
                            section: "section-forecast-manpower",
                            label_vi: "Manpower",
                            label_en: "Manpower",
                            help: "forecast-manpower",
                            lazy: "loadForecastManpower",
                            nest: ["section-estimate-ratio"],
                        },
                        { section: "section-evm", label_vi: "EVM", label_en: "EVM", help: "evm", lazy: "loadEarnedValue" },
                        { section: "section-pic-overload", label_vi: "PIC Overload", label_en: "PIC Overload", help: "pic-overload", lazy: "loadPicOverload" },
                        { section: "section-capacity", label_vi: "Capacity", label_en: "Capacity", help: "capacity" },
                    ],
                },
            ],
        },
        {
            group: "analysis",
            label_vi: "PHÂN TÍCH",
            label_en: "ANALYSIS",
            icon: "ti-chart-pie",
            defaultCollapsed: true,
            items: [
                {
                    id: "section-analysis",
                    label_vi: "Phân tích",
                    label_en: "Analysis",
                    icon: "ti-chart-pie",
                    tabs: [
                        { section: "section-pic", label_vi: "PIC", label_en: "PIC", help: "pic" },
                        { section: "section-priority", label_vi: "Priority", label_en: "Priority", help: "priority" },
                        { section: "section-fitgap-dashboard", label_vi: "FIT/GAP", label_en: "FIT/GAP", help: "fitgap", lazy: "loadFitgapDashboard" },
                        { section: "section-effort", label_vi: "Effort", label_en: "Effort", help: "effort" },
                        { section: "section-scope-creep", label_vi: "Scope Creep", label_en: "Scope Creep", help: "scope-creep" },
                        { section: "section-process", label_vi: "Quy trình", label_en: "Process", help: "process" },
                        { section: "section-duration", label_vi: "Thời lượng", label_en: "Duration", help: "duration" },
                        { section: "section-slow", label_vi: "PIC chậm", label_en: "Slow PIC", help: "slow" },
                        { section: "section-deps", label_vi: "Phụ thuộc", label_en: "Deps", help: "deps" },
                    ],
                },
            ],
        },
        {
            group: "admin",
            label_vi: "QUẢN TRỊ",
            label_en: "ADMIN",
            icon: "ti-settings",
            defaultCollapsed: true,
            items: [
                {
                    id: "section-admin",
                    label_vi: "Quản trị",
                    label_en: "Admin",
                    icon: "ti-settings",
                    tabs: [
                        { section: "section-pm", label_vi: "Chiều PM", label_en: "PM dimension", help: "pm" },
                        { section: "section-compare", label_vi: "Compare", label_en: "Compare", help: "compare" },
                        { section: "section-custom-dashboards", label_vi: "Custom Dashboard", label_en: "Custom Dashboard", help: "custom-dashboards", lazy: "loadCustomDashboards" },
                        { section: "section-history", label_vi: "History", label_en: "History", help: "history" },
                        { section: "section-kanban", label_vi: "Kanban", label_en: "Kanban", help: "kanban", lazy: "loadKanban" },
                        { section: "section-my-bookmarks", label_vi: "Bookmarks", label_en: "Bookmarks", help: "bookmarks", lazy: "loadBookmarks" },
                        { section: "section-digest", label_vi: "Digest", label_en: "Digest", help: "digest" },
                        { section: "section-my-digests", label_vi: "Digest lưu trữ", label_en: "Digest archive", help: "my-digests", lazy: "loadDigests" },
                        { section: "section-exec-dashboard", label_vi: "Điều hành", label_en: "Executive", help: "exec", lazy: "loadExecutiveDashboard" },
                    ],
                },
            ],
        },
    ];

    /** Child section → hub id */
    const CHILD_TO_HUB = {};
    const HUB_IDS = new Set(["section-summary"]);
    const ALL_HUB_ITEMS = [];

    SIDEBAR_NAV_TREE.forEach((g) => {
        (g.items || []).forEach((item) => {
            ALL_HUB_ITEMS.push(item);
            HUB_IDS.add(item.id);
            if (item.tabs) {
                item.tabs.forEach((t) => {
                    CHILD_TO_HUB[t.section] = item.id;
                    (t.nest || []).forEach((n) => { CHILD_TO_HUB[n] = item.id; });
                });
            } else {
                CHILD_TO_HUB[item.id] = item.id;
            }
        });
    });

    const DEFAULT_HUB_DOM_ORDER = [
        "section-summary",
        "section-globalfilter",
        "section-module-progress",
        "section-issues",
        "section-risk-hub",
        "section-timeline",
        "section-weekly",
        "section-ba-tasks",
        "section-plan",
        "section-manpower",
        "section-analysis",
        "section-admin",
    ];

    function _lang() {
        if (typeof I18n !== "undefined" && I18n.getLang) return I18n.getLang();
        return "vi";
    }

    function _t(vi, en) {
        return _lang() === "en" ? (en || vi) : vi;
    }

    function _lsGet(key, fallback) {
        try {
            const v = localStorage.getItem(key);
            return v == null ? fallback : v;
        } catch (_) {
            return fallback;
        }
    }

    function _lsSet(key, val) {
        try { localStorage.setItem(key, val); } catch (_) { /* ignore */ }
    }

    function _findNode(el) {
        return el && document.getElementById
            ? (typeof el === "string" ? document.getElementById(el) : el)
            : null;
    }

    /** Lấy element section; nếu nằm trong grid wrapper rỗng → unwrap sau move. */
    function _takeSection(sid) {
        const el = document.getElementById(sid);
        if (!el) return null;
        // Bỏ class hidden cứng từ HTML nếu section sẽ do tab quản lý
        return el;
    }

    function _emptyParentCleanup(parent) {
        if (!parent || parent.id === "dashboard" || parent.id === "stickyTopBlock") return;
        if (parent.id && parent.id.startsWith("section-")) return;
        const kids = parent.querySelectorAll(":scope > [id^='section-'], :scope > .section-hub");
        if (!kids.length && parent.parentElement) {
            const p = parent.parentElement;
            parent.remove();
            _emptyParentCleanup(p);
        }
    }

    let _hubsBuilt = false;

    function initSectionHubs(force) {
        const dash = document.getElementById("dashboard");
        if (!dash) return;
        if (_hubsBuilt && !force) return;
        if (force) {
            // DOM có thể đã restore HTML gốc — cho phép build lại
            _hubsBuilt = false;
            dash.querySelectorAll(".section-hub").forEach((h) => h.remove());
        }
        ALL_HUB_ITEMS.forEach((item) => {
            if (!item.tabs || !item.tabs.length) return;
            if (document.getElementById(item.id)) return;

            const hub = document.createElement("section");
            hub.id = item.id;
            hub.className = "section-hub bg-white dashboard-card rounded-xl shadow-md p-4 mb-6";
            hub.dataset.hub = item.id;

            const head = document.createElement("div");
            head.className = "section-hub-head";
            head.innerHTML =
                `<h3 class="section-hub-title">${_t(item.label_vi, item.label_en)}</h3>`
                + `<div class="section-tabs" role="tablist" data-hub-tabs="${item.id}"></div>`;
            hub.appendChild(head);

            const tabsBar = head.querySelector(".section-tabs");
            const panesWrap = document.createElement("div");
            panesWrap.className = "section-hub-panes";
            hub.appendChild(panesWrap);

            let insertBefore = null;
            let insertParent = dash;
            const moved = [];

            item.tabs.forEach((tab, idx) => {
                const btn = document.createElement("button");
                btn.type = "button";
                btn.className = "section-tab";
                btn.setAttribute("role", "tab");
                btn.dataset.tab = tab.section;
                btn.dataset.hub = item.id;
                btn.innerHTML =
                    `<span class="section-tab-label">${_t(tab.label_vi, tab.label_en)}</span>`
                    + (tab.badge
                        ? `<span class="section-tab-badge" data-badge="${tab.badge}"></span>`
                        : "");
                if (tab.help) btn.setAttribute("data-help-id", tab.help);
                tabsBar.appendChild(btn);

                const pane = document.createElement("div");
                pane.className = "tab-pane";
                pane.dataset.pane = tab.section;
                pane.id = `tab-${tab.section.replace(/^section-/, "")}`;

                const sec = _takeSection(tab.section);
                if (sec) {
                    if (!insertBefore) {
                        // Chèn hub tại vị trí phần tử đầu tiên — dùng comment marker
                        // giữ chỗ TRƯỚC khi move sec, vì sec (tab đầu) sẽ bị dời vào
                        // trong pane/hub nên không còn dùng được làm mốc insertBefore
                        // (gây lỗi "new child contains parent" khi chèn hub ngược lại).
                        insertParent = sec.parentElement || dash;
                        insertBefore = document.createComment(`hub-anchor-${item.id}`);
                        insertParent.insertBefore(insertBefore, sec);
                    }
                    const oldParent = sec.parentElement;
                    // Chuẩn hóa card style khi nằm trong pane
                    sec.classList.remove("mb-6");
                    sec.classList.add("tab-pane-section");
                    // Bỏ hidden cứng — tab quản lý visibility
                    if (sec.classList.contains("hidden") && !sec.dataset.userHidden) {
                        sec.classList.remove("hidden");
                        sec.dataset.hubWasHidden = "1";
                    }
                    pane.appendChild(sec);
                    moved.push({ sec, oldParent });

                    // Nest estimate-ratio dưới Manpower
                    (tab.nest || []).forEach((nid) => {
                        const nest = _takeSection(nid);
                        if (!nest) return;
                        nest.classList.remove("mb-6");
                        const details = document.createElement("details");
                        details.className = "hub-nested-panel mt-3";
                        details.id = `panel-${nid}`;
                        const sum = document.createElement("summary");
                        sum.className = "hub-nested-summary";
                        sum.textContent = _t("Ước lượng hệ số", "Estimate by ratio");
                        details.appendChild(sum);
                        details.appendChild(nest);
                        pane.appendChild(details);
                        if (nest.parentElement === oldParent) { /* already moved */ }
                        _emptyParentCleanup(nest.parentElement);
                    });
                } else {
                    pane.innerHTML = `<div class="text-xs text-slate-400 p-3">Section ${tab.section} không có trong DOM.</div>`;
                }
                panesWrap.appendChild(pane);

                btn.addEventListener("click", () => activateHubTab(item.id, tab.section));
            });

            // Nút export + help chung trên tab bar
            const tools = document.createElement("div");
            tools.className = "section-tabs-tools no-print";
            tools.innerHTML =
                `<button type="button" class="section-tab-export" title="Xuất tab đang chọn">📥</button>`;
            tabsBar.appendChild(tools);
            tools.querySelector(".section-tab-export").addEventListener("click", (ev) => {
                const active = item.tabs.find((t) => {
                    const p = hub.querySelector(`.tab-pane[data-pane="${t.section}"]`);
                    return p && p.classList.contains("active");
                });
                if (active && active.export && typeof openExportModePicker === "function") {
                    openExportModePicker(ev, active.export);
                } else if (typeof showToast === "function") {
                    showToast("Tab này chưa có export riêng", "orange");
                }
            });

            if (insertBefore && insertBefore.parentElement) {
                insertBefore.parentElement.insertBefore(hub, insertBefore);
                insertBefore.remove();
            } else {
                // Fallback: append sau summary
                const gf = document.getElementById("section-globalfilter");
                if (gf && gf.parentElement) gf.parentElement.insertBefore(hub, gf.nextSibling);
                else dash.appendChild(hub);
            }

            moved.forEach(({ oldParent }) => _emptyParentCleanup(oldParent));

            // Nếu hub bị chèn lồng trong 1 wrapper layout cũ (VD grid 2-cột
            // section-module/section-tasktype trước đây) — do marker nằm
            // trong wrapper đó — "nâng" hub ra làm con trực tiếp của #dashboard
            // rồi dọn wrapper rỗng. Không làm vậy sẽ để hub chiếm 1/2 chiều
            // rộng grid cũ (trống nửa còn lại) và lệch vị trí so với thứ tự
            // sidebar mong đợi.
            let hubParent = hub.parentElement;
            while (
                hubParent && hubParent !== dash
                && hubParent.id !== "stickyTopBlock"
                && !(hubParent.id && hubParent.id.startsWith("section-"))
                && !hubParent.classList.contains("section-hub")
            ) {
                const grandParent = hubParent.parentElement;
                if (!grandParent) break;
                grandParent.insertBefore(hub, hubParent);
                if (!hubParent.children.length) hubParent.remove();
                hubParent = hub.parentElement;
            }

            // Active tab từ localStorage
            const saved = _lsGet(TAB_KEY(item.id), item.tabs[0].section);
            const startTab = item.tabs.some((t) => t.section === saved) ? saved : item.tabs[0].section;
            activateHubTab(item.id, startTab, { skipStore: true, skipScroll: true });
        });

        _hubsBuilt = true;
        // Resize charts khi tab hiện
        try {
            if (typeof attachSectionHelp === "function") attachSectionHelp();
            if (typeof attachUnifiedSectionHelp === "function") attachUnifiedSectionHelp();
        } catch (_) { /* ignore */ }
    }

    function activateHubTab(hubId, sectionId, opts) {
        opts = opts || {};
        const hub = document.getElementById(hubId);
        if (!hub) return;
        hub.querySelectorAll(".section-tab").forEach((b) => {
            b.classList.toggle("active", b.dataset.tab === sectionId);
        });
        hub.querySelectorAll(".tab-pane").forEach((p) => {
            const on = p.dataset.pane === sectionId;
            p.classList.toggle("active", on);
            p.hidden = !on;
        });
        if (!opts.skipStore) _lsSet(TAB_KEY(hubId), sectionId);

        // Lazy load
        const item = ALL_HUB_ITEMS.find((i) => i.id === hubId);
        const tab = item && item.tabs ? item.tabs.find((t) => t.section === sectionId) : null;
        if (tab && tab.lazy && typeof global[tab.lazy] === "function") {
            try { global[tab.lazy](); } catch (e) { console.warn("[hub lazy]", tab.lazy, e); }
        }

        // Chart.js resize khi pane hiện
        setTimeout(() => {
            try {
                if (typeof chartInstances === "object") {
                    Object.values(chartInstances).forEach((c) => {
                        if (c && typeof c.resize === "function") c.resize();
                    });
                }
            } catch (_) { /* ignore */ }
        }, 50);
    }

    function buildSidebarNav() {
        const wrap = document.getElementById("sidebarNavLinks");
        if (!wrap) return;
        wrap.innerHTML = "";

        SIDEBAR_NAV_TREE.forEach((g) => {
            const groupEl = document.createElement("div");
            groupEl.className = "sidebar-nav-group";
            groupEl.dataset.group = g.group;

            const collapsedPref = _lsGet(COLLAPSE_KEY(g.group), g.defaultCollapsed ? "1" : "0");
            if (collapsedPref === "1" && !g.noCollapse) groupEl.classList.add("is-collapsed");

            const label = document.createElement("button");
            label.type = "button";
            label.className = "sidebar-group-label";
            label.innerHTML =
                `<i class="ti ${g.icon}" aria-hidden="true"></i>`
                + `<span>${_t(g.label_vi, g.label_en)}</span>`
                + (g.noCollapse ? "" : `<i class="ti ti-chevron-down sidebar-collapse-icon" aria-hidden="true"></i>`);
            if (!g.noCollapse) {
                label.addEventListener("click", () => {
                    groupEl.classList.toggle("is-collapsed");
                    _lsSet(COLLAPSE_KEY(g.group), groupEl.classList.contains("is-collapsed") ? "1" : "0");
                });
            }
            groupEl.appendChild(label);

            const itemsWrap = document.createElement("div");
            itemsWrap.className = "sidebar-group-items";

            (g.items || []).forEach((item) => {
                const a = document.createElement("a");
                a.href = `#${item.id}`;
                a.className = "sidebar-nav-item";
                a.dataset.navId = item.id;
                a.innerHTML =
                    `<i class="ti ${item.icon}" aria-hidden="true"></i>`
                    + `<span class="sidebar-nav-text">${_t(item.label_vi, item.label_en)}</span>`
                    + (item.badges
                        ? `<span class="sidebar-badges" data-badges-for="${item.id}">`
                            + `<span class="sidebar-badge sidebar-badge--danger" data-b="overdue">0</span>`
                            + `<span class="sidebar-badge sidebar-badge--warning" data-b="unassigned">0</span>`
                            + `<span class="sidebar-badge sidebar-badge--muted" data-b="stalled">0</span>`
                            + `</span>`
                        : "");
                a.addEventListener("click", (ev) => {
                    ev.preventDefault();
                    scrollToSection(item.id);
                });
                itemsWrap.appendChild(a);
            });
            groupEl.appendChild(itemsWrap);
            wrap.appendChild(groupEl);
        });

        _wireSidebarSearch();
        _wireSidebarActiveObserver();
        updateSidebarIssueBadges();
    }

    function _wireSidebarSearch() {
        const input = document.getElementById("sidebarSearchInput");
        if (!input || input.dataset.wired) return;
        input.dataset.wired = "1";
        input.addEventListener("input", () => filterSidebarNav(input.value));
        input.addEventListener("keydown", (e) => {
            if (e.key === "Escape") {
                input.value = "";
                filterSidebarNav("");
                input.blur();
            }
        });
    }

    function filterSidebarNav(q) {
        const query = (q || "").trim().toLowerCase();
        document.querySelectorAll("#sidebarNavLinks .sidebar-nav-item").forEach((a) => {
            const text = (a.textContent || "").toLowerCase();
            const show = !query || text.includes(query);
            a.classList.toggle("sidebar-search-hide", !show);
        });
        document.querySelectorAll("#sidebarNavLinks .sidebar-nav-group").forEach((g) => {
            const any = g.querySelectorAll(".sidebar-nav-item:not(.sidebar-search-hide)").length > 0;
            g.classList.toggle("sidebar-search-hide", !any);
            if (query && any) g.classList.remove("is-collapsed");
        });
    }

    function focusSidebarSearch() {
        const nav = document.getElementById("sidebarNav");
        const input = document.getElementById("sidebarSearchInput");
        if (nav) nav.classList.remove("hidden", "collapsed");
        if (input) {
            input.focus();
            input.select();
        }
    }

    function updateSidebarIssueBadges() {
        const s = (global.metricsData && global.metricsData.summary) || {};
        const stalled = (global.metricsData && global.metricsData.stalled_tasks
            && global.metricsData.stalled_tasks.items) || [];
        const counts = {
            overdue: Number(s.total_overdue) || 0,
            unassigned: Number(s.unassigned_count) || 0,
            stalled: stalled.length || Number(s.stalled_count) || 0,
        };
        document.querySelectorAll("[data-badges-for] [data-b]").forEach((el) => {
            const k = el.getAttribute("data-b");
            const n = counts[k] || 0;
            el.textContent = String(n);
            el.classList.toggle("sidebar-badge--muted", n === 0);
            el.classList.toggle("sidebar-badge--danger", k === "overdue" && n > 0);
            el.classList.toggle("sidebar-badge--warning", k === "unassigned" && n > 0);
            if (k === "stalled") {
                el.classList.toggle("sidebar-badge--warning", n > 0);
            }
        });
        // Tab badges trong Issues hub
        document.querySelectorAll(".section-tab-badge[data-badge]").forEach((el) => {
            const k = el.getAttribute("data-badge");
            const n = counts[k] || 0;
            el.textContent = n > 0 ? String(n) : "";
            el.classList.toggle("is-zero", n === 0);
        });
    }

    let _io = null;
    function _wireSidebarActiveObserver() {
        if (_io) {
            try { _io.disconnect(); } catch (_) { /* ignore */ }
        }
        const hubs = ALL_HUB_ITEMS.map((i) => document.getElementById(i.id)).filter(Boolean);
        if (!hubs.length || !("IntersectionObserver" in window)) return;
        _io = new IntersectionObserver((entries) => {
            // Pick most visible
            let best = null;
            let bestRatio = 0;
            entries.forEach((en) => {
                if (en.isIntersecting && en.intersectionRatio > bestRatio) {
                    bestRatio = en.intersectionRatio;
                    best = en.target;
                }
            });
            if (!best) return;
            document.querySelectorAll("#sidebarNavLinks .sidebar-nav-item").forEach((a) => {
                a.classList.toggle("is-active", a.dataset.navId === best.id);
            });
        }, { rootMargin: "-20% 0px -55% 0px", threshold: [0.1, 0.25, 0.5] });
        hubs.forEach((h) => _io.observe(h));
    }

    function scrollToSection(sectionId) {
        if (!sectionId) return;
        // Nếu là child → mở hub + tab trước
        const hubId = CHILD_TO_HUB[sectionId] || (HUB_IDS.has(sectionId) ? sectionId : null);
        if (hubId && hubId !== sectionId && document.getElementById(hubId)) {
            activateHubTab(hubId, sectionId);
        }
        const target = document.getElementById(hubId && document.getElementById(hubId) ? hubId : sectionId)
            || document.getElementById(sectionId);
        if (!target) return;
        // Mở group sidebar chứa item
        const navItem = document.querySelector(`#sidebarNavLinks .sidebar-nav-item[data-nav-id="${hubId || sectionId}"]`);
        if (navItem) {
            const g = navItem.closest(".sidebar-nav-group");
            if (g) g.classList.remove("is-collapsed");
            document.querySelectorAll("#sidebarNavLinks .sidebar-nav-item").forEach((a) => {
                a.classList.toggle("is-active", a === navItem);
            });
        }
        target.scrollIntoView({ behavior: "smooth", block: "start" });
        // Bỏ hidden user nếu có
        target.classList.remove("group-filtered-out");
    }

    /** Map order cũ 30+ → 12 hub (backward compat). */
    function migrateSectionOrder(order) {
        if (!Array.isArray(order) || !order.length) return DEFAULT_HUB_DOM_ORDER.slice();
        // Đã là hub order?
        const hubHits = order.filter((k) => HUB_IDS.has(k) || k === "section-globalfilter").length;
        if (hubHits >= Math.min(4, order.length) && hubHits >= order.length * 0.5) {
            return order;
        }
        const out = [];
        const seen = new Set();
        const push = (id) => {
            if (!id || seen.has(id)) return;
            seen.add(id);
            out.push(id);
        };
        // Luôn giữ summary + filter đầu
        push("section-summary");
        push("section-globalfilter");
        order.forEach((key) => {
            if (!key) return;
            if (key === "section-summary" || key === "section-globalfilter") return;
            if (HUB_IDS.has(key)) {
                push(key);
                return;
            }
            // grid:section-a+section-b
            if (String(key).startsWith("grid:")) {
                const parts = String(key).slice(5).split("+");
                parts.forEach((p) => {
                    const hub = CHILD_TO_HUB[p];
                    if (hub) push(hub);
                });
                return;
            }
            const hub = CHILD_TO_HUB[key];
            if (hub) push(hub);
        });
        DEFAULT_HUB_DOM_ORDER.forEach(push);
        return out;
    }

    function initSidebarHubsUX() {
        try { initSectionHubs(); } catch (e) { console.error("[initSectionHubs]", e); }
        try { buildSidebarNav(); } catch (e) { console.error("[buildSidebarNav]", e); }
        try { updateSidebarIssueBadges(); } catch (e) { /* ignore */ }
    }

    // Expose
    global.SIDEBAR_NAV_TREE = SIDEBAR_NAV_TREE;
    global.DEFAULT_HUB_DOM_ORDER = DEFAULT_HUB_DOM_ORDER;
    global.CHILD_TO_HUB = CHILD_TO_HUB;
    global.HUB_IDS = HUB_IDS;
    global.initSectionHubs = initSectionHubs;
    global.buildSidebarNav = buildSidebarNav;
    global.activateHubTab = activateHubTab;
    global.scrollToSection = scrollToSection;
    global.migrateSectionOrder = migrateSectionOrder;
    global.updateSidebarIssueBadges = updateSidebarIssueBadges;
    global.focusSidebarSearch = focusSidebarSearch;
    global.filterSidebarNav = filterSidebarNav;
    global.initSidebarHubsUX = initSidebarHubsUX;

})(typeof window !== "undefined" ? window : globalThis);
