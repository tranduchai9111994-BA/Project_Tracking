/**
 * iHRP Function List Tracker — Dashboard JS (V2)
 * Vanilla ES6, Chart.js cho biểu đồ.
 *
 * Sections được chia theo docs:
 *   - Core (V1): summary, module, task-type, matrix, phase stack, PIC, priority, complexity, fit/gap, giai đoạn, overdue
 *   - Advanced (V2 P1): unassigned, duration, stalled, risk score
 *   - Advanced (V2 P2): effort, snapshot compare, weekly digest
 *   - Advanced (V2 P3): process treemap, gantt timeline, UX (dark mode, fullscreen, search)
 */

// ========================================================================
// STATE
// ========================================================================
let metricsData = null;
let snapshotsData = [];
let currentCompareResult = null;
let chartInstances = {};

// V3: Project state
let currentProjectSlug = "default";
let allProjects = [];

// V3.1 → Wave 2: Global filter multi-select (Module / Quy trình / PIC)
// Áp cho toàn bộ dashboard — khi user chọn, gọi lại /dashboard?module=A,B&process=X&pic=Y
// Semantics: OR trong 1 chiều, AND giữa các chiều (backend xử lý).
let globalFilters = { modules: [], processes: [], pics: [] };
let structureCache = null;  // cache all_modules, all_processes, all_pics từ lần load không filter đầu tiên
// Registry của multi-select instance để có thể set/refresh options từ bên ngoài
const _msInstances = {};

// ========================================================================
// CONSTANTS
// ========================================================================
// Task 19: STATUS_COLORS + CHART_PALETTE giờ derive từ window.Palette
// (analyzer/palette.py + static/js/palette.js). Giữ export cũ cho các nơi
// còn reference trực tiếp — nhưng khuyến khích dùng Palette.statusColor()
// / Palette.categoricalColors() cho code mới để hỗ trợ dark mode + threshold
// config.
const STATUS_COLORS = new Proxy({}, {
    get(_t, key) {
        // window.Palette lazy — reference tại thời điểm access
        return (window.Palette && window.Palette.STATUS[key]) || "#94a3b8";
    },
});

// Cycle categorical 15 màu — Palette.CATEGORICAL 10 màu, extend +5 màu bổ sung
const CHART_PALETTE = (() => {
    const base = (window.Palette && window.Palette.CATEGORICAL) || [
        "#4e79a7", "#f28e2b", "#e15759", "#76b7b2", "#59a14f",
        "#edc948", "#b07aa1", "#ff9da7", "#9c755f", "#bab0ac",
    ];
    return [...base, "#06b6d4", "#a855f7", "#10b981", "#e11d48", "#0ea5e9"];
})();

const PHASE_COLORS = {
    "Phân tích": "#8b5cf6",
    "Lập trình": "#3b82f6",
    "Kiểm thử": "#06b6d4",
    "Cấu hình UAT": "#14b8a6",
    "UAT": "#22c55e",
    "Cấu hình Golive": "#eab308",
    "Tài liệu": "#94a3b8",
};

// ========================================================================
// INIT
// ========================================================================
document.addEventListener("DOMContentLoaded", () => {
    const zone = document.getElementById("uploadZone");
    const input = document.getElementById("fileInput");

    zone.addEventListener("dragover", (e) => { e.preventDefault(); zone.classList.add("drag-over"); });
    zone.addEventListener("dragleave", () => zone.classList.remove("drag-over"));
    zone.addEventListener("drop", (e) => {
        e.preventDefault();
        zone.classList.remove("drag-over");
        if (e.dataTransfer.files.length) handleFile(e.dataTransfer.files[0]);
    });

    input.addEventListener("change", () => { if (input.files.length) handleFile(input.files[0]); });

    // Overdue filter events — chỉ còn PIC là single-select native. Module/Phase
    // đã chuyển sang multi-select (createMultiSelect) → set onChange trong
    // populateFilters(). Mỗi lần đổi filter → reset pagination về trang 1.
    const picEl = document.getElementById("filterPIC");
    if (picEl) {
        picEl.addEventListener("change", () => {
            pageState.overdue.page = 1;
            renderOverdueTable();
        });
    }

    // Compare upload
    const cmpInput = document.getElementById("compareUpload");
    if (cmpInput) {
        cmpInput.addEventListener("change", (e) => {
            if (e.target.files.length) handleCompareUpload(e.target.files[0]);
        });
    }

    // Search
    const searchBox = document.getElementById("searchBox");
    if (searchBox) {
        searchBox.addEventListener("input", handleSearch);
        searchBox.addEventListener("focus", handleSearch);
        document.addEventListener("click", (e) => {
            if (!e.target.closest("#searchWrap")) {
                document.getElementById("searchResults").classList.add("hidden");
            }
        });
    }

    // Escape: ưu tiên đóng help popover, sau đó fullscreen, sau đó modal khác.
    // Function Detail modal (Task 1) đóng qua Esc cho UX consistent với drill-down.
    document.addEventListener("keydown", (e) => {
        if (e.key === "Escape") {
            if (typeof closeChartHelp === "function" && closeChartHelp()) return;
            // Function detail modal đang mở?
            const fnModal = document.getElementById("functionDetailModal");
            if (fnModal && !fnModal.classList.contains("hidden")) {
                closeFunctionDetail();
                return;
            }
            closeFullscreen();
        }
    });

    // Window resize → resize toàn bộ chart (debounced)
    let _resizeTimer = null;
    window.addEventListener("resize", () => {
        if (_resizeTimer) clearTimeout(_resizeTimer);
        _resizeTimer = setTimeout(() => {
            Object.values(chartInstances).forEach(c => {
                try { c.resize(); } catch (e) {}
            });
        }, 150);
    });

    // Init theme icon
    updateThemeIcon();

    // Load project list và auto-load state của project đang chọn
    loadProjectList().then(() => {
        // Nếu project đang chọn đã có dữ liệu → tự load dashboard
        tryLoadDashboardForCurrent();
    });
});

// ========================================================================
// PROJECT MANAGEMENT
// ========================================================================

/** Load danh sách project, populate selector. */
async function loadProjectList() {
    try {
        const r = await fetch("/api/projects");
        const data = await r.json();
        allProjects = data.projects || [];

        const sel = document.getElementById("projectSelector");
        sel.innerHTML = "";
        for (const p of allProjects) {
            const opt = document.createElement("option");
            opt.value = p.slug;
            const label = p.name + (p.snapshot_count ? ` (${p.snapshot_count})` : "");
            opt.textContent = label;
            sel.appendChild(opt);
        }

        // Restore last selected từ localStorage nếu còn tồn tại
        const saved = localStorage.getItem("current_project");
        if (saved && allProjects.some(p => p.slug === saved)) {
            currentProjectSlug = saved;
        } else if (allProjects.length > 0) {
            currentProjectSlug = allProjects[0].slug;
        }
        sel.value = currentProjectSlug;
        updateUploadTargetLabel();
    } catch (err) {
        console.error("Không load được project list", err);
    }
}

function updateUploadTargetLabel() {
    const p = allProjects.find(x => x.slug === currentProjectSlug);
    const el = document.getElementById("uploadTargetProject");
    if (el && p) el.textContent = p.name;
}

/** Chuyển sang project khác — reload dashboard. */
async function switchProject(slug) {
    currentProjectSlug = slug;
    localStorage.setItem("current_project", slug);
    updateUploadTargetLabel();
    // Xóa dashboard cũ, reset state
    metricsData = null;
    snapshotsData = [];
    Object.values(chartInstances).forEach(c => c && c.destroy && c.destroy());
    chartInstances = {};
    document.getElementById("dashboard").classList.add("hidden");
    document.getElementById("fileInfo").classList.add("hidden");
    // Thử load state của project mới
    await tryLoadDashboardForCurrent();
}

/** Nếu project hiện tại đã có file trên server → load dashboard. */
async function tryLoadDashboardForCurrent(preserveFilters = false) {
    try {
        // Reset filters khi switch project (trừ trường hợp refresh cùng project)
        if (!preserveFilters) {
            globalFilters = { modules: [], processes: [], pics: [] };
        }
        const url = _buildDashboardUrl();
        const r = await fetch(url);
        if (r.status === 404) return;
        if (!r.ok) return;
        const data = await r.json();
        applyDashboardResponse(data);
        if (!preserveFilters) {
            showToast(`Đã tải project: ${data.project.name}`);
        }
    } catch (err) {
        console.warn("Không load được dashboard project:", err);
    }
}

function _buildDashboardUrl() {
    const params = new URLSearchParams();
    // Comma-separated: URL gọn + backend cũng chấp nhận repeated → tương thích 2 chiều
    if (globalFilters.modules.length) params.set("module", globalFilters.modules.join(","));
    if (globalFilters.processes.length) params.set("process", globalFilters.processes.join(","));
    if (globalFilters.pics.length) params.set("pic", globalFilters.pics.join(","));
    const qs = params.toString();
    return `/api/projects/${currentProjectSlug}/dashboard${qs ? "?" + qs : ""}`;
}

/**
 * Áp response upload/dashboard vào UI + render.
 *
 * QUAN TRỌNG: Mỗi bước phụ (sidebar chrome, PIC blacklist badge, structure cache,
 * global filters…) bọc trong _step() để nếu 1 bước bất kỳ throw, dashboard render
 * vẫn chạy. Đây là root-cause fix cho bug "summary cards hiện 0 sau khi filter":
 * trước fix, 1 exception ở bước phụ (VD sidebar / localStorage / MutationObserver)
 * làm hàm dừng giữa chừng trước khi tới renderDashboard(), cards giữ giá trị mặc định
 * (0) dù metricsData đã đúng.
 */
function applyDashboardResponse(data) {
    // Helper: chạy 1 bước, log lỗi nhưng KHÔNG throw để step sau vẫn chạy
    const _step = (name, fn) => {
        try { fn(); }
        catch (err) { console.error(`[applyDashboardResponse] ${name} failed:`, err); }
    };

    // Bước core BẮT BUỘC: set state metrics — nếu bước này lỗi thì đúng là hết cứu
    metricsData = data.metrics;
    snapshotsData = data.snapshots || [];

    _step("meta", () => {
        window._projectMeta = {
            settings: data.settings || null,
            project: data.project || null,
            upload_time: data.upload_time || null,
        };
    });

    // BUG P0-A fix: tách các thao tác thành sub-step độc lập. Trước đây gom
    // hết vào 1 `_step("fileInfo")` — nếu step nào ném lỗi (VD `#fileName`
    // element bị refactor mất, hoặc `data.upload_time` null → Date(null)
    // an toàn nhưng có thể phá downstream), thì các thao tác sau bị bỏ lỡ
    // → `searchWrap.remove("hidden")` không chạy → ô search Function
    // Traceability biến mất sau upload/switch project.
    _step("fileInfo.fileName", () => {
        const el = document.getElementById("fileName");
        if (el) el.textContent = data.filename || "";
    });
    _step("fileInfo.rowCount", () => {
        const el = document.getElementById("rowCount");
        if (el) el.textContent = data?.metrics?.summary?.total_functions ?? 0;
    });
    _step("fileInfo.uploadTime", () => {
        const el = document.getElementById("uploadTime");
        if (el && data.upload_time) el.textContent = new Date(data.upload_time).toLocaleString("vi-VN");
    });
    _step("fileInfo.visibility", () => {
        document.getElementById("fileInfo")?.classList.remove("hidden");
    });
    // Tách hẳn thành step riêng để KHÔNG BAO GIỜ bị nuốt bởi lỗi upstream.
    _step("searchVisibility", () => {
        document.getElementById("searchWrap")?.classList.remove("hidden");
    });

    _step("sidebar", () => showSidebarChrome());

    _step("warnings", () => {
        if (Array.isArray(data.warnings) && data.warnings.length) {
            _showUploadWarnings(data.warnings);
        }
    });

    _step("picBlacklist", () => _updatePicBlacklistBadge(data.pic_blacklist_count || 0));

    _step("structureCache", () => {
        // Cache structure gốc (full list) từ lần load đầu (không có filter)
        // để filter dropdown luôn giữ nguyên option kể cả khi backend
        // trả subset (filter đang active).
        if (!data.applied_filter && data.metrics.structure) {
            structureCache = {
                all_modules: data.metrics.structure.all_modules || [],
                all_processes: data.metrics.structure.all_processes || [],
                all_pics: data.metrics.structure.all_pics || [],
                processes_by_module: data.metrics.structure.processes_by_module || {},
                pics_by_module: data.metrics.structure.pics_by_module || {},
            };
        }
    });

    _step("globalFilters", () => populateGlobalFilters(data.applied_filter));

    // *** RENDER DASHBOARD — bước quan trọng nhất, giờ luôn được chạy ***
    _step("renderDashboard", () => renderDashboard());

    _step("emptyFilter", () => renderEmptyFilterState(data.applied_filter));
    _step("scopeSubtitles", () => updateChartScopeSubtitles(data.applied_filter));

    _step("showDashboard", () => {
        document.getElementById("dashboard").classList.remove("hidden");
        document.getElementById("dashboard").classList.add("fade-in");
    });

    _step("refreshReminder", () => checkRefreshReminder());

    // P3/P4 hooks — lazy analytics + saved views + deep-link URL.
    try { if (typeof loadBurndownAndSLA === "function") setTimeout(loadBurndownAndSLA, 100); } catch (e) {}
    // Task 2 — FIT/GAP Dashboard: fetch riêng như SLA/Capacity vì compute nặng
    // (đi qua tất cả rows) và support aging_threshold_days configurable.
    try { if (typeof loadFitgapDashboard === "function") setTimeout(loadFitgapDashboard, 120); } catch (e) {}
    // Task 3 — Function Diff: fetch riêng vì cần load snapshot pickle (chậm hơn dashboard)
    try { if (typeof loadFunctionDiff === "function") setTimeout(loadFunctionDiff, 150); } catch (e) {}
    try { if (typeof loadSavedViews === "function") setTimeout(loadSavedViews, 120); } catch (e) {}
    try { if (typeof _updateDeepLink === "function") _updateDeepLink(); } catch (e) {}
    // Task 4b: Load custom section order (nếu user đã customize) — apply DOM reorder
    // TRƯỚC khi user nhìn thấy dashboard (idempotent: nếu order khớp default sẽ no-op).
    try { if (typeof loadSectionOrder === "function") loadSectionOrder(); } catch (e) {}
    // Task 6: Inject gear buttons + load chart configs (title/caption/hidden overrides)
    try {
        if (typeof injectChartConfigGears === "function") setTimeout(injectChartConfigGears, 250);
        if (typeof loadChartConfigs === "function") setTimeout(loadChartConfigs, 260);
    } catch (e) {}
    // Task 9: Load custom dashboards + render section
    try {
        if (typeof loadCustomDashboards === "function") setTimeout(loadCustomDashboards, 400);
    } catch (e) {}
    // Task 10: Kanban theo tuần (cần role map trước để card hiện role chip)
    try {
        if (typeof loadPicRoles === "function") {
            setTimeout(async () => {
                await loadPicRoles();
                if (typeof loadKanban === "function") loadKanban();
            }, 500);
        }
    } catch (e) {}
}

// ========================================================================
// GLOBAL FILTER MULTI-SELECT (Wave 2) — Module / Quy trình / PIC
// ========================================================================

/**
 * Component multi-select dropdown tái sử dụng, viết bằng JS thuần.
 * API (giống spec trong task):
 *   createMultiSelect({
 *     el: '#id' | HTMLElement,     // container để render vào
 *     key: 'modules',              // key để đăng ký vào _msInstances
 *     label: 'Module',
 *     options: ['A', 'B', ...],
 *     selected: [],
 *     allText: 'Tất cả module',    // text hiển thị khi chưa chọn gì (mặc định)
 *     onChange: (arr) => {...},
 *   })
 * Trả về object { setOptions, setSelected, getSelected, refresh }.
 */
function createMultiSelect(opts) {
    const container = typeof opts.el === "string" ? document.querySelector(opts.el) : opts.el;
    if (!container) return null;
    const state = {
        label: opts.label || "",
        options: Array.isArray(opts.options) ? opts.options.slice() : [],
        selected: new Set(opts.selected || []),
        allText: opts.allText || `Tất cả ${opts.label ? opts.label.toLowerCase() : ""}`.trim(),
        onChange: typeof opts.onChange === "function" ? opts.onChange : () => {},
        keyword: "",
        isOpen: false,
    };

    // Xây skeleton DOM 1 lần rồi update in-place mỗi lần state đổi (tránh mất focus search)
    container.innerHTML = "";
    container.classList.add("ms-container");

    const trigger = document.createElement("button");
    trigger.type = "button";
    trigger.className = "ms-trigger";
    trigger.innerHTML =
        `<span class="ms-label"></span>` +
        `<span class="ms-summary"></span>` +
        `<span class="ms-caret">▾</span>`;
    container.appendChild(trigger);

    // Nút clear filter (chỉ hiện khi có selection)
    const clearBtn = document.createElement("button");
    clearBtn.type = "button";
    clearBtn.className = "ms-clear";
    clearBtn.title = `Xóa filter ${state.label}`;
    clearBtn.textContent = "×";
    clearBtn.style.display = "none";
    container.appendChild(clearBtn);

    const panel = document.createElement("div");
    panel.className = "ms-panel";
    panel.innerHTML = `
        <input type="text" class="ms-search" placeholder="🔍 Tìm..." />
        <div class="ms-toolbar">
            <div>
                <button type="button" class="ms-select-all">☑ Chọn tất cả</button>
                <button type="button" class="ms-clear-all">☐ Bỏ chọn</button>
            </div>
            <span class="ms-count"></span>
        </div>
        <div class="ms-list"></div>
    `;
    container.appendChild(panel);

    const $ = (sel) => panel.querySelector(sel);
    const searchInput = $(".ms-search");
    const listEl = $(".ms-list");
    const countEl = $(".ms-count");
    const btnAll = $(".ms-select-all");
    const btnNone = $(".ms-clear-all");

    // ---- Renderers ----
    function renderTrigger() {
        const lbl = trigger.querySelector(".ms-label");
        const sum = trigger.querySelector(".ms-summary");
        lbl.textContent = state.label + ":";
        const n = state.selected.size;
        if (n === 0) {
            sum.textContent = state.allText;
            trigger.classList.remove("ms-active");
            clearBtn.style.display = "none";
        } else if (n === 1) {
            const only = [...state.selected][0];
            sum.textContent = only;
            sum.title = only;
            trigger.classList.add("ms-active");
            clearBtn.style.display = "";
        } else {
            sum.textContent = `${n} đã chọn`;
            sum.title = [...state.selected].join(", ");
            trigger.classList.add("ms-active");
            clearBtn.style.display = "";
        }
    }

    function renderList() {
        const q = state.keyword.trim().toLowerCase();
        // Wave 3: khi cascade, option đang chọn có thể KHÔNG còn hợp lệ trong scope
        // hiện tại (VD chọn Process=HR.BP.02 rồi cascade Module=PR). Thay vì drop
        // (làm mất selection thầm lặng → bug UX), merge selected vào visible list
        // và đánh dấu style .ms-item-stale để user thấy rõ.
        const optSet = new Set(state.options);
        // Selected nào không có trong options → stale
        const staleSelected = [...state.selected].filter(v => !optSet.has(v));
        // Danh sách visible sau apply search
        const visibleOptions = q
            ? state.options.filter(o => String(o).toLowerCase().includes(q))
            : state.options.slice();
        const visibleStale = q
            ? staleSelected.filter(o => String(o).toLowerCase().includes(q))
            : staleSelected;
        // Stale option luôn hiển thị ở đầu (ưu tiên để user thấy cảnh báo)
        const finalList = visibleStale.concat(visibleOptions);
        if (finalList.length === 0) {
            listEl.innerHTML = `<div class="ms-empty">Không có option nào ${q ? "khớp keyword" : ""}</div>`;
        } else {
            listEl.innerHTML = finalList.map(o => {
                const checked = state.selected.has(o) ? "checked" : "";
                const isStale = !optSet.has(o);
                // Value attribute cần HTML-escape (không phải JS-escape).
                // Sau đó khi đọc lại qua cb.value browser tự decode → khớp option gốc.
                const val = escapeHtml(o);
                const cls = isStale ? "ms-item ms-item-stale" : "ms-item";
                const staleIcon = isStale ? `<span class="ms-stale-icon" title="Không nằm trong scope hiện tại — có thể ra 0 kết quả">⚠️</span>` : "";
                return `<label class="${cls}"${isStale ? ' title="Filter đang chọn nhưng không hợp lệ với scope hiện tại"' : ""}>
                    <input type="checkbox" value="${val}" ${checked} />
                    <span class="ms-item-label">${escapeHtml(o)}</span>
                    ${staleIcon}
                </label>`;
            }).join("");
        }
        // Count reflect cả stale (user đang chọn) + total available options
        const totalDisplay = state.options.length + staleSelected.length;
        countEl.textContent = `${state.selected.size}/${totalDisplay}`;
    }

    // ---- Event handlers ----
    function openPanel() {
        // Đóng các panel khác trước khi mở panel này (chỉ mở 1 lúc 1 dropdown)
        Object.values(_msInstances).forEach(inst => inst && inst.close && inst.close());
        state.isOpen = true;
        panel.classList.add("ms-open");
        searchInput.value = state.keyword;
        // Focus vào ô search cho tiện gõ ngay
        setTimeout(() => searchInput.focus(), 0);
    }
    function closePanel() {
        state.isOpen = false;
        panel.classList.remove("ms-open");
    }

    trigger.addEventListener("click", (e) => {
        e.stopPropagation();
        state.isOpen ? closePanel() : openPanel();
    });

    clearBtn.addEventListener("click", (e) => {
        e.stopPropagation();
        state.selected.clear();
        renderTrigger();
        renderList();
        state.onChange([]);
    });

    searchInput.addEventListener("input", () => {
        state.keyword = searchInput.value;
        renderList();
    });
    // Chặn click search input đóng panel (nhờ stopPropagation trong document listener)
    panel.addEventListener("click", (e) => e.stopPropagation());

    listEl.addEventListener("change", (e) => {
        const cb = e.target.closest("input[type=checkbox]");
        if (!cb) return;
        const val = cb.value;
        if (cb.checked) state.selected.add(val);
        else state.selected.delete(val);
        renderTrigger();
        countEl.textContent = `${state.selected.size}/${state.options.length}`;
        state.onChange([...state.selected]);
    });

    btnAll.addEventListener("click", (e) => {
        e.stopPropagation();
        // Chỉ chọn options đang hiển thị (respect search filter) để tránh spam ngoài ý
        const q = state.keyword.trim().toLowerCase();
        const target = q
            ? state.options.filter(o => String(o).toLowerCase().includes(q))
            : state.options;
        target.forEach(o => state.selected.add(o));
        renderTrigger();
        renderList();
        state.onChange([...state.selected]);
    });

    btnNone.addEventListener("click", (e) => {
        e.stopPropagation();
        state.selected.clear();
        renderTrigger();
        renderList();
        state.onChange([]);
    });

    // Click ngoài → đóng panel (registration 1 lần global, xem init block dưới)

    renderTrigger();
    renderList();

    const api = {
        /**
         * Cập nhật danh sách options. Wave 3 mặc định KHÔNG drop selection —
         * option đang chọn nhưng không còn hợp lệ sẽ hiện dưới dạng stale
         * (icon ⚠️ + màu vàng) để user biết filter đang cause 0-row result.
         *
         * @param newOpts       list option mới
         * @param dropInvalid   true = drop selected không hợp lệ (behavior cũ,
         *                      giữ để backward-compat với call site chưa migrate);
         *                      false = preserve + mark stale (behavior mới)
         */
        setOptions(newOpts, dropInvalid = false) {
            state.options = Array.isArray(newOpts) ? newOpts.slice() : [];
            if (dropInvalid) {
                // Legacy path: drop selected không còn hợp lệ (không dùng cho cascade nữa)
                const optSet = new Set(state.options);
                let dropped = false;
                for (const v of [...state.selected]) {
                    if (!optSet.has(v)) {
                        state.selected.delete(v);
                        dropped = true;
                    }
                }
                if (dropped) state.onChange([...state.selected]);
            }
            renderTrigger();
            renderList();
        },
        setSelected(arr, silent = false) {
            state.selected = new Set(arr || []);
            renderTrigger();
            renderList();
            if (!silent) state.onChange([...state.selected]);
        },
        getSelected() { return [...state.selected]; },
        close: closePanel,
        refresh() { renderTrigger(); renderList(); },
    };
    if (opts.key) _msInstances[opts.key] = api;
    return api;
}

// Global click listener — đóng mọi multi-select panel nếu click ngoài (1 lần khi load)
document.addEventListener("click", (e) => {
    if (e.target.closest(".ms-container")) return;  // click trong 1 dropdown → skip
    Object.values(_msInstances).forEach(inst => inst && inst.close && inst.close());
});

/**
 * Fill 3 multi-select Module / Quy trình / PIC.
 * Gọi lại mỗi lần applyDashboardResponse — nhưng chỉ init component 1 lần
 * (nếu instance đã tồn tại → refresh options).
 */
function populateGlobalFilters(appliedFilter) {
    const s = structureCache || {
        all_modules: metricsData.structure.all_modules || [],
        all_processes: metricsData.structure.all_processes || [],
        all_pics: metricsData.structure.all_pics || [],
        processes_by_module: metricsData.structure.processes_by_module || {},
    };

    // Init hoặc refresh 3 dropdown
    if (!_msInstances.modules) {
        createMultiSelect({
            el: "#globalFilterModule",
            key: "modules",
            label: "Module",
            options: s.all_modules,
            selected: globalFilters.modules,
            allText: "Tất cả module",
            onChange: (arr) => {
                globalFilters.modules = arr;
                // Wave 3: cascade CẢ Quy trình VÀ PIC theo module vừa chọn.
                // Task: khi chọn Module=PR → dropdown PIC chỉ hiện PIC có work ở PR.
                // Dropdown Module KHÔNG cascade ngược từ PIC/Process → giữ full option.
                _refreshProcessOptions();
                _refreshPicOptions();
                onGlobalFilterChange();
            },
        });
    } else {
        _msInstances.modules.setOptions(s.all_modules, /*dropInvalid=*/false);
        _msInstances.modules.setSelected(globalFilters.modules, /*silent=*/true);
    }

    if (!_msInstances.processes) {
        createMultiSelect({
            el: "#globalFilterProcess",
            key: "processes",
            label: "Quy trình",
            options: _computeCascadedProcesses(s),
            selected: globalFilters.processes,
            allText: "Tất cả quy trình",
            onChange: (arr) => {
                globalFilters.processes = arr;
                onGlobalFilterChange();
            },
        });
    } else {
        _refreshProcessOptions();
    }

    if (!_msInstances.pics) {
        createMultiSelect({
            el: "#globalFilterPIC",
            key: "pics",
            label: "PIC",
            // Wave 3: PIC dropdown cascade theo Module đang chọn.
            options: _computeCascadedPics(s),
            selected: globalFilters.pics,
            allText: "Tất cả PIC",
            onChange: (arr) => {
                globalFilters.pics = arr;
                onGlobalFilterChange();
            },
        });
    } else {
        _refreshPicOptions();
    }

    // Update banner status
    const status = document.getElementById("globalFilterStatus");
    const clearBtn = document.getElementById("globalFilterClear");
    if (appliedFilter) {
        const parts = [];
        if (appliedFilter.modules && appliedFilter.modules.length) {
            parts.push(`Module: <b>${appliedFilter.modules.map(escapeHtml).join(", ")}</b>`);
        }
        if (appliedFilter.processes && appliedFilter.processes.length) {
            parts.push(`Quy trình: <b>${appliedFilter.processes.map(escapeHtml).join(", ")}</b>`);
        }
        if (appliedFilter.pics && appliedFilter.pics.length) {
            parts.push(`PIC: <b>${appliedFilter.pics.map(escapeHtml).join(", ")}</b>`);
        }
        status.innerHTML = `🎯 Đang lọc → ${parts.join(" · ")} · <b>${appliedFilter.row_count}</b> function`;
        clearBtn.classList.remove("hidden");
    } else {
        status.innerHTML = "";
        clearBtn.classList.add("hidden");
    }
}

/**
 * Tính danh sách Quy trình available sau cascade từ module đang chọn.
 * - modules rỗng → toàn bộ all_processes
 * - modules chọn nhiều → UNION các processes_by_module[m] (OR — vì filter module OR)
 */
function _computeCascadedProcesses(structOrNull) {
    const s = structOrNull || structureCache;
    if (!s) return [];
    const mods = globalFilters.modules || [];
    if (mods.length === 0) return s.all_processes || [];
    const pbm = s.processes_by_module || {};
    const merged = new Set();
    mods.forEach(m => {
        (pbm[m] || []).forEach(p => merged.add(p));
    });
    return [...merged].sort();
}

/**
 * Tính danh sách PIC available sau cascade từ module đang chọn.
 * - modules rỗng → toàn bộ all_pics
 * - modules chọn nhiều → UNION các pics_by_module[m]
 *
 * Note: PIC có thể work cross-module (1 người làm nhiều module) → union OR.
 * User đã chọn PIC không thuộc scope → giữ dưới dạng stale-option (không drop).
 */
function _computeCascadedPics(structOrNull) {
    const s = structOrNull || structureCache;
    if (!s) return [];
    const mods = globalFilters.modules || [];
    if (mods.length === 0) return s.all_pics || [];
    const pbm = s.pics_by_module || {};
    const merged = new Set();
    mods.forEach(m => {
        (pbm[m] || []).forEach(p => merged.add(p));
    });
    return [...merged].sort();
}

/**
 * Rebuild options cho Quy trình dropdown. Wave 3: KHÔNG drop selected —
 * option không hợp lệ giữ lại dạng stale (⚠️) để user biết filter đang lọc rỗng.
 */
function _refreshProcessOptions() {
    if (!_msInstances.processes) return;
    const opts = _computeCascadedProcesses();
    _msInstances.processes.setOptions(opts, /*dropInvalid=*/false);
    // Đồng bộ state từ component (selection giữ nguyên vì preserve)
    globalFilters.processes = _msInstances.processes.getSelected();
}

/**
 * Rebuild options cho PIC dropdown. Wave 3: cascade PIC theo Module,
 * preserve selection (stale marker cho PIC ngoài scope).
 */
function _refreshPicOptions() {
    if (!_msInstances.pics) return;
    const opts = _computeCascadedPics();
    _msInstances.pics.setOptions(opts, /*dropInvalid=*/false);
    globalFilters.pics = _msInstances.pics.getSelected();
}

// Debounce để tránh spam gọi API khi user click nhanh nhiều checkbox liên tiếp
let _filterFetchTimer = null;
async function onGlobalFilterChange() {
    if (_filterFetchTimer) clearTimeout(_filterFetchTimer);
    _filterFetchTimer = setTimeout(_doGlobalFilterFetch, 180);
}

async function _doGlobalFilterFetch() {
    try {
        const url = _buildDashboardUrl();
        const r = await fetch(url);
        if (!r.ok) {
            showToast("Không tải được dashboard", "red");
            return;
        }
        const data = await r.json();
        applyDashboardResponse(data);
        if (data.applied_filter) {
            const rc = data.applied_filter.row_count;
            if (rc === 0) {
                showToast("Không có function nào khớp filter", "red");
            } else {
                showToast(`Đã lọc: ${rc} function`);
            }
        }
    } catch (e) {
        showToast("Lỗi mạng: " + e.message, "red");
    }
}

function clearGlobalFilters() {
    globalFilters = { modules: [], processes: [], pics: [] };
    // Reset UI + trigger 1 lần fetch (setSelected silent để tránh 3 lần fetch)
    if (_msInstances.modules) _msInstances.modules.setSelected([], /*silent=*/true);
    if (_msInstances.processes) _msInstances.processes.setSelected([], /*silent=*/true);
    if (_msInstances.pics) _msInstances.pics.setSelected([], /*silent=*/true);
    // Rebuild lại full options cho Quy trình + PIC (không còn module lọc)
    _refreshProcessOptions();
    _refreshPicOptions();
    onGlobalFilterChange();
}

/**
 * Hiển thị banner + ẩn dashboard chính khi filter ra 0 function.
 * Case xảy ra chủ yếu khi user chọn combination Module + Quy trình không
 * tồn tại trong dữ liệu (VD Module=PR nhưng Quy trình thuộc module HR).
 * Trước fix cascade, đây là root cause chính của bug "chart trống trắng".
 */
function renderEmptyFilterState(appliedFilter) {
    const banner = document.getElementById("globalFilterEmptyBanner");
    if (!banner) return;
    const isEmpty = !!(appliedFilter && appliedFilter.row_count === 0);
    if (isEmpty) {
        banner.classList.remove("hidden");
    } else {
        banner.classList.add("hidden");
    }
}

// ========================================================================
// DYNAMIC CHART SUBTITLE — hiển thị scope (đang lọc gì) trên từng chart
// ========================================================================
// Task 2 (P1): sau khi backend cascade đúng, user vẫn tưởng "chart hiện all"
// vì SUBTITLE static "Số function của toàn dữ án" không update. Thêm dòng
// scope động dưới mỗi chart chính để user biết đang xem SLICE nào.
// ------------------------------------------------------------------------

/**
 * Rút gọn tên quy trình → mã trước " – " / " - " (VD: "PRM.BP.03 – Foo" → "PRM.BP.03").
 * Dùng cho scope label để tránh text dài đè card.
 */
function _shortProcessCode(name) {
    if (!name) return "";
    const s = String(name);
    const m = s.split(/\s+[–-]\s+/);
    return (m[0] || s).trim();
}

/**
 * Trả chuỗi mô tả scope hiện tại, format thân thiện cho user.
 * Quy trình: chỉ hiện mã (max 2 rồi +N) để tránh sticky/overlap.
 * VD: "🔍 Đang lọc: Module = [PR] · Quy trình = [PRM.BP.03, PRM.BP.01]"
 */
function _buildScopeLabel(appliedFilter) {
    if (!appliedFilter) return "📂 Toàn bộ dữ liệu (chưa lọc)";
    const parts = [];
    const fmt = (arr, maxShow) => {
        const n = maxShow == null ? 3 : maxShow;
        return arr.length <= n
            ? arr.join(", ")
            : `${arr.slice(0, n).join(", ")} +${arr.length - n}`;
    };
    if (appliedFilter.modules && appliedFilter.modules.length) {
        parts.push(`Module = [${fmt(appliedFilter.modules)}]`);
    }
    if (appliedFilter.processes && appliedFilter.processes.length) {
        const codes = appliedFilter.processes.map(_shortProcessCode);
        parts.push(`Quy trình = [${fmt(codes, 2)}]`);
    }
    if (appliedFilter.pics && appliedFilter.pics.length) {
        parts.push(`PIC = [${fmt(appliedFilter.pics)}]`);
    }
    if (parts.length === 0) return "📂 Toàn bộ dữ liệu (chưa lọc)";
    return `🔍 Đang lọc: ${parts.join(" · ")} → <b>${appliedFilter.row_count}</b> function`;
}

/** Chuỗi FULL (không rút gọn) để gắn title tooltip trên .chart-scope. */
function _buildScopeTitleFull(appliedFilter) {
    if (!appliedFilter) return "Toàn bộ dữ liệu (chưa lọc)";
    const parts = [];
    const fmt = (arr) => arr.join(", ");
    if (appliedFilter.modules && appliedFilter.modules.length) {
        parts.push(`Module = [${fmt(appliedFilter.modules)}]`);
    }
    if (appliedFilter.processes && appliedFilter.processes.length) {
        parts.push(`Quy trình = [${fmt(appliedFilter.processes)}]`);
    }
    if (appliedFilter.pics && appliedFilter.pics.length) {
        parts.push(`PIC = [${fmt(appliedFilter.pics)}]`);
    }
    if (parts.length === 0) return "Toàn bộ dữ liệu (chưa lọc)";
    return `Đang lọc: ${parts.join(" · ")} → ${appliedFilter.row_count} function`;
}

/**
 * Cập nhật mọi element .chart-scope trên trang.
 * Hiển thị label rút gọn; title = text đầy đủ (hover để xem hết).
 */
function updateChartScopeSubtitles(appliedFilter) {
    const html = _buildScopeLabel(appliedFilter);
    const fullTitle = _buildScopeTitleFull(appliedFilter);
    const cls = appliedFilter ? "chart-scope active" : "chart-scope";
    document.querySelectorAll(".chart-scope").forEach(el => {
        el.innerHTML = html;
        el.className = cls;
        el.setAttribute("title", fullTitle);
    });
}

// ========================================================================
// PROJECT MANAGER MODAL
// ========================================================================

async function openProjectManager() {
    document.getElementById("projectManagerModal").classList.remove("hidden");
    document.getElementById("projectManagerModal").classList.add("flex");
    await refreshProjectListInModal();
}

function closeProjectManager() {
    document.getElementById("projectManagerModal").classList.add("hidden");
    document.getElementById("projectManagerModal").classList.remove("flex");
}

async function refreshProjectListInModal() {
    const container = document.getElementById("projectList");
    container.innerHTML = '<div class="text-gray-400 text-center py-4">Đang tải…</div>';
    try {
        const r = await fetch("/api/projects?include_archived=1");
        const data = await r.json();
        allProjects = data.projects.filter(p => !p.is_archived);
        const archived = data.projects.filter(p => p.is_archived);

        if (data.projects.length === 0) {
            container.innerHTML = '<div class="text-gray-500 py-4 text-center">Chưa có project nào.</div>';
            return;
        }

        const rows = [];
        for (const p of data.projects) {
            const isActive = p.slug === currentProjectSlug;
            const badge = p.is_archived
                ? '<span class="text-xs bg-gray-300 text-gray-700 px-2 py-0.5 rounded">Archived</span>'
                : isActive
                    ? '<span class="text-xs bg-green-100 text-green-700 px-2 py-0.5 rounded">Đang chọn</span>'
                    : '';
            const lastUpload = p.last_upload_at
                ? new Date(p.last_upload_at).toLocaleString("vi-VN")
                : '<span class="text-gray-400">Chưa upload</span>';
            const actions = p.is_archived
                ? `<button onclick="restoreProject('${p.slug}')" class="text-blue-600 hover:underline text-xs">Khôi phục</button>
                   <button onclick="deleteProjectHard('${p.slug}')" class="text-red-600 hover:underline text-xs">Xóa vĩnh viễn</button>`
                : `<button onclick="renameProjectPrompt('${p.slug}','${escapeAttr(p.name)}','${escapeAttr(p.description || '')}')" class="text-blue-600 hover:underline text-xs">Đổi tên</button>
                   <button onclick="exportProjectByslug('${p.slug}')" class="text-emerald-600 hover:underline text-xs">Xuất .zip</button>
                   ${p.slug !== 'default' ? `<button onclick="archiveProject('${p.slug}')" class="text-orange-600 hover:underline text-xs">Archive</button>
                   <button onclick="deleteProjectHard('${p.slug}')" class="text-red-600 hover:underline text-xs">Xóa</button>` : '<span class="text-xs text-gray-400">(project mặc định)</span>'}`;

            rows.push(`
              <div class="border dark:border-slate-600 rounded-lg p-3 ${isActive ? 'bg-green-50 dark:bg-slate-700' : 'bg-white dark:bg-slate-800'}">
                <div class="flex items-center justify-between gap-2 flex-wrap">
                  <div>
                    <div class="font-semibold text-gray-800 dark:text-gray-100">${escapeHtml(p.name)} ${badge}</div>
                    <div class="text-xs text-gray-500 dark:text-gray-400">Slug: <code>${p.slug}</code> · ${p.snapshot_count} snapshot · Upload gần nhất: ${lastUpload}</div>
                    ${p.description ? `<div class="text-xs text-gray-600 dark:text-gray-300 mt-1">${escapeHtml(p.description)}</div>` : ''}
                  </div>
                  <div class="flex gap-2 flex-wrap">${actions}</div>
                </div>
              </div>
            `);
        }
        container.innerHTML = rows.join("");
    } catch (err) {
        container.innerHTML = `<div class="text-red-500 py-4 text-center">Lỗi: ${err.message}</div>`;
    }
}

async function createNewProject() {
    const name = document.getElementById("newProjectName").value.trim();
    const desc = document.getElementById("newProjectDesc").value.trim();
    if (!name) {
        showToast("Vui lòng nhập tên project", "red");
        return;
    }
    try {
        const r = await fetch("/api/projects", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ name, description: desc }),
        });
        const data = await r.json();
        if (!r.ok) throw new Error(data.error || "Lỗi tạo project");
        document.getElementById("newProjectName").value = "";
        document.getElementById("newProjectDesc").value = "";
        showToast(`Đã tạo project: ${data.project.name}`);
        await loadProjectList();
        await refreshProjectListInModal();
        // Tự động switch sang project mới
        currentProjectSlug = data.project.slug;
        document.getElementById("projectSelector").value = currentProjectSlug;
        localStorage.setItem("current_project", currentProjectSlug);
        updateUploadTargetLabel();
    } catch (err) {
        showToast("Lỗi: " + err.message, "red");
    }
}

async function renameProjectPrompt(slug, currentName, currentDesc) {
    const newName = prompt("Đổi tên project:", currentName);
    if (!newName || newName.trim() === "") return;
    const newDesc = prompt("Mô tả (để trống nếu không đổi):", currentDesc || "");
    try {
        const r = await fetch(`/api/projects/${slug}`, {
            method: "PUT",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ name: newName.trim(), description: newDesc ?? currentDesc }),
        });
        if (!r.ok) throw new Error("Lỗi");
        showToast("Đã đổi tên project");
        await loadProjectList();
        await refreshProjectListInModal();
    } catch (err) {
        showToast("Lỗi đổi tên: " + err.message, "red");
    }
}

async function archiveProject(slug) {
    if (!confirm("Archive project này? (có thể khôi phục sau)")) return;
    const r = await fetch(`/api/projects/${slug}?soft=1`, { method: "DELETE" });
    if (r.ok) {
        showToast("Đã archive project");
        // Nếu đang chọn project này → switch về default
        if (currentProjectSlug === slug) {
            currentProjectSlug = "default";
            document.getElementById("projectSelector").value = "default";
            localStorage.setItem("current_project", "default");
            await switchProject("default");
        }
        await loadProjectList();
        await refreshProjectListInModal();
    }
}

async function restoreProject(slug) {
    const r = await fetch(`/api/projects/${slug}/restore`, { method: "POST" });
    if (r.ok) {
        showToast("Đã khôi phục project");
        await loadProjectList();
        await refreshProjectListInModal();
    }
}

async function deleteProjectHard(slug) {
    if (!confirm(`XÓA VĨNH VIỄN project "${slug}"?\nToàn bộ file, snapshot, meta sẽ mất — không hồi phục được.`)) return;
    const r = await fetch(`/api/projects/${slug}`, { method: "DELETE" });
    if (r.ok) {
        showToast("Đã xóa project");
        if (currentProjectSlug === slug) {
            currentProjectSlug = "default";
            document.getElementById("projectSelector").value = "default";
            localStorage.setItem("current_project", "default");
            await switchProject("default");
        }
        await loadProjectList();
        await refreshProjectListInModal();
    } else {
        const err = await r.json();
        showToast("Lỗi: " + (err.error || "Không xóa được"), "red");
    }
}

async function exportProjectByslug(slug) {
    window.location.href = `/api/projects/${slug}/export-package`;
}

async function exportCurrentProject() {
    await exportProjectByslug(currentProjectSlug);
}

async function importProjectFromZip(file) {
    if (!file) return;
    const fd = new FormData();
    fd.append("file", file);
    try {
        const r = await fetch("/api/projects/import-package", { method: "POST", body: fd });
        const data = await r.json();
        if (!r.ok) throw new Error(data.error || "Lỗi import");
        showToast(`Đã import: ${data.project.name}`);
        await loadProjectList();
        await refreshProjectListInModal();
    } catch (err) {
        showToast("Lỗi import: " + err.message, "red");
    }
}

function escapeAttr(s) {
    return String(s || "").replace(/["'\\]/g, m => "\\" + m);
}

// ========================================================================
// UPLOAD
// ========================================================================
async function handleFile(file) {
    if (!file.name.toLowerCase().endsWith(".xlsx") && !file.name.toLowerCase().endsWith(".xls")) {
        showToast("Chỉ hỗ trợ file .xlsx", "red");
        return;
    }
    document.getElementById("uploadProgress").classList.remove("hidden");

    const formData = new FormData();
    formData.append("file", file);
    const threshold = document.getElementById("durationThreshold")?.value || 3;

    try {
        // Upload vào project hiện tại
        const url = `/api/projects/${currentProjectSlug}/upload?threshold=${threshold}`;
        const resp = await fetch(url, { method: "POST", body: formData });
        const data = await resp.json();
        if (data.error) {
            showToast("Lỗi: " + data.error, "red");
            return;
        }
        applyDashboardResponse(data);
        // Refresh project list để cập nhật snapshot_count + last_upload_at
        await loadProjectList();
        showToast(`Đã tải ${data.rows_count} chức năng vào project "${data.project.name}"!`);
    } catch (err) {
        showToast("Lỗi kết nối server: " + err.message, "red");
    } finally {
        document.getElementById("uploadProgress").classList.add("hidden");
    }
}

async function applyThreshold() {
    // Re-upload không khả thi (mất file). Chỉ đơn giản re-render duration analysis
    // với threshold mới bằng cách lọc client-side.
    if (!metricsData) return;
    const t = parseInt(document.getElementById("durationThreshold").value) || 3;
    // Recompute local: gọi lại API dashboard sẽ không đổi threshold vì backend đã tính
    // → cần upload lại. Nhắc user.
    showToast(`Ngưỡng ${t} ngày. Upload lại file để backend áp dụng.`, "red");
    // Vẫn cập nhật lọc client-side cho bảng
    const dur = metricsData.duration_analysis;
    if (dur) {
        dur.threshold_days = t;
        dur.items = (dur.items || []).filter(i => i.duration_days > t);
        renderDurationSection();
    }
}

// ========================================================================
// MAIN RENDER
// ========================================================================
function renderDashboard() {
    if (!metricsData) return;

    // Mỗi render bọc try/catch — 1 chart lỗi không làm blank các chart sau
    const _safe = (name, fn) => {
        try { fn(); }
        catch (err) { console.error(`[renderDashboard] ${name} failed:`, err); }
    };

    _safe("summary", renderSummaryCards);
    _safe("module", () => {
        _loadModuleGroupBy();
        _fetchModuleOverview();
    });
    _safe("taskType", () => { _loadTaskTypeGroupBy(); renderTaskTypeChart(); });
    _safe("phaseMatrix", renderPhaseMatrix);
    _safe("phaseStacked", renderPhaseStackedChart);
    _safe("pic", renderPICChart);
    _safe("priority", renderPriorityChart);
    _safe("complexity", renderComplexityChart);
    _safe("fitGap", renderFitGapChart);
    _safe("giaiDoan", renderGiaiDoanChart);
    _safe("filters", populateFilters);
    _safe("overdue", renderOverdueTable);

    // V2 sections
    _safe("unassigned", renderUnassignedSection);
    _safe("duration", renderDurationSection);
    _safe("stalled", renderStalledSection);
    _safe("risk", renderRiskSection);
    _safe("effort", renderEffortSection);
    _safe("process", renderProcessTreemap);
    _safe("gantt", renderGanttTimeline);

    // Compare section (chỉ hiện nếu có >= 2 snapshots)
    _safe("compare", renderCompareSection);

    // T21: Data Quality panel (lazy fetch — không block render chính)
    _safe("dataQuality", loadDataQuality);

    // T22: Aging WIP tracking
    _safe("agingWip", loadAgingWip);

    // T24: Bookmarks section
    _safe("bookmarks", loadBookmarks);

    // Populate PIC dropdown (export by pic)
    _safe("picExport", populatePicExportSelect);
}

// ========================================================================
// 1. SUMMARY CARDS
// ========================================================================
function renderSummaryCards() {
    const s = metricsData.summary;
    const total = s.total_functions || 0;
    document.getElementById("cardTotal").textContent = total;
    document.getElementById("cardProgress").textContent = s.overall_progress_pct + "%";
    // Card mới dùng công thức weighted_all: closed_records / (rows × phases).
    // Show last_phase_pct + last_phase_name làm phụ chú để user hiểu.
    const cpLabel = document.getElementById("cardProgressLabel");
    if (cpLabel) {
        const lastPhaseInfo = s.last_phase_name
            ? ` · Riêng phase "${s.last_phase_name}": ${s.last_phase_progress_pct ?? 0}%`
            : "";
        cpLabel.innerHTML = `Weighted (closed / (rows × phases))${lastPhaseInfo}`;
        cpLabel.title = "Công thức: tổng số phase-record có status 'Closed' chia cho tổng (số function × số phase). Coi phase blank là 'chưa làm'. Đây là baseline nghiêm khắc phản ánh tiến độ tổng thể qua tất cả phase.";
        cpLabel.style.cursor = "help";
    }
    document.getElementById("cardOverdue").textContent = s.total_overdue;
    if (s.total_overdue_records && s.total_overdue_records !== s.total_overdue) {
        document.getElementById("cardOverdueRecords").textContent = ` (${s.total_overdue_records} phase)`;
    } else {
        document.getElementById("cardOverdueRecords").textContent = "";
    }
    document.getElementById("cardUnassigned").textContent = s.unassigned_count || 0;
    if (s.unassigned_records && s.unassigned_records !== s.unassigned_count) {
        document.getElementById("cardUnassignedRecords").textContent = ` (${s.unassigned_records} phase)`;
    } else {
        document.getElementById("cardUnassignedRecords").textContent = "";
    }
    document.getElementById("cardHighRisk").textContent = s.high_risk_count || 0;
    document.getElementById("cardModules").textContent = s.modules_count;

    // Wave 1 - Task 5: sub-info dòng 2 cho các card
    const pct = (n) => (total > 0 ? Math.round((n / total) * 100) : 0);
    const $sub = (id, text) => {
        const el = document.getElementById(id);
        if (el) el.textContent = text;
    };
    $sub("cardTotalSub", `${s.modules_count || 0} module · ${(metricsData.structure?.all_pics || []).length} PIC`);
    $sub("cardProgressSub", s.last_phase_name ? `trong ${total} function` : "");
    $sub("cardOverdueSub", total ? `${pct(s.total_overdue)}% tổng · click để xem` : "click để xem");
    $sub("cardUnassignedSub", total ? `${pct(s.unassigned_count || 0)}% tổng · click để xem` : "click để xem");
    $sub("cardHighRiskSub", total ? `${pct(s.high_risk_count || 0)}% tổng · click để xem` : "click để xem");
    $sub("cardModulesSub", (metricsData.structure?.all_processes || []).length
        ? `${(metricsData.structure.all_processes || []).length} quy trình`
        : "");

    // Wire click drill-down cho Unassigned / High-risk cards
    const uaEl = document.getElementById("cardUnassigned")?.closest("div[onclick]");
    const hrEl = document.getElementById("cardHighRisk")?.closest("div[onclick]");
    if (uaEl && !uaEl.dataset.drillWired) {
        uaEl.dataset.drillWired = "1";
        uaEl.addEventListener("click", (ev) => {
            ev.preventDefault();
            openDrillDown("unassigned", {});
        });
    }
    if (hrEl && !hrEl.dataset.drillWired) {
        hrEl.dataset.drillWired = "1";
        hrEl.addEventListener("click", (ev) => {
            ev.preventDefault();
            openDrillDown("risk", { level: "high" });
        });
    }
}

// ========================================================================
// 2. MODULE TABLE
// ========================================================================
// Task 17: state cho segmented control "Nhóm theo" của Tổng quan Module.
// Persist trong localStorage cho từng project.
let _moduleGroupBy = "module";   // "module" | "process" | "both"
const _MO_EXPANDED = new Set();  // module names đang expand khi group_by=both
let _taskTypeGroupBy = "module"; // "module" | "process" cho chart task-type

function _ttKey() { return `taskTypeGroupBy:${currentProjectSlug || "default"}`; }
function _loadTaskTypeGroupBy() {
    try { _taskTypeGroupBy = localStorage.getItem(_ttKey()) || "module"; }
    catch(e) { _taskTypeGroupBy = "module"; }
    _syncTtGroupButtons();
}
function _syncTtGroupButtons() {
    document.querySelectorAll(".tt-group-btn").forEach(btn => {
        const active = btn.dataset.ttGroup === _taskTypeGroupBy;
        btn.classList.toggle("bg-blue-600", active);
        btn.classList.toggle("text-white", active);
        btn.classList.toggle("hover:bg-blue-50", !active);
    });
}
window.setTaskTypeGroupBy = function (mode) {
    _taskTypeGroupBy = mode;
    try { localStorage.setItem(_ttKey(), mode); } catch(e){}
    _syncTtGroupButtons();
    renderTaskTypeChart();
};

function _mgKey() { return `moduleGroupBy:${currentProjectSlug || "default"}`; }
function _loadModuleGroupBy() {
    try { _moduleGroupBy = localStorage.getItem(_mgKey()) || "module"; }
    catch(e) { _moduleGroupBy = "module"; }
    _syncMoGroupButtons();
}
function _syncMoGroupButtons() {
    document.querySelectorAll(".mo-group-btn").forEach(btn => {
        const active = btn.dataset.moGroup === _moduleGroupBy;
        btn.classList.toggle("bg-blue-600", active);
        btn.classList.toggle("text-white", active);
        btn.classList.toggle("hover:bg-blue-50", !active);
    });
}

window.setModuleGroupBy = async function (mode) {
    _moduleGroupBy = mode;
    try { localStorage.setItem(_mgKey(), mode); } catch(e){}
    _syncMoGroupButtons();
    await _fetchModuleOverview();
};

async function _fetchModuleOverview() {
    if (_moduleGroupBy === "module") {
        // Dùng data đã có sẵn trong metricsData (backward-compat).
        renderModuleTable();
        return;
    }
    // Fetch từ endpoint mới. BUG P0-B fix: bổ sung global filter query để
    // backend áp filter (trước đây endpoint trả ALL kể cả khi user filter
    // theo module/process/pic).
    try {
        const qsFilter = _buildFilterQuery();
        const url = `/api/projects/${currentProjectSlug}/module-overview?group_by=${_moduleGroupBy}${qsFilter ? "&" + qsFilter : ""}`;
        const r = await fetch(url);
        if (!r.ok) throw new Error(await r.text());
        const d = await r.json();
        _renderModuleTableCustom(d.rows, _moduleGroupBy);
    } catch (err) {
        console.error("[moduleOverview]", err);
        showToast("Lỗi tải overview: " + err.message, "red");
    }
}

function _mgProgressColor(pct) {
    // Task 19: dùng Palette.progressColor (semantic tiered đỏ/vàng/xanh).
    // Fallback logic cũ nếu Palette chưa load.
    if (window.Palette && window.Palette.progressColor) {
        return window.Palette.progressColor(pct);
    }
    return pct >= 70 ? "#16a34a"
         : pct >= 30 ? "#f59e0b" : "#dc2626";
}

function _mgRowHtml(r, opts = {}) {
    const color = _mgProgressColor(r.progress_pct);
    const indent = opts.indent ? "pl-6" : "";
    const clickAttr = opts.onclick
        ? `onclick="${opts.onclick}"`
        : `onclick="_moduleRowClickGeneric(this)"`;
    const dataAttrs = `data-mod="${escapeAttr(r.module || "")}" data-proc="${escapeAttr(r.process || "")}"`;
    return `<tr class="border-b hover:bg-blue-50 cursor-pointer" ${dataAttrs} ${clickAttr}>
        <td class="px-2 py-2 text-center">${r.stt}</td>
        <td class="px-2 py-2 font-semibold text-blue-700 ${indent}">
            ${opts.prefix || ""}${escapeHtml(r.label || r.module)}
        </td>
        <td class="px-2 py-2 text-center">${r.total}</td>
        <td class="px-2 py-2 text-center">${r.quy_trinh_count}</td>
        <td class="px-2 py-2">
            <div class="progress-bar-wrap">
                <div class="progress-bar-fill" style="width:${Math.max(r.progress_pct, 8)}%;background:${color}">
                    ${r.progress_pct}%
                </div>
            </div>
        </td>
        <td class="px-2 py-2 text-center text-xs">${escapeHtml(r.active_phase || "")}</td>
        <td class="px-2 py-2 text-center ${r.overdue_count > 0 ? 'text-red-600 font-bold' : ''}">${r.overdue_count}</td>
    </tr>`;
}

function _renderModuleTableCustom(rows, mode) {
    const tbody = document.getElementById("moduleTable");
    if (!tbody) return;
    if (mode === "process") {
        // 1 hàng / (module, process) — nhưng col Module đang hiện label từ meta.
        // Trong table header col 2 là "Module" — để tránh mất context, hiển thị
        // "MOD · PROCESS" trong col label.
        tbody.innerHTML = rows.map((r, i) => {
            r.label = `${r.module} · ${r.process}`;
            r.stt = i + 1;
            return _mgRowHtml(r, {
                onclick: "_moduleRowClickGeneric(this)",
            });
        }).join("");
        return;
    }
    if (mode === "both") {
        const parts = [];
        rows.forEach(m => {
            const expanded = _MO_EXPANDED.has(m.module);
            const arrow = expanded ? "▼ " : "▶ ";
            parts.push(_mgRowHtml(m, {
                prefix: `<span class="mo-toggle" data-mod="${escapeAttr(m.module)}">${arrow}</span>`,
                onclick: "_moToggleExpand(this)",
            }));
            if (expanded && (m.children || []).length) {
                m.children.forEach((c, ci) => {
                    c.stt = `${m.stt}.${ci + 1}`;
                    parts.push(_mgRowHtml(
                        { ...c, label: c.process },
                        { indent: true, onclick: "_moduleRowClickGeneric(this)" },
                    ));
                });
            }
        });
        tbody.innerHTML = parts.join("");
        return;
    }
    // fallback = module
    renderModuleTable();
}

window._moToggleExpand = function (el) {
    const mod = el.dataset.mod;
    if (!mod) return;
    if (_MO_EXPANDED.has(mod)) _MO_EXPANDED.delete(mod);
    else _MO_EXPANDED.add(mod);
    _fetchModuleOverview();
};

window._moduleRowClickGeneric = function (el) {
    const mod = el.dataset.mod;
    const proc = el.dataset.proc;
    if (proc) return openDrillDown("module", { module: mod, process: proc });
    if (mod)  return openDrillDown("module", { module: mod });
};

function renderModuleTable() {
    const tbody = document.getElementById("moduleTable");
    const rows = metricsData.module_overview;
    tbody.innerHTML = rows.map(r => {
        const color = _mgProgressColor(r.progress_pct);
        return `<tr class="border-b hover:bg-blue-50 cursor-pointer"
                    data-mod="${escapeAttr(r.module)}" onclick="_moduleRowClick(this)"
                    title="Click để xem chi tiết ${escapeAttr(r.total)} function của module ${escapeAttr(r.module)}">
            <td class="px-2 py-2 text-center">${r.stt}</td>
            <td class="px-2 py-2 font-semibold text-blue-700">${escapeHtml(r.module)}</td>
            <td class="px-2 py-2 text-center">${r.total}</td>
            <td class="px-2 py-2 text-center">${r.quy_trinh_count}</td>
            <td class="px-2 py-2">
                <div class="progress-bar-wrap">
                    <div class="progress-bar-fill" style="width:${Math.max(r.progress_pct, 8)}%;background:${color}">
                        ${r.progress_pct}%
                    </div>
                </div>
            </td>
            <td class="px-2 py-2 text-center text-xs">${escapeHtml(r.active_phase)}</td>
            <td class="px-2 py-2 text-center ${r.overdue_count > 0 ? 'text-red-600 font-bold' : ''}">${r.overdue_count}</td>
        </tr>`;
    }).join("");
}

// Click 1 row Module Overview → drill-down full list function của module đó
function _moduleRowClick(el) {
    const mod = el.dataset.mod;
    if (mod) openDrillDown("module", { module: mod });
}

/**
 * Hiện thông báo trống trong .chart-box (không để canvas blank).
 * Distribution charts (Priority/Complexity/TaskType/Giai đoạn) LUÔN vẽ chart
 * khi có data — KHÔNG thay bằng single-group card.
 * Single-group card CHỈ dành cho multi-group comparison (FIT/GAP, Process treemap).
 */
function _showChartEmpty(canvasId, message) {
    if (chartInstances[canvasId]) {
        try { chartInstances[canvasId].destroy(); } catch (e) {}
        delete chartInstances[canvasId];
    }
    const canvas = document.getElementById(canvasId);
    if (!canvas) return;
    const box = canvas.closest(".chart-box") || canvas.parentElement;
    if (!box) return;
    canvas.style.display = "none";
    box.querySelectorAll(".chart-empty-msg, .single-group-wrap").forEach(el => el.remove());
    const msg = document.createElement("div");
    msg.className = "chart-empty-msg";
    msg.textContent = message || "Không có dữ liệu";
    box.appendChild(msg);
}

/** Xóa empty message / card, hiện lại canvas trước khi vẽ chart. */
function _clearChartEmpty(canvasId) {
    const canvas = document.getElementById(canvasId);
    if (!canvas) return;
    canvas.style.display = "";
    const box = canvas.closest(".chart-box") || canvas.parentElement;
    if (!box) return;
    box.querySelectorAll(".chart-empty-msg, .single-group-wrap").forEach(el => el.remove());
}

// ========================================================================
// 3. TASK TYPE CHART — aggregate 1 bar / task_type (mean % across modules)
// ========================================================================
function renderTaskTypeChart() {
    try {
        const d = metricsData.progress_by_task_type || {};
        const taskTypes = d.task_types || [];
        if (!taskTypes.length) {
            _showChartEmpty("chartTaskType", "Không có dữ liệu loại công việc");
            return;
        }
        _clearChartEmpty("chartTaskType");
        _restoreCanvas("chartTaskType");
        const ctx = getCanvas("chartTaskType");
        if (!ctx) return;

        // Task 17: aggregate theo Module (mặc định) hoặc theo Quy trình.
        // Trung bình % Closed của các group có dữ liệu cho từng task_type.
        const groupBy = _taskTypeGroupBy || "module";
        const bySource = groupBy === "process" ? (d.by_process || {}) : (d.by_module || {});
        const groups = Object.keys(bySource);
        const values = taskTypes.map(tt => {
            const vals = groups
                .map(g => bySource[g]?.[tt])
                .filter(v => v !== undefined && v !== null);
            if (!vals.length) return 0;
            return Math.round(vals.reduce((a, b) => a + b, 0) / vals.length);
        });

        // Task 19: mỗi bar tô màu semantic tiered theo % Closed (đỏ/vàng/xanh)
        // thay vì random categorical → user đọc được ngay task nào yếu.
        const bgColors = values.map(v => window.Palette?.progressColor
            ? window.Palette.progressColor(v)
            : CHART_PALETTE[values.indexOf(v) % CHART_PALETTE.length]);
        const chart = createChart(ctx, "bar", {
            labels: taskTypes,
            datasets: [{
                label: "% Closed",
                data: values,
                backgroundColor: bgColors,
                borderRadius: 3,
            }],
        }, {
            layout: { padding: { top: 24 } },
            plugins: {
                legend: { display: false },
                tooltip: {
                    callbacks: {
                        label: (c) => `${c.label}: ${c.parsed.y}%`,
                        footer: () => "💡 Click để xem chi tiết",
                    },
                },
                datalabels: _labelsForVerticalBar("%", 0),
            },
            scales: {
                y: { beginAtZero: true, max: 100, ticks: { callback: v => v + "%", stepSize: 20 },
                     grid: { color: "rgba(148, 163, 184, 0.15)" } },
                x: { ticks: { font: { size: 10 } }, grid: { display: false } },
            },
            onHover: CLICKABLE_CHART_OPTS.onHover,
            onClick: _chartClickHandler("task_type", (el, chart) => ({
                task_type: chart.data.labels[el.index],
            })),
        });
        try { if (chart) chart.resize(); } catch (e) {}
    } catch (err) {
        console.error("[renderTaskTypeChart]", err);
        _showChartEmpty("chartTaskType", "Lỗi render chart công việc");
    }
}

// ========================================================================
// 4. PHASE × MODULE MATRIX
// ========================================================================
function renderPhaseMatrix() {
    const m = metricsData.phase_status_matrix;
    const phases = m.phases;
    const modules = m.modules;

    const thead = document.getElementById("matrixHead");
    thead.innerHTML = `<tr class="bg-gray-800 text-white text-xs">
        <th class="px-2 py-2 text-left">Module</th>
        ${phases.map(p => `<th class="px-2 py-2 text-center">${p}</th>`).join("")}
    </tr>`;

    const tbody = document.getElementById("matrixBody");
    tbody.innerHTML = modules.map(mod => {
        const cells = phases.map(ph => {
            const cell = m.data[mod]?.[ph] || {};
            const pct = cell.pct_closed || 0;
            const total = cell.total || 0;
            const closed = cell.Closed || 0;
            const inprog = cell["In-progress"] || 0;
            const assigned = cell["Assigned"] || 0;
            const open = cell["Open"] || 0;
            const bg = total === 0 ? "var(--heatmap-none)"
                     : pct === 100 ? "#166534"
                     : pct >= 80 ? "#22c55e"
                     : pct >= 50 ? "#eab308"
                     : pct >= 20 ? "#f97316" : "#ef4444";
            const textColor = (pct >= 80 && total > 0) || total === 0 ? "white" : "#1e293b";
            const tooltip = total > 0
                ? `${mod} × ${ph} · ${closed}/${total} Closed (${pct}%) · In-prog: ${inprog} · Assign: ${assigned} · Open: ${open}`
                : "Không có dữ liệu";
            const clickAttr = total > 0
                ? `data-mod="${escapeAttr(mod)}" data-ph="${escapeAttr(ph)}" onclick="_matrixCellClick(this)" style="cursor:pointer"`
                : "";

            return `<td class="px-1 py-1 text-center" ${clickAttr} title="${escapeAttr(tooltip)}">
                <div class="heatmap-cell rounded px-2 py-2 text-xs font-semibold"
                     style="background:${bg};color:${total === 0 ? '#9ca3af' : textColor}">
                    ${total > 0 ? pct + "%" : "-"}
                    <div class="heatmap-tooltip">${escapeHtml(tooltip)}${total > 0 ? "<br>💡 Click để xem chi tiết" : ""}</div>
                </div>
            </td>`;
        }).join("");
        return `<tr class="border-b"><td class="px-2 py-2 font-semibold text-sm">${mod}</td>${cells}</tr>`;
    }).join("");
}

// ========================================================================
// 5. PHASE STACKED CHART
// ========================================================================
function renderPhaseStackedChart() {
    const d = metricsData.phase_progress_stacked;
    const ctx = getCanvas("chartPhaseStacked");
    // Bug 6 fix: override global Chart.defaults.datasets.bar.borderRadius=4.
    // Trong stacked bar, borderRadius trên MỌI segment làm segment nhỏ bị "nuốt"
    // → user chỉ thấy segment lớn nhất (Closed) sau khi filter, các status khác
    // (Assigned, In-progress...) bị mất tích dù data đúng.
    // Đặt borderRadius=0 và borderSkipped=false để mọi segment đều render đủ.
    const datasets = d.statuses.map(status => ({
        label: status,
        data: d.phases.map(ph => d.data[ph]?.[status] || 0),
        backgroundColor: STATUS_COLORS[status] || "#94a3b8",
        borderWidth: 0,
        borderRadius: 0,
        borderSkipped: false,
        stack: "phase_status",  // explicit stack group cho tường minh
    }));

    createChart(ctx, "bar", { labels: d.phases, datasets }, {
        plugins: {
            legend: {
                position: "top",
                labels: { font: { size: 10 }, padding: 10, boxWidth: 10, usePointStyle: true },
            },
            tooltip: {
                callbacks: {
                    label: (c) => {
                        const total = (c.chart.data.datasets || [])
                            .reduce((s, ds) => s + (Number(ds.data[c.dataIndex]) || 0), 0);
                        const pct = total ? Math.round((c.parsed.y / total) * 100) : 0;
                        return `${c.dataset.label}: ${c.parsed.y}  (${pct}% của phase)`;
                    },
                    footer: () => "💡 Click để xem chi tiết",
                },
            },
            datalabels: _labelsForStackedBar(5),
        },
        scales: {
            x: { stacked: true, ticks: { font: { size: 10 } }, grid: { display: false } },
            y: { stacked: true, beginAtZero: true, grid: { color: "rgba(148, 163, 184, 0.15)" } },
        },
        onHover: CLICKABLE_CHART_OPTS.onHover,
        onClick: _chartClickHandler("phase_stacked", (el, chart) => {
            const phase = chart.data.labels[el.index];
            const status = chart.data.datasets[el.datasetIndex].label;
            return { phase, status };
        }),
    });
}

// ========================================================================
// 6. PIC CHART — Wave 2: thêm filter "Xem theo phase"
// ========================================================================

/**
 * Populate options cho dropdown #picChartPhaseSelector.
 * - Option đầu: "Tất cả phase" (value="")
 * - Sau đó: liệt kê all_phases từ structure
 * Giữ nguyên value đang chọn nếu vẫn còn hợp lệ (case user filter data).
 */
function _populatePICPhaseSelector() {
    const sel = document.getElementById("picChartPhaseSelector");
    if (!sel) return;
    const phases = (metricsData?.structure?.all_phases || []);
    const prev = sel.value;
    sel.innerHTML = `<option value="">Tất cả phase</option>` +
        phases.map(p => `<option value="${escapeAttr(p)}">${escapeHtml(p)}</option>`).join("");
    // Giữ lại lựa chọn cũ nếu vẫn còn phase đó
    if (prev && phases.includes(prev)) sel.value = prev;
    else sel.value = "";
}

function renderPICChart() {
    _populatePICPhaseSelector();
    const sel = document.getElementById("picChartPhaseSelector");
    const selectedPhase = sel ? sel.value : "";

    // Nếu chọn 1 phase cụ thể → map mỗi PIC sang stats của phase đó (fallback = 0)
    // Sau đó lọc bỏ PIC có total=0 (không tham gia phase này) và sort giảm dần theo total,
    // lấy top 15. Nếu "Tất cả phase" → dùng aggregate như cũ.
    let workingPics;
    if (selectedPhase) {
        const source = (metricsData.pic_workload || [])
            .map(p => {
                const stats = (p.by_phase && p.by_phase[selectedPhase]) || null;
                if (!stats || !stats.total) return null;  // PIC không làm phase này
                return {
                    pic: p.pic,
                    closed: stats.closed || 0,
                    in_progress: stats.in_progress || 0,
                    assigned: stats.assigned || 0,
                    overdue: stats.overdue || 0,
                    _total: stats.total,  // dùng để sort
                };
            })
            .filter(Boolean)
            .sort((a, b) => b._total - a._total);
        workingPics = source.slice(0, 15);
    } else {
        workingPics = (metricsData.pic_workload || []).slice(0, 15);
    }

    // Empty-state: 0 hoặc 1 PIC → bar chart không có nghĩa so sánh workload
    if (workingPics.length <= 1) {
        const only = workingPics[0];
        if (only) {
            const total = (only.closed || 0) + (only.in_progress || 0) + (only.assigned || 0);
            _replaceCanvasWithCard("chartPIC", {
                groupType: "PIC",
                groupName: only.pic,
                total,
                pctClosed: total ? Math.round(((only.closed || 0) / total) * 100) : 0,
                extra: (selectedPhase ? `Phase: ${selectedPhase} · ` : "") + `Overdue: ${only.overdue || 0}`,
            });
        } else {
            _replaceCanvasWithCard("chartPIC", {
                groupType: "PIC",
                groupName: selectedPhase
                    ? `Không có PIC nào ở phase "${selectedPhase}"`
                    : "Không có PIC nào",
                total: 0,
                hint: selectedPhase
                    ? "Chọn 'Tất cả phase' hoặc phase khác để xem workload"
                    : "Bỏ bớt bộ lọc để xem workload nhiều PIC",
            });
        }
        return;
    }
    _restoreCanvas("chartPIC");
    const ctx = getCanvas("chartPIC");
    // Map dataset label -> status filter cho backend
    const LABEL_TO_STATUS = {
        "Closed": "Closed",
        "In-progress": "In-progress",
        "Assigned": "Assigned",
        "Overdue": "overdue",
    };
    const picDatasets = [
        { label: "Closed", data: workingPics.map(p => p.closed), backgroundColor: "#22c55e" },
        { label: "In-progress", data: workingPics.map(p => p.in_progress), backgroundColor: "#3b82f6" },
        { label: "Assigned", data: workingPics.map(p => p.assigned), backgroundColor: "#f59e0b" },
        { label: "Overdue", data: workingPics.map(p => p.overdue), backgroundColor: "#ef4444" },
    ];
    createChart(ctx, "bar", {
        labels: workingPics.map(p => p.pic),
        datasets: picDatasets,
    }, {
        indexAxis: "y",
        plugins: {
            legend: { position: "top", labels: { font: { size: 10 } } },
            tooltip: {
                callbacks: {
                    // Nhắc user biết đang xem phase nào (tránh nhầm với aggregate)
                    title: (items) => {
                        const base = items[0]?.label || "";
                        return selectedPhase ? `${base} · Phase: ${selectedPhase}` : base;
                    },
                    footer: () => "💡 Click để xem chi tiết",
                },
            },
            datalabels: _labelsForBarTotal(picDatasets.length - 1),
        },
        scales: {
            x: { stacked: true, beginAtZero: true, grid: { color: "rgba(148, 163, 184, 0.15)" } },
            y: { stacked: true, ticks: { font: { size: 10 } }, grid: { display: false } },
        },
        onHover: CLICKABLE_CHART_OPTS.onHover,
        onClick: _chartClickHandler("pic_workload", (el, chart) => {
            const pic = chart.data.labels[el.index];
            const label = chart.data.datasets[el.datasetIndex].label;
            // Nếu đang xem 1 phase cụ thể → include phase vào filter drill-down
            const filters = { pic, status: LABEL_TO_STATUS[label] || "" };
            if (selectedPhase) filters.phase = selectedPhase;
            return filters;
        }),
    });
}

// ========================================================================
// 7. PRIORITY — distribution chart: LUÔN vẽ doughnut (không single-group card)
// ========================================================================
function renderPriorityChart() {
    const d = metricsData.priority_breakdown || {};
    const labels = Object.keys(d).filter(k => k !== "None" && k !== "N/A" && d[k] > 0);
    if (!labels.length) {
        _showChartEmpty("chartPriority", "Không có dữ liệu Priority");
        return;
    }
    _clearChartEmpty("chartPriority");
    _restoreCanvas("chartPriority");
    const ctx = getCanvas("chartPriority");
    if (!ctx) return;
    const values = labels.map(l => d[l]);
    const total = values.reduce((a, b) => a + b, 0);
    // Task 19: Priority fixed mapping — High=red, Medium=amber, Low=slate.
    const priColor = (lb) => {
        const s = (lb || "").toLowerCase();
        if (/high|must|1|critic/.test(s)) return window.Palette?.STATUS?.Overdue || "#dc2626";
        if (/med|should|2/.test(s))        return window.Palette?.STATUS?.Pending || "#f59e0b";
        if (/low|could|3/.test(s))         return window.Palette?.STATUS?.Open || "#64748b";
        // Categorical fallback (Nice/Won't/Other)
        return window.Palette?.CATEGORICAL?.[3] || "#76b7b2";
    };
    const priColors = labels.map(priColor);
    createChart(ctx, "doughnut", {
        labels,
        datasets: [{
            data: values,
            backgroundColor: priColors,
            borderColor: "#fff",
            borderWidth: 2,
            hoverOffset: 8,
        }],
    }, {
        cutout: "62%",
        plugins: {
            legend: { position: "bottom", labels: { font: { size: 11 }, padding: 10 } },
            tooltip: {
                callbacks: {
                    label: (c) => {
                        const pct = total ? ((c.parsed / total) * 100).toFixed(1) : 0;
                        return `${c.label}: ${c.parsed} function (${pct}%)`;
                    },
                    footer: () => "💡 Click để xem chi tiết",
                },
            },
            datalabels: _labelsForDoughnut(4),
        },
        onHover: CLICKABLE_CHART_OPTS.onHover,
        onClick: _chartClickHandler("priority", (el, chart) => ({
            priority: chart.data.labels[el.index],
        })),
    });
}

// ========================================================================
// 8. COMPLEXITY — distribution chart: LUÔN vẽ doughnut (không single-group card)
// ========================================================================
function renderComplexityChart() {
    const d = metricsData.complexity_breakdown || {};
    const labels = Object.keys(d).filter(k => k !== "None" && k !== "N/A" && d[k] > 0);
    if (!labels.length) {
        _showChartEmpty("chartComplexity", "Không có dữ liệu Complexity");
        return;
    }
    _clearChartEmpty("chartComplexity");
    _restoreCanvas("chartComplexity");
    const ctx = getCanvas("chartComplexity");
    if (!ctx) return;
    const values = labels.map(l => d[l]);
    const total = values.reduce((a, b) => a + b, 0);
    // Task 19: Complexity sequential — high=darkblue, med=blue, low=lightblue.
    const cmpColor = (lb) => {
        const s = (lb || "").toLowerCase();
        if (/high|hard|khó|3|complex/.test(s))       return "#1e3a8a";   // dark blue
        if (/med|trung|2|moderate/.test(s))          return "#3b82f6";   // blue
        if (/low|easy|dễ|1|simple/.test(s))          return "#93c5fd";   // light blue
        return "#94a3b8";   // slate
    };
    const cmpColors = labels.map(cmpColor);
    createChart(ctx, "doughnut", {
        labels,
        datasets: [{
            data: values,
            backgroundColor: cmpColors,
            borderColor: "#fff",
            borderWidth: 2,
            hoverOffset: 8,
        }],
    }, {
        cutout: "62%",
        plugins: {
            legend: { position: "bottom", labels: { font: { size: 11 }, padding: 10 } },
            tooltip: {
                callbacks: {
                    label: (c) => {
                        const pct = total ? ((c.parsed / total) * 100).toFixed(1) : 0;
                        return `${c.label}: ${c.parsed} function (${pct}%)`;
                    },
                    footer: () => "💡 Click để xem chi tiết",
                },
            },
            datalabels: _labelsForDoughnut(4),
        },
        onHover: CLICKABLE_CHART_OPTS.onHover,
        onClick: _chartClickHandler("complexity", (el, chart) => ({
            complexity: chart.data.labels[el.index],
        })),
    });
}

// ========================================================================
// 9. FIT/GAP — comparison chart: single-group card OK khi ≤1 module
// ========================================================================
function renderFitGapChart() {
    const d = metricsData.fit_gap_analysis;
    const modules = Object.keys(d);
    const allTypes = new Set();
    modules.forEach(m => Object.keys(d[m]).forEach(t => { if (t !== "None" && t !== "N/A") allTypes.add(t); }));
    const types = [...allTypes];

    // Empty-state: ≤ 1 module → bar không thể so sánh cross-module
    // (Single-group card CHỈ cho comparison charts — FIT/GAP, Process treemap)
    if (modules.length <= 1) {
        const mod = modules[0];
        if (mod) {
            const counts = types.map(t => d[mod][t] || 0);
            const total = counts.reduce((a, b) => a + b, 0);
            const breakdown = types.map((t, i) => `${t}: ${counts[i]}`).join(" · ");
            _replaceCanvasWithCard("chartFitGap", {
                groupType: "Module",
                groupName: mod,
                total,
                extra: breakdown,
            });
        } else {
            _replaceCanvasWithCard("chartFitGap", {
                groupType: "Module",
                groupName: "Không có module nào",
                total: 0,
            });
        }
        return;
    }
    _restoreCanvas("chartFitGap");
    const ctx = getCanvas("chartFitGap");
    // Task 19: FIT=green, GAP=red, khác=categorical.
    const fgColor = (t) => {
        const s = (t || "").toLowerCase();
        if (s === "fit") return window.Palette?.STATUS?.Closed || "#16a34a";
        if (s === "gap") return window.Palette?.STATUS?.Overdue || "#dc2626";
        return CHART_PALETTE[types.indexOf(t) % CHART_PALETTE.length];
    };
    const datasets = types.map(t => ({
        label: t,
        data: modules.map(m => d[m][t] || 0),
        backgroundColor: fgColor(t),
    }));
    createChart(ctx, "bar", { labels: modules, datasets }, {
        plugins: {
            legend: { position: "top" },
            tooltip: { callbacks: { footer: () => "💡 Click để xem chi tiết" } },
            datalabels: _labelsForStackedBar(6),
        },
        scales: {
            x: { stacked: true, grid: { display: false } },
            y: { stacked: true, beginAtZero: true, grid: { color: "rgba(148, 163, 184, 0.15)" } },
        },
        onHover: CLICKABLE_CHART_OPTS.onHover,
        onClick: _chartClickHandler("fit_gap", (el, chart) => {
            const module = chart.data.labels[el.index];
            const fit_gap = chart.data.datasets[el.datasetIndex].label;
            return { module, fit_gap };
        }),
    });
}

// ========================================================================
// 10. GIAI DOAN — distribution: LUÔN vẽ bar khi ≥1 giai đoạn (kể cả length===1)
// ========================================================================
function renderGiaiDoanChart() {
    const d = metricsData.giai_doan_progress || {};
    const giaiDoans = Object.keys(d);
    if (giaiDoans.length === 0) {
        document.getElementById("section-giaidoan").classList.add("hidden");
        return;
    }
    document.getElementById("section-giaidoan").classList.remove("hidden");
    const phases = metricsData.structure.all_phases;
    _clearChartEmpty("chartGiaiDoan");
    _restoreCanvas("chartGiaiDoan");
    const ctx = getCanvas("chartGiaiDoan");
    if (!ctx) return;
    const datasets = giaiDoans.map((gd, i) => ({
        label: "Giai đoạn " + gd,
        _gd: gd,   // giữ raw value để dispatch drill-down
        data: phases.map(ph => d[gd][ph]?.pct || 0),
        backgroundColor: CHART_PALETTE[i % CHART_PALETTE.length],
        borderRadius: 3,
    }));
    createChart(ctx, "bar", { labels: phases, datasets }, {
        layout: { padding: { top: 24 } },
        plugins: {
            legend: {
                position: "top",
                align: "start",
                // Bug 9 fix: label chồng lên nhau khi có > 2 giai đoạn.
                // Tăng padding + boxWidth để mỗi item có đủ chỗ; usePointStyle
                // cho legend gọn hơn, không dùng hình chữ nhật dài.
                labels: {
                    usePointStyle: true,
                    boxWidth: 8,
                    padding: 16,
                    font: { size: 11 },
                },
            },
            tooltip: {
                callbacks: {
                    label: (c) => {
                        const gd = c.dataset._gd;
                        const cell = (metricsData.giai_doan_progress || {})[gd]?.[c.label] || {};
                        const denom = cell.total ?? 0;
                        const closed = cell.closed ?? 0;
                        return `${c.dataset.label} · ${c.label}: ${c.parsed.y}%  (${closed}/${denom} func)`;
                    },
                    footer: () => "💡 Click để xem chi tiết",
                },
            },
            datalabels: _labelsForVerticalBar("%", 0),
        },
        scales: {
            y: { beginAtZero: true, max: 100, ticks: { callback: v => v + "%", stepSize: 20 },
                 grid: { color: "rgba(148, 163, 184, 0.15)" } },
            x: { grid: { display: false } },
        },
        onHover: CLICKABLE_CHART_OPTS.onHover,
        onClick: _chartClickHandler("giai_doan", (el, chart) => {
            const phase = chart.data.labels[el.index];
            const ds = chart.data.datasets[el.datasetIndex];
            const giai_doan = ds._gd;
            return { giai_doan, phase };
        }),
    });
}

// ========================================================================
// 11. OVERDUE
// ========================================================================
function populateFilters() {
    const s = metricsData.structure;
    // Task 15: Module + Phase dùng multi-select; PIC giữ single-select vì
    // có thể quá nhiều (list PIC riêng cho Overdue chỉ những người thực sự
    // có task trễ → dropdown scroll đủ dùng).
    const overduePics = new Set();
    metricsData.overdue_list.forEach(item => item.pic.forEach(p => overduePics.add(p)));
    fillSelect("filterPIC", [...overduePics].sort(), "Tất cả PIC");

    const onFilterChange = () => {
        pageState.overdue.page = 1;
        renderOverdueTable();
    };
    if (!_msInstances.overdueModule) {
        createMultiSelect({
            el: "#filterModuleMS",
            key: "overdueModule",
            label: "Module",
            options: s.all_modules || [],
            selected: [],
            allText: "Tất cả Module",
            onChange: onFilterChange,
        });
    } else {
        _msInstances.overdueModule.setOptions(s.all_modules || [], /*dropInvalid=*/false);
    }
    if (!_msInstances.overduePhase) {
        createMultiSelect({
            el: "#filterPhaseMS",
            key: "overduePhase",
            label: "Phase",
            options: s.all_phases || [],
            selected: [],
            allText: "Tất cả Phase",
            onChange: onFilterChange,
        });
    } else {
        _msInstances.overduePhase.setOptions(s.all_phases || [], /*dropInvalid=*/false);
    }
}

function fillSelect(id, options, defaultText) {
    const sel = document.getElementById(id);
    sel.innerHTML = `<option value="">${defaultText}</option>` +
        options.map(o => `<option value="${escapeHtml(o)}">${escapeHtml(o)}</option>`).join("");
}

function renderOverdueTable() {
    const tbody = document.getElementById("overdueTable");
    let items = metricsData.overdue_list;
    // Task 15: Module + Phase multi-select → array; PIC single-select → string.
    const fmArr = _msInstances.overdueModule?.getSelected?.() || [];
    const fphArr = _msInstances.overduePhase?.getSelected?.() || [];
    const fp = document.getElementById("filterPIC")?.value || "";
    if (fmArr.length) items = items.filter(i => fmArr.includes(i.module));
    if (fp) items = items.filter(i => i.pic.includes(fp));
    if (fphArr.length) items = items.filter(i => fphArr.includes(i.phase));

    const { start, end, pageItems } = _pageSlice("overdue", items);
    tbody.innerHTML = pageItems.map((item, idx) => {
        const cls = item.days_overdue > 14 ? "overdue-critical"
                  : item.days_overdue > 7 ? "overdue-warning" : "overdue-mild";
        return `<tr class="${cls}">
            <td class="px-2 py-2 text-center">${start + idx + 1}</td>
            <td class="px-2 py-2 font-mono text-xs">${escapeHtml(item.ma_cn)}</td>
            <td class="px-2 py-2">${escapeHtml(item.ten_cn)}</td>
            <td class="px-2 py-2 text-center">${escapeHtml(item.module)}</td>
            <td class="px-2 py-2 text-center text-xs">${escapeHtml(item.phase)}</td>
            <td class="px-2 py-2 text-center text-xs">${item.end_date}</td>
            <td class="px-2 py-2 text-center font-bold text-red-600">${item.days_overdue}</td>
            <td class="px-2 py-2 text-center">${statusBadge(item.status)}</td>
            <td class="px-2 py-2 text-xs">${escapeHtml(item.pic.join(", "))}</td>
            <td class="px-2 py-2 text-center text-xs">${escapeHtml(item.priority)}</td>
        </tr>`;
    }).join("");

    renderPager("overdueShowMoreWrap", "overdue", items.length, () => renderOverdueTable());

    document.getElementById("overdueCount").textContent =
        items.length === 0
            ? "Không có task trễ"
            : `Đang xem ${start + 1}–${end}/${items.length} task trễ deadline`;
}

async function exportOverdue() {
    // Task 15: Module + Phase multi-select → comma-sep (backend
    // _parse_multi_arg tự tách).
    const fmArr = _msInstances.overdueModule?.getSelected?.() || [];
    const fphArr = _msInstances.overduePhase?.getSelected?.() || [];
    const fp = document.getElementById("filterPIC")?.value || "";
    const params = new URLSearchParams();
    if (fmArr.length) params.set("module", fmArr.join(","));
    if (fp) params.set("pic", fp);
    if (fphArr.length) params.set("phase", fphArr.join(","));
    await downloadFile(`/api/projects/${currentProjectSlug}/export-overdue?` + params.toString(), "Overdue_Report.xlsx");
}

// ========================================================================
// V2: UNASSIGNED
// ========================================================================
// Pagination: mỗi bảng giữ {page, size}. size=0 nghĩa là "Tất cả".
const PAGE_DEFAULT_SIZE = 10;   // User yêu cầu default 10/page cho mọi bảng
const pageState = {
    overdue:    { page: 1, size: PAGE_DEFAULT_SIZE },
    unassigned: { page: 1, size: PAGE_DEFAULT_SIZE },
    duration:   { page: 1, size: PAGE_DEFAULT_SIZE },
    stalled:    { page: 1, size: PAGE_DEFAULT_SIZE },
    risk:       { page: 1, size: PAGE_DEFAULT_SIZE },
    drill:      { page: 1, size: PAGE_DEFAULT_SIZE },
    // P4+P5 tables: SLA, Capacity, Slow, Dependency, Baseline, History
    sla:        { page: 1, size: PAGE_DEFAULT_SIZE },
    capacity:   { page: 1, size: PAGE_DEFAULT_SIZE },
    slow:       { page: 1, size: PAGE_DEFAULT_SIZE },
    deps:       { page: 1, size: PAGE_DEFAULT_SIZE },
    baseline:   { page: 1, size: PAGE_DEFAULT_SIZE },
    history:    { page: 1, size: PAGE_DEFAULT_SIZE },
    // Task 2: FIT/GAP aging table
    fitgap:     { page: 1, size: PAGE_DEFAULT_SIZE },
    // Task 3: Function Diff — 1 pager dùng chung cho tab active
    fdiff:      { page: 1, size: PAGE_DEFAULT_SIZE },
};

/** Cắt page slice từ list theo pageState[sectionKey]. */
function _pageSlice(sectionKey, items) {
    const st = pageState[sectionKey] || { page: 1, size: PAGE_DEFAULT_SIZE };
    const total = items.length;
    if (!st.size || st.size <= 0) {
        // size=0 → Tất cả
        return { start: 0, end: total, pageItems: items };
    }
    const totalPages = Math.max(1, Math.ceil(total / st.size) || 1);
    if (st.page > totalPages) st.page = totalPages;
    if (st.page < 1) st.page = 1;
    const start = (st.page - 1) * st.size;
    const end = Math.min(start + st.size, total);
    return { start, end, pageItems: items.slice(start, end) };
}

/**
 * Render pager UI: select 10/20/50 + ‹ › + "Tất cả".
 * onChange được gọi sau khi đổi page/size (caller re-render bảng).
 */
function renderPager(containerId, sectionKey, total, onChange) {
    const wrap = document.getElementById(containerId);
    if (!wrap) return;
    const st = pageState[sectionKey] || (pageState[sectionKey] = { page: 1, size: PAGE_DEFAULT_SIZE });
    if (total <= 0) {
        wrap.innerHTML = "";
        return;
    }
    const showAll = !st.size || st.size <= 0;
    const size = showAll ? total : st.size;
    const totalPages = showAll ? 1 : Math.max(1, Math.ceil(total / size));
    if (!showAll && st.page > totalPages) st.page = totalPages;

    const sizeOpts = [10, 20, 50].map(n =>
        `<option value="${n}" ${!showAll && st.size === n ? "selected" : ""}>${n}</option>`
    ).join("");

    wrap.innerHTML = `<div class="pager-bar">
        <label class="pager-size">Hiển thị
            <select onchange="pagerSetSize('${sectionKey}', this.value)">
                ${sizeOpts}
                <option value="0" ${showAll ? "selected" : ""}>Tất cả</option>
            </select>
        </label>
        <div class="pager-nav">
            <button type="button" class="pager-btn" ${st.page <= 1 || showAll ? "disabled" : ""}
                    onclick="pagerGo('${sectionKey}', ${st.page - 1})">‹</button>
            <span class="pager-info">Trang ${showAll ? 1 : st.page}/${totalPages}</span>
            <button type="button" class="pager-btn" ${st.page >= totalPages || showAll ? "disabled" : ""}
                    onclick="pagerGo('${sectionKey}', ${st.page + 1})">›</button>
        </div>
        <span class="pager-total">${total} dòng</span>
    </div>`;

    // Lưu callback để pagerGo/pagerSetSize gọi lại
    pageState[sectionKey]._onChange = onChange;
}

function pagerGo(sectionKey, page) {
    const st = pageState[sectionKey];
    if (!st) return;
    st.page = Math.max(1, page);
    if (typeof st._onChange === "function") st._onChange();
}

function pagerSetSize(sectionKey, sizeVal) {
    const st = pageState[sectionKey];
    if (!st) return;
    st.size = parseInt(sizeVal, 10) || 0;
    st.page = 1;
    if (typeof st._onChange === "function") st._onChange();
}

function renderUnassignedSection() {
    const items = metricsData.unassigned_tasks || [];
    const total = metricsData.unassigned_tasks_total || items.length;
    const tbody = document.getElementById("unassignedTable");
    if (!tbody) return;
    if (items.length === 0) {
        tbody.innerHTML = `<tr><td colspan="9" class="px-4 py-6 text-center text-gray-500">Không có task nào chưa được giao PIC</td></tr>`;
        renderPager("unassignedShowMoreWrap", "unassigned", 0, () => renderUnassignedSection());
        document.getElementById("unassignedCount").textContent = "0 task chưa có PIC";
        return;
    }
    const { start, end, pageItems } = _pageSlice("unassigned", items);
    tbody.innerHTML = pageItems.map((i, idx) => {
        const rowCls = i.is_overdue ? "overdue-critical"
                    : (String(i.priority).includes("Must") ? "overdue-warning" : "");
        return `<tr class="${rowCls} border-b cursor-pointer hover:bg-orange-50"
                    onclick="openDrillDown('unassigned', {})"
                    title="Click để xem chi tiết">
            <td class="px-2 py-2 text-center">${start + idx + 1}</td>
            <td class="px-2 py-2 font-mono text-xs">${escapeHtml(i.ma_cn)}</td>
            <td class="px-2 py-2">${escapeHtml(i.ten_cn)}</td>
            <td class="px-2 py-2 text-center">${escapeHtml(i.module)}</td>
            <td class="px-2 py-2 text-center text-xs">${escapeHtml(i.phase)}</td>
            <td class="px-2 py-2 text-center">${statusBadge(i.status)}</td>
            <td class="px-2 py-2 text-center text-xs">${escapeHtml(i.priority)}</td>
            <td class="px-2 py-2 text-center text-xs">${i.end_date || "-"}</td>
            <td class="px-2 py-2 text-center ${i.is_overdue ? 'text-red-600 font-bold' : 'text-gray-500'}">${i.days_overdue || 0}</td>
        </tr>`;
    }).join("");

    renderPager("unassignedShowMoreWrap", "unassigned", items.length, () => renderUnassignedSection());
    document.getElementById("unassignedCount").textContent =
        `Đang xem ${start + 1}–${end}/${total} task chưa có PIC`;
}

// ========================================================================
// V2: DURATION
// ========================================================================
function renderDurationSection() {
    const d = metricsData.duration_analysis || {};
    const summary = d.summary || {};
    document.getElementById("durAvg").textContent = summary.avg_duration || 0;
    document.getElementById("durOver3").textContent = summary.count_over_3 || 0;
    document.getElementById("durOver7").textContent = summary.count_over_7 || 0;
    document.getElementById("durThresholdView").textContent = (d.threshold_days || 3) + " ngày";

    // Box plot: floating bar min-max, marker median
    const distribution = d.distribution || {};
    const phases = Object.keys(distribution);
    const boxData = phases.map(p => [distribution[p].min, distribution[p].max]);
    const medianData = phases.map(p => distribution[p].median);
    const avgData = phases.map(p => distribution[p].avg);

    const ctxBox = getCanvas("chartDurationBox");
    createChart(ctxBox, "bar", {
        labels: phases,
        datasets: [
            {
                label: "Range (min–max)",
                data: boxData,
                backgroundColor: "rgba(59,130,246,0.25)",
                borderColor: "#3b82f6",
                borderWidth: 1,
            },
            {
                label: "Median",
                type: "line",
                data: medianData,
                borderColor: "#ef4444",
                backgroundColor: "#ef4444",
                pointRadius: 5,
                showLine: false,
            },
            {
                label: "Avg",
                type: "line",
                data: avgData,
                borderColor: "#22c55e",
                backgroundColor: "#22c55e",
                pointRadius: 4,
                pointStyle: "rectRot",
                showLine: false,
            },
        ],
    }, {
        indexAxis: "y",
        responsive: true,
        plugins: {
            legend: { position: "top" },
            tooltip: {
                callbacks: {
                    label: (ctx) => {
                        const p = phases[ctx.dataIndex];
                        const s = distribution[p];
                        return `${p}: min=${s.min}, Q1=${s.q1}, med=${s.median}, Q3=${s.q3}, max=${s.max}, avg=${s.avg} (n=${s.count})`;
                    },
                },
            },
        },
        scales: {
            x: { beginAtZero: true, title: { display: true, text: "Ngày" } },
        },
    });

    // Scatter: Duration vs Estimate MH
    const scatterPoints = d.scatter || [];
    const closedPts = scatterPoints.filter(p => p.status === "Closed");
    const activePts = scatterPoints.filter(p => p.type === "elapsed");
    const otherPts = scatterPoints.filter(p => p.status !== "Closed" && p.type !== "elapsed");

    const ctxScatter = getCanvas("chartDurationScatter");
    createChart(ctxScatter, "scatter", {
        datasets: [
            {
                label: "Đã Closed",
                data: closedPts.map(p => ({ x: p.estimate_mh, y: p.duration, ma_cn: p.ma_cn, phase: p.phase })),
                backgroundColor: "#22c55e",
                pointRadius: 4,
            },
            {
                label: "Đang chạy (elapsed)",
                data: activePts.map(p => ({ x: p.estimate_mh, y: p.duration, ma_cn: p.ma_cn, phase: p.phase })),
                backgroundColor: "#ef4444",
                pointRadius: 5,
            },
            {
                label: "Khác",
                data: otherPts.map(p => ({ x: p.estimate_mh, y: p.duration, ma_cn: p.ma_cn, phase: p.phase })),
                backgroundColor: "#94a3b8",
                pointRadius: 3,
            },
        ],
    }, {
        responsive: true,
        plugins: {
            legend: { position: "top" },
            tooltip: {
                callbacks: {
                    label: (ctx) => {
                        const r = ctx.raw;
                        return `${r.ma_cn || "?"} — ${r.phase}: ${r.x}h → ${r.y}d`;
                    },
                },
            },
        },
        scales: {
            x: { title: { display: true, text: "Estimate MH" }, beginAtZero: true },
            y: { title: { display: true, text: "Duration (ngày)" }, beginAtZero: true },
        },
    });

    // Bảng chi tiết (tách hàm để expand chỉ re-render bảng, không re-render chart)
    renderDurationTable();
}

function renderDurationTable() {
    const d = metricsData?.duration_analysis || {};
    const items = d.items || [];
    const tbody = document.getElementById("durationTable");
    if (!tbody) return;
    const { start, end, pageItems } = _pageSlice("duration", items);
    tbody.innerHTML = pageItems.map((i, idx) => {
        const cls = i.duration_days > 14 ? "overdue-critical"
                  : i.duration_days > 7 ? "overdue-warning" : "overdue-mild";
        return `<tr class="${cls} border-b cursor-pointer hover:bg-blue-50"
                    onclick="openDrillDown('duration', {})"
                    title="Click để xem chi tiết duration">
            <td class="px-2 py-2 text-center">${start + idx + 1}</td>
            <td class="px-2 py-2 font-mono text-xs">${escapeHtml(i.ma_cn)}</td>
            <td class="px-2 py-2">${escapeHtml(i.ten_cn)}</td>
            <td class="px-2 py-2 text-center">${escapeHtml(i.module)}</td>
            <td class="px-2 py-2 text-center text-xs">${escapeHtml(i.phase)}</td>
            <td class="px-2 py-2 text-center text-xs">${i.start_date || "-"}</td>
            <td class="px-2 py-2 text-center text-xs">${i.end_date || "-"}</td>
            <td class="px-2 py-2 text-center font-bold">${i.duration_days}</td>
            <td class="px-2 py-2 text-center text-xs">${i.duration_type === "elapsed" ? "🔴 Đang" : "📅 KH"}</td>
            <td class="px-2 py-2 text-center">${statusBadge(i.status)}</td>
            <td class="px-2 py-2 text-xs">${escapeHtml((i.pic || []).join(", "))}</td>
        </tr>`;
    }).join("");

    renderPager("durationShowMoreWrap", "duration", items.length, () => renderDurationTable());
    const cnt = document.getElementById("durationCount");
    if (cnt) {
        cnt.textContent = items.length === 0
            ? "Không có task theo duration"
            : `Đang xem ${start + 1}–${end}/${items.length} task theo duration`;
    }
}

// ========================================================================
// V2: STALLED
// ========================================================================
function renderStalledSection() {
    const data = metricsData.stalled_tasks || {};
    const funnel = data.funnel || [];
    const transitions = data.transitions || [];

    // Funnel — count NGOÀI bar để không overlap với label
    const totalTop = funnel.length ? Math.max(...funnel.map(f => f.closed), 1) : 1;
    const funnelEl = document.getElementById("funnelChart");
    funnelEl.innerHTML = funnel.map(f => {
        const width = (f.closed / totalTop) * 100;
        return `<div class="funnel-row">
            <div class="funnel-label">${escapeHtml(f.phase)}</div>
            <div class="funnel-track"><div class="funnel-bar" style="width:${Math.max(width, 4)}%"></div></div>
            <div class="funnel-count">${f.closed} Closed</div>
        </div>`;
    }).join("");

    // Transitions
    const trWrap = document.getElementById("transitionList");
    if (transitions.length === 0) {
        trWrap.innerHTML = `<div class="text-gray-500 text-xs italic">Không có task bị đình trệ</div>`;
    } else {
        trWrap.innerHTML = transitions
            .sort((a, b) => b.count - a.count)
            .map(t => `<div class="flex items-center justify-between py-1 border-b border-gray-100">
                <span class="text-xs">${escapeHtml(t.from)} → <span class="text-red-500">${escapeHtml(t.to)}</span></span>
                <span class="font-bold text-orange-600">${t.count}</span>
            </div>`).join("");
    }

    renderStalledTable();
}

function renderStalledTable() {
    const data = metricsData?.stalled_tasks || {};
    const items = data.items || [];
    const tbody = document.getElementById("stalledTable");
    if (!tbody) return;
    const { start, end, pageItems } = _pageSlice("stalled", items);
    tbody.innerHTML = pageItems.map((i, idx) => {
        const cls = i.wait_days > 14 ? "overdue-critical"
                  : i.wait_days > 7 ? "overdue-warning" : "";
        return `<tr class="${cls} border-b cursor-pointer hover:bg-orange-50"
                    onclick="openDrillDown('stalled', {})"
                    title="Click để xem chi tiết đình trệ">
            <td class="px-2 py-2 text-center">${start + idx + 1}</td>
            <td class="px-2 py-2 font-mono text-xs">${escapeHtml(i.ma_cn)}</td>
            <td class="px-2 py-2">${escapeHtml(i.ten_cn)}</td>
            <td class="px-2 py-2 text-center">${escapeHtml(i.module)}</td>
            <td class="px-2 py-2 text-center text-xs">${escapeHtml(i.completed_phase)}</td>
            <td class="px-2 py-2 text-center text-xs text-red-500">${escapeHtml(i.waiting_phase)}</td>
            <td class="px-2 py-2 text-center text-xs">${i.completed_date || "-"}</td>
            <td class="px-2 py-2 text-center font-bold">${i.wait_days}</td>
            <td class="px-2 py-2 text-center text-xs">${escapeHtml(i.priority)}</td>
        </tr>`;
    }).join("");

    renderPager("stalledShowMoreWrap", "stalled", items.length, () => renderStalledTable());
    const cnt = document.getElementById("stalledCount");
    if (cnt) {
        cnt.textContent = items.length === 0
            ? "Không có task bị đình trệ"
            : `Đang xem ${start + 1}–${end}/${items.length} task bị đình trệ`;
    }
}

// ========================================================================
// V2: RISK SCORE
// ========================================================================
function renderRiskSection() {
    const all = metricsData.risk_scores || [];
    const total = metricsData.risk_scores_total || all.length;
    const tbody = document.getElementById("riskTable");
    const { start, end, pageItems } = _pageSlice("risk", all);
    tbody.innerHTML = pageItems.map((r, idx) => {
        const color = r.risk_score >= 80 ? "#ef4444"
                    : r.risk_score >= 50 ? "#f97316"
                    : r.risk_score >= 30 ? "#eab308" : "#22c55e";
        return `<tr class="border-b hover:bg-red-50 cursor-pointer"
                    onclick="openDrillDown('risk', {ma_cn: '${escapeAttr(r.ma_cn)}'})"
                    title="Click để xem chi tiết">
            <td class="px-2 py-2 text-center">${start + idx + 1}</td>
            <td class="px-2 py-2 font-mono text-xs">${escapeHtml(r.ma_cn)}</td>
            <td class="px-2 py-2">${escapeHtml(r.ten_cn)}</td>
            <td class="px-2 py-2 text-center">${escapeHtml(r.module)}</td>
            <td class="px-2 py-2 text-center text-xs">${escapeHtml(r.priority)}</td>
            <td class="px-2 py-2 text-center">
                <div class="flex items-center gap-2">
                    <div class="risk-bar-wrap"><div class="risk-bar-fill" style="width:${r.risk_score}%;background:${color}"></div></div>
                    <span class="font-bold" style="color:${color}">${r.risk_score}</span>
                </div>
            </td>
            <td class="px-2 py-2 text-xs">
                ${(r.risk_factors || []).map(f => `<span class="inline-block bg-red-100 text-red-700 rounded px-1.5 py-0.5 mr-1 mb-0.5">${escapeHtml(f)}</span>`).join("")}
            </td>
        </tr>`;
    }).join("");
    renderPager("riskShowMoreWrap", "risk", all.length, () => renderRiskSection());
    const cnt = document.getElementById("riskCount");
    if (cnt) {
        cnt.textContent = all.length === 0
            ? "Không có function rủi ro"
            : `Đang xem ${start + 1}–${end}/${total} function rủi ro`;
    }
}

// ========================================================================
// V2: EFFORT — đơn vị MH/MD/MM + filter status PIC
// ========================================================================
let _effortUnit = "MH";  // "MH" | "MD" | "MM"
let _effortPicFilter = "all";  // "all" | "open" | "closed"
const EFFORT_UNIT_FACTOR = { MH: 1, MD: 1 / 8, MM: 1 / 176 };

function setEffortUnit(unit) {
    if (!["MH", "MD", "MM"].includes(unit)) return;
    _effortUnit = unit;
    document.querySelectorAll(".effort-unit-btn").forEach(b => {
        b.classList.toggle("bg-blue-600", b.dataset.unit === unit);
        b.classList.toggle("text-white", b.dataset.unit === unit);
    });
    renderEffortSection();
}

function setEffortPicFilter(val) {
    _effortPicFilter = val || "all";
    renderEffortSection();
}

function _toEffortUnit(mh) {
    const f = EFFORT_UNIT_FACTOR[_effortUnit] || 1;
    return Math.round((Number(mh) || 0) * f * 10) / 10;
}

function renderEffortSection() {
    const e = metricsData.effort_analysis || {};
    const unit = _effortUnit;
    document.getElementById("effortTotal").textContent = fmtNum(_toEffortUnit(e.total_estimated));
    document.getElementById("effortClosed").textContent = fmtNum(_toEffortUnit(e.total_closed_mh));
    document.getElementById("effortRemaining").textContent = fmtNum(_toEffortUnit(e.remaining_mh));
    document.getElementById("effortPct").textContent = (e.closed_pct || 0) + "%";
    // Cập nhật label đơn vị trên KPI
    document.querySelectorAll("[data-effort-unit-label]").forEach(el => {
        el.textContent = unit;
    });

    // Heatmap Module × Phase
    const modules = e.modules || [];
    const phases = e.phases || [];
    const heatmap = e.heatmap || {};

    let maxMH = 0;
    modules.forEach(m => {
        phases.forEach(p => {
            const v = heatmap[m]?.[p] || 0;
            if (v > maxMH) maxMH = v;
        });
    });

    const thead = document.getElementById("effortHeatmapHead");
    thead.innerHTML = `<tr class="bg-slate-700 text-white text-xs">
        <th class="px-2 py-1 text-left">Module</th>
        ${phases.map(p => `<th class="px-2 py-1 text-center">${escapeHtml(p)}</th>`).join("")}
    </tr>`;

    const tbody = document.getElementById("effortHeatmapBody");
    tbody.innerHTML = modules.map(m => {
        const cells = phases.map(p => {
            const raw = heatmap[m]?.[p] || 0;
            const v = _toEffortUnit(raw);
            const intensity = maxMH > 0 ? Math.round((raw / maxMH) * 100) : 0;
            const bg = raw === 0 ? "var(--heatmap-none)" : `rgba(59, 130, 246, ${0.15 + (intensity / 100) * 0.7})`;
            return `<td class="px-2 py-1 text-center cursor-pointer hover:ring-2 hover:ring-blue-400"
                        style="background:${bg}"
                        onclick="openDrillDown('effort_heatmap', {module:'${escapeAttr(m)}', phase:'${escapeAttr(p)}'})"
                        title="${escapeAttr(m)} × ${escapeAttr(p)}: ${v} ${unit} · Click xem chi tiết">
                <span class="text-xs font-medium">${raw > 0 ? v : "-"}</span>
            </td>`;
        }).join("");
        return `<tr class="border-b"><td class="px-2 py-1 font-semibold">${escapeHtml(m)}</td>${cells}</tr>`;
    }).join("");

    // PIC: All → chart; Chưa done → bảng open_tasks; Closed → chart chỉ closed
    const openWrap = document.getElementById("effortOpenTasksWrap");
    const chartBox = document.getElementById("chartPICEffort")?.closest(".chart-box");
    const chartParent = document.getElementById("effortPicChartWrap");

    if (_effortPicFilter === "open") {
        // Hiện bảng open tasks, ẩn chart
        if (chartParent) chartParent.classList.add("hidden");
        if (openWrap) {
            openWrap.classList.remove("hidden");
            const openTasks = e.open_tasks_by_pic || [];
            openWrap.innerHTML = `<div class="overflow-x-auto max-h-72 overflow-y-auto">
                <table class="w-full text-xs">
                    <thead class="bg-gray-100 sticky top-0"><tr>
                        <th class="px-2 py-1 text-left">Mã CN</th>
                        <th class="px-2 py-1 text-left">Tên</th>
                        <th class="px-2 py-1">Module</th>
                        <th class="px-2 py-1">Phase</th>
                        <th class="px-2 py-1">PIC</th>
                        <th class="px-2 py-1">Status</th>
                        <th class="px-2 py-1">End</th>
                        <th class="px-2 py-1">${unit}</th>
                    </tr></thead>
                    <tbody>${openTasks.length === 0
                        ? `<tr><td colspan="8" class="px-2 py-4 text-center text-gray-500">Không có task mở</td></tr>`
                        : openTasks.map(t => `<tr class="border-b hover:bg-blue-50 cursor-pointer"
                            onclick="openDrillDown('effort_pic', {pic:'${escapeAttr((t.pic||[])[0]||'')}', status:'remaining'})">
                            <td class="px-2 py-1 font-mono">${escapeHtml(t.ma_cn)}</td>
                            <td class="px-2 py-1">${escapeHtml(t.ten_cn)}</td>
                            <td class="px-2 py-1 text-center">${escapeHtml(t.module)}</td>
                            <td class="px-2 py-1 text-center">${escapeHtml(t.phase)}</td>
                            <td class="px-2 py-1">${escapeHtml((t.pic||[]).join(", "))}</td>
                            <td class="px-2 py-1 text-center">${statusBadge(t.status)}</td>
                            <td class="px-2 py-1 text-center">${t.end_date || "-"}</td>
                            <td class="px-2 py-1 text-center font-semibold">${_toEffortUnit(t.estimate_mh)}</td>
                        </tr>`).join("")}
                    </tbody>
                </table>
            </div>`;
        }
        return;
    }

    if (openWrap) { openWrap.classList.add("hidden"); openWrap.innerHTML = ""; }
    if (chartParent) chartParent.classList.remove("hidden");

    const picList = (e.by_pic || []).slice(0, 15);
    const ctx = getCanvas("chartPICEffort");
    if (!ctx) return;
    const closedData = picList.map(p => _toEffortUnit(p.closed_mh));
    const remainData = picList.map(p => _toEffortUnit(p.remaining_mh));
    const datasets = _effortPicFilter === "closed"
        ? [{ label: `Đã Closed ${unit}`, data: closedData, backgroundColor: "#22c55e" }]
        : [
            { label: `Đã Closed ${unit}`, data: closedData, backgroundColor: "#22c55e" },
            { label: `Còn lại ${unit}`, data: remainData, backgroundColor: "#f97316" },
        ];
    createChart(ctx, "bar", {
        labels: picList.map(p => p.pic),
        datasets: datasets.map(ds => ({
            ...ds,
            // Bug 6-pattern: bỏ borderRadius (default global = 4) để segment
            // nhỏ (VD PIC có ít MH closed) không bị "nuốt" mất trên horizontal
            // stacked bar.
            borderRadius: 0,
            borderSkipped: false,
            stack: "effort_pic",
        })),
    }, {
        indexAxis: "y",
        responsive: true,
        plugins: {
            legend: {
                position: "top",
                labels: { usePointStyle: true, boxWidth: 10, padding: 12 },
            },
            tooltip: { callbacks: { footer: () => "💡 Click để xem chi tiết" } },
            // Bug 11: Hiện số MM (hoặc MD) trực tiếp trên từng segment,
            // user không cần hover mới thấy. Bỏ qua segment có value < 0.1
            // để tránh overlap khi PIC có phần rất nhỏ.
            datalabels: {
                display: (ctx) => {
                    const val = Number(ctx.dataset.data[ctx.dataIndex]) || 0;
                    return val >= 0.1;
                },
                color: "#fff",
                font: { size: 10, weight: "bold" },
                textStrokeColor: "rgba(0,0,0,0.55)",
                textStrokeWidth: 2,
                formatter: (val) => (val >= 0.1 ? `${Math.round(val * 10) / 10}` : ""),
                anchor: "center",
                align: "center",
            },
        },
        scales: {
            x: { stacked: true, beginAtZero: true, title: { display: true, text: unit } },
            y: { stacked: true, ticks: { font: { size: 10 } } },
        },
        onHover: CLICKABLE_CHART_OPTS.onHover,
        onClick: _chartClickHandler("effort_pic", (el, chart) => {
            const pic = chart.data.labels[el.index];
            const label = chart.data.datasets[el.datasetIndex].label || "";
            const status = label.includes("Closed") ? "closed" : "remaining";
            return { pic, status };
        }),
    });
}

// ========================================================================
// V2: PROCESS TREEMAP (custom flexbox layout - không cần chart plugin)
// ========================================================================
function renderProcessTreemap() {
    const items = metricsData.process_analysis || [];
    const el = document.getElementById("processTreemap");
    if (items.length === 0) {
        el.innerHTML = `<div class="text-gray-500 text-sm italic p-4">Không có dữ liệu Quy trình</div>`;
        document.getElementById("section-process").classList.add("hidden");
        return;
    }
    document.getElementById("section-process").classList.remove("hidden");

    // Single-group card CHỈ cho comparison charts (Process treemap, FIT/GAP)
    if (items.length === 1) {
        const only = items[0];
        _renderSingleGroupCard(el, {
            groupType: "quy trình",
            groupName: only.process,
            total: only.total,
            pctClosed: only.pct_closed,
            extra: (only.modules || []).join(", ")
                + (only.overdue ? ` · ⚠️ ${only.overdue} trễ` : ""),
        });
        return;
    }

    const totalFuncs = items.reduce((s, i) => s + i.total, 0);
    el.innerHTML = `
        <div class="flex flex-wrap gap-1" style="min-height:300px;">
            ${items.map(i => {
                const width = Math.max(10, (i.total / totalFuncs) * 100);
                const color = i.pct_closed >= 80 ? "#16a34a"
                            : i.pct_closed >= 50 ? "#eab308"
                            : i.pct_closed >= 20 ? "#f97316" : "#ef4444";
                return `<div class="treemap-cell cursor-pointer" style="flex-basis:calc(${width}% - 4px);min-width:150px;min-height:80px;background:${color};"
                    onclick="openDrillDown('process', {process: '${escapeAttr(i.process)}'})"
                    title="Click để xem ${escapeAttr(i.process)}">
                    <div class="tm-title" title="${escapeHtml(i.process)}">${escapeHtml(shortenProcess(i.process))}</div>
                    <div class="tm-info">${i.total} func · ${i.pct_closed}% ✓${i.overdue ? " · ⚠️" + i.overdue : ""}</div>
                    <div class="tm-info text-xs">${(i.modules || []).join(", ")}</div>
                </div>`;
            }).join("")}
        </div>`;
}

function shortenProcess(name) {
    if (!name) return "";
    if (name.length > 45) return name.substring(0, 42) + "...";
    return name;
}

// ========================================================================
// V2: GANTT TIMELINE (Bug 1 REWORK + groupBy module|process)
// ========================================================================
// State cho Gantt: user preference giữ giữa các re-render (đổi filter, resize…).
// Không lưu localStorage — session-only, tránh state stuck khi user muốn reset.
// Legacy — layout mode "vertical" removed vì render sai. Chỉ giữ horizontal.
const _ganttState = {
    zoom: "month",              // "week" | "month" | "quarter"
    layout: "horizontal",       // "horizontal" | "vertical"
    // 3 mode (issue #2):
    //   "module"   → 1 row / module (aggregate min-start → max-end)
    //   "process"  → 1 row / quy trình (aggregate)
    //   "function" → 1 row / function, phase là segment (mode cũ)
    groupBy: "function",
    foldedModules: new Set(),   // nhóm đang fold (chỉ áp dụng cho mode "function")
    initialized: false,         // để biết lần đầu render thì set default fold
};

// Palette segment theo status — ưu tiên overdue (đỏ) trước
const GANTT_STATUS_COLORS = {
    "Closed":      "#22c55e",
    "In-progress": "#3b82f6",
    "Assigned":    "#f59e0b",
    "Open":        "#94a3b8",
    "Pending":     "#94a3b8",
    "Resolved":    "#8b5cf6",
    "Cancelled":   "#cbd5e1",
};
const GANTT_OVERDUE_COLOR = "#ef4444";

function _ganttSegColor(seg) {
    if (seg.overdue) return GANTT_OVERDUE_COLOR;
    return GANTT_STATUS_COLORS[seg.status] || "#94a3b8";
}

/** Public toolbar handlers (gọi từ HTML onclick). */
function setGanttZoom(zoom) {
    if (!["week", "month", "quarter"].includes(zoom)) return;
    _ganttState.zoom = zoom;
    document.querySelectorAll(".gantt-zoom-btn").forEach(b => {
        b.classList.toggle("bg-blue-600", b.dataset.zoom === zoom);
        b.classList.toggle("text-white", b.dataset.zoom === zoom);
    });
    renderGanttTimeline();
}
// Compact label toggle: rút gọn cột label để timeline rộng hơn.
// Thay thế "Layout dọc" cũ (render sai) — user request: label không nên chiếm nhiều chỗ.
function toggleGanttCompact() {
    _ganttState.compact = !_ganttState.compact;
    const btn = document.getElementById("ganttCompactBtn");
    if (btn) {
        btn.classList.toggle("bg-blue-600", _ganttState.compact);
        btn.classList.toggle("text-white", _ganttState.compact);
    }
    renderGanttTimeline();
}
// Legacy stub — nếu code cũ còn call setGanttLayout, fallback về horizontal (no-op).
function setGanttLayout() { /* deprecated */ }
function setGanttGroupBy(groupBy) {
    if (!["module", "process", "function"].includes(groupBy)) return;
    _ganttState.groupBy = groupBy;
    _ganttState.foldedModules.clear();
    _ganttState.initialized = false;
    _ganttState.userInteracted = false;
    document.querySelectorAll(".gantt-groupby-btn").forEach(b => {
        b.classList.toggle("bg-blue-600", b.dataset.groupby === groupBy);
        b.classList.toggle("text-white", b.dataset.groupby === groupBy);
    });
    renderGanttTimeline();
}
function toggleAllGanttModules() {
    const groups = _ganttGroupKeys();
    const anyFolded = groups.some(m => _ganttState.foldedModules.has(m));
    _ganttState.foldedModules.clear();
    if (!anyFolded) {
        groups.forEach(m => _ganttState.foldedModules.add(m));
    }
    _ganttState.userInteracted = true;
    _updateGanttToggleAllBtn();
    renderGanttTimeline();
}
function toggleGanttModule(module) {
    if (_ganttState.foldedModules.has(module)) {
        _ganttState.foldedModules.delete(module);
    } else {
        _ganttState.foldedModules.add(module);
    }
    _ganttState.userInteracted = true;
    _updateGanttToggleAllBtn();
    renderGanttTimeline();
}
function _updateGanttToggleAllBtn() {
    const btn = document.getElementById("ganttToggleAllBtn");
    if (!btn) return;
    const groups = _ganttGroupKeys();
    const anyFolded = groups.some(m => _ganttState.foldedModules.has(m));
    btn.textContent = anyFolded ? "📂 Mở tất cả" : "📁 Đóng tất cả";
}

/**
 * Lấy map group → list function theo mode hiện tại.
 * - "process": group theo quy_trinh
 * - "module"  : group theo module (aggregate render)
 * - "function": group theo module (giữ nguyên hành vi fold/expand cũ)
 */
function _ganttGroupedFunctions() {
    const t = metricsData?.timeline_data || {};
    if (_ganttState.groupBy === "process") {
        // Prefer BE functions_by_process; fallback flatten từ functions_by_module
        if (t.functions_by_process) return t.functions_by_process;
        const byProc = {};
        Object.entries(t.functions_by_module || {}).forEach(([mod, list]) => {
            (list || []).forEach(f => {
                const key = f.quy_trinh || "N/A";
                if (!byProc[key]) byProc[key] = [];
                byProc[key].push({ ...f, module: f.module || mod });
            });
        });
        return byProc;
    }
    // "module" hoặc "function" → group theo module
    return t.functions_by_module || {};
}

function _ganttGroupKeys() {
    const t = metricsData?.timeline_data || {};
    if (_ganttState.groupBy === "process") {
        if (t.processes) return t.processes;
        return Object.keys(_ganttGroupedFunctions()).sort();
    }
    return t.modules || [];
}

/**
 * Tính aggregate cho 1 group (module hoặc process) trong mode "module"/"process":
 * - minStart / maxEnd trên mọi phase của mọi function trong group
 * - closedPct = weighted_all formula (giống module_overview):
 *     closedPhase / (funcs.length × total_all_phases)
 *   → phase blank / chưa touch ĐƯỢC ĐẾM VÀO mẫu số (như "chưa làm"), không
 *   bị bỏ qua. Trước đây denominator = totalPhaseWithStatus (chỉ phase có
 *   status set) → khi filter còn ít row + hầu như phase blank + 1 vài phase
 *   Closed → % bị đẩy về 100% giả tạo.
 * - overdueCount = số function có ít nhất 1 phase overdue
 */
function _ganttAggregate(funcs) {
    let minStart = null, maxEnd = null;
    let closedPhase = 0;
    let overdueCount = 0;
    let totalPhaseSlots = 0;
    (funcs || []).forEach(f => {
        if (f.has_overdue) overdueCount += 1;
        (f.phases || []).forEach(p => {
            totalPhaseSlots += 1;
            if (p.start) {
                const d = new Date(p.start);
                if (!minStart || d < minStart) minStart = d;
                if (!maxEnd || d > maxEnd) maxEnd = d;
            }
            if (p.end) {
                const d = new Date(p.end);
                if (!minStart || d < minStart) minStart = d;
                if (!maxEnd || d > maxEnd) maxEnd = d;
            }
            if (p.status === "Closed") closedPhase += 1;
        });
    });
    // Weighted denominator: mỗi function ứng với TOÀN BỘ phase định nghĩa
    // trong project (giống module_overview / summary.overall_progress_pct).
    // `functions_by_module` chỉ giữ phase user đã touch → dùng total_all_phases
    // từ metricsData.timeline_data.phases (list tất cả phase định nghĩa) làm
    // divisor chuẩn.
    const totalAllPhases = (metricsData?.timeline_data?.phases || []).length ||
                           (metricsData?.structure?.all_phases || []).length || 0;
    const nFuncs = (funcs || []).length;
    const weightedDenom = nFuncs * totalAllPhases;
    const closedPct = weightedDenom > 0
        ? Math.round(closedPhase / weightedDenom * 100)
        : 0;
    return {
        minStart, maxEnd,
        totalFuncs: nFuncs,
        totalPhaseSlots,
        closedPct,
        overdueCount,
    };
}

/** Color theo % Closed weighted (giống module_overview). Task 19: dùng Palette. */
function _ganttAggregateColor(pct, hasOverdue) {
    if (hasOverdue) return (window.Palette?.STATUS?.Overdue) || "#dc2626";
    if (window.Palette?.progressColor) return window.Palette.progressColor(pct);
    // Fallback nếu palette.js chưa load
    return pct >= 70 ? "#16a34a" : pct >= 30 ? "#f59e0b" : "#dc2626";
}

/** Render chính. */
function renderGanttTimeline() {
    const t = metricsData?.timeline_data || {};
    const container = document.getElementById("ganttContainer");
    if (!container) return;

    const funcsByGroup = _ganttGroupedFunctions();
    const groups = _ganttGroupKeys().filter(g => (funcsByGroup[g] || []).length > 0);
    const today = t.today ? new Date(t.today) : new Date();
    const totalFuncs = t.total_functions || Object.values(funcsByGroup).reduce((s, l) => s + (l || []).length, 0);
    const hasActiveFilter = !!(
        globalFilters.modules.length ||
        globalFilters.processes.length ||
        globalFilters.pics.length
    );
    // Label header: theo mode
    const groupLabel = _ganttState.groupBy === "process" ? "Quy trình"
                      : _ganttState.groupBy === "module" ? "Module"
                      : "Module / Function";
    // Aggregate mode = "module" hoặc "process" — mỗi group 1 row aggregate, không expand
    const isAggregate = _ganttState.groupBy === "module" || _ganttState.groupBy === "process";

    // Empty state
    if (groups.length === 0 || totalFuncs === 0) {
        container.innerHTML = `<div class="gantt-empty">
            Không có function/date nào để vẽ timeline.<br>
            <span class="text-xs">Function cần có Start hoặc End date ở ít nhất 1 phase.</span>
        </div>`;
        document.getElementById("ganttSizeBanner").classList.add("hidden");
        return;
    }

    // Fold state chỉ áp dụng cho mode "function" (aggregate không expand)
    if (isAggregate) {
        _ganttState.foldedModules.clear();
    } else {
        if (!_ganttState.initialized) {
            _ganttState.initialized = true;
            if (groups.length > 5) {
                groups.forEach(m => _ganttState.foldedModules.add(m));
            }
        } else {
            for (const m of [..._ganttState.foldedModules]) {
                if (!groups.includes(m)) _ganttState.foldedModules.delete(m);
            }
        }
    }

    const banner = document.getElementById("ganttSizeBanner");
    const bannerMsg = document.getElementById("ganttSizeBannerMsg");
    if (!isAggregate && totalFuncs > 100 && !hasActiveFilter) {
        banner.classList.remove("hidden");
        bannerMsg.textContent = `${totalFuncs} function — mặc định đã fold tất cả module để dashboard nhẹ. Click header để mở, hoặc `;
        if (!_ganttState.userInteracted) {
            groups.forEach(m => _ganttState.foldedModules.add(m));
        }
    } else {
        banner.classList.add("hidden");
    }
    // Toggle All button chỉ có nghĩa ở mode "function"
    const toggleAllBtn = document.getElementById("ganttToggleAllBtn");
    if (toggleAllBtn) {
        toggleAllBtn.style.display = isAggregate ? "none" : "";
    }
    _updateGanttToggleAllBtn();

    // Collect min/max date
    const allDates = [];
    Object.values(funcsByGroup).forEach(list => {
        (list || []).forEach(f => {
            (f.phases || []).forEach(p => {
                if (p.start) allDates.push(new Date(p.start));
                if (p.end) allDates.push(new Date(p.end));
            });
        });
    });
    if (allDates.length === 0) {
        container.innerHTML = `<div class="gantt-empty">Không có date nào để vẽ timeline.</div>`;
        return;
    }

    let minDate = new Date(Math.min(...allDates));
    let maxDate = new Date(Math.max(...allDates));
    const rangeMs = maxDate - minDate;
    const padMs = Math.max(rangeMs * 0.02, 1000 * 60 * 60 * 24);
    minDate = new Date(minDate.getTime() - padMs);
    maxDate = new Date(maxDate.getTime() + padMs);

    const rangeDays = Math.max(1, (maxDate - minDate) / (1000 * 60 * 60 * 24));

    const zoom = _ganttState.zoom;
    const pxPerDay = zoom === "week" ? 12
                   : zoom === "month" ? 2.2
                   : /* quarter */     0.9;
    const tickW = zoom === "week" ? 12 * 7
               : zoom === "month" ? 2.2 * 30
               : /* quarter */     0.9 * 90;

    const trackW = Math.max(600, Math.round(rangeDays * pxPerDay));
    const labelW = 220;

    const dateToPx = (d) => ((new Date(d) - minDate) / (1000 * 60 * 60 * 24)) * pxPerDay;
    const ticks = _generateGanttTicks(minDate, maxDate, zoom, dateToPx);

    // Compact mode: giảm label width 220 → 110 để timeline rộng hơn
    const effectiveLabelW = _ganttState.compact ? 110 : labelW;
    container.className = "gantt-container-v2" + (_ganttState.compact ? " compact-label" : "");
    container.style.setProperty("--gantt-label-w", effectiveLabelW + "px");
    container.style.setProperty("--gantt-track-w", trackW + "px");
    container.style.setProperty("--gantt-tick-w", tickW + "px");

    const parts = [];

    parts.push(`<div class="gantt-ruler">
        <div class="gantt-ruler-label">${escapeHtml(groupLabel)}</div>
        <div class="gantt-ruler-track">
            ${ticks.map(tk => `<div class="gantt-tick" style="left:${tk.px}px">${escapeHtml(tk.label)}</div>`).join("")}
        </div>
    </div>`);

    const todayPx = dateToPx(today);
    let todayLineHtml = "";
    if (todayPx >= 0 && todayPx <= trackW) {
        todayLineHtml = `<div class="gantt-today-line-v2" style="left:${labelW + todayPx}px"></div>`;
    }

    groups.forEach(group => {
        const funcs = funcsByGroup[group] || [];
        if (funcs.length === 0) return;

        const displayName = _ganttState.groupBy === "process" ? shortenProcess(group) : group;

        // ====== MODE "module" / "process" ======
        // Mỗi group render 1 row duy nhất với 1 segment kéo dài min-start → max-end,
        // màu theo % Closed weighted của group. Không có expand/fold.
        if (isAggregate) {
            const agg = _ganttAggregate(funcs);
            if (!agg.minStart || !agg.maxEnd) {
                // Nhóm không có date nào → hiện label + msg
                parts.push(`<div class="gantt-func-row">
                    <div class="gantt-func-label"><b>${escapeHtml(displayName)}</b> · ${funcs.length} func</div>
                    <div class="gantt-func-track">
                        <div class="gantt-empty-track" style="left:0;padding-left:8px;color:#94a3b8;font-size:11px">
                            (Chưa có date)
                        </div>
                    </div>
                </div>`);
                return;
            }
            const leftPx = dateToPx(agg.minStart);
            const rightPx = dateToPx(agg.maxEnd);
            const widthPx = Math.max(6, rightPx - leftPx);
            const color = _ganttAggregateColor(agg.closedPct, agg.overdueCount > 0);
            const tip = [
                `${displayName}`,
                `Số function: ${agg.totalFuncs}`,
                `Số phase-record: ${agg.totalPhaseSlots}`,
                `% Closed (weighted): ${agg.closedPct}%`,
                `Overdue: ${agg.overdueCount} function`,
                `Thời gian: ${agg.minStart.toISOString().slice(0,10)} → ${agg.maxEnd.toISOString().slice(0,10)}`,
            ].join("\n");
            const innerLabel = widthPx > 80
                ? `${escapeHtml(displayName)} · ${agg.closedPct}%`
                : (widthPx > 40 ? `${agg.closedPct}%` : "");
            // Click aggregate row → drill-down module/process
            const drillChart = _ganttState.groupBy === "module" ? "module" : "process";
            const drillFilterKey = _ganttState.groupBy === "module" ? "module" : "process";
            const rowLabel = `<b>${escapeHtml(displayName)}</b>
                <span class="text-xs text-gray-500">${agg.totalFuncs} func · ${agg.closedPct}%${
                    agg.overdueCount > 0 ? ` · <span class="text-red-600">⚠️ ${agg.overdueCount}</span>` : ""
                }</span>`;
            parts.push(`<div class="gantt-func-row cursor-pointer"
                onclick="openDrillDown('${drillChart}', {${drillFilterKey}: '${escapeAttr(group)}'})"
                title="${escapeAttr(tip)}">
                <div class="gantt-func-label">${rowLabel}</div>
                <div class="gantt-func-track">
                    <div class="gantt-seg gantt-seg-aggregate"
                        style="left:${leftPx}px;width:${widthPx}px;background:${color}"
                        title="${escapeAttr(tip)}">${innerLabel}</div>
                </div>
            </div>`);
            return;
        }

        // ====== MODE "function" ======
        // Hành vi cũ: group header (fold/expand) + function rows với phase segment
        const folded = _ganttState.foldedModules.has(group);
        const overdueCount = funcs.filter(f => f.has_overdue).length;
        const totalPhases = funcs.reduce((s, f) => s + (f.phases || []).length, 0);

        parts.push(`<div class="gantt-module-header" data-folded="${folded}"
                        onclick="toggleGanttModule('${escapeAttr(group)}')" title="Click để ${folded ? "mở" : "đóng"} ${escapeHtml(group)}">
            <div class="gantt-module-header-label">
                <span class="gantt-fold-arrow">▶</span>
                ${escapeHtml(displayName)}
            </div>
            <div class="gantt-module-header-meta">
                <span>📦 ${funcs.length} function</span>
                <span>📊 ${totalPhases} phase</span>
                ${overdueCount > 0 ? `<span class="text-red-600 font-semibold">⚠️ ${overdueCount} overdue</span>` : ""}
            </div>
        </div>`);

        if (folded) return;

        funcs.forEach(f => {
            const modForDrill = f.module || group;
            const rowLabel = _ganttState.compact
                ? `<span class="code">${escapeHtml(f.ma_cn || "")}</span>`
                : `<span class="code">${escapeHtml(f.ma_cn || "")}</span> ${escapeHtml(f.ten_cn || "")}`;
            const segments = (f.phases || []).map(seg => {
                let segStart = seg.start ? new Date(seg.start) : null;
                let segEnd = seg.end ? new Date(seg.end) : null;
                if (!segStart && segEnd) segStart = new Date(segEnd.getTime() - 86400000);
                if (segStart && !segEnd) segEnd = new Date(today.getTime());
                if (!segStart || !segEnd) return "";

                const leftPx = dateToPx(segStart);
                const rightPx = dateToPx(segEnd);
                const widthPx = Math.max(6, rightPx - leftPx);
                const color = _ganttSegColor(seg);
                const overdueCls = seg.overdue ? " overdue" : "";
                const picsStr = (seg.pics || []).join(", ") || "Chưa PIC";
                const tip = [
                    `${f.ma_cn || "?"} — ${f.ten_cn || ""}`,
                    `Phase: ${seg.name}`,
                    `Status: ${seg.status || "?"}${seg.overdue ? " ⚠️ OVERDUE" : ""}`,
                    `PIC: ${picsStr}`,
                    `Thời gian: ${seg.start || "?"} → ${seg.end || "đang chạy"}`,
                ].join("\n");
                const inner = widthPx > 60 ? escapeHtml(seg.name) : (widthPx > 24 ? escapeHtml(seg.name.substring(0, 3)) : "");
                return `<div class="gantt-seg${overdueCls}"
                    style="left:${leftPx}px;width:${widthPx}px;background:${color}"
                    title="${escapeAttr(tip)}">${inner}</div>`;
            }).join("");

            parts.push(`<div class="gantt-func-row cursor-pointer"
                onclick="openDrillDown('timeline', {module:'${escapeAttr(modForDrill)}', ma_cn:'${escapeAttr(f.ma_cn || "")}'})"
                title="${escapeAttr((f.ma_cn||"") + " — " + (f.ten_cn||"") + " · Click xem chi tiết")}">
                <div class="gantt-func-label">${rowLabel}</div>
                <div class="gantt-func-track">
                    ${segments}
                </div>
            </div>`);
        });
    });

    container.innerHTML = `<div style="position:relative;min-width:${effectiveLabelW + trackW}px">
        ${parts.join("")}
        ${todayLineHtml}
    </div>`;
}

/**
 * Sinh danh sách tick trên ruler.
 * - week: mỗi tick = 1 tuần, label = "dd/MM"
 * - month: mỗi tick = 1 tháng, label = "MM/yyyy"
 * - quarter: mỗi tick = 1 quý, label = "Q1/yyyy"
 */
function _generateGanttTicks(minDate, maxDate, zoom, dateToPx) {
    const ticks = [];
    const d = new Date(minDate);
    if (zoom === "week") {
        // Bắt đầu từ thứ Hai gần nhất trước minDate
        const day = d.getDay(); // 0=CN, 1=T2
        const backToMonday = day === 0 ? 6 : day - 1;
        d.setDate(d.getDate() - backToMonday);
        while (d <= maxDate) {
            ticks.push({
                px: dateToPx(d),
                label: `${String(d.getDate()).padStart(2, "0")}/${String(d.getMonth() + 1).padStart(2, "0")}`,
            });
            d.setDate(d.getDate() + 7);
        }
    } else if (zoom === "month") {
        d.setDate(1);
        while (d <= maxDate) {
            ticks.push({
                px: dateToPx(d),
                label: `T${d.getMonth() + 1}/${d.getFullYear()}`,
            });
            d.setMonth(d.getMonth() + 1);
        }
    } else {  // quarter
        d.setDate(1);
        d.setMonth(Math.floor(d.getMonth() / 3) * 3);
        while (d <= maxDate) {
            const q = Math.floor(d.getMonth() / 3) + 1;
            ticks.push({
                px: dateToPx(d),
                label: `Q${q}/${d.getFullYear()}`,
            });
            d.setMonth(d.getMonth() + 3);
        }
    }
    return ticks;
}

// ========================================================================
// V2: COMPARE / SNAPSHOTS
// ========================================================================
function renderCompareSection() {
    const section = document.getElementById("section-compare");
    const emptyEl = document.getElementById("compareEmpty");
    const contentEl = document.getElementById("compareContent");
    if (!section || !emptyEl || !contentEl) return;
    section.classList.remove("hidden");

    // 3 case rõ ràng:
    //  - 0 snapshot → empty text mặc định + không populate select
    //  - 1 snapshot → empty text đặc thù "cần thêm 1 nữa" + populate select
    //    để user có thể "Upload file cũ" hoặc chờ upload mới
    //  - ≥ 2 snapshot → auto-compare 2 cái mới nhất
    const n = snapshotsData ? snapshotsData.length : 0;
    if (n < 2) {
        contentEl.classList.add("hidden");
        emptyEl.classList.remove("hidden");
        if (n === 0) {
            emptyEl.innerHTML = `<div class="text-gray-500">
                Chưa có snapshot nào để so sánh. Snapshot được tạo tự động mỗi lần upload file mới.
            </div>`;
        } else {
            // n === 1
            const s = snapshotsData[0];
            emptyEl.innerHTML = `<div class="text-gray-600 dark:text-gray-300 space-y-2 text-sm">
                <div>
                    Hiện có <b>1 snapshot</b>: ${escapeHtml(s.date)}
                    (${s.total_functions} func, ${s.overall_pct}%).
                </div>
                <div class="text-gray-500">
                    Để so sánh, cần <b>ít nhất 2 snapshot</b>. Chọn 1 trong 2 cách:
                </div>
                <ul class="list-disc pl-6 text-gray-500">
                    <li>Upload file cập nhật mới hơn → snapshot thứ 2 tự tạo.</li>
                    <li>Dùng nút <b>"Upload file cũ"</b> bên phải để đối chiếu tạm với 1 file khác (không lưu snapshot).</li>
                </ul>
            </div>`;
        }
        // Populate dropdown dù chỉ 1 snapshot để nút "So sánh" và "Xuất Excel" có context
        fillSnapshotSelect("compareOld", snapshotsData || []);
        fillSnapshotSelect("compareNew", snapshotsData || []);
        return;
    }
    // ≥ 2 snapshot
    fillSnapshotSelect("compareOld", snapshotsData, snapshotsData[1].date); // cũ hơn
    fillSnapshotSelect("compareNew", snapshotsData, snapshotsData[0].date); // mới nhất
    doCompare();
}

function fillSnapshotSelect(id, snapshots, selectedDate) {
    const sel = document.getElementById(id);
    if (!sel) return;
    sel.innerHTML = snapshots.map(s =>
        `<option value="${s.date}" ${s.date === selectedDate ? "selected" : ""}>${s.date} (${s.total_functions} func, ${s.overall_pct}%)</option>`
    ).join("");
}

async function doCompare() {
    const oldDate = document.getElementById("compareOld").value;
    const newDate = document.getElementById("compareNew").value;
    if (!oldDate || !newDate || oldDate === newDate) {
        showToast("Chọn 2 snapshot khác nhau", "red");
        return;
    }
    try {
        const resp = await fetch(`/api/projects/${currentProjectSlug}/compare?old=${oldDate}&new=${newDate}`);
        const data = await resp.json();
        if (data.error) {
            showToast("Lỗi: " + data.error, "red");
            return;
        }
        currentCompareResult = data.result;
        renderCompareResult(data.result);
        renderWeeklyDigest(data.result);
    } catch (err) {
        showToast("Lỗi: " + err.message, "red");
    }
}

async function handleCompareUpload(file) {
    const fd = new FormData();
    fd.append("file", file);
    try {
        const resp = await fetch(`/api/projects/${currentProjectSlug}/upload-compare`, { method: "POST", body: fd });
        const data = await resp.json();
        if (data.error) {
            showToast("Lỗi: " + data.error, "red");
            return;
        }
        currentCompareResult = data.result;
        renderCompareResult(data.result);
        renderWeeklyDigest(data.result);
        showToast("So sánh với file upload hoàn tất");
    } catch (err) {
        showToast("Lỗi: " + err.message, "red");
    }
}

function renderCompareResult(r) {
    document.getElementById("compareContent").classList.remove("hidden");
    document.getElementById("compareEmpty").classList.add("hidden");

    // Delta cards
    const deltaCards = [
        {
            label: "Tiến độ chung",
            old: r.old_overall_pct + "%",
            new: r.new_overall_pct + "%",
            delta: r.delta_pct,
            unit: "%",
            positiveIsGood: true,
        },
        {
            label: "Overdue",
            old: r.old_overdue,
            new: r.new_overdue,
            delta: r.delta_overdue,
            unit: "",
            positiveIsGood: false,
        },
        {
            label: "Function mới phát sinh",
            old: "-",
            new: r.new_functions.length,
            delta: r.new_functions.length,
            unit: "",
            positiveIsGood: false,
            forceOrange: true,
        },
        {
            label: "Tốc độ close",
            old: "-",
            new: r.velocity.close_rate_per_day != null ? r.velocity.close_rate_per_day + " f/ngày" : "N/A",
            delta: r.velocity.est_days_remaining,
            unit: r.velocity.est_days_remaining ? "ngày còn lại" : "",
            positiveIsGood: null,
        },
    ];

    const cardsEl = document.getElementById("deltaCards");
    cardsEl.innerHTML = deltaCards.map(c => {
        let cls = "delta-neutral";
        let arrow = "";
        if (c.forceOrange) {
            cls = "delta-warning";
        } else if (typeof c.delta === "number") {
            if (c.delta > 0) {
                cls = c.positiveIsGood ? "delta-positive" : "delta-negative";
                arrow = " ▲";
            } else if (c.delta < 0) {
                cls = c.positiveIsGood ? "delta-negative" : "delta-positive";
                arrow = " ▼";
            }
        }
        return `<div class="delta-card ${cls}">
            <div class="text-xs text-gray-500">${c.label}</div>
            <div class="text-xl font-bold">${c.new}${arrow}</div>
            <div class="text-xs text-gray-500">Trước: ${c.old} ${typeof c.delta === "number" ? `(${c.delta > 0 ? "+" : ""}${c.delta}${c.unit})` : ""}</div>
        </div>`;
    }).join("");

    // Module delta chart
    const modules = Object.keys(r.module_deltas || {});
    const ctx = getCanvas("chartModuleDelta");
    createChart(ctx, "bar", {
        labels: modules,
        datasets: [
            { label: "Trước", data: modules.map(m => r.module_deltas[m].old_pct), backgroundColor: "#94a3b8" },
            { label: "Sau", data: modules.map(m => r.module_deltas[m].new_pct), backgroundColor: "#3b82f6" },
        ],
    }, {
        responsive: true,
        plugins: { legend: { position: "top" } },
        scales: { y: { beginAtZero: true, max: 100, ticks: { callback: v => v + "%" } } },
    });

    // Status transitions
    const trEl = document.getElementById("statusFlow");
    const tr = r.transitions_agg || {};
    const trKeys = Object.keys(tr).sort((a, b) => tr[b] - tr[a]);
    if (trKeys.length === 0) {
        trEl.innerHTML = `<div class="text-gray-500 italic text-xs">Không có thay đổi status</div>`;
    } else {
        trEl.innerHTML = trKeys.slice(0, 12).map(k => {
            const isForward = /→ Closed/.test(k);
            const color = isForward ? "#22c55e" : "#64748b";
            return `<div class="flex justify-between border-b py-1 text-xs">
                <span style="color:${color}">${escapeHtml(k)}</span>
                <span class="font-bold">${tr[k]}</span>
            </div>`;
        }).join("");
    }

    // New functions table
    const newFns = r.new_functions || [];
    const wrap = document.getElementById("newFunctionsWrap");
    if (newFns.length === 0) {
        wrap.innerHTML = `<div class="text-gray-500 italic text-xs">Không có function mới phát sinh</div>`;
    } else {
        wrap.innerHTML = `
            <h4 class="text-sm font-semibold text-orange-600 mb-2">🆕 ${newFns.length} function mới phát sinh (scope creep)</h4>
            <div class="overflow-x-auto">
                <table class="w-full text-xs">
                    <thead><tr class="bg-orange-100">
                        <th class="px-2 py-1 text-left">Mã CN</th>
                        <th class="px-2 py-1 text-left">Tên CN</th>
                        <th class="px-2 py-1">Module</th>
                        <th class="px-2 py-1">Priority</th>
                    </tr></thead>
                    <tbody>${newFns.slice(0, 30).map(f => `
                        <tr class="border-b">
                            <td class="px-2 py-1 font-mono">${escapeHtml(f.ma_cn)}</td>
                            <td class="px-2 py-1">${escapeHtml(f.ten_cn)}</td>
                            <td class="px-2 py-1 text-center">${escapeHtml(f.module)}</td>
                            <td class="px-2 py-1 text-center">${escapeHtml(f.priority)}</td>
                        </tr>`).join("")}
                    </tbody>
                </table>
            </div>`;
    }
}

async function downloadCompareReport() {
    const oldDate = document.getElementById("compareOld").value;
    const newDate = document.getElementById("compareNew").value;
    if (!oldDate || !newDate) return;
    await downloadFile(`/api/projects/${currentProjectSlug}/export-compare?old=${oldDate}&new=${newDate}`,
                       `Compare_${oldDate}_vs_${newDate}.xlsx`);
}

// ========================================================================
// V2: WEEKLY DIGEST
// ========================================================================
function renderWeeklyDigest(r) {
    const section = document.getElementById("section-digest");
    if (!r) {
        section.classList.add("hidden");
        return;
    }
    section.classList.remove("hidden");
    const v = r.velocity || {};

    // Top module tiến bộ
    const mds = r.module_deltas || {};
    const modArr = Object.entries(mds).map(([m, d]) => ({ module: m, ...d }));
    const topProgress = modArr.filter(m => m.delta_pct > 0)
                              .sort((a, b) => b.delta_pct - a.delta_pct).slice(0, 3);
    const topConcern = modArr.filter(m => m.delta_pct < 0 || m.new_count > 0)
                             .sort((a, b) => (b.new_count - b.delta_pct) - (a.new_count - a.delta_pct)).slice(0, 3);

    const forward = (r.status_changes || []).filter(s => s.direction === "forward").length;
    const backward = (r.status_changes || []).filter(s => s.direction === "backward").length;

    const el = document.getElementById("weeklyDigest");
    el.innerHTML = `
        <div class="mb-3 text-sm text-gray-500">
            So sánh <strong class="text-gray-800">${r.old_date}</strong> → <strong class="text-gray-800">${r.new_date}</strong>
            ${v.days_between ? `(${v.days_between} ngày)` : ""}
        </div>
        <div class="grid grid-cols-1 md:grid-cols-3 gap-4 mb-4">
            <div class="p-4 bg-green-50 rounded-lg border-l-4 border-green-500">
                <div class="text-xs text-gray-600">Function đã Closed</div>
                <div class="text-3xl font-bold text-green-600">${v.functions_closed || 0}</div>
                ${v.close_rate_per_day ? `<div class="text-xs text-gray-500">${v.close_rate_per_day} f/ngày</div>` : ""}
            </div>
            <div class="p-4 bg-orange-50 rounded-lg border-l-4 border-orange-500">
                <div class="text-xs text-gray-600">Function mới phát sinh</div>
                <div class="text-3xl font-bold text-orange-600">${v.functions_new || 0}</div>
                <div class="text-xs text-gray-500">Net progress: ${v.net_progress || 0}</div>
            </div>
            <div class="p-4 bg-blue-50 rounded-lg border-l-4 border-blue-500">
                <div class="text-xs text-gray-600">Dự báo còn lại</div>
                <div class="text-3xl font-bold text-blue-600">${v.est_days_remaining != null ? v.est_days_remaining : "N/A"}</div>
                <div class="text-xs text-gray-500">ngày (với tốc độ hiện tại)</div>
            </div>
        </div>
        <div class="grid grid-cols-1 md:grid-cols-2 gap-4 mb-4">
            <div>
                <h4 class="font-semibold text-sm text-green-700 mb-2">✅ Top 3 Module tiến bộ</h4>
                ${topProgress.length === 0 ? '<div class="text-xs text-gray-500 italic">Chưa có module nào tiến bộ đáng kể</div>' :
                    topProgress.map(m => `
                        <div class="text-sm py-1 border-b flex justify-between">
                            <span>${escapeHtml(m.module)}</span>
                            <span class="text-green-600 font-semibold">+${m.delta_pct}%</span>
                        </div>`).join("")}
            </div>
            <div>
                <h4 class="font-semibold text-sm text-red-700 mb-2">⚠️ Top 3 Module cần chú ý</h4>
                ${topConcern.length === 0 ? '<div class="text-xs text-gray-500 italic">Không có cảnh báo</div>' :
                    topConcern.map(m => `
                        <div class="text-sm py-1 border-b flex justify-between">
                            <span>${escapeHtml(m.module)}</span>
                            <span class="text-red-500 text-xs">${m.delta_pct < 0 ? `${m.delta_pct}%` : ""} ${m.new_count > 0 ? `+${m.new_count} mới` : ""}</span>
                        </div>`).join("")}
            </div>
        </div>
        <div class="grid grid-cols-2 md:grid-cols-4 gap-3 text-sm">
            <div class="p-3 bg-gray-50 rounded"><div class="text-xs text-gray-500">Chuyển tiếp forward</div><div class="text-2xl font-bold text-green-600">${forward}</div></div>
            <div class="p-3 bg-gray-50 rounded"><div class="text-xs text-gray-500">Bị revert (backward)</div><div class="text-2xl font-bold text-red-600">${backward}</div></div>
            <div class="p-3 bg-gray-50 rounded"><div class="text-xs text-gray-500">Function bị xóa</div><div class="text-2xl font-bold">${(r.removed_functions || []).length}</div></div>
            <div class="p-3 bg-gray-50 rounded"><div class="text-xs text-gray-500">Delta tổng</div><div class="text-2xl font-bold">${r.delta_total >= 0 ? "+" : ""}${r.delta_total}</div></div>
        </div>`;
}

// ========================================================================
// V2: EXPORTS
// ========================================================================
async function downloadFullReport() {
    await downloadFile(`/api/projects/${currentProjectSlug}/export-full-report`, "Full_Report.xlsx");
}

function populatePicExportSelect() {
    const sel = document.getElementById("picExportSelect");
    if (!sel) return;
    // Bug 4: enable sau khi upload — label rõ ràng hơn để user hiểu chức năng.
    const pics = (metricsData?.structure?.all_pics) || [];
    sel.disabled = pics.length === 0;
    sel.innerHTML = `<option value="">📥 Chọn PIC để xuất báo cáo riêng (${pics.length} PIC)</option>` +
        pics.map(p => `<option value="${escapeHtml(p)}">${escapeHtml(p)}</option>`).join("");
}

async function downloadPicReport() {
    const pic = document.getElementById("picExportSelect").value;
    if (!pic) {
        showToast("Chọn PIC trước", "red");
        return;
    }
    await downloadFile(`/api/projects/${currentProjectSlug}/export-by-pic?pic=${encodeURIComponent(pic)}`, `PIC_${pic}.xlsx`);
}

async function downloadFile(url, defaultName) {
    try {
        const resp = await fetch(url);
        if (!resp.ok) {
            const err = await resp.json().catch(() => ({}));
            showToast("Lỗi: " + (err.error || "Không thể xuất file"), "red");
            return;
        }
        const blob = await resp.blob();
        const objUrl = URL.createObjectURL(blob);
        const cd = resp.headers.get("Content-Disposition") || "";
        const nameMatch = cd.match(/filename[^;=\n]*=([^;\n]*)/);
        const filename = nameMatch ? nameMatch[1].replace(/["']/g, "").trim() : defaultName;
        const a = document.createElement("a");
        a.href = objUrl;
        a.download = filename;
        a.click();
        URL.revokeObjectURL(objUrl);
        showToast("Đã tải file: " + filename);
    } catch (err) {
        showToast("Lỗi: " + err.message, "red");
    }
}

/**
 * Xuất Excel cho 1 chart chính (module_overview, task_type, effort_heatmap…).
 * Dùng API /api/projects/<slug>/export-chart — áp dụng global filter hiện tại nếu có.
 */
async function exportChartData(chartKey) {
    if (!metricsData) {
        showToast("Chưa có dữ liệu — hãy upload file", "red");
        return;
    }
    const params = new URLSearchParams({ chart: chartKey });
    // Forward global filters (param name khớp _parse_multi_arg: module/process/pic)
    if (globalFilters.modules.length) params.set("module", globalFilters.modules.join(","));
    if (globalFilters.processes.length) params.set("process", globalFilters.processes.join(","));
    if (globalFilters.pics.length) params.set("pic", globalFilters.pics.join(","));
    await downloadFile(
        `/api/projects/${currentProjectSlug}/export-chart?${params.toString()}`,
        `Chart_${chartKey}.xlsx`
    );
}

/**
 * Xuất Report Đánh giá (audit) — scope=all|filtered.
 */
async function exportAuditReport() {
    if (!metricsData) {
        showToast("Chưa có dữ liệu — hãy upload file", "red");
        return;
    }
    const sel = document.getElementById("auditScopeSelect");
    const scope = (sel && sel.value) || "all";
    const params = new URLSearchParams({ scope });
    if (scope === "filtered") {
        if (globalFilters.modules.length) params.set("module", globalFilters.modules.join(","));
        if (globalFilters.processes.length) params.set("process", globalFilters.processes.join(","));
        if (globalFilters.pics.length) params.set("pic", globalFilters.pics.join(","));
    }
    await downloadFile(
        `/api/projects/${currentProjectSlug}/audit-report?${params.toString()}`,
        "Audit_Report.xlsx"
    );
}

/**
 * Xuất Excel cho 4 section Phase 4/5 (Vấn đề 3).
 *
 * section ∈ { "sla", "capacity", "slow", "baseline" }
 * Áp global filter hiện tại (module/process/pic) — backend luôn xuất ALL record
 * (rule V4: XEM PHÂN TRANG NHƯNG XUẤT ALL).
 *
 * Dùng POST body JSON để tránh URL quá dài khi filter có nhiều quy trình.
 */
async function exportSection(section) {
    if (!metricsData) {
        showToast("Chưa có dữ liệu — hãy upload file", "red");
        return;
    }
    const ALLOWED = { sla: 1, capacity: 1, slow: 1, baseline: 1 };
    if (!ALLOWED[section]) {
        showToast(`Section không hỗ trợ: ${section}`, "red");
        return;
    }
    // POST body chứa filter → tránh URL length limit + không phụ thuộc encoding query
    const body = {
        module: globalFilters.modules,
        process: globalFilters.processes,
        pic: globalFilters.pics,
    };
    try {
        const url = `/api/projects/${currentProjectSlug}/export-${section}`;
        const resp = await fetch(url, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(body),
        });
        if (!resp.ok) {
            const err = await resp.json().catch(() => ({}));
            showToast("Lỗi: " + (err.error || "Không thể xuất file"), "red");
            return;
        }
        const blob = await resp.blob();
        const objUrl = URL.createObjectURL(blob);
        const cd = resp.headers.get("Content-Disposition") || "";
        const nameMatch = cd.match(/filename[^;=\n]*=([^;\n]*)/);
        const defaultName = {
            sla: "SLA_Violations.xlsx",
            capacity: "Capacity_PIC.xlsx",
            slow: "Slow_Heatmap.xlsx",
            baseline: "Baseline_Variance.xlsx",
        }[section];
        const filename = nameMatch ? nameMatch[1].replace(/["']/g, "").trim() : defaultName;
        const a = document.createElement("a");
        a.href = objUrl;
        a.download = filename;
        a.click();
        URL.revokeObjectURL(objUrl);
        showToast("Đã tải file: " + filename);
    } catch (err) {
        showToast("Lỗi: " + err.message, "red");
    }
}

// ========================================================================
// V2: SEARCH
// ========================================================================
// Task 1 — Function Traceability search.
// Autocomplete hit backend /function-search (debounce 200ms) → click 1 kết quả
// mở modal "Hồ sơ chức năng" với full lifecycle. Đã thay thế logic cũ (chỉ
// tìm trong overdue/unassigned/risk in-memory) vì backend cover toàn bộ rows.
let _fnSearchTimer = null;
let _fnSearchInflight = 0;
let _fnSearchLastQuery = "";

function handleSearch() {
    if (_fnSearchTimer) clearTimeout(_fnSearchTimer);
    const q = document.getElementById("searchBox").value.trim();
    const results = document.getElementById("searchResults");
    if (!q) {
        results.classList.add("hidden");
        results.innerHTML = "";
        return;
    }
    // Debounce 200ms: tránh gọi API mỗi ký tự khi user gõ nhanh.
    _fnSearchTimer = setTimeout(() => _runFnSearch(q), 200);
}

async function _runFnSearch(q) {
    const results = document.getElementById("searchResults");
    _fnSearchLastQuery = q;
    const myTicket = ++_fnSearchInflight;
    try {
        const r = await fetch(
            `/api/projects/${currentProjectSlug}/function-search`
            + `?q=${encodeURIComponent(q)}&limit=10`
        );
        // Nếu người dùng đã gõ tiếp (query cũ) → bỏ result này
        if (myTicket !== _fnSearchInflight) return;
        if (!r.ok) {
            results.innerHTML = `<div class="p-3 text-red-500 text-sm">Lỗi ${r.status}</div>`;
            results.classList.remove("hidden");
            return;
        }
        const data = await r.json();
        const hits = data.items || [];
        if (hits.length === 0) {
            results.innerHTML = `<div class="p-3 text-gray-500 text-sm">Không tìm thấy chức năng nào khớp "${escapeHtml(q)}"</div>`;
        } else {
            results.innerHTML = hits.map(h => {
                const badge = h.fit_gap
                    ? `<span class="ml-1 px-1.5 py-0 rounded text-[10px] ${
                        String(h.fit_gap).toUpperCase() === 'GAP'
                          ? 'bg-orange-100 text-orange-700'
                          : 'bg-green-100 text-green-700'
                    }">${escapeHtml(h.fit_gap)}</span>`
                    : "";
                const pri = h.priority
                    ? `<span class="ml-1 text-[10px] text-gray-400">· ${escapeHtml(h.priority)}</span>`
                    : "";
                return `
                    <div class="search-item" onclick="openFunctionDetail(${h.row_num})">
                        <div class="font-mono text-xs text-gray-500">
                            ${escapeHtml(h.ma_cn || '(chưa có mã)')}
                            · ${escapeHtml(h.module || '—')}
                            ${badge}${pri}
                        </div>
                        <div>${escapeHtml(h.ten_cn || '')}</div>
                        <div class="text-[10px] text-gray-400 truncate">
                            ${escapeHtml(h.quy_trinh || '')}
                        </div>
                    </div>`;
            }).join("");
        }
        results.classList.remove("hidden");
    } catch (e) {
        if (myTicket !== _fnSearchInflight) return;
        results.innerHTML = `<div class="p-3 text-red-500 text-sm">Lỗi mạng: ${escapeHtml(e.message)}</div>`;
        results.classList.remove("hidden");
    }
}

// ------------------------------------------------------------------
// Modal "Hồ sơ chức năng" — hiển thị full lifecycle 1 function.
// Data từ /function-detail/<row_num>.
// ------------------------------------------------------------------

async function openFunctionDetail(rowNum) {
    // Đóng dropdown search + clear input để user thấy chuyển context sang modal
    const results = document.getElementById("searchResults");
    if (results) results.classList.add("hidden");
    const box = document.getElementById("searchBox");
    if (box) box.value = "";

    const modal = document.getElementById("functionDetailModal");
    if (!modal) return;
    modal.classList.remove("hidden");
    modal.classList.add("flex");

    document.getElementById("fnDetailMaCn").textContent = "—";
    document.getElementById("fnDetailBadges").innerHTML = "";
    document.getElementById("fnDetailTenCn").textContent = "Đang tải…";
    document.getElementById("fnDetailBody").innerHTML =
        `<div class="text-gray-400 text-center py-10">⏳ Đang tải chi tiết…</div>`;
    document.getElementById("fnDetailFooter").textContent = `Row #${rowNum}`;

    try {
        const r = await fetch(`/api/projects/${currentProjectSlug}/function-detail/${rowNum}`);
        if (!r.ok) {
            const err = await r.json().catch(() => ({}));
            document.getElementById("fnDetailBody").innerHTML =
                `<div class="text-red-600 text-center py-10">Lỗi: ${escapeHtml(err.error || r.statusText)}</div>`;
            return;
        }
        const data = await r.json();
        _renderFunctionDetail(data);
        // T24: sync bookmark + note state cho function này (Mã CN từ meta)
        _currentFnMaCn = String(data?.meta?.ma_cn || "").trim();
        _syncBookmarkNoteUi();
    } catch (e) {
        document.getElementById("fnDetailBody").innerHTML =
            `<div class="text-red-600 text-center py-10">Lỗi mạng: ${escapeHtml(e.message)}</div>`;
    }
}

function closeFunctionDetail() {
    const modal = document.getElementById("functionDetailModal");
    if (!modal) return;
    modal.classList.add("hidden");
    modal.classList.remove("flex");
}

/** Style class Tailwind cho status badge trong modal detail. */
function _fnStatusBadgeClass(status) {
    const s = String(status || "").toLowerCase();
    if (s === "closed")       return "bg-green-100 text-green-800 border-green-200";
    if (s === "in-progress")  return "bg-blue-100 text-blue-800 border-blue-200";
    if (s === "assigned")     return "bg-amber-100 text-amber-800 border-amber-200";
    if (s === "resolved")     return "bg-purple-100 text-purple-800 border-purple-200";
    if (s === "pending")      return "bg-orange-100 text-orange-800 border-orange-200";
    if (s === "cancelled")    return "bg-red-100 text-red-800 border-red-200";
    if (s === "open")         return "bg-gray-100 text-gray-700 border-gray-200";
    return "bg-gray-50 text-gray-500 border-gray-200";
}

function _fnRenderPhaseCard(p) {
    // Card 1 phase: header (task_type + status badge) + Start/End + PIC chips + note
    const st = p.status || "";
    const stCls = _fnStatusBadgeClass(st);
    const overdueBadge = p.is_overdue
        ? `<span class="ml-2 text-[10px] px-1.5 py-0.5 rounded bg-red-600 text-white font-semibold">⚠️ TRỄ</span>`
        : "";
    const closedRibbon = p.is_closed
        ? `<div class="absolute top-2 right-2 text-[10px] text-green-600">✓ Closed</div>`
        : "";
    const start = p.start_date || "—";
    const end = p.end_date || "—";
    let dur = "";
    if (p.duration_days != null) dur = ` <span class="text-gray-400 text-[10px]">(${p.duration_days}d)</span>`;
    let daysToEndTxt = "";
    if (p.days_to_end != null && !p.is_closed) {
        if (p.days_to_end < 0) daysToEndTxt = `<span class="text-red-600 text-[11px]">quá ${-p.days_to_end} ngày</span>`;
        else if (p.days_to_end === 0) daysToEndTxt = `<span class="text-orange-600 text-[11px]">hết hôm nay</span>`;
        else daysToEndTxt = `<span class="text-gray-500 text-[11px]">còn ${p.days_to_end} ngày</span>`;
    }
    const pics = (p.pics || []).map(pic => `
        <span class="inline-flex items-center gap-1 px-2 py-0.5 rounded text-xs bg-slate-100 dark:bg-slate-700 dark:text-gray-100 font-medium">
            👤 ${escapeHtml(pic)}
        </span>`).join("") || `<span class="text-xs text-gray-400 italic">chưa có PIC</span>`;
    const est = (typeof p.estimate_mh === "number")
        ? `<span class="text-[11px] text-gray-500">${p.estimate_mh} MH</span>`
        : "";
    const note = p.note
        ? `<div class="mt-2 text-[11px] text-gray-600 dark:text-gray-300 bg-yellow-50 dark:bg-yellow-900/20 border-l-2 border-yellow-400 px-2 py-1 rounded">📝 ${escapeHtml(p.note)}</div>`
        : "";

    const borderCls = p.is_overdue
        ? "border-red-300 dark:border-red-600"
        : p.is_closed
            ? "border-green-200 dark:border-green-800"
            : "border-gray-200 dark:border-slate-700";

    return `
        <div class="relative border ${borderCls} rounded-lg p-3 bg-white dark:bg-slate-800">
            ${closedRibbon}
            <div class="flex items-center justify-between gap-2 mb-2">
                <div class="min-w-0">
                    <div class="text-sm font-semibold text-gray-800 dark:text-gray-100 truncate">
                        ${escapeHtml(p.task_type || p.name)}${overdueBadge}
                    </div>
                    <div class="text-[10px] text-gray-400">phase: ${escapeHtml(p.name)}</div>
                </div>
                <span class="text-[11px] px-2 py-0.5 rounded border ${stCls} font-medium shrink-0">
                    ${escapeHtml(st || 'Chưa có')}
                </span>
            </div>
            <div class="text-xs text-gray-600 dark:text-gray-300 space-y-1">
                <div>📅 ${escapeHtml(start)} → ${escapeHtml(end)}${dur} ${daysToEndTxt}</div>
                <div class="flex flex-wrap gap-1 items-center">${pics}</div>
                ${est ? `<div>${est}</div>` : ""}
                ${note}
            </div>
        </div>`;
}

function _renderFunctionDetail(data) {
    const meta = data.meta || {};
    const s = data.summary || {};
    const phases = data.phases || [];

    // Header: mã CN + badges
    document.getElementById("fnDetailMaCn").textContent = meta.ma_cn || `Row #${data.row_num}`;
    document.getElementById("fnDetailTenCn").textContent = meta.ten_cn || "(chưa có tên)";
    const badges = [];
    if (meta.module) badges.push(`<span class="px-1.5 py-0.5 rounded text-[10px] bg-blue-100 text-blue-700 font-medium">${escapeHtml(meta.module)}</span>`);
    if (meta.priority) badges.push(`<span class="px-1.5 py-0.5 rounded text-[10px] bg-slate-100 text-slate-700">${escapeHtml(meta.priority)}</span>`);
    if (meta.complexity) badges.push(`<span class="px-1.5 py-0.5 rounded text-[10px] bg-purple-100 text-purple-700">${escapeHtml(meta.complexity)}</span>`);
    if (meta.fit_gap) {
        const isGap = String(meta.fit_gap).toUpperCase().includes("GAP");
        badges.push(`<span class="px-1.5 py-0.5 rounded text-[10px] ${isGap ? 'bg-orange-100 text-orange-800' : 'bg-green-100 text-green-800'} font-semibold">${escapeHtml(meta.fit_gap)}</span>`);
    }
    if (meta.giai_doan) badges.push(`<span class="px-1.5 py-0.5 rounded text-[10px] bg-gray-100 text-gray-700">GĐ ${escapeHtml(meta.giai_doan)}</span>`);
    document.getElementById("fnDetailBadges").innerHTML = badges.join("");

    // Summary strip — 5 card
    const overdueBanner = s.is_overdue
        ? `<div class="col-span-full bg-red-50 dark:bg-red-900/20 border-l-4 border-red-500 px-3 py-2 rounded text-sm text-red-700 dark:text-red-200">
             ⚠️ Function đang trễ deadline. Số ngày trễ tối đa của 1 phase: <b>${s.days_overdue_max}</b> ngày.
           </div>`
        : "";

    const progressPct = s.total_phases > 0
        ? Math.round((s.closed_count / s.total_phases) * 100)
        : 0;

    const nextDl = s.next_deadline
        ? `${escapeHtml(s.next_deadline)}${
            s.days_to_next_deadline != null
              ? (s.days_to_next_deadline >= 0
                  ? ` <span class="text-[10px] text-gray-500">(còn ${s.days_to_next_deadline}d)</span>`
                  : ` <span class="text-[10px] text-red-600">(quá ${-s.days_to_next_deadline}d)</span>`)
              : ""
          }`
        : `<span class="text-gray-400">—</span>`;

    const summaryStrip = `
        ${overdueBanner}
        <div class="rounded-lg border dark:border-slate-700 bg-slate-50 dark:bg-slate-900/50 p-3">
            <div class="text-[10px] uppercase text-gray-500 font-semibold">Đang ở phase</div>
            <div class="text-base font-bold text-gray-800 dark:text-gray-100 mt-1">${escapeHtml(s.current_phase || '—')}</div>
        </div>
        <div class="rounded-lg border dark:border-slate-700 bg-slate-50 dark:bg-slate-900/50 p-3">
            <div class="text-[10px] uppercase text-gray-500 font-semibold">Tiến độ</div>
            <div class="text-base font-bold text-gray-800 dark:text-gray-100 mt-1">
                ${s.closed_count}/${s.total_phases}
                <span class="text-xs text-gray-500 font-normal">phase (${progressPct}%)</span>
            </div>
        </div>
        <div class="rounded-lg border dark:border-slate-700 bg-slate-50 dark:bg-slate-900/50 p-3">
            <div class="text-[10px] uppercase text-gray-500 font-semibold">Tổng Estimate</div>
            <div class="text-base font-bold text-gray-800 dark:text-gray-100 mt-1">
                ${s.total_estimate_mh != null ? `${s.total_estimate_mh} MH` : '—'}
            </div>
        </div>
        <div class="rounded-lg border dark:border-slate-700 bg-slate-50 dark:bg-slate-900/50 p-3">
            <div class="text-[10px] uppercase text-gray-500 font-semibold">Next deadline</div>
            <div class="text-base font-bold text-gray-800 dark:text-gray-100 mt-1">${nextDl}</div>
        </div>
        <div class="rounded-lg border dark:border-slate-700 ${s.is_overdue ? 'bg-red-50 dark:bg-red-900/20' : 'bg-slate-50 dark:bg-slate-900/50'} p-3">
            <div class="text-[10px] uppercase text-gray-500 font-semibold">Tình trạng</div>
            <div class="text-base font-bold mt-1 ${s.is_overdue ? 'text-red-600' : 'text-green-600'}">
                ${s.is_overdue ? '⚠️ Trễ deadline' : '✓ Đúng tiến độ'}
            </div>
        </div>`;

    // Timeline: mỗi phase 1 card, grid 2 cột trên desktop
    const phaseCards = phases.map(_fnRenderPhaseCard).join("");

    // Extra info nếu có
    const extras = [];
    if (meta.quy_trinh) extras.push(`<div><span class="text-gray-500">Quy trình:</span> ${escapeHtml(meta.quy_trinh)}</div>`);
    if (meta.risk_blocker) extras.push(`<div><span class="text-gray-500">Risk/Blocker:</span> <span class="text-red-600">${escapeHtml(meta.risk_blocker)}</span></div>`);
    if (meta.mo_ta) extras.push(`<div><span class="text-gray-500">Mô tả:</span> ${escapeHtml(meta.mo_ta)}</div>`);
    if (meta.function_lq) extras.push(`<div><span class="text-gray-500">Function liên quan:</span> ${escapeHtml(meta.function_lq)}</div>`);
    if (meta.remark) extras.push(`<div><span class="text-gray-500">Remark:</span> ${escapeHtml(meta.remark)}</div>`);
    const extraBlock = extras.length
        ? `<div class="mt-4 text-xs bg-slate-50 dark:bg-slate-900/50 rounded-lg p-3 space-y-1">${extras.join("")}</div>`
        : "";

    document.getElementById("fnDetailBody").innerHTML = `
        <div class="grid grid-cols-2 md:grid-cols-5 gap-2 mb-4">${summaryStrip}</div>
        <h3 class="text-sm font-semibold text-gray-700 dark:text-gray-200 mb-2">⏱️ Timeline lifecycle</h3>
        <div class="grid grid-cols-1 md:grid-cols-2 gap-3">${phaseCards}</div>
        ${extraBlock}
    `;
    document.getElementById("fnDetailFooter").textContent =
        `Row Excel #${data.row_num} · ${phases.length} phase${meta.ma_cn ? ` · ${meta.ma_cn}` : ""}`;
}

// ========================================================================
// V2: THEME
// ========================================================================
function toggleTheme() {
    document.documentElement.classList.toggle("dark");
    localStorage.setItem("theme",
        document.documentElement.classList.contains("dark") ? "dark" : "light");
    updateThemeIcon();
    // Chart re-render để cập nhật màu
    if (metricsData) renderDashboard();
}

function updateThemeIcon() {
    const icon = document.getElementById("themeIcon");
    if (icon) icon.textContent = document.documentElement.classList.contains("dark") ? "☀️" : "🌙";
}

// ========================================================================
// V2: FULLSCREEN CHART
// ========================================================================
let fullscreenChartInstance = null;

function fullscreenChart(chartId) {
    const source = chartInstances[chartId];
    if (!source) return;
    const modal = document.getElementById("fullscreenModal");
    const canvas = document.getElementById("fullscreenCanvas");
    if (fullscreenChartInstance) fullscreenChartInstance.destroy();
    // QUAN TRỌNG: dùng source.config.data / source.config.options (raw user config)
    // thay vì source.data / source.options (đã bị Chart.js v4 wrap qua Proxy scriptable
    // resolver). Nếu truyền source.options thẳng vào new Chart(), internal resolver
    // sẽ throw "t.startsWith is not a function" ở tầng _scriptable → modal mở ra
    // nhưng canvas rỗng, chỉ hiện nút Đóng.
    try {
        fullscreenChartInstance = new Chart(canvas.getContext("2d"), {
            type: source.config.type,
            data: JSON.parse(JSON.stringify(source.config.data)),
            options: Object.assign({}, source.config.options || {}, { maintainAspectRatio: false }),
        });
        modal.classList.remove("hidden");
    } catch (e) {
        // Fail-safe: nếu chart nào có config lỗi thì báo user, không để modal
        // treo lơ lửng với overlay đen mà không có content.
        console.error("[fullscreenChart] Không mở được fullscreen cho", chartId, ":", e);
        if (typeof showToast === "function") {
            showToast(`Không mở được phóng to biểu đồ này (${e.message})`, "red");
        }
    }
}

function closeFullscreen() {
    document.getElementById("fullscreenModal").classList.add("hidden");
    if (fullscreenChartInstance) {
        fullscreenChartInstance.destroy();
        fullscreenChartInstance = null;
    }
}

// ========================================================================
// V2: REFRESH REMINDER + P6 UPLOAD REMINDER
// ========================================================================
function checkRefreshReminder() {
    if (!metricsData) return;

    // Banner 1 (V2): dashboard đã > 24h (refresh nhỏ, mỗi lần vào)
    if (snapshotsData.length > 0) {
        const latest = new Date(snapshotsData[0].upload_time);
        const hoursDiff = (Date.now() - latest) / (1000 * 60 * 60);
        if (hoursDiff > 24) {
            document.getElementById("dataAge").textContent =
                latest.toLocaleString("vi-VN") + ` (${Math.floor(hoursDiff)}h trước)`;
            document.getElementById("refreshBanner").classList.remove("hidden");
        }
    }

    // Banner 2 (P6 #21): reminder mạnh hơn nếu vượt ngưỡng ngày theo project settings.
    // Ngưỡng mặc định 7 ngày, config qua project_settings.json.
    const meta = window._projectMeta || {};
    const days = (meta.settings?.upload_reminder_days) || 7;
    const ts = meta.upload_time || (snapshotsData[0]?.upload_time);
    const banner = document.getElementById("uploadReminderBanner");
    const txt = document.getElementById("uploadReminderText");
    if (!banner || !ts) return;
    const daysDiff = (Date.now() - new Date(ts)) / (1000 * 60 * 60 * 24);
    if (daysDiff >= days) {
        if (txt) {
            txt.textContent = `File Function List đã ${Math.floor(daysDiff)} ngày chưa cập nhật (ngưỡng ${days} ngày).`;
        }
        banner.classList.remove("hidden");
    } else {
        banner.classList.add("hidden");
    }
}

/**
 * P6: hiển thị warnings sau upload dưới dạng toast xếp chồng.
 * warnings: [{level: "critical"|"warning"|"info", code, message}]
 */
function _showUploadWarnings(warnings) {
    const colorByLevel = { critical: "red", warning: "orange", info: "blue" };
    warnings.forEach((w, i) => {
        const c = colorByLevel[w.level] || "gray";
        // Stagger 400ms để 3-4 toast không đè lên nhau
        setTimeout(() => showToast(`⚠️ ${w.message}`, c), i * 400);
    });
}

// ========================================================================
// HELPERS
// ========================================================================
function getCanvas(id) {
    if (chartInstances[id]) {
        chartInstances[id].destroy();
        delete chartInstances[id];
    }
    return document.getElementById(id).getContext("2d");
}

// Chart.js — defaults thẩm mỹ chung.
// Bọc try/catch để nếu CDN Chart.js load chưa xong / structure Chart.defaults
// đổi giữa version, top-level không throw làm hỏng khai báo (TDZ) các const/let
// bên dưới (như SIDEBAR_COLLAPSE_KEY).
try {
    if (typeof Chart !== "undefined") {
        Chart.defaults.font.family = "system-ui, -apple-system, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif";
        Chart.defaults.font.size = 11;
        Chart.defaults.color = "#334155";
        Chart.defaults.plugins.legend.labels.usePointStyle = true;
        Chart.defaults.plugins.legend.labels.boxWidth = 10;
        Chart.defaults.plugins.legend.labels.padding = 12;
        Chart.defaults.plugins.tooltip.backgroundColor = "rgba(15, 23, 42, 0.92)";
        Chart.defaults.plugins.tooltip.padding = 10;
        Chart.defaults.plugins.tooltip.cornerRadius = 8;
        Chart.defaults.plugins.tooltip.titleFont = { weight: "600", size: 12 };
        Chart.defaults.plugins.tooltip.bodyFont = { size: 11 };
        Chart.defaults.plugins.tooltip.boxPadding = 4;
        // Phase 7 Slim: tắt animation mặc định — máy yếu / dataset lớn render mượt hơn.
        Chart.defaults.animation = false;
        // Bar chart
        if (Chart.defaults.datasets && Chart.defaults.datasets.bar) {
            Chart.defaults.datasets.bar.borderRadius = 4;
            Chart.defaults.datasets.bar.maxBarThickness = 40;
        }
        // ChartDataLabels — register global nhưng mặc định TẮT.
        if (typeof ChartDataLabels !== "undefined") {
            Chart.register(ChartDataLabels);
            Chart.defaults.plugins.datalabels = { display: false };
        }
        // Dark mode listener → cập nhật màu
        _applyChartTheme();
        const observer = new MutationObserver(_applyChartTheme);
        observer.observe(document.documentElement, { attributes: true, attributeFilter: ["class"] });
    }
} catch (e) {
    console.error("[dashboard.js] Chart.js init failed (bỏ qua để không chặn khai báo const bên dưới):", e);
}

// ==========================================================================
// DATA LABELS — helpers dùng chung để wire vào chart cần hiển thị số/%
// ==========================================================================

/**
 * Config cho doughnut/pie: hiện "value (pct%)" giữa mỗi segment.
 * Bỏ qua segment quá nhỏ (< minPct) để tránh chữ đè lên nhau.
 */
function _labelsForDoughnut(minPct = 4) {
    return {
        display: (ctx) => {
            const total = (ctx.dataset.data || []).reduce((s, v) => s + (Number(v) || 0), 0);
            if (!total) return false;
            const pct = (Number(ctx.dataset.data[ctx.dataIndex]) / total) * 100;
            return pct >= minPct;
        },
        color: "#fff",
        font: { weight: "bold", size: 11 },
        textStrokeColor: "rgba(0,0,0,0.55)",
        textStrokeWidth: 3,
        formatter: (val, ctx) => {
            const total = (ctx.dataset.data || []).reduce((s, v) => s + (Number(v) || 0), 0);
            const pct = total ? Math.round((val / total) * 100) : 0;
            return `${val}\n(${pct}%)`;
        },
        textAlign: "center",
    };
}

/**
 * Config cho bar chart (vertical): hiện value ở đỉnh mỗi cột.
 * unit: "" | "%" — nếu là % sẽ append.
 * minValue: bỏ qua giá trị 0.
 */
function _labelsForVerticalBar(unit = "", minValue = 0) {
    return {
        display: (ctx) => (Number(ctx.dataset.data[ctx.dataIndex]) || 0) > minValue,
        anchor: "end",
        align: "end",
        offset: 2,
        color: "#1e293b",
        backgroundColor: "rgba(255,255,255,0.85)",
        borderRadius: 3,
        padding: { top: 1, bottom: 1, left: 3, right: 3 },
        font: { size: 10, weight: "bold" },
        formatter: (val) => (val > 0 ? `${val}${unit}` : ""),
    };
}

/**
 * Config cho stacked bar (vertical hoặc horizontal): hiện value giữa mỗi segment
 * nhưng chỉ khi segment ≥ minPct % của total (tránh chữ tràn qua segment nhỏ).
 */
function _labelsForStackedBar(minPct = 5) {
    return {
        display: (ctx) => {
            const val = Number(ctx.dataset.data[ctx.dataIndex]) || 0;
            if (val <= 0) return false;
            // Tính tổng của stack tại vị trí đó (cùng label, khác dataset)
            const chart = ctx.chart;
            const idx = ctx.dataIndex;
            let total = 0;
            (chart.data.datasets || []).forEach(ds => {
                total += Number(ds.data[idx]) || 0;
            });
            return total > 0 && (val / total) * 100 >= minPct;
        },
        color: "#fff",
        font: { size: 10, weight: "bold" },
        textStrokeColor: "rgba(0,0,0,0.5)",
        textStrokeWidth: 2,
        formatter: (val) => (val > 0 ? val : ""),
    };
}

/**
 * Render 1 card info gọn thay chart khi filter chỉ còn 1 nhóm.
 * Ví dụ khi user filter Module=PR + Quy trình=PRM.BP.04 → Process Treemap
 * chỉ có 1 ô đỏ khổng lồ → thay bằng card giải thích rõ hơn.
 *
 * @param {HTMLElement} container — element chứa chart (thường là parent của <canvas>)
 * @param {Object} info — { groupType, groupName, total, pctClosed, extra, hint }
 */
function _renderSingleGroupCard(container, info) {
    if (!container) return;
    const {
        groupType = "nhóm",
        groupName = "",
        total = 0,
        pctClosed = null,
        extra = "",
        hint = "Bỏ bớt bộ lọc để so sánh giữa nhiều nhóm",
    } = info || {};
    const metaParts = [];
    if (total) metaParts.push(`<b>${total}</b> function`);
    if (pctClosed !== null && pctClosed !== undefined) metaParts.push(`<b>${pctClosed}%</b> Closed`);
    if (extra) metaParts.push(escapeHtml(extra));
    container.innerHTML = `
        <div class="single-group-card">
            <div class="sgc-icon">⚠️</div>
            <div class="sgc-body">
                <div class="sgc-title">Chỉ còn 1 ${escapeHtml(groupType)} sau khi lọc</div>
                <div class="sgc-name">${escapeHtml(groupName || "-")}</div>
                <div class="sgc-meta">${metaParts.join(" · ")}</div>
                <div class="sgc-hint">💡 ${escapeHtml(hint)}</div>
            </div>
        </div>`;
}

/**
 * Hủy chart instance + thay canvas parent bằng card info.
 * Dùng khi số nhóm ≤ 1 → chart không có ý nghĩa so sánh.
 */
function _replaceCanvasWithCard(canvasId, info) {
    if (chartInstances[canvasId]) {
        try { chartInstances[canvasId].destroy(); } catch (e) {}
        delete chartInstances[canvasId];
    }
    const canvas = document.getElementById(canvasId);
    if (!canvas) return;
    const box = canvas.closest(".chart-box") || canvas.parentElement;
    if (!box) return;
    // Giữ canvas ẩn để lần render sau có element để re-create chart
    canvas.style.display = "none";
    // Xóa mọi card cũ trong box, thêm card mới
    box.querySelectorAll(".single-group-card").forEach(el => el.remove());
    const wrap = document.createElement("div");
    wrap.className = "single-group-wrap";
    box.appendChild(wrap);
    _renderSingleGroupCard(wrap, info);
}

/** Đảo ngược: khi số nhóm > 1 → show lại canvas, xóa card. */
function _restoreCanvas(canvasId) {
    const canvas = document.getElementById(canvasId);
    if (!canvas) return;
    canvas.style.display = "";
    const box = canvas.closest(".chart-box") || canvas.parentElement;
    if (!box) return;
    box.querySelectorAll(".single-group-wrap").forEach(el => el.remove());
}

/**
 * Config cho horizontal bar chart hiển thị TỔNG ở cuối bar (dùng cho PIC Workload).
 * Áp cho MỘT dataset duy nhất (last dataset) để tránh trùng lặp.
 */
function _labelsForBarTotal(lastDatasetIndex) {
    return {
        display: (ctx) => ctx.datasetIndex === lastDatasetIndex,
        anchor: "end",
        align: "end",
        offset: 4,
        color: "#1e293b",
        backgroundColor: "rgba(255,255,255,0.85)",
        borderRadius: 3,
        padding: { top: 1, bottom: 1, left: 4, right: 4 },
        font: { size: 10, weight: "bold" },
        formatter: (val, ctx) => {
            const chart = ctx.chart;
            const idx = ctx.dataIndex;
            let total = 0;
            (chart.data.datasets || []).forEach(ds => {
                total += Number(ds.data[idx]) || 0;
            });
            return total > 0 ? `Σ ${total}` : "";
        },
    };
}

function _applyChartTheme() {
    const isDark = document.documentElement.classList.contains("dark");
    if (typeof Chart === "undefined") return;
    Chart.defaults.color = isDark ? "#cbd5e1" : "#334155";
    Chart.defaults.borderColor = isDark ? "rgba(148, 163, 184, 0.2)" : "rgba(148, 163, 184, 0.25)";
    // Re-render tất cả chart hiện có với màu mới
    Object.values(chartInstances).forEach(c => { try { c.update("none"); } catch (e) {} });
}

function createChart(ctx, type, data, options) {
    // FORCE: mọi chart đều responsive + maintainAspectRatio:false để chart co giãn
    // theo container (.chart-box đã có height cố định qua CSS).
    const isCircular = type === "doughnut" || type === "pie" || type === "polarArea";
    const baseOpts = {
        responsive: true,
        maintainAspectRatio: false,
        resizeDelay: 120,
        // Phase 7 Slim: tắt animation mặc định — máy yếu / dataset lớn render mượt.
        // Caller có thể override `animation: { duration: 300 }` cho chart cần mềm mại.
        animation: false,
        layout: { padding: isCircular ? { top: 6, right: 6, bottom: 6, left: 6 } : { top: 4, right: 8, bottom: 4, left: 4 } },
        plugins: {
            legend: {
                position: isCircular ? "bottom" : "top",
                labels: {
                    boxWidth: 12,
                    boxHeight: 12,
                    padding: 8,
                    font: { size: 11 },
                    usePointStyle: isCircular,
                },
            },
            tooltip: {
                backgroundColor: "rgba(15, 23, 42, 0.92)",
                titleFont: { size: 12, weight: "bold" },
                bodyFont: { size: 12 },
                padding: 10,
                boxPadding: 4,
                cornerRadius: 6,
                displayColors: true,
            },
        },
    };
    // Deep-merge cho plugins/scales để không override option chart-specific
    const finalOptions = _deepMerge(baseOpts, options || {});
    finalOptions.responsive = true;
    finalOptions.maintainAspectRatio = false;

    // Destroy chart cũ trên cùng canvas (tránh leak / blank)
    const canvasId = ctx.canvas?.id;
    if (canvasId && chartInstances[canvasId]) {
        try { chartInstances[canvasId].destroy(); } catch (e) {}
        delete chartInstances[canvasId];
    }

    const chart = new Chart(ctx, { type, data, options: finalOptions });
    if (canvasId) chartInstances[canvasId] = chart;
    // Resize sau 1 frame — canvas mới hiện lại sau empty-state thường cần force size
    requestAnimationFrame(() => {
        try { chart.resize(); } catch (e) {}
    });
    return chart;
}

// Deep merge cho options (không overwrite plugins.legend, scales... nested)
function _deepMerge(target, source) {
    const out = Array.isArray(target) ? target.slice() : Object.assign({}, target);
    for (const key in source) {
        const sv = source[key];
        const tv = out[key];
        if (sv && typeof sv === "object" && !Array.isArray(sv) &&
            tv && typeof tv === "object" && !Array.isArray(tv)) {
            out[key] = _deepMerge(tv, sv);
        } else {
            out[key] = sv;
        }
    }
    return out;
}

function showToast(msg, color = "green") {
    const toast = document.getElementById("toast");
    toast.textContent = msg;
    toast.className = `fixed bottom-5 right-5 ${color === "red" ? "bg-red-600" : "bg-green-600"} text-white px-5 py-3 rounded-lg shadow-lg z-50`;
    toast.classList.remove("hidden");
    setTimeout(() => toast.classList.add("hidden"), 3500);
}

function statusBadge(status) {
    if (!status) return "";
    const c = STATUS_COLORS[status] || "#94a3b8";
    return `<span class="px-2 py-0.5 rounded text-xs font-medium" style="background:${c}20;color:${c}">${escapeHtml(status)}</span>`;
}

function escapeHtml(str) {
    if (str === null || str === undefined) return "";
    return String(str)
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;")
        .replace(/'/g, "&#039;");
}

function fmtNum(v) {
    if (v === null || v === undefined || v === "") return "0";
    if (typeof v === "number") return v.toLocaleString("vi-VN");
    return v;
}

// ==========================================================================
// DRILL-DOWN — click biểu đồ → xem data table + xuất Excel
// ==========================================================================

const drillState = {
    chart: null,       // chart type
    filters: {},       // filter TỪ chart cũ (module, phase, ...) — server-side
    title: "",
    items: [],
    filtered: [],
    sortKey: null,
    sortDir: "asc",
    // Client-side filter panel (áp SAU khi nhận items từ server)
    ui: {
        search: "",
        statuses: new Set(),    // rỗng = tất cả
        pic: "",
        dateFrom: "",           // YYYY-MM-DD
        dateTo: "",
        overdueOnly: false,
    },
    availableStatuses: [],      // populated từ items
};

const DRILL_COLUMNS = [
    { key: "ma_cn",        label: "Mã CN",       width: "w-24" },
    { key: "ten_cn",       label: "Tên chức năng", width: "" },
    { key: "module",       label: "Module",      width: "w-16" },
    { key: "phase",        label: "Phase",       width: "w-24" },
    { key: "status",       label: "Status",      width: "w-24", render: v => statusBadge(v) },
    { key: "pics",         label: "PIC",         width: "w-32", render: v => Array.isArray(v) ? v.join(", ") : (v || "") },
    { key: "start_date",   label: "Start",       width: "w-24" },
    { key: "end_date",     label: "End",         width: "w-24" },
    { key: "days_overdue", label: "Trễ (ngày)",  width: "w-20", render: v => v ? `<span class="text-red-600 font-semibold">${v}</span>` : "-" },
    { key: "priority",     label: "Priority",    width: "w-20" },
    { key: "complexity",   label: "Complexity",  width: "w-20" },
    { key: "fit_gap",      label: "FIT/GAP",     width: "w-16" },
];

async function openDrillDown(chart, filters, titleOverride) {
    if (!metricsData) {
        showToast("Chưa có dữ liệu — hãy upload file", "red");
        return;
    }
    drillState.chart = chart;
    drillState.filters = filters || {};
    drillState.sortKey = null;
    drillState.sortDir = "asc";
    pageState.drill.page = 1;

    const modal = document.getElementById("drillDownModal");
    modal.classList.remove("hidden");
    modal.classList.add("flex");

    document.getElementById("drillBody").innerHTML =
        `<div class="text-gray-400 text-center py-10">⏳ Đang tải chi tiết…</div>`;
    document.getElementById("drillTitle").textContent = titleOverride || "Chi tiết";
    document.getElementById("drillSubtitle").textContent = "";
    // Reset filter panel về default mỗi khi mở drill mới
    _resetDrillFilterState();

    // Merge chart filter + global filter (prefix _g_ để không đè chart filter).
    // Global filter đảm bảo drill-down luôn scope theo bộ lọc chính hiện tại
    // (VD user lọc Module=PR thì click chart nào chi tiết ra cũng chỉ PR).
    const params = new URLSearchParams({ chart, ...filters });
    if (globalFilters.modules.length) {
        globalFilters.modules.forEach(m => params.append("_g_module", m));
    }
    if (globalFilters.processes.length) {
        globalFilters.processes.forEach(p => params.append("_g_process", p));
    }
    if (globalFilters.pics.length) {
        globalFilters.pics.forEach(p => params.append("_g_pic", p));
    }
    const qs = params.toString();
    try {
        const res = await fetch(`/api/projects/${currentProjectSlug}/drill-down?${qs}`);
        const data = await res.json();
        if (!res.ok || data.error) {
            document.getElementById("drillBody").innerHTML =
                `<div class="text-red-600 text-center py-10">Lỗi: ${escapeHtml(data.error || "unknown")}</div>`;
            return;
        }
        drillState.title = titleOverride || data.title || chart;
        drillState.items = data.items || [];
        drillState.filtered = drillState.items.slice();
        // Populate status filter dropdown từ items nhận về
        _buildDrillStatusMenu();
        document.getElementById("drillTitle").textContent = drillState.title;
        // Subtitle: chart + chart filter + global filter (để user thấy rõ scope drill này lấy từ đâu)
        const gfParts = [];
        if (globalFilters.modules.length) gfParts.push(`Module=[${globalFilters.modules.join(",")}]`);
        if (globalFilters.processes.length) gfParts.push(`Quy trình=[${globalFilters.processes.map(p => p.split(/[-–]/)[0].trim()).join(",")}]`);
        if (globalFilters.pics.length) gfParts.push(`PIC=[${globalFilters.pics.join(",")}]`);
        const gfStr = gfParts.length ? ` · 🌐 Global: ${gfParts.join(" · ")}` : "";
        document.getElementById("drillSubtitle").textContent =
            `Chart: ${chart} · Project: ${currentProjectSlug} · Chart filter: ${JSON.stringify(filters)}${gfStr}`;
        renderDrillTable();
    } catch (e) {
        document.getElementById("drillBody").innerHTML =
            `<div class="text-red-600 text-center py-10">Lỗi mạng: ${escapeHtml(e.message)}</div>`;
    }
}

/** Reset toàn bộ input filter panel về trạng thái mặc định. */
function _resetDrillFilterState() {
    drillState.ui = {
        search: "",
        statuses: new Set(),
        pic: "",
        dateFrom: "",
        dateTo: "",
        overdueOnly: false,
    };
    const $s = document.getElementById("drillSearch");
    const $p = document.getElementById("drillPicFilter");
    const $df = document.getElementById("drillDateFrom");
    const $dt = document.getElementById("drillDateTo");
    const $od = document.getElementById("drillOverdueOnly");
    if ($s) $s.value = "";
    if ($p) $p.value = "";
    if ($df) $df.value = "";
    if ($dt) $dt.value = "";
    if ($od) $od.checked = false;
    const $lbl = document.getElementById("drillStatusLabel");
    if ($lbl) $lbl.textContent = "Tất cả";
    const $af = document.getElementById("drillActiveFilters");
    if ($af) $af.textContent = "";
}

/** Populate status dropdown menu từ unique status trong drillState.items. */
function _buildDrillStatusMenu() {
    const menu = document.getElementById("drillStatusMenu");
    if (!menu) return;
    const uniq = new Set();
    drillState.items.forEach(it => {
        if (it.status) uniq.add(String(it.status));
    });
    drillState.availableStatuses = [...uniq].sort();
    if (drillState.availableStatuses.length === 0) {
        menu.innerHTML = `<div class="text-gray-400 italic p-2">Không có status</div>`;
        return;
    }
    menu.innerHTML = drillState.availableStatuses.map(st => `
        <label class="flex items-center gap-2 py-1 px-1 hover:bg-blue-50 dark:hover:bg-slate-600 rounded cursor-pointer">
            <input type="checkbox" value="${escapeAttr(st)}"
                   class="w-4 h-4 accent-blue-600 drill-status-cb"
                   onchange="_onDrillStatusChange()" />
            <span>${escapeHtml(st)}</span>
        </label>
    `).join("");
}

/** Toggle status dropdown menu (click nút Trạng thái). */
function _toggleDrillStatusMenu(evt) {
    evt.stopPropagation();
    const menu = document.getElementById("drillStatusMenu");
    if (!menu) return;
    menu.classList.toggle("hidden");
    // Click ngoài menu → đóng
    if (!menu.classList.contains("hidden")) {
        const closeHandler = (e) => {
            if (!menu.contains(e.target) && e.target.id !== "drillStatusBtn") {
                menu.classList.add("hidden");
                document.removeEventListener("click", closeHandler);
            }
        };
        setTimeout(() => document.addEventListener("click", closeHandler), 10);
    }
}

/** Handler khi tick checkbox status. */
function _onDrillStatusChange() {
    drillState.ui.statuses = new Set(
        [...document.querySelectorAll(".drill-status-cb:checked")].map(cb => cb.value)
    );
    const lbl = document.getElementById("drillStatusLabel");
    if (lbl) {
        const n = drillState.ui.statuses.size;
        lbl.textContent = n === 0 ? "Tất cả"
            : n === 1 ? [...drillState.ui.statuses][0]
            : `${n} status`;
    }
    applyDrillFilters();
}

/** Reset toàn bộ filter (nút Reset). */
function resetDrillFilters() {
    _resetDrillFilterState();
    document.querySelectorAll(".drill-status-cb").forEach(cb => cb.checked = false);
    applyDrillFilters();
}

/**
 * Apply filter panel — kết hợp AND giữa 5 field:
 *   search (mã CN / tên), status (multi OR), PIC (contains),
 *   date range (Start hoặc End trong khoảng), overdueOnly.
 */
function applyDrillFilters() {
    // Đọc state từ DOM (in case direct edit)
    drillState.ui.search = (document.getElementById("drillSearch")?.value || "").toLowerCase().trim();
    drillState.ui.pic = (document.getElementById("drillPicFilter")?.value || "").toLowerCase().trim();
    drillState.ui.dateFrom = document.getElementById("drillDateFrom")?.value || "";
    drillState.ui.dateTo = document.getElementById("drillDateTo")?.value || "";
    drillState.ui.overdueOnly = document.getElementById("drillOverdueOnly")?.checked || false;

    const { search, statuses, pic, dateFrom, dateTo, overdueOnly } = drillState.ui;

    const parseD = (s) => {
        if (!s) return null;
        const d = new Date(s);
        return isNaN(d.getTime()) ? null : d;
    };
    const fromD = parseD(dateFrom);
    const toD = parseD(dateTo);

    drillState.filtered = drillState.items.filter(it => {
        // 1. Text search (Mã CN + Tên)
        if (search) {
            const hay = ((it.ma_cn || "") + " " + (it.ten_cn || "")).toLowerCase();
            if (!hay.includes(search)) return false;
        }
        // 2. Status (OR trong set)
        if (statuses.size > 0) {
            if (!statuses.has(String(it.status || ""))) return false;
        }
        // 3. PIC (contains — check trong array pics)
        if (pic) {
            const pics = Array.isArray(it.pics) ? it.pics : (it.pic ? [it.pic] : []);
            const joined = pics.join(",").toLowerCase();
            if (!joined.includes(pic)) return false;
        }
        // 4. Date range: match nếu Start HOẶC End nằm trong [fromD, toD]
        if (fromD || toD) {
            const start = parseD(it.start_date);
            const end = parseD(it.end_date);
            const inRange = (d) => {
                if (!d) return false;
                if (fromD && d < fromD) return false;
                if (toD && d > toD) return false;
                return true;
            };
            // Chấp nhận nếu ít nhất 1 trong 2 (start/end) nằm trong range.
            if (!inRange(start) && !inRange(end)) return false;
        }
        // 5. Overdue only
        if (overdueOnly && !it.is_overdue) return false;

        return true;
    });

    pageState.drill.page = 1;

    // Update summary text
    const $af = document.getElementById("drillActiveFilters");
    if ($af) {
        const parts = [];
        if (search) parts.push(`Chức năng ~ "${search}"`);
        if (statuses.size > 0) parts.push(`Status ∈ {${[...statuses].join(", ")}}`);
        if (pic) parts.push(`PIC ~ "${pic}"`);
        if (fromD || toD) parts.push(`Ngày ${dateFrom || "…"} → ${dateTo || "…"}`);
        if (overdueOnly) parts.push(`Chỉ trễ`);
        $af.innerHTML = parts.length === 0
            ? `<span class="text-gray-400">Chưa áp filter — đang xem ${drillState.items.length} dòng</span>`
            : `<b>Filter đang áp:</b> ${parts.join(" · ")} → còn ${drillState.filtered.length}/${drillState.items.length} dòng`;
    }

    renderDrillTable();
}

function closeDrillDown() {
    const modal = document.getElementById("drillDownModal");
    modal.classList.add("hidden");
    modal.classList.remove("flex");
}

function renderDrillTable() {
    const body = document.getElementById("drillBody");
    const items = drillState.filtered;
    if (items.length === 0) {
        body.innerHTML = `<div class="text-gray-400 text-center py-10">Không có function nào phù hợp.</div>`;
        document.getElementById("drillFooter").textContent = "Tổng: 0";
        const pagerEl = document.getElementById("drillPagerWrap");
        if (pagerEl) pagerEl.innerHTML = "";
        return;
    }

    const overdue = items.filter(i => i.is_overdue).length;
    const closed = items.filter(i => (i.status || "").toLowerCase() === "closed").length;
    const inProgress = items.filter(i => ["In-progress", "Assigned"].includes(i.status)).length;
    const { start, end, pageItems } = _pageSlice("drill", items);
    document.getElementById("drillFooter").textContent =
        `Tổng: ${items.length} · Đang xem ${start + 1}–${end} · Closed: ${closed} · Đang làm: ${inProgress} · Trễ: ${overdue}`;

    const thead = `<thead class="bg-gray-100 dark:bg-slate-700 sticky top-0 z-10">
        <tr class="text-xs">
            <th class="px-2 py-2 text-center w-10">#</th>
            ${DRILL_COLUMNS.map(c => `
                <th class="px-2 py-2 text-left cursor-pointer hover:bg-gray-200 dark:hover:bg-slate-600 ${c.width}"
                    onclick="sortDrillTable('${c.key}')">
                    ${escapeHtml(c.label)}${drillState.sortKey === c.key ? (drillState.sortDir === "asc" ? " ▲" : " ▼") : ""}
                </th>
            `).join("")}
        </tr>
    </thead>`;

    const rows = pageItems.map((it, idx) => {
        const rowCls = it.is_overdue ? "bg-red-50 dark:bg-red-900/20"
            : (it.status || "").toLowerCase() === "closed" ? "bg-green-50 dark:bg-green-900/10"
            : "";
        return `<tr class="text-xs border-b dark:border-slate-700 ${rowCls}">
            <td class="px-2 py-1 text-center text-gray-500">${start + idx + 1}</td>
            ${DRILL_COLUMNS.map(c => {
                const v = it[c.key];
                const display = c.render ? c.render(v) : escapeHtml(v === null || v === undefined ? "" : String(v));
                return `<td class="px-2 py-1 align-top">${display}</td>`;
            }).join("")}
        </tr>`;
    }).join("");

    body.innerHTML = `<table class="w-full text-sm">${thead}<tbody>${rows}</tbody></table>`;
    // Pager dưới footer nếu có wrap; nếu không thì inject vào footer area
    let pagerEl = document.getElementById("drillPagerWrap");
    if (!pagerEl) {
        const footer = document.getElementById("drillFooter");
        if (footer && footer.parentElement) {
            pagerEl = document.createElement("div");
            pagerEl.id = "drillPagerWrap";
            footer.parentElement.insertBefore(pagerEl, footer);
        }
    }
    if (pagerEl) {
        renderPager("drillPagerWrap", "drill", items.length, () => renderDrillTable());
    }
}

// Legacy — deprecated. Wire vẫn giữ để BC nếu code cũ còn call.
// Giờ redirect vào applyDrillFilters (đã đọc value trực tiếp từ DOM).
function filterDrillTable(kw) {
    const $s = document.getElementById("drillSearch");
    if ($s && kw !== undefined && kw !== null) $s.value = kw;
    applyDrillFilters();
}

function sortDrillTable(key) {
    if (drillState.sortKey === key) {
        drillState.sortDir = drillState.sortDir === "asc" ? "desc" : "asc";
    } else {
        drillState.sortKey = key;
        drillState.sortDir = "asc";
    }
    const dir = drillState.sortDir === "asc" ? 1 : -1;
    drillState.filtered.sort((a, b) => {
        let x = a[key], y = b[key];
        if (Array.isArray(x)) x = x.join(",");
        if (Array.isArray(y)) y = y.join(",");
        if (x === null || x === undefined) x = "";
        if (y === null || y === undefined) y = "";
        if (typeof x === "number" && typeof y === "number") return (x - y) * dir;
        return String(x).localeCompare(String(y)) * dir;
    });
    renderDrillTable();
}

async function exportDrillDown() {
    if (!drillState.chart) return;
    // Chart custom (VD "_overdue_custom") → backend không hỗ trợ export.
    // Gợi ý user dùng nút xuất Excel của section-overdue.
    if (drillState.chart.startsWith("_")) {
        showToast("Dùng nút 📥 Xuất Excel ở section Overdue để export danh sách này", "red");
        return;
    }
    try {
        showToast("⏳ Đang xuất Excel…", "green");
        const res = await fetch(`/api/projects/${currentProjectSlug}/drill-down/export`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                chart: drillState.chart,
                filters: drillState.filters,
                // Bao gồm global filter để export nhất quán với view (không lộ data ngoài scope)
                global_filter: {
                    modules: globalFilters.modules,
                    processes: globalFilters.processes,
                    pics: globalFilters.pics,
                },
            }),
        });
        if (!res.ok) {
            const err = await res.json().catch(() => ({ error: "unknown" }));
            showToast("Lỗi xuất Excel: " + (err.error || res.status), "red");
            return;
        }
        const blob = await res.blob();
        const url = URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = url;
        const cd = res.headers.get("Content-Disposition") || "";
        const match = cd.match(/filename="?([^"]+)"?/);
        a.download = match ? match[1] : `DrillDown_${drillState.chart}.xlsx`;
        a.click();
        URL.revokeObjectURL(url);
        showToast("✅ Đã tải file Excel");
    } catch (e) {
        showToast("Lỗi mạng: " + e.message, "red");
    }
}

// --------------------------------------------------------------------------
// Chart.js onClick helper — dùng chung
// --------------------------------------------------------------------------
function _chartClickHandler(chart, buildFilterFn) {
    return function (evt, elements, chartCtx) {
        if (!elements || elements.length === 0) return;
        const el = elements[0];
        const filters = buildFilterFn(el, chartCtx || this);
        if (!filters) return;
        openDrillDown(chart, filters);
    };
}

// Click handler cho ô Phase Matrix (HTML table)
function _matrixCellClick(el) {
    openDrillDown("phase_matrix", {
        module: el.dataset.mod,
        phase: el.dataset.ph,
    });
}

/**
 * Drill-down modal cho card "Function trễ deadline".
 * Backend không có chart="overdue" trong SUPPORTED_CHARTS → reuse endpoint
 * `/api/projects/<slug>/overdue` sẵn có, adapt data về format drillState.
 * Tránh phải thêm chart type mới vào backend (không muốn đụng test 195/195).
 */
async function openOverdueDrillDown() {
    if (!metricsData) {
        showToast("Chưa có dữ liệu — hãy upload file", "red");
        return;
    }
    // Giả lập drillState như openDrillDown chuẩn
    drillState.chart = "_overdue_custom";  // đánh dấu để không dùng export drill-down chuẩn
    drillState.filters = {};
    drillState.sortKey = null;
    drillState.sortDir = "asc";

    const modal = document.getElementById("drillDownModal");
    modal.classList.remove("hidden");
    modal.classList.add("flex");

    document.getElementById("drillBody").innerHTML =
        `<div class="text-gray-400 text-center py-10">⏳ Đang tải danh sách trễ deadline…</div>`;
    document.getElementById("drillTitle").textContent = "⚠️ Chi tiết Function trễ deadline";
    document.getElementById("drillSubtitle").textContent = "";
    document.getElementById("drillSearch").value = "";

    try {
        const res = await fetch(`/api/projects/${currentProjectSlug}/overdue`);
        const data = await res.json();
        if (!res.ok || data.error) {
            document.getElementById("drillBody").innerHTML =
                `<div class="text-red-600 text-center py-10">Lỗi: ${escapeHtml(data.error || "unknown")}</div>`;
            return;
        }
        // Adapt overdue item → drill-down row schema (ma_cn, ten_cn, module, phase, status, pics, end_date, days_overdue, priority, is_overdue)
        const items = (data.overdue || []).map(it => ({
            ma_cn: it.ma_cn,
            ten_cn: it.ten_cn,
            module: it.module,
            phase: it.phase,
            status: it.status,
            pics: it.pic || [],
            start_date: it.start_date || "",
            end_date: it.end_date || "",
            days_overdue: it.days_overdue,
            priority: it.priority || "",
            complexity: it.complexity || "",
            fit_gap: it.fit_gap || "",
            is_overdue: true,
        }));
        drillState.items = items;
        drillState.filtered = items.slice();
        drillState.title = "⚠️ Chi tiết Function trễ deadline";
        document.getElementById("drillSubtitle").textContent =
            `Tổng: ${items.length} phase-record trễ · Project: ${currentProjectSlug}`;
        renderDrillTable();
    } catch (e) {
        document.getElementById("drillBody").innerHTML =
            `<div class="text-red-600 text-center py-10">Lỗi mạng: ${escapeHtml(e.message)}</div>`;
    }
}

// Cursor pointer khi hover element có thể click
const CLICKABLE_CHART_OPTS = {
    onHover: (event, elements) => {
        event.native.target.style.cursor = elements.length ? "pointer" : "default";
    },
};

// ==========================================================================
// PIC BLACKLIST — data-quality modal
// ==========================================================================

/**
 * Cập nhật hiển thị nút "PIC bị bỏ" / chip "PIC sạch" trên toolbar.
 * Gọi mỗi lần applyDashboardResponse — count từ top-level field của response.
 */
function _updatePicBlacklistBadge(count) {
    const btn = document.getElementById("picBlacklistBtn");
    const clean = document.getElementById("picBlacklistClean");
    const cntEl = document.getElementById("picBlacklistCount");
    if (!btn || !clean) return;
    if (count > 0) {
        btn.classList.remove("hidden");
        clean.classList.add("hidden");
        if (cntEl) cntEl.textContent = count;
    } else {
        btn.classList.add("hidden");
        clean.classList.remove("hidden");
    }
}

/**
 * Mở modal + fetch danh sách blacklist chi tiết từ backend.
 * Endpoint `/pic-blacklist` không filter (toàn dataset).
 */
async function openPicBlacklistModal() {
    const modal = document.getElementById("picBlacklistModal");
    if (!modal) return;
    modal.classList.remove("hidden");
    modal.classList.add("flex");

    const body = document.getElementById("picBlacklistBody");
    const kwEl = document.getElementById("picBlacklistKeywords");
    body.innerHTML = `<div class="text-gray-400 text-center py-10">⏳ Đang tải danh sách…</div>`;

    try {
        const res = await fetch(`/api/projects/${currentProjectSlug}/pic-blacklist`);
        const data = await res.json();
        if (!res.ok || data.error) {
            body.innerHTML =
                `<div class="text-red-600 text-center py-10">Lỗi: ${escapeHtml(data.error || "unknown")}</div>`;
            return;
        }

        const items = data.items || [];
        const kw = (data.keywords || []).map(escapeHtml).join(", ") || "(không có)";
        if (kwEl) kwEl.innerHTML = kw;

        if (items.length === 0) {
            body.innerHTML = `<div class="text-center py-10">
                <div class="text-4xl mb-2">🟢</div>
                <div class="text-lg font-semibold text-green-700">Dữ liệu PIC sạch</div>
                <div class="text-sm text-gray-500 mt-1">
                    Không có token PIC nào bị parser blacklist. File Function List
                    không có ô nào lệch cột Status sang PIC.
                </div>
            </div>`;
            return;
        }

        body.innerHTML = _renderPicBlacklistTable(items);
    } catch (e) {
        body.innerHTML =
            `<div class="text-red-600 text-center py-10">Lỗi mạng: ${escapeHtml(e.message)}</div>`;
    }
}

function closePicBlacklistModal() {
    const modal = document.getElementById("picBlacklistModal");
    if (!modal) return;
    modal.classList.add("hidden");
    modal.classList.remove("flex");
}

/**
 * Render bảng blacklist. Cột: #, Row Excel, Mã CN, Module, Phase, Cột (header),
 * Giá trị bị bỏ, Keyword khớp.
 */
function _renderPicBlacklistTable(items) {
    const header = `<thead class="bg-amber-100 dark:bg-slate-700 sticky top-0">
        <tr class="text-xs">
            <th class="px-2 py-2 text-center w-10">#</th>
            <th class="px-2 py-2 text-center w-20">Row Excel</th>
            <th class="px-2 py-2 text-left w-24">Mã CN</th>
            <th class="px-2 py-2 text-center w-16">Module</th>
            <th class="px-2 py-2 text-center w-20">Phase</th>
            <th class="px-2 py-2 text-left w-40">Cột (header)</th>
            <th class="px-2 py-2 text-left w-28">Giá trị bị bỏ</th>
            <th class="px-2 py-2 text-center w-24">Keyword khớp</th>
        </tr>
    </thead>`;
    const rows = items.map((it, idx) => `
        <tr class="text-xs border-b dark:border-slate-700 hover:bg-amber-50 dark:hover:bg-slate-700">
            <td class="px-2 py-1 text-center text-gray-500">${idx + 1}</td>
            <td class="px-2 py-1 text-center font-mono">${escapeHtml(it.row_index)}</td>
            <td class="px-2 py-1 font-mono">${escapeHtml(it.ma_cn || "")}</td>
            <td class="px-2 py-1 text-center">${escapeHtml(it.module || "")}</td>
            <td class="px-2 py-1 text-center">${escapeHtml(it.phase_name || "")}</td>
            <td class="px-2 py-1 font-mono text-[11px] text-gray-600">${escapeHtml(it.header_text || "")}</td>
            <td class="px-2 py-1"><span class="inline-block bg-red-100 text-red-700 px-1.5 py-0.5 rounded font-mono">${escapeHtml(it.raw_value || "")}</span></td>
            <td class="px-2 py-1 text-center"><span class="inline-block bg-amber-100 text-amber-800 px-1.5 py-0.5 rounded">${escapeHtml(it.matched_keyword || "")}</span></td>
        </tr>
    `).join("");

    return `<table class="w-full text-sm">${header}<tbody>${rows}</tbody></table>
            <div class="mt-3 text-xs text-gray-500 italic">
                Tổng: ${items.length} token bị bỏ · Sử dụng "Row Excel" + "Cột (header)" để tra chính xác ô trong file gốc.
            </div>`;
}

async function downloadPicBlacklist() {
    await downloadFile(
        `/api/projects/${currentProjectSlug}/pic-blacklist/export`,
        "PIC_Blacklist.xlsx",
    );
}

// ========================================================================
// ============  PORTFOLIO (V3 Level 1/2/3) — cross-project  ==============
// ========================================================================
// Namespace tất cả code portfolio riêng để không đụng code existing.
// - Level 1: global search bar (#portfolioSearchBox) — debounced 300ms
// - Level 2: compare modal (#portfolioCompareModal) — chọn 2-4 project
// - Level 3: rollup modal (#portfolioRollupModal) — aggregated dashboard

const Portfolio = (function () {
    // ==== Internal state ====
    let _searchTimer = null;
    let _compareState = null;    // {slugs, result} — cho export re-use
    let _rollupState = null;     // {slugs, data} — cho re-render nếu switch subset
    let _rollupCharts = {};      // Chart instance registry cho rollup section
    let _pendingHighlight = null; // {ma_cn, project_slug} — deep-link sau switchProject

    const SEARCH_DEBOUNCE_MS = 300;
    const SEARCH_MIN_CHARS = 2;

    // ============================================================
    // Level 1: SEARCH (portfolio-wide)
    // ============================================================

    /** Init: bind event handlers cho portfolio search box. */
    function initSearchBox() {
        const box = document.getElementById("portfolioSearchBox");
        if (!box) return;

        box.addEventListener("input", (e) => {
            if (_searchTimer) clearTimeout(_searchTimer);
            _searchTimer = setTimeout(() => _doSearch(e.target.value), SEARCH_DEBOUNCE_MS);
        });
        box.addEventListener("keydown", (e) => {
            if (e.key === "Enter") {
                if (_searchTimer) clearTimeout(_searchTimer);
                _doSearch(e.target.value);
            }
            if (e.key === "Escape") {
                _hideDropdown();
                box.blur();
            }
        });
        box.addEventListener("focus", () => {
            const v = box.value.trim();
            if (v.length >= SEARCH_MIN_CHARS) _doSearch(v);
        });

        // Click ngoài → đóng dropdown
        document.addEventListener("click", (e) => {
            if (!e.target.closest("#portfolioSearchWrap")) _hideDropdown();
        });
    }

    async function _doSearch(query) {
        const q = (query || "").trim();
        const results = document.getElementById("portfolioSearchResults");
        if (!results) return;

        if (q.length < SEARCH_MIN_CHARS) {
            _hideDropdown();
            return;
        }

        results.innerHTML = `<div class="p-3 text-gray-500 text-sm">⏳ Đang tìm…</div>`;
        results.classList.remove("hidden");

        try {
            const r = await fetch(`/api/portfolio/search?q=${encodeURIComponent(q)}&scope=all&limit=50`);
            if (!r.ok) {
                results.innerHTML = `<div class="p-3 text-red-500 text-sm">Lỗi tìm kiếm</div>`;
                return;
            }
            const data = await r.json();
            _renderSearchDropdown(data, q);
        } catch (err) {
            results.innerHTML = `<div class="p-3 text-red-500 text-sm">Lỗi: ${escapeHtml(err.message)}</div>`;
        }
    }

    function _renderSearchDropdown(data, q) {
        const results = document.getElementById("portfolioSearchResults");
        const items = data.results || [];

        if (items.length === 0) {
            const skippedNote = (data.projects_skipped || []).length > 0
                ? `<div class="text-xs text-gray-400 mt-1">Đã bỏ qua ${data.projects_skipped.length} dự án chưa upload file</div>`
                : "";
            results.innerHTML = `
                <div class="p-3 text-gray-500 text-sm">
                    Không tìm thấy "${escapeHtml(q)}" trong ${data.projects_searched} dự án.
                    ${skippedNote}
                </div>`;
            return;
        }

        // Group theo project
        const grouped = {};
        for (const it of items) {
            (grouped[it.project_slug] = grouped[it.project_slug] || {
                name: it.project_name, items: []
            }).items.push(it);
        }

        const projects = allProjects.reduce((m, p) => { m[p.slug] = p; return m; }, {});

        const html = Object.entries(grouped).map(([slug, g]) => {
            const p = projects[slug] || { name: g.name };
            const itemsHtml = g.items.map(it => {
                const badge = it.overdue_flag
                    ? `<span class="inline-block bg-red-100 text-red-700 text-[10px] px-1.5 rounded ml-1">TRỄ</span>`
                    : "";
                const phase = it.active_phase
                    ? `<span class="text-[10px] text-blue-600 ml-1">· ${escapeHtml(it.active_phase)}</span>`
                    : "";
                const pic = (it.pic || []).slice(0, 2).join(", ");
                const picHtml = pic ? ` · <span class="text-gray-600">${escapeHtml(pic)}</span>` : "";
                return `
                    <div class="search-item px-3 py-2 hover:bg-blue-50 dark:hover:bg-slate-700 cursor-pointer border-b border-gray-100 dark:border-slate-700"
                         onclick="Portfolio.goToResult('${escapeHtml(slug)}', '${escapeHtml(it.ma_cn)}')">
                        <div class="text-xs font-mono text-gray-500">${escapeHtml(it.ma_cn)} · ${escapeHtml(it.module)}${phase}${badge}</div>
                        <div class="text-sm">${escapeHtml(it.ten_cn)}${picHtml}</div>
                    </div>`;
            }).join("");
            return `
                <div class="search-project-group">
                    <div class="px-3 py-1.5 bg-gray-100 dark:bg-slate-700 text-xs font-bold text-gray-700 dark:text-gray-200 sticky top-0">
                        🗂️ ${escapeHtml(p.name)} <span class="text-gray-400 font-normal">(${g.items.length})</span>
                    </div>
                    ${itemsHtml}
                </div>`;
        }).join("");

        let footer = "";
        if (data.truncated) {
            footer = `<div class="px-3 py-2 bg-amber-50 dark:bg-amber-900/30 text-amber-800 text-xs border-t">
                Đang hiển thị ${items.length}/${data.total} kết quả — nhập từ khoá cụ thể hơn để lọc.
            </div>`;
        }
        const skippedHtml = (data.projects_skipped || []).length > 0
            ? `<div class="px-3 py-1 text-[10px] text-gray-400 border-t">Bỏ qua ${data.projects_skipped.length} dự án chưa upload</div>`
            : "";

        results.innerHTML = html + footer + skippedHtml;
    }

    function _hideDropdown() {
        const el = document.getElementById("portfolioSearchResults");
        if (el) el.classList.add("hidden");
    }

    /**
     * Click 1 search result → switch project (nếu khác) + scroll + highlight ma_cn.
     * Best-effort: nếu function không có row trong bảng nào → toast báo.
     */
    async function goToResult(projectSlug, maCn) {
        _hideDropdown();
        document.getElementById("portfolioSearchBox").value = "";

        _pendingHighlight = { ma_cn: maCn, project_slug: projectSlug };

        if (projectSlug !== currentProjectSlug) {
            // switchProject là async, sẽ tự trigger tryLoadDashboardForCurrent
            document.getElementById("projectSelector").value = projectSlug;
            await switchProject(projectSlug);
        }

        // Đợi 1 tick để DOM render xong sau switchProject
        setTimeout(() => _applyPendingHighlight(), 500);
    }

    function _applyPendingHighlight() {
        if (!_pendingHighlight) return;
        const { ma_cn } = _pendingHighlight;
        _pendingHighlight = null;

        // Best-effort: scan text content của các bảng chi tiết để tìm row chứa ma_cn.
        // Không dùng data-attribute vì các bảng existing chưa gắn.
        const tables = document.querySelectorAll("#dashboard table tbody tr");
        let found = null;
        for (const tr of tables) {
            if (tr.textContent.includes(ma_cn)) {
                found = tr;
                break;
            }
        }

        if (found) {
            found.scrollIntoView({ behavior: "smooth", block: "center" });
            found.classList.add("portfolio-search-highlight");
            setTimeout(() => found.classList.remove("portfolio-search-highlight"), 3000);
            showToast(`Đã tìm thấy ${ma_cn}`);
        } else {
            showToast(`Đã chuyển sang project — "${ma_cn}" không có trong bảng chi tiết nào (function chỉ nằm trong dashboard tổng hợp)`, "orange");
        }
    }

    // ============================================================
    // Level 2: COMPARE
    // ============================================================

    function openCompareModal() {
        // Đóng project manager modal nếu đang mở
        const pm = document.getElementById("projectManagerModal");
        if (pm && !pm.classList.contains("hidden")) {
            pm.classList.add("hidden");
            pm.classList.remove("flex");
        }
        const modal = document.getElementById("portfolioCompareModal");
        modal.classList.remove("hidden");
        modal.classList.add("flex");

        // Reset state
        _compareState = null;
        document.getElementById("pfCompareResult").classList.add("hidden");
        document.getElementById("pfCompareExportBtn").disabled = true;
        _renderCompareCheckboxes();
    }

    function closeCompareModal() {
        const modal = document.getElementById("portfolioCompareModal");
        modal.classList.add("hidden");
        modal.classList.remove("flex");
    }

    function _renderCompareCheckboxes() {
        const container = document.getElementById("pfCompareCheckboxes");
        if (!allProjects || allProjects.length < 2) {
            container.innerHTML = `<div class="text-amber-700 text-sm col-span-2 py-2">
                ⚠️ Cần ≥ 2 dự án để so sánh. Hiện chỉ có ${allProjects.length} dự án.
                <a href="#" onclick="openProjectManager(); return false;" class="text-blue-600 underline">Tạo project mới</a>.
            </div>`;
            document.getElementById("pfCompareRunBtn").disabled = true;
            return;
        }
        document.getElementById("pfCompareRunBtn").disabled = false;

        container.innerHTML = allProjects.map(p => `
            <label class="flex items-center gap-2 border border-gray-200 dark:border-slate-600 rounded px-3 py-2 cursor-pointer hover:bg-indigo-50 dark:hover:bg-slate-600">
                <input type="checkbox" class="pf-compare-cb" value="${escapeHtml(p.slug)}"
                       onchange="Portfolio._updateCompareHint()" />
                <span class="text-sm font-medium">${escapeHtml(p.name)}</span>
                <span class="text-xs text-gray-400 ml-auto">${p.snapshot_count || 0} snap</span>
            </label>
        `).join("");
        _updateCompareHint();
    }

    function _updateCompareHint() {
        const cbs = document.querySelectorAll(".pf-compare-cb:checked");
        const hint = document.getElementById("pfCompareHint");
        const btn = document.getElementById("pfCompareRunBtn");
        const n = cbs.length;
        if (n === 0) {
            hint.textContent = "Chưa chọn dự án nào";
            hint.className = "text-xs text-gray-500 ml-auto";
            btn.disabled = true;
        } else if (n === 1) {
            hint.textContent = "Chọn ít nhất 2 dự án";
            hint.className = "text-xs text-amber-600 ml-auto";
            btn.disabled = true;
        } else if (n > 4) {
            hint.textContent = `Đã chọn ${n} — chỉ nên chọn tối đa 4 để dễ đọc`;
            hint.className = "text-xs text-amber-600 ml-auto";
            btn.disabled = false;
        } else {
            hint.textContent = `Đã chọn ${n} dự án`;
            hint.className = "text-xs text-green-600 ml-auto";
            btn.disabled = false;
        }
    }

    async function runCompare() {
        const slugs = Array.from(document.querySelectorAll(".pf-compare-cb:checked"))
            .map(cb => cb.value);
        if (slugs.length < 2) {
            showToast("Cần chọn ít nhất 2 dự án", "red");
            return;
        }
        const btn = document.getElementById("pfCompareRunBtn");
        btn.disabled = true;
        btn.textContent = "Đang so sánh...";
        try {
            const r = await fetch("/api/portfolio/compare", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ slugs }),
            });
            const data = await r.json();
            if (!r.ok) {
                showToast(data.error || "Lỗi", "red");
                return;
            }
            _compareState = { slugs, result: data };
            _renderCompareTable(data);
            document.getElementById("pfCompareResult").classList.remove("hidden");
            document.getElementById("pfCompareExportBtn").disabled = false;
        } catch (err) {
            showToast("Lỗi: " + err.message, "red");
        } finally {
            btn.disabled = false;
            btn.textContent = "So sánh";
        }
    }

    function _renderCompareTable(data) {
        const projects = data.projects || [];
        const metrics = data.metrics || {};
        const labels = data.metric_labels || [];
        const bw = data.best_worst || {};

        const head = `<tr class="bg-indigo-700 text-white">
            <th class="px-3 py-2 text-left">Chỉ tiêu</th>
            ${projects.map(p => `<th class="px-3 py-2 text-center" title="${escapeHtml(p.slug)}">
                ${escapeHtml(p.name)}
            </th>`).join("")}
        </tr>`;
        document.getElementById("pfCompareTableHead").innerHTML = head;

        const rows = labels.map(ml => {
            const cells = projects.map(p => {
                const v = metrics[ml.key]?.[p.slug];
                const bwEntry = bw[ml.key];
                let cls = "px-3 py-2 text-center border";
                if (bwEntry && bwEntry.best === p.slug) {
                    cls += " bg-green-100 dark:bg-green-900/30 text-green-800 dark:text-green-100 font-semibold";
                } else if (bwEntry && bwEntry.worst === p.slug) {
                    cls += " bg-red-100 dark:bg-red-900/30 text-red-800 dark:text-red-100 font-semibold";
                }
                const display = (v === null || v === undefined || v === "") ? "—" : String(v);
                return `<td class="${cls}">${escapeHtml(display)}</td>`;
            }).join("");
            const arrow = ml.higher_is_better === true ? " ⬆️"
                : ml.higher_is_better === false ? " ⬇️" : "";
            return `<tr class="border-b hover:bg-gray-50 dark:hover:bg-slate-700">
                <td class="px-3 py-2 font-medium border">${escapeHtml(ml.label)}<span class="text-[10px] text-gray-400">${arrow}</span></td>
                ${cells}
            </tr>`;
        }).join("");
        document.getElementById("pfCompareTableBody").innerHTML = rows;

        // Skipped
        const skippedEl = document.getElementById("pfCompareSkipped");
        if ((data.skipped || []).length > 0) {
            skippedEl.innerHTML = `⚠️ Bỏ qua ${data.skipped.length} dự án: ${data.skipped.map(s => `${s.slug} (${s.reason})`).join(", ")}`;
        } else {
            skippedEl.innerHTML = "";
        }
    }

    async function exportCompare() {
        if (!_compareState) {
            showToast("Chưa có kết quả compare", "red");
            return;
        }
        try {
            const r = await fetch("/api/portfolio/compare/export", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ slugs: _compareState.slugs }),
            });
            if (!r.ok) {
                const err = await r.json();
                showToast(err.error || "Lỗi xuất Excel", "red");
                return;
            }
            const blob = await r.blob();
            const url = URL.createObjectURL(blob);
            const cd = r.headers.get("Content-Disposition") || "";
            const nameMatch = cd.match(/filename[^;=\n]*=([^;\n]*)/);
            const fname = nameMatch ? nameMatch[1].replace(/["']/g, "").trim() : "Portfolio_Compare.xlsx";
            const a = document.createElement("a");
            a.href = url;
            a.download = fname;
            a.click();
            URL.revokeObjectURL(url);
            showToast(`Đã tải: ${fname}`);
        } catch (err) {
            showToast("Lỗi: " + err.message, "red");
        }
    }

    // ============================================================
    // Level 3: ROLLUP DASHBOARD
    // ============================================================

    async function openRollup(slugs = null) {
        // Đóng project manager modal
        const pm = document.getElementById("projectManagerModal");
        if (pm && !pm.classList.contains("hidden")) {
            pm.classList.add("hidden");
            pm.classList.remove("flex");
        }
        const modal = document.getElementById("portfolioRollupModal");
        modal.classList.remove("hidden");
        modal.classList.add("flex");
        document.getElementById("pfRollupSubtitle").textContent = "⏳ Đang tổng hợp…";
        document.getElementById("pfRollupSummary").innerHTML = "";
        document.getElementById("pfRollupTable").innerHTML = "";
        document.getElementById("pfRollupSkipped").innerHTML = "";
        _destroyRollupCharts();

        try {
            let url = "/api/portfolio/rollup";
            if (slugs && slugs.length) {
                url += "?slugs=" + slugs.map(encodeURIComponent).join(",");
            }
            const r = await fetch(url);
            if (r.status === 404) {
                const err = await r.json();
                document.getElementById("pfRollupSubtitle").textContent = err.error || "Không có project nào có file";
                return;
            }
            if (!r.ok) {
                document.getElementById("pfRollupSubtitle").textContent = "Lỗi tải rollup";
                return;
            }
            const data = await r.json();
            _rollupState = { slugs, data };
            _renderRollup(data);
        } catch (err) {
            document.getElementById("pfRollupSubtitle").textContent = "Lỗi: " + err.message;
        }
    }

    function closeRollup() {
        const modal = document.getElementById("portfolioRollupModal");
        modal.classList.add("hidden");
        modal.classList.remove("flex");
        _destroyRollupCharts();
    }

    function _renderRollup(data) {
        const s = data.metrics.summary || {};
        const per = data.per_project || [];

        document.getElementById("pfRollupSubtitle").textContent =
            `Aggregated ${data.projects_count} dự án · ${s.total_functions || 0} function · Tiến độ TB ${s.overall_progress_pct || 0}% (weighted)`;

        // Summary cards
        const cards = [
            { label: "Số dự án", value: data.projects_count, icon: "🗂️", color: "border-teal-500" },
            { label: "Tổng function", value: s.total_functions || 0, icon: "📋", color: "border-blue-500" },
            { label: "Tiến độ (weighted)", value: (s.overall_progress_pct || 0) + "%", icon: "✅", color: "border-green-500" },
            { label: "Overdue", value: s.total_overdue || 0, icon: "⚠️", color: "border-red-500" },
            { label: "Chưa PIC", value: s.unassigned_count || 0, icon: "🚨", color: "border-orange-500" },
            { label: "High risk", value: s.high_risk_count || 0, icon: "⚡", color: "border-rose-500" },
        ];
        document.getElementById("pfRollupSummary").innerHTML = cards.map(c => `
            <div class="bg-white dark:bg-slate-800 rounded-lg shadow p-3 border-l-4 ${c.color}">
                <div class="text-2xl">${c.icon}</div>
                <div class="text-xl font-bold text-gray-800 dark:text-gray-100">${escapeHtml(String(c.value))}</div>
                <div class="text-gray-500 text-xs">${c.label}</div>
            </div>
        `).join("");

        // Bảng per-project
        document.getElementById("pfRollupTable").innerHTML = per.map(p => `
            <tr class="border-b hover:bg-gray-50 dark:hover:bg-slate-700">
                <td class="px-2 py-2 font-medium">${escapeHtml(p.name)} <span class="text-xs text-gray-400">(${escapeHtml(p.slug)})</span></td>
                <td class="px-2 py-2 text-right">${p.total}</td>
                <td class="px-2 py-2 text-right"><span class="font-mono">${p.progress_pct}%</span></td>
                <td class="px-2 py-2 text-right ${p.overdue > 0 ? 'text-red-600 font-semibold' : ''}">${p.overdue}</td>
                <td class="px-2 py-2 text-right ${p.unassigned > 0 ? 'text-orange-600' : ''}">${p.unassigned}</td>
                <td class="px-2 py-2 text-right ${p.high_risk > 0 ? 'text-rose-600' : ''}">${p.high_risk}</td>
            </tr>
        `).join("");

        // Skipped
        if ((data.skipped || []).length > 0) {
            document.getElementById("pfRollupSkipped").innerHTML =
                `⚠️ Bỏ qua ${data.skipped.length} dự án: ${data.skipped.map(s => `${s.slug} (${s.reason})`).join(", ")}`;
        }

        // 2 charts — đợi modal layout xong (tránh canvas 0×0 trong flex modal)
        _renderRollupCharts(per);
    }

    /** Lấy context 2d cho canvas rollup, destroy chart cũ nếu có. */
    function _getRollupCanvas(id) {
        if (chartInstances[id]) {
            try { chartInstances[id].destroy(); } catch (e) { /* ignore */ }
            delete chartInstances[id];
        }
        const el = document.getElementById(id);
        if (!el) return null;
        return el.getContext("2d");
    }

    function _renderRollupCharts(per) {
        _destroyRollupCharts();
        if (!per || per.length === 0) return;

        // Double rAF: đảm bảo .chart-box đã có height sau khi modal hiện + summary cards render
        requestAnimationFrame(() => {
            requestAnimationFrame(() => _renderRollupChartsNow(per));
        });
    }

    function _renderRollupChartsNow(per) {
        const labels = per.map(p => p.name);

        // Chart 1: Progress theo project
        const ctx1 = _getRollupCanvas("pfRollupProgressChart");
        if (ctx1) {
            _rollupCharts.progress = createChart(ctx1, "bar", {
                labels,
                datasets: [{
                    label: "Tiến độ (%)",
                    data: per.map(p => Number(p.progress_pct) || 0),
                    backgroundColor: per.map(p => {
                        const pct = Number(p.progress_pct) || 0;
                        if (pct >= 80) return "#22c55e";
                        if (pct >= 50) return "#3b82f6";
                        if (pct >= 25) return "#f59e0b";
                        return "#ef4444";
                    }),
                }],
            }, {
                plugins: {
                    legend: { display: false },
                    datalabels: {
                        display: true,
                        anchor: "end", align: "end",
                        formatter: (v) => v + "%",
                        font: { size: 11, weight: "bold" },
                    },
                },
                scales: {
                    y: { beginAtZero: true, max: 100, ticks: { callback: (v) => v + "%" } },
                },
            });
            try { _rollupCharts.progress.resize(); } catch (e) { /* ignore */ }
        }

        // Chart 2: Overdue vs On-time stacked
        const ctx2 = _getRollupCanvas("pfRollupOverdueChart");
        if (ctx2) {
            _rollupCharts.overdue = createChart(ctx2, "bar", {
                labels,
                datasets: [
                    {
                        label: "On-time",
                        data: per.map(p => Number(p.on_time) || 0),
                        backgroundColor: "#22c55e",
                    },
                    {
                        label: "Overdue",
                        data: per.map(p => Number(p.overdue) || 0),
                        backgroundColor: "#ef4444",
                    },
                ],
            }, {
                plugins: {
                    legend: { position: "bottom" },
                    datalabels: {
                        display: true,
                        color: "white",
                        font: { size: 10, weight: "bold" },
                        formatter: (v) => v > 0 ? v : "",
                    },
                },
                scales: {
                    x: { stacked: true },
                    y: { stacked: true, beginAtZero: true },
                },
            });
            try { _rollupCharts.overdue.resize(); } catch (e) { /* ignore */ }
        }
    }

    function _destroyRollupCharts() {
        ["pfRollupProgressChart", "pfRollupOverdueChart"].forEach(id => {
            if (chartInstances[id]) {
                try { chartInstances[id].destroy(); } catch (e) { /* ignore */ }
                delete chartInstances[id];
            }
        });
        Object.values(_rollupCharts).forEach(c => {
            try { c.destroy(); } catch (e) { /* ignore */ }
        });
        _rollupCharts = {};
    }

    // ---- Rollup project picker (subset filter) ----

    function openRollupPicker() {
        const picker = document.getElementById("pfRollupProjectPicker");
        picker.classList.toggle("hidden");
        if (!picker.classList.contains("hidden")) {
            const currentSlugs = _rollupState?.data?.per_project?.map(p => p.slug) || [];
            document.getElementById("pfRollupCheckboxes").innerHTML = allProjects.map(p => `
                <label class="flex items-center gap-2 border rounded px-2 py-1 cursor-pointer hover:bg-teal-50">
                    <input type="checkbox" class="pf-rollup-cb" value="${escapeHtml(p.slug)}"
                           ${currentSlugs.includes(p.slug) ? 'checked' : ''} />
                    <span class="text-sm">${escapeHtml(p.name)}</span>
                </label>
            `).join("");
        }
    }

    function applyRollupFilter() {
        const slugs = Array.from(document.querySelectorAll(".pf-rollup-cb:checked"))
            .map(cb => cb.value);
        document.getElementById("pfRollupProjectPicker").classList.add("hidden");
        openRollup(slugs);
    }

    function clearRollupFilter() {
        document.getElementById("pfRollupProjectPicker").classList.add("hidden");
        openRollup(null);
    }

    // ============================================================
    // PUBLIC API
    // ============================================================
    return {
        initSearchBox,
        goToResult,
        openCompareModal,
        closeCompareModal,
        runCompare,
        exportCompare,
        _updateCompareHint,      // dùng cho onchange trong HTML
        openRollup,
        closeRollup,
        openRollupPicker,
        applyRollupFilter,
        clearRollupFilter,
    };
})();

// ==== Global wrappers để HTML onclick gọi được ngắn gọn ====
function openPortfolioCompareModal() { Portfolio.openCompareModal(); }
function closePortfolioCompareModal() { Portfolio.closeCompareModal(); }
function runPortfolioCompare() { Portfolio.runCompare(); }
function exportPortfolioCompare() { Portfolio.exportCompare(); }
function openPortfolioRollup() { Portfolio.openRollup(); }
function closePortfolioRollup() { Portfolio.closeRollup(); }
function openPfRollupProjectPicker() { Portfolio.openRollupPicker(); }
function applyPfRollupFilter() { Portfolio.applyRollupFilter(); }
function clearPfRollupFilter() { Portfolio.clearRollupFilter(); }

// Init search box khi DOM ready (đảm bảo chạy sau existing DOMContentLoaded)
if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", () => Portfolio.initSearchBox());
} else {
    Portfolio.initSearchBox();
}

// ========================================================================
// SIDEBAR ẩn/hiện (Task 1)
// Hai trạng thái ĐỘC LẬP:
//   - class "hidden"    → chưa có data (chưa upload / chưa load project)
//   - class "collapsed" → user chủ động ẩn, lưu ở localStorage
// ========================================================================

const SIDEBAR_COLLAPSE_KEY = "sidebarCollapsed";

/** Đọc preference collapse của user (default: expand). */
function isSidebarCollapsed() {
    return localStorage.getItem(SIDEBAR_COLLAPSE_KEY) === "1";
}

/** Áp trạng thái collapse lên sidebar + đổi icon nút toggle. */
function applySidebarCollapsed(collapsed) {
    const nav = document.getElementById("sidebarNav");
    const btn = document.getElementById("btnToggleSidebar");
    if (nav) nav.classList.toggle("collapsed", collapsed);
    if (btn) {
        btn.textContent = collapsed ? "☰" : "◀";
        btn.title = collapsed ? "Hiện menu section" : "Ẩn menu section";
        btn.setAttribute("aria-expanded", collapsed ? "false" : "true");
    }
}

/**
 * Gọi sau khi có data: bỏ "hidden" cho sidebar + nút toggle,
 * rồi áp lại preference collapse đã lưu.
 */
function showSidebarChrome() {
    const nav = document.getElementById("sidebarNav");
    const btn = document.getElementById("btnToggleSidebar");
    if (nav) nav.classList.remove("hidden");
    if (btn) btn.classList.remove("hidden");
    applySidebarCollapsed(isSidebarCollapsed());
    attachSectionHelp();
}

/** Click nút toggle → đảo trạng thái + persist. */
function toggleSidebar() {
    const collapsed = !isSidebarCollapsed();
    localStorage.setItem(SIDEBAR_COLLAPSE_KEY, collapsed ? "1" : "0");
    applySidebarCollapsed(collapsed);
}

// ========================================================================
// CHART HELP (Task 2) — nút "?" mỗi section + popover giải thích
// Nội dung bám logic thật của analyzer/ (không copy doc cũ).
// ========================================================================

const CHART_HELP = {
    "section-summary": {
        title: "📋 Tổng quan dự án (Summary cards)",
        meaning: "6 chỉ số sức khoẻ dự án ở mức cao nhất: tổng chức năng, tiến độ, trễ deadline, chưa có PIC, high-risk, số module.",
        logic: "Tiến độ = % function có Status <b>Closed</b> ở phase cuối cùng. Card Trễ và Chưa PIC đếm <b>function unique</b>; số nhỏ trong ngoặc là số record phase-level (1 function có thể trễ ở nhiều phase). High-risk = function có Risk Score ≥ 50.",
        example: "375 chức năng, 44 function trễ nhưng 74 record phase → card hiện “44” và “(74 phase)”.",
        note: "Các card đổi theo Global filter (Module / Quy trình / PIC) đang bật."
    },
    "section-compare": {
        title: "📊 So sánh với snapshot trước",
        meaning: "Đo thay đổi giữa 2 lần upload: tiến độ, overdue, function mới phát sinh, tốc độ close.",
        logic: "Lấy 2 snapshot (cũ → mới), tính delta từng chỉ số và delta % Closed theo Module. Overdue tăng hiển thị đỏ (xấu), giảm hiển thị xanh.",
        example: "Tiến độ 42% → 51% (▲9%); overdue 74 → 61 (▼13, xanh).",
        note: "Section này <b>không</b> áp Global filter — luôn dùng full snapshot để velocity đo chuẩn."
    },
    "section-module": {
        title: "📊 Tổng quan theo Module",
        meaning: "Bảng tóm tắt mỗi phân hệ: khối lượng, số quy trình, tiến độ, phase đang làm, số function trễ.",
        logic: "SL = số function trong module; QT = số quy trình unique; Tiến độ = % function Closed ở phase cuối; “Đang ở” = phase active nhiều nhất; Trễ = số function unique có ít nhất 1 phase overdue.",
        example: "Module PR: 60 function, 12 quy trình, 45% Closed, đang ở Dev, 8 function trễ.",
        note: "Module đã xong 100% hiện “✓ Hoàn thành” thay vì tên phase."
    },
    "section-tasktype": {
        title: "📈 Tiến độ theo công việc",
        meaning: "So sánh tiến độ các loại công việc (Phân tích, Lập trình, Cấu hình, Test, UAT, Golive, Tài liệu) giữa các module.",
        logic: "Phase name được map sang task type tự động, sau đó tính % Closed = số function Closed / tổng function của cặp (module, task type).",
        example: "Module HR — Phân tích 90%, Lập trình 40% → analysis xong nhưng dev đang chậm.",
        note: "Cột trống nghĩa là module không có phase thuộc loại công việc đó."
    },
    "section-matrix": {
        title: "🔥 Chi tiết Phase × Module (% Closed)",
        meaning: "Heatmap cho biết cặp Module × Phase nào đang là điểm nghẽn.",
        logic: "Mỗi ô = % function Closed của module đó tại phase đó. Màu: ≥80% xanh, 50–79% vàng, 20–49% cam, <20% đỏ, không có data = xám.",
        example: "Ô (PR, Config UAT) = 20% màu cam → PR chưa cấu hình UAT xong.",
        note: "Click vào ô để mở drill-down danh sách function của ô đó."
    },
    "section-phase": {
        title: "📊 Tiến độ theo Phase",
        meaning: "Số lượng function ở từng trạng thái trong mỗi phase — thấy được phase nào còn nhiều việc mở.",
        logic: "Stacked bar đếm record phase-level theo Status: Closed / Resolved / In-progress / Assigned / Open / Pending / Cancelled.",
        example: "Phase Dev: 120 Closed + 45 In-progress + 30 Open = 195 function có phase Dev.",
        note: "Ô Status chứa số (1, 2, 8…) là lỗi lệch cột Estimate MH nên bị bỏ qua, không tính vào stack."
    },
    "section-pic": {
        title: "👥 Workload theo PIC (Top 15)",
        meaning: "Ai đang gánh nhiều việc nhất và trong đó bao nhiêu việc đang trễ.",
        logic: "Đếm <b>task phase-level</b> (1 function × N phase × M người = N×M record), stack theo Closed / In-progress / Assigned / Overdue. Ô PIC nhiều người được tách theo dấu phẩy, chấm phẩy, dấu cộng hoặc xuống dòng.",
        example: "“BaoLQ31+ NhiVN” ở phase Analysis → tính 1 task cho BaoLQ31 và 1 task cho NhiVN.",
        note: "Số này lớn hơn số function vì mỗi phase tính riêng."
    },
    "section-priority": {
        title: "🎯 Priority",
        meaning: "Cơ cấu mức ưu tiên của toàn bộ function trong phạm vi đang lọc.",
        logic: "Đếm function theo giá trị cột Priority (Must-have / Should-have / Could-have…), bỏ ô rỗng và “N/A”.",
        example: "Must-have 120, Should-have 80, Could-have 25 → 53% khối lượng là Must-have.",
        note: "Must-have được cộng +20 điểm trong Risk Score."
    },
    "section-complexity": {
        title: "⚙️ Complexity",
        meaning: "Cơ cấu độ phức tạp — dùng để ước lượng effort và rủi ro kỹ thuật.",
        logic: "Đếm function theo cột Complexity (Low / Medium / High), bỏ ô rỗng.",
        example: "High 40, Medium 150, Low 185 → 40 function cần dev senior.",
        note: "High cộng +15, Medium cộng +5 vào Risk Score."
    },
    "section-fitgap": {
        title: "🔍 FIT / GAP",
        meaning: "Tỉ lệ chức năng dùng được sẵn (FIT) so với phải customize (GAP) theo từng module.",
        logic: "Stacked bar đếm function theo giá trị cột FIT/GAP trong mỗi module; các loại (FIT, GAP, Customization, Pending…) được auto-detect từ dữ liệu.",
        example: "Module PR: 30 FIT + 25 GAP → hơn 45% khối lượng cần customize.",
        note: "GAP nhiều thường kéo theo Estimate MH và rủi ro cao hơn."
    },
    "section-giaidoan": {
        title: "📅 Tiến độ theo Giai đoạn",
        meaning: "So sánh tiến độ các phase giữa những giai đoạn triển khai (Giai đoạn 1 / 2 / 3).",
        logic: "Nhóm function theo cột “Giai đoạn”, mỗi giai đoạn là một nhóm cột, giá trị = % Closed của từng phase.",
        example: "Giai đoạn 1 — Analysis 100%, Dev 70%; Giai đoạn 2 — Analysis 40% → GĐ2 mới bắt đầu.",
        note: "Section tự ẩn nếu file không có cột “Giai đoạn”."
    },
    "section-unassigned": {
        title: "🚨 Task chưa có PIC phụ trách",
        meaning: "Việc còn đang mở nhưng không có ai chịu trách nhiệm — nguồn chậm tiến độ phổ biến nhất.",
        logic: "Lấy record phase-level có Status thuộc Open / Assigned / In-progress / Resolved / Pending nhưng ô PIC rỗng. Sắp xếp: đang trễ trước → Must-have trước → trễ nhiều ngày trước.",
        example: "PR-012 phase Dev, Status Open, PIC rỗng, deadline 10/07 → vừa chưa gán vừa đã trễ, tô đỏ.",
        note: "Dòng đỏ = chưa PIC và đã trễ; cam = chưa PIC và Must-have."
    },
    "section-duration": {
        title: "⏱️ Phân tích Duration",
        meaning: "Phát hiện phase kéo dài bất thường so với ngưỡng cho phép.",
        logic: "Có cả Start và End → duration “kế hoạch” = End − Start. Chỉ có Start và chưa Closed → duration “đang chạy” = hôm nay − Start. Chỉ giữ record vượt ngưỡng (mặc định 3 ngày, điều chỉnh bằng slider).",
        example: "Start 01/07, End 15/07 → 14 ngày, vượt ngưỡng 3 ngày nên vào danh sách.",
        note: "Box plot theo phase và scatter Duration vs Estimate MH giúp nhận ra phase nào ước lượng lệch thực tế."
    },
    "section-stalled": {
        title: "🔄 Pipeline / Task bị Đình trệ",
        meaning: "Function bị kẹt giữa hai phase: phase trước đã xong nhưng phase sau chưa ai bắt đầu.",
        logic: "Với mỗi cặp phase liền nhau: phase trước Status Closed, phase sau chưa có tiến triển → tính số ngày chờ = hôm nay − ngày End của phase trước.",
        example: "HR-045 Analysis Closed 01/07, Dev vẫn Open → chờ 27 ngày, cần escalate.",
        note: "Chờ > 7 ngày tô cam, > 14 ngày tô đỏ. Danh sách transitions cho biết chặng chuyển giao nào tắc nhiều nhất."
    },
    "section-risk": {
        title: "⚡ Top 20 Functions rủi ro cao",
        meaning: "Xếp hạng function cần chú ý trước, gộp nhiều yếu tố rủi ro thành một điểm 0–100.",
        logic: "Cộng điểm: Must-have +20 / Should-have +10; Complexity High +15 / Medium +5; có phase overdue +20; thêm +10 mỗi 7 ngày trễ (tối đa +30); phase active chưa có PIC +15; duration vượt ngưỡng +10; bị stalled +10; có ghi chú Risk/Blocker +5. Tổng bị chặn ở 100.",
        example: "Must-have (20) + High (15) + overdue 15 ngày (20+20) + chưa PIC (15) = 90 điểm.",
        note: "Card “High-risk” ở Summary đếm function từ 50 điểm trở lên."
    },
    "section-effort": {
        title: "📊 Phân tích Effort (Man-hour)",
        meaning: "Tổng hợp Estimate Man-hour theo Module × Phase và theo từng PIC để thấy khối lượng còn lại.",
        logic: "Chỉ lấy phase có Estimate MH > 0. MH của phase có Status <b>Closed</b> được cộng vào “đã Closed”, phần còn lại là “còn lại”. Nếu một phase có nhiều PIC thì MH chia đều cho từng người.",
        example: "Module PR phase Analysis có 10 chức năng × 8 MH = 80 MH; phase đó 2 người phụ trách → mỗi người 4 MH mỗi chức năng.",
        note: "Ô Estimate MH bị ghi lệch sang cột Status sẽ được parser bỏ qua nên không cộng vào tổng."
    },
    "section-process": {
        title: "🏷️ Phân tích theo Quy trình",
        meaning: "Xem tiến độ theo nghiệp vụ (quy trình) thay vì theo module kỹ thuật.",
        logic: "Nhóm function theo cột “Quy trình”, tính số function, % Closed, số overdue và top PIC chính. Chiều rộng ô tỉ lệ với số function; màu theo % Closed.",
        example: "Quy trình “Tính lương”: 45 function, 62% Closed, 5 overdue.",
        note: "Section tự ẩn nếu file không có cột “Quy trình”."
    },
    "section-gantt": {
        title: "📅 Timeline (Gantt-style)",
        meaning: "Trực quan lịch chạy thực tế: mỗi function một dòng, các phase là segment liên tiếp.",
        logic: "Segment vẽ từ Start đến End của từng phase; vạch dọc đỏ là hôm nay. Segment đỏ khi có overdue, xanh khi đã Closed, còn lại theo mức % hoàn thành.",
        example: "Phase Dev 01/07 → 20/07 mà hôm nay 28/07 và chưa Closed → segment nằm bên trái vạch đỏ và tô đỏ.",
        note: "Trên 100 function sẽ có banner cảnh báo; nên lọc Module hoặc fold nhóm để xem cho nhẹ."
    },
    "section-overdue": {
        title: "⚠️ Danh sách trễ deadline",
        meaning: "Danh sách chi tiết mọi phase đã quá hạn, dùng để họp và giao việc.",
        logic: "Một phase là overdue khi có ngày End, End < hôm nay và Status <b>không</b> phải Closed hoặc Cancelled. Số ngày trễ = hôm nay − End. Sắp xếp trễ nhiều ngày trước.",
        example: "Deadline 10/07, hôm nay 28/07, Status In-progress → trễ 18 ngày, tô đỏ.",
        note: "Status <b>Resolved vẫn tính là trễ</b> (đã xử lý nhưng chưa được verify). Mỗi phase là một dòng nên một function có thể xuất hiện nhiều lần."
    },
    "section-digest": {
        title: "📈 Weekly Digest (Báo cáo tuần)",
        meaning: "Bản tóm tắt in được cho báo cáo tuần, sinh tự động sau khi so sánh 2 snapshot.",
        logic: "Dựa trên delta giữa 2 snapshot: số function được Closed, function mới phát sinh, tốc độ close mỗi ngày và ước lượng số ngày còn lại, kèm top module tiến bộ / cần chú ý.",
        example: "7 ngày: Closed 25 function → ~3.6 function/ngày; còn 180 function → ước tính ~50 ngày.",
        note: "Cần ít nhất 2 snapshot; bấm “In / Xuất PDF” để lấy bản in gọn."
    }
};

let _chartHelpOpenKey = null;

/**
 * Inject nút "?" vào mọi tiêu đề có data-help (chạy được nhiều lần, idempotent).
 * Section-summary dùng header nhỏ riêng vì grid card không có h2/h3.
 */
function attachSectionHelp() {
    document.querySelectorAll("[data-help]").forEach(el => {
        const key = el.getAttribute("data-help");
        if (!CHART_HELP[key]) return;
        if (el.querySelector(".chart-help-btn")) return;   // đã inject rồi

        const btn = document.createElement("button");
        btn.type = "button";
        btn.className = "chart-help-btn";
        btn.textContent = "?";
        btn.title = "Giải thích cách tính";
        btn.setAttribute("aria-expanded", "false");
        btn.addEventListener("click", (e) => {
            e.stopPropagation();
            e.preventDefault();
            toggleChartHelp(key, btn);
        });
        el.appendChild(btn);
    });
}

/** Bấm lại nút đang mở thì đóng, ngược lại mở nội dung mới. */
function toggleChartHelp(key, btn) {
    if (_chartHelpOpenKey === key) {
        closeChartHelp();
        return;
    }
    openChartHelp(key, btn);
}

/** Mở popover, neo cạnh nút "?" và tự né mép viewport. */
function openChartHelp(key, btn) {
    const help = CHART_HELP[key];
    const pop = document.getElementById("chartHelpPopover");
    if (!help || !pop) return;

    document.getElementById("chartHelpTitle").textContent = help.title;

    const blocks = [
        ["Ý nghĩa", help.meaning],
        ["Logic tính", help.logic],
        ["Ví dụ", help.example],
        ["Lưu ý", help.note],
    ];
    document.getElementById("chartHelpBody").innerHTML = blocks
        .filter(([, value]) => value)
        .map(([label, value]) => `<div class="help-block"><span class="help-label">${label}</span>${value}</div>`)
        .join("");

    pop.classList.remove("hidden");

    // Neo popover: mặc định dưới nút, lật lên trên nếu tràn đáy
    const r = btn.getBoundingClientRect();
    const pr = pop.getBoundingClientRect();
    let left = r.left;
    if (left + pr.width > window.innerWidth - 12) left = window.innerWidth - pr.width - 12;
    if (left < 12) left = 12;
    let top = r.bottom + 8;
    if (top + pr.height > window.innerHeight - 12) top = Math.max(12, r.top - pr.height - 8);
    pop.style.left = `${left}px`;
    pop.style.top = `${top}px`;

    document.querySelectorAll(".chart-help-btn").forEach(b => b.setAttribute("aria-expanded", "false"));
    btn.setAttribute("aria-expanded", "true");
    _chartHelpOpenKey = key;
}

/** Đóng popover. Return true nếu vừa đóng (để Escape biết đã xử lý). */
function closeChartHelp() {
    const pop = document.getElementById("chartHelpPopover");
    if (!pop || pop.classList.contains("hidden")) return false;
    pop.classList.add("hidden");
    document.querySelectorAll(".chart-help-btn").forEach(b => b.setAttribute("aria-expanded", "false"));
    _chartHelpOpenKey = null;
    return true;
}

/** Wire event cho nút toggle sidebar + popover help (Escape đã wire ở DOMContentLoaded chính). */
function initSidebarAndHelp() {
    const btn = document.getElementById("btnToggleSidebar");
    if (btn) btn.addEventListener("click", toggleSidebar);

    const closeBtn = document.getElementById("chartHelpClose");
    if (closeBtn) closeBtn.addEventListener("click", closeChartHelp);

    // Click ngoài popover và ngoài nút "?" → đóng
    document.addEventListener("click", (e) => {
        if (e.target.closest("#chartHelpPopover") || e.target.closest(".chart-help-btn")) return;
        closeChartHelp();
    });

    // Đổi kích thước cửa sổ khi popover đang mở dễ làm lệch vị trí → đóng cho gọn
    window.addEventListener("resize", closeChartHelp);

    applySidebarCollapsed(isSidebarCollapsed());
    attachSectionHelp();
}

if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initSidebarAndHelp);
} else {
    initSidebarAndHelp();
}

// ========================================================================
// PHASE 4 — BURNDOWN + SLA (lazy-fetch, gọi sau applyDashboardResponse)
// ========================================================================

/** Endpoint helper — trả URL cho API của project hiện tại (null nếu chưa switch). */
function _apiUrl(pathSuffix) {
    if (!currentProjectSlug) return null;
    return `/api/projects/${currentProjectSlug}/${pathSuffix}`;
}

async function loadBurndownAndSLA() {
    if (!currentProjectSlug || !metricsData) return;
    // Build filter query string chung để mọi endpoint nhận cùng global filter.
    // Upload-history KHÔNG cần filter (là data-quality info per project).
    const qsFilter = _buildFilterQuery();
    try {
        const safeJson = (path, withFilter = true) => {
            const url = _apiUrl(path) + (withFilter && qsFilter ? "?" + qsFilter : "");
            return fetch(url).then(r => r.ok ? r.json() : null).catch(() => null);
        };
        const [bd, sla, cap, slow, deps, bsl, hist] = await Promise.all([
            safeJson("burndown"),
            safeJson("sla"),
            safeJson("capacity-load"),
            safeJson("slow-heatmap"),
            safeJson("dependency-blockers"),
            safeJson("baseline-variance"),
            safeJson("upload-history", false),
        ]);
        renderBurndownSection(bd);
        renderSLASection(sla);
        renderCapacitySection(cap);
        renderSlowHeatmapSection(slow);
        renderDependencySection(deps);
        renderBaselineSection(bsl);
        renderUploadHistorySection(hist);
    } catch (err) {
        console.error("[loadBurndownAndSLA]", err);
    }
}

/** Build query string cho filter chung — dùng cho endpoint P4/P5/P6. */
function _buildFilterQuery() {
    const p = new URLSearchParams();
    if (globalFilters.modules.length) p.set("module", globalFilters.modules.join(","));
    if (globalFilters.processes.length) p.set("process", globalFilters.processes.join(","));
    if (globalFilters.pics.length) p.set("pic", globalFilters.pics.join(","));
    return p.toString();
}

function renderBurndownSection(bd) {
    const section = document.getElementById("section-burndown");
    if (!section) return;
    if (!bd || !bd.weeks || bd.weeks.length === 0) {
        section.classList.add("hidden");
        return;
    }
    section.classList.remove("hidden");
    document.getElementById("burndownVelocity").textContent = bd.velocity_4w ?? "—";
    document.getElementById("burndownTotal").textContent = bd.total_closed_events ?? "—";

    const ctx = getCanvas("chartBurndown");
    if (!ctx) return;
    createChart(ctx, "bar", {
        labels: bd.weeks.map(w => w.slice(5)),
        datasets: [
            {
                type: "bar",
                label: "Closed / tuần",
                data: bd.closed_per_week,
                backgroundColor: "rgba(59, 130, 246, 0.7)",
                borderRadius: 3,
                yAxisID: "y",
                order: 2,
            },
            {
                type: "line",
                label: "Lũy kế Closed",
                data: bd.cumulative,
                borderColor: "#10b981",
                backgroundColor: "rgba(16, 185, 129, 0.15)",
                borderWidth: 2,
                pointRadius: 2,
                fill: true,
                yAxisID: "y1",
                order: 1,
                tension: 0.25,
            },
        ],
    }, {
        plugins: {
            legend: { position: "top", labels: { boxWidth: 12, font: { size: 11 } } },
            tooltip: { mode: "index", intersect: false },
            datalabels: { display: false },
        },
        scales: {
            y: { beginAtZero: true, position: "left", title: { display: true, text: "Closed/tuần" } },
            y1: { beginAtZero: true, position: "right", grid: { display: false }, title: { display: true, text: "Lũy kế" } },
            x: { ticks: { font: { size: 10 } } },
        },
    });
}

// State cache — cần thiết vì pager click gọi lại render function bằng closure
let _lastSlaData = null;
let _lastCapacityData = null;
let _lastSlowData = null;
let _lastDepsData = null;
let _lastBaselineData = null;
let _lastHistoryData = null;
let _lastFitgapData = null;   // Task 2 — cache để pager re-render


// ========================================================================
// Task 2 — FIT/GAP Dashboard: fetch analytics + render summary/charts/aging.
// Chart instances cached ở chartInstances (theo canvas id) để destroy khi
// re-render (đổi filter / đổi aging threshold).
// ========================================================================

async function loadFitgapDashboard() {
    const thrInput = document.getElementById("fitgapAgingThr");
    const thr = thrInput ? parseInt(thrInput.value, 10) || 14 : 14;
    const qs = new URLSearchParams();
    qs.set("aging_threshold_days", thr);
    // Apply global filter chung với các section khác
    if (globalFilters.modules.length) qs.set("module", globalFilters.modules.join(","));
    if (globalFilters.processes.length) qs.set("process", globalFilters.processes.join(","));
    if (globalFilters.pics.length) qs.set("pic", globalFilters.pics.join(","));

    try {
        const url = `/api/projects/${currentProjectSlug}/fitgap-analytics?${qs.toString()}`;
        const r = await fetch(url);
        if (!r.ok) {
            console.warn("[fitgap] fetch failed", r.status);
            return;
        }
        const data = await r.json();
        _lastFitgapData = data;
        renderFitgapSection(data);
    } catch (e) {
        console.error("[loadFitgapDashboard]", e);
    }
}

function renderFitgapSection(data) {
    const section = document.getElementById("section-fitgap-dashboard");
    if (!section || !data) return;
    const s = data.summary || {};

    // Ẩn section nếu không có function nào (parser chưa detect được cột FIT/GAP,
    // hoặc file chưa có data). Tránh hiển thị section rỗng gây rối UI.
    if ((s.total || 0) === 0) {
        section.classList.add("hidden");
        return;
    }
    section.classList.remove("hidden");

    // --- Summary cards ---
    const cardsWrap = document.getElementById("fitgapSummaryCards");
    if (cardsWrap) {
        const gapPct = s.total ? Math.round((s.gap / s.total) * 100) : 0;
        cardsWrap.innerHTML = [
            _fitgapCard("Tổng function", s.total, "bg-slate-100 text-slate-800"),
            _fitgapCard("FIT", s.fit, "bg-green-100 text-green-800"),
            _fitgapCard(`GAP (${gapPct}%)`, s.gap, "bg-orange-100 text-orange-800"),
            _fitgapCard("GAP đã đóng", s.gap_closed, "bg-emerald-100 text-emerald-800"),
            _fitgapCard("GAP đang mở", s.gap_open, "bg-amber-100 text-amber-800"),
            _fitgapCard(`Aging > ${s.aging_threshold_days}d`, s.gap_open_aging, "bg-red-100 text-red-800"),
        ].join("");
    }

    // --- 3 bar charts ---
    _fitgapRenderStackedBar("chartFitgapByModule",  data.by_module,   "module");
    _fitgapRenderStackedBar("chartFitgapByProcess", data.by_process,  "process");
    _fitgapRenderStackedBar("chartFitgapByPriority", data.by_priority, "priority");

    // --- Aging table ---
    const lbl = document.getElementById("fitgapAgingThrLabel");
    if (lbl) lbl.textContent = s.aging_threshold_days;
    _renderFitgapAgingTable(data.aging_items || []);
}

function _fitgapCard(label, value, cls) {
    return `<div class="rounded-lg border dark:border-slate-700 p-2 ${cls}">
        <div class="text-[10px] uppercase font-semibold opacity-70">${escapeHtml(label)}</div>
        <div class="text-xl font-bold mt-0.5">${value ?? 0}</div>
    </div>`;
}

function _fitgapRenderStackedBar(canvasId, rows, keyField) {
    const ctx = getCanvas(canvasId);
    if (!ctx || !rows) return;
    // Giữ top 8 để chart đọc được — chart phải responsive với file lớn
    const items = rows.slice(0, 8);
    const labels = items.map(r => (r[keyField] || "—").length > 22
        ? r[keyField].slice(0, 20) + "…"
        : (r[keyField] || "—"));
    createChart(ctx, "bar", {
        labels,
        datasets: [
            {
                label: "FIT",
                data: items.map(r => r.fit || 0),
                backgroundColor: "rgba(34, 197, 94, 0.75)",
                borderRadius: 0,
                borderSkipped: false,
                stack: "fg",
            },
            {
                label: "GAP",
                data: items.map(r => r.gap || 0),
                backgroundColor: "rgba(249, 115, 22, 0.85)",
                borderRadius: 0,
                borderSkipped: false,
                stack: "fg",
            },
        ],
    }, {
        indexAxis: "y",
        plugins: {
            legend: { position: "bottom", labels: { boxWidth: 10, font: { size: 10 } } },
            tooltip: {
                mode: "index", intersect: false,
                callbacks: {
                    afterLabel: (ctx) => {
                        const r = items[ctx.dataIndex];
                        return `Tổng: ${r.total} · %GAP: ${r.pct_gap}%`;
                    },
                },
            },
            datalabels: { display: false },
        },
        scales: {
            x: { beginAtZero: true, stacked: true, ticks: { font: { size: 10 } } },
            y: { stacked: true, ticks: { font: { size: 10 } } },
        },
    });
}

function _renderFitgapAgingTable(items) {
    const tbody = document.getElementById("fitgapAgingBody");
    const countLbl = document.getElementById("fitgapAgingCount");
    if (!tbody) return;
    if (countLbl) countLbl.textContent = `(${items.length} function)`;

    if (items.length === 0) {
        tbody.innerHTML = `<tr><td colspan="7" class="px-2 py-4 text-center text-gray-400 italic">
            ✓ Không có GAP nào aging vượt ngưỡng
        </td></tr>`;
        document.getElementById("fitgapPagerWrap").innerHTML = "";
        return;
    }
    const { pageItems } = _pageSlice("fitgap", items);
    tbody.innerHTML = pageItems.map(it => {
        const d = it.aging_days;
        const rowCls =
            d == null           ? "" :
            d >= 30             ? "bg-red-50 dark:bg-red-900/20" :
            d >= 21             ? "bg-orange-50 dark:bg-orange-900/20" :
            /* >=14 */            "bg-yellow-50 dark:bg-yellow-900/20";
        const agingBadge =
            d == null           ? `<span class="text-gray-400">N/A</span>` :
            d >= 30             ? `<span class="text-red-700 font-bold">${d}d</span>` :
            d >= 21             ? `<span class="text-orange-700 font-semibold">${d}d</span>` :
                                  `<span class="text-yellow-700">${d}d</span>`;
        const picStr = (it.pics || []).slice(0, 3).join(", ")
            + ((it.pics || []).length > 3 ? ` +${it.pics.length - 3}` : "");
        return `<tr class="border-b dark:border-slate-700 ${rowCls} hover:bg-blue-50 dark:hover:bg-slate-700 cursor-pointer"
                    onclick="openFunctionDetail(${it.row_num})">
            <td class="px-2 py-1.5 font-mono">${escapeHtml(it.ma_cn || "—")}</td>
            <td class="px-2 py-1.5">${escapeHtml(it.ten_cn || "")}</td>
            <td class="px-2 py-1.5">${escapeHtml(it.module || "")}</td>
            <td class="px-2 py-1.5">${escapeHtml(it.opened_date || "—")}</td>
            <td class="px-2 py-1.5 text-right">${agingBadge}</td>
            <td class="px-2 py-1.5">${escapeHtml(picStr || "—")}</td>
            <td class="px-2 py-1.5">
                <span class="font-medium">${escapeHtml(it.current_phase || "—")}</span>
                <span class="text-gray-500 text-[11px]"> · ${escapeHtml(it.status || "")}</span>
            </td>
        </tr>`;
    }).join("");
    renderPager("fitgapPagerWrap", "fitgap", items.length,
        () => _renderFitgapAgingTable(items));
}

// ========================================================================
// Task 3 — Function Diff between snapshots.
// Fetch diff, render summary cards + tab bar + table. Tabs share pager
// (pageState.fdiff) — chuyển tab reset page về 1.
// ========================================================================

// Cấu hình tab: id → {label, dataKey trong payload, columns [{key, label, cls}]}
const FDIFF_TABS = [
    {
        id: "added", label: "➕ Mới thêm", dataKey: "added",
        countKey: "added",
        columns: [
            { key: "ma_cn", label: "Mã CN", cls: "font-mono" },
            { key: "ten_cn", label: "Tên chức năng", cls: "" },
            { key: "module", label: "Module", cls: "" },
            { key: "quy_trinh", label: "Quy trình", cls: "" },
            { key: "priority", label: "Priority", cls: "" },
            { key: "fit_gap", label: "FIT/GAP", cls: "" },
        ],
    },
    {
        id: "deleted", label: "➖ Bị xoá", dataKey: "deleted",
        countKey: "deleted",
        columns: [
            { key: "ma_cn", label: "Mã CN", cls: "font-mono" },
            { key: "ten_cn", label: "Tên chức năng", cls: "" },
            { key: "module", label: "Module", cls: "" },
            { key: "quy_trinh", label: "Quy trình", cls: "" },
            { key: "priority", label: "Priority", cls: "" },
            { key: "fit_gap", label: "FIT/GAP", cls: "" },
        ],
    },
    {
        id: "pic_changed", label: "👤 Đổi PIC", dataKey: "pic_changed",
        countKey: "pic_changed",
        columns: [
            { key: "ma_cn", label: "Mã CN", cls: "font-mono" },
            { key: "ten_cn", label: "Tên chức năng", cls: "" },
            { key: "module", label: "Module", cls: "" },
            { key: "phase", label: "Phase", cls: "" },
            { key: "old", label: "PIC cũ", cls: "text-red-600" },
            { key: "new", label: "PIC mới", cls: "text-green-700 font-medium" },
        ],
    },
    {
        id: "priority_complexity_changed", label: "🎯 Đổi Priority/Complexity", dataKey: "priority_complexity_changed",
        countKey: "prio_complex_changed",
        columns: [
            { key: "ma_cn", label: "Mã CN", cls: "font-mono" },
            { key: "ten_cn", label: "Tên chức năng", cls: "" },
            { key: "module", label: "Module", cls: "" },
            { key: "field", label: "Field", cls: "font-medium" },
            { key: "old", label: "Cũ", cls: "text-red-600" },
            { key: "new", label: "Mới", cls: "text-green-700 font-medium" },
        ],
    },
    {
        id: "fitgap_changed", label: "🧩 Đổi FIT/GAP", dataKey: "fitgap_changed",
        countKey: "fitgap_changed",
        columns: [
            { key: "ma_cn", label: "Mã CN", cls: "font-mono" },
            { key: "ten_cn", label: "Tên chức năng", cls: "" },
            { key: "module", label: "Module", cls: "" },
            { key: "old", label: "Cũ", cls: "text-red-600" },
            { key: "new", label: "Mới", cls: "text-green-700 font-medium" },
        ],
    },
    {
        id: "phase_status_changed", label: "🔄 Đổi Status phase", dataKey: "phase_status_changed",
        countKey: "status_changed",
        columns: [
            { key: "ma_cn", label: "Mã CN", cls: "font-mono" },
            { key: "ten_cn", label: "Tên chức năng", cls: "" },
            { key: "module", label: "Module", cls: "" },
            { key: "phase", label: "Phase", cls: "" },
            { key: "old", label: "Status cũ", cls: "text-red-600" },
            { key: "new", label: "Status mới", cls: "text-green-700 font-medium" },
        ],
    },
];

let _lastFdiffData = null;
let _fdiffActiveTab = "added";

async function loadFunctionDiff() {
    const sel = document.getElementById("fdiffVsSelect");
    const vs = sel ? (sel.value || "previous") : "previous";
    try {
        const url = `/api/projects/${currentProjectSlug}/function-diff?vs=${encodeURIComponent(vs)}`;
        const r = await fetch(url);
        const section = document.getElementById("section-function-diff");
        if (!section) return;

        if (!r.ok) {
            // 404 = chưa đủ snapshot / snapshot không tồn tại. Show empty state.
            const err = await r.json().catch(() => ({}));
            _renderFdiffEmpty(err);
            return;
        }
        const data = await r.json();
        _lastFdiffData = data;
        _renderFunctionDiff(data);
    } catch (e) {
        console.error("[loadFunctionDiff]", e);
    }
}

function _renderFdiffEmpty(errPayload) {
    const section = document.getElementById("section-function-diff");
    if (!section) return;
    // Nếu chưa upload lần đầu (NO_SNAPSHOT) — ẩn hoàn toàn section, không phiền user
    const code = errPayload && errPayload.code;
    if (code === "NO_SNAPSHOT") {
        section.classList.add("hidden");
        return;
    }
    // SINGLE_SNAPSHOT: hiện section với empty message
    section.classList.remove("hidden");
    document.getElementById("fdiffSummaryCards").innerHTML = "";
    document.getElementById("fdiffTabsWrap").innerHTML = "";
    document.getElementById("fdiffTableHead").innerHTML = "";
    document.getElementById("fdiffTableBody").innerHTML = "";
    document.getElementById("fdiffPagerWrap").innerHTML = "";
    document.getElementById("fdiffHeaderTs").textContent = "—";
    const empty = document.getElementById("fdiffEmptyState");
    const msg = document.getElementById("fdiffEmptyMessage");
    if (empty && msg) {
        empty.classList.remove("hidden");
        msg.textContent = (errPayload && errPayload.error) ||
            "Chưa có snapshot trước để so sánh. Upload file lần 2 để bắt đầu track diff.";
    }
}

function _renderFunctionDiff(data) {
    const section = document.getElementById("section-function-diff");
    if (!section) return;
    section.classList.remove("hidden");
    document.getElementById("fdiffEmptyState").classList.add("hidden");

    // --- Header timestamp + subtitle ---
    const cur = data.current_snapshot || {};
    const prev = data.previous_snapshot || {};
    document.getElementById("fdiffHeaderTs").textContent =
        `[${prev.date || "—"} → ${cur.date || "—"}]`;
    document.getElementById("fdiffSubtitle").textContent =
        `${prev.filename || "—"}  ↔  ${cur.filename || "—"}  ·  `
        + `${data.counts.previous_total} chức năng → ${data.counts.current_total} chức năng`;

    // --- Dropdown "So với" ---
    const sel = document.getElementById("fdiffVsSelect");
    if (sel && Array.isArray(data.available_snapshots)) {
        const currentVal = sel.value || "previous";
        // Rebuild options: previous + tất cả snapshot theo date desc (bỏ snapshot hiện tại - index 0)
        const opts = ['<option value="previous">Snapshot ngay trước</option>'];
        (data.available_snapshots || []).slice(1).forEach(sn => {
            opts.push(`<option value="${escapeHtml(sn.date)}">${escapeHtml(sn.date)} — ${escapeHtml(sn.filename || "")}</option>`);
        });
        sel.innerHTML = opts.join("");
        sel.value = currentVal;
    }

    // --- Summary cards ---
    const c = data.counts || {};
    const cardsWrap = document.getElementById("fdiffSummaryCards");
    cardsWrap.innerHTML = [
        _fdiffCard("+ Mới thêm", c.added, "bg-green-100 text-green-800"),
        _fdiffCard("- Bị xoá", c.deleted, "bg-red-100 text-red-800"),
        _fdiffCard("⇄ Function đổi", c.total_changed, "bg-amber-100 text-amber-800"),
        _fdiffCard("Đổi PIC (bản ghi)", c.pic_changed, "bg-blue-100 text-blue-800"),
        _fdiffCard("Đổi Prio/Complex", c.prio_complex_changed, "bg-purple-100 text-purple-800"),
        _fdiffCard("Đổi Status phase", c.status_changed, "bg-indigo-100 text-indigo-800"),
    ].join("");

    // --- Tabs ---
    _renderFdiffTabs(data);

    // --- Table cho active tab ---
    _renderFdiffTable(data);
}

function _fdiffCard(label, val, cls) {
    return `<div class="rounded-lg border dark:border-slate-700 p-2 ${cls}">
        <div class="text-[10px] uppercase font-semibold opacity-70">${escapeHtml(label)}</div>
        <div class="text-xl font-bold mt-0.5">${val ?? 0}</div>
    </div>`;
}

function _renderFdiffTabs(data) {
    const wrap = document.getElementById("fdiffTabsWrap");
    if (!wrap) return;
    const c = data.counts || {};

    // Nếu tab active không có data → auto switch sang tab đầu tiên có data
    // để user không nhìn "empty table" ngay khi mở
    const activeTabDef = FDIFF_TABS.find(t => t.id === _fdiffActiveTab);
    if (!activeTabDef || (c[activeTabDef.countKey] || 0) === 0) {
        const firstWithData = FDIFF_TABS.find(t => (c[t.countKey] || 0) > 0);
        if (firstWithData) _fdiffActiveTab = firstWithData.id;
    }

    wrap.innerHTML = FDIFF_TABS.map(t => {
        const cnt = c[t.countKey] || 0;
        const isActive = t.id === _fdiffActiveTab;
        const activeCls = isActive
            ? "bg-white dark:bg-slate-800 border-b-2 border-blue-600 text-blue-700 font-semibold"
            : "text-gray-500 hover:text-gray-700 dark:hover:text-gray-200";
        const countBadge = cnt > 0
            ? `<span class="ml-1 text-[10px] px-1.5 py-0.5 rounded-full ${isActive ? 'bg-blue-100 text-blue-700' : 'bg-gray-100 text-gray-500'}">${cnt}</span>`
            : "";
        return `<button onclick="_fdiffSetActiveTab('${t.id}')"
                    class="px-3 py-1.5 text-xs ${activeCls} whitespace-nowrap">
            ${t.label}${countBadge}
        </button>`;
    }).join("");
}

function _fdiffSetActiveTab(tabId) {
    _fdiffActiveTab = tabId;
    pageState.fdiff.page = 1;
    if (_lastFdiffData) {
        _renderFdiffTabs(_lastFdiffData);
        _renderFdiffTable(_lastFdiffData);
    }
}

function _renderFdiffTable(data) {
    const head = document.getElementById("fdiffTableHead");
    const body = document.getElementById("fdiffTableBody");
    const pager = document.getElementById("fdiffPagerWrap");
    if (!head || !body) return;

    const tab = FDIFF_TABS.find(t => t.id === _fdiffActiveTab) || FDIFF_TABS[0];
    const items = (data && data[tab.dataKey]) || [];

    head.innerHTML = tab.columns.map(col =>
        `<th class="px-2 py-2 text-left">${escapeHtml(col.label)}</th>`
    ).join("");

    if (items.length === 0) {
        body.innerHTML = `<tr><td colspan="${tab.columns.length}" class="px-2 py-4 text-center text-gray-400 italic">
            Không có thay đổi nào trong nhóm này
        </td></tr>`;
        pager.innerHTML = "";
        return;
    }
    const { pageItems } = _pageSlice("fdiff", items);
    body.innerHTML = pageItems.map(it => {
        const cells = tab.columns.map(col => {
            const val = it[col.key];
            return `<td class="px-2 py-1.5 ${col.cls}">${escapeHtml(val ?? "—")}</td>`;
        }).join("");
        // Click row → mở function detail (nếu có ma_cn và row_num — hầu hết đều có)
        const rowNum = it.row_num;
        const clickable = rowNum
            ? `onclick="openFunctionDetail(${rowNum})" class="border-b dark:border-slate-700 hover:bg-blue-50 dark:hover:bg-slate-700 cursor-pointer"`
            : `class="border-b dark:border-slate-700"`;
        return `<tr ${clickable}>${cells}</tr>`;
    }).join("");

    renderPager("fdiffPagerWrap", "fdiff", items.length, () => _renderFdiffTable(data));
}

async function exportFunctionDiff() {
    const sel = document.getElementById("fdiffVsSelect");
    const vs = sel ? (sel.value || "previous") : "previous";
    const url = `/api/projects/${currentProjectSlug}/export-function-diff?vs=${encodeURIComponent(vs)}`;
    try {
        const r = await fetch(url);
        if (!r.ok) {
            const err = await r.json().catch(() => ({}));
            if (typeof showToast === "function")
                showToast(`Xuất Excel lỗi: ${err.error || r.statusText}`, "red");
            return;
        }
        const blob = await r.blob();
        const cd = r.headers.get("Content-Disposition") || "";
        const m = /filename\*?=(?:UTF-8'')?"?([^\";]+)"?/i.exec(cd);
        const fname = m ? decodeURIComponent(m[1]) : `Function_Diff_${Date.now()}.xlsx`;
        const link = document.createElement("a");
        link.href = URL.createObjectURL(blob);
        link.download = fname;
        document.body.appendChild(link);
        link.click();
        link.remove();
        setTimeout(() => URL.revokeObjectURL(link.href), 1000);
        if (typeof showToast === "function") showToast("Đã xuất Excel Diff", "green");
    } catch (e) {
        if (typeof showToast === "function") showToast(`Lỗi mạng: ${e.message}`, "red");
    }
}


/** Xuất Excel FIT/GAP — POST filter body để cùng chuẩn với 4 export khác. */
async function exportFitgapReport() {
    const thrInput = document.getElementById("fitgapAgingThr");
    const thr = thrInput ? parseInt(thrInput.value, 10) || 14 : 14;
    const qs = new URLSearchParams();
    qs.set("aging_threshold_days", thr);
    const url = `/api/projects/${currentProjectSlug}/export-fitgap?${qs.toString()}`;
    try {
        const r = await fetch(url, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                module: globalFilters.modules,
                process: globalFilters.processes,
                pic: globalFilters.pics,
            }),
        });
        if (!r.ok) {
            const err = await r.json().catch(() => ({}));
            showToast(`Xuất Excel lỗi: ${err.error || r.statusText}`, "red");
            return;
        }
        // Trigger download
        const blob = await r.blob();
        const cd = r.headers.get("Content-Disposition") || "";
        const match = /filename\*?=(?:UTF-8'')?"?([^\";]+)"?/i.exec(cd);
        const fname = match ? decodeURIComponent(match[1]) : `FITGAP_Dashboard_${Date.now()}.xlsx`;
        const link = document.createElement("a");
        link.href = URL.createObjectURL(blob);
        link.download = fname;
        document.body.appendChild(link);
        link.click();
        link.remove();
        setTimeout(() => URL.revokeObjectURL(link.href), 1000);
        if (typeof showToast === "function") showToast("Đã xuất Excel FIT/GAP", "green");
    } catch (e) {
        if (typeof showToast === "function") showToast(`Lỗi mạng: ${e.message}`, "red");
    }
}

function renderSLASection(sla) {
    _lastSlaData = sla;
    const section = document.getElementById("section-sla");
    if (!section) return;
    if (!sla || !sla.items || sla.items.length === 0) {
        section.classList.add("hidden");
        return;
    }
    section.classList.remove("hidden");
    const th = sla.thresholds || {};
    document.getElementById("slaMustDays").textContent = th.must_have_days ?? 3;
    document.getElementById("slaShouldDays").textContent = th.should_have_days ?? 7;
    document.getElementById("slaCritical").textContent = sla.critical_count ?? 0;
    document.getElementById("slaWarning").textContent = sla.warning_count ?? 0;

    const wrap = document.getElementById("slaTableWrap");
    if (!wrap) return;
    const allItems = sla.items || [];
    const { pageItems } = _pageSlice("sla", allItems);
    if (allItems.length === 0) {
        wrap.innerHTML = `<div class="text-gray-500 text-sm italic p-3">Không có vi phạm SLA</div>`;
        return;
    }
    const badge = (sev) => sev === "critical"
        ? `<span class="text-[10px] font-bold bg-red-100 text-red-700 px-2 py-0.5 rounded">CRITICAL</span>`
        : `<span class="text-[10px] font-bold bg-amber-100 text-amber-700 px-2 py-0.5 rounded">WARNING</span>`;
    wrap.innerHTML = `
        <table class="w-full text-xs">
            <thead class="bg-gray-100 text-gray-700">
                <tr>
                    <th class="px-2 py-1 text-left">Mã CN</th>
                    <th class="px-2 py-1 text-left">Tên chức năng</th>
                    <th class="px-2 py-1 text-left">Module</th>
                    <th class="px-2 py-1 text-left">Priority</th>
                    <th class="px-2 py-1 text-left">Phase</th>
                    <th class="px-2 py-1 text-right">End</th>
                    <th class="px-2 py-1 text-right">Trễ (ngày)</th>
                    <th class="px-2 py-1 text-center">Severity</th>
                    <th class="px-2 py-1 text-left">PIC</th>
                </tr>
            </thead>
            <tbody>${pageItems.map(r => `
                <tr class="border-b hover:bg-red-50">
                    <td class="px-2 py-1 font-mono">${escapeHtml(r.ma_cn)}</td>
                    <td class="px-2 py-1">${escapeHtml(r.ten_cn)}</td>
                    <td class="px-2 py-1">${escapeHtml(r.module)}</td>
                    <td class="px-2 py-1">${escapeHtml(r.priority)}</td>
                    <td class="px-2 py-1">${escapeHtml(r.phase)}</td>
                    <td class="px-2 py-1 text-right">${escapeHtml(r.end_date)}</td>
                    <td class="px-2 py-1 text-right font-bold ${r.severity === "critical" ? "text-red-600" : "text-amber-600"}">${r.days_late}</td>
                    <td class="px-2 py-1 text-center">${badge(r.severity)}</td>
                    <td class="px-2 py-1">${(r.pics || []).map(escapeHtml).join(", ")}</td>
                </tr>`).join("")}
            </tbody>
        </table>`;
    renderPager("slaPagerWrap", "sla", allItems.length, () => renderSLASection(_lastSlaData));
}

// ------------------------------------------------------------------
// P4 rest — Capacity + Slow heatmap
// ------------------------------------------------------------------

function renderCapacitySection(cap) {
    _lastCapacityData = cap;
    const section = document.getElementById("section-capacity");
    if (!section) return;
    const allRows = cap?.by_pic || [];
    if (allRows.length === 0) {
        section.classList.add("hidden");
        return;
    }
    section.classList.remove("hidden");
    document.getElementById("capDefaultMD").textContent = cap.default_md_per_week ?? 5;
    document.getElementById("capOverload").textContent = cap.overload_count ?? 0;

    const { pageItems } = _pageSlice("capacity", allRows);
    const wrap = document.getElementById("capacityTableWrap");
    if (!wrap) return;
    wrap.innerHTML = `
        <table class="w-full text-xs">
            <thead class="bg-gray-100 text-gray-700">
                <tr>
                    <th class="px-2 py-1 text-left">PIC</th>
                    <th class="px-2 py-1 text-right">Remaining (MH)</th>
                    <th class="px-2 py-1 text-right">Closed (MH)</th>
                    <th class="px-2 py-1 text-right">Capacity (MH/tuần)</th>
                    <th class="px-2 py-1 text-right">Tuần cần</th>
                    <th class="px-2 py-1 text-center">Status</th>
                </tr>
            </thead>
            <tbody>${pageItems.map(r => `
                <tr class="border-b hover:bg-blue-50">
                    <td class="px-2 py-1 font-medium">${escapeHtml(r.pic)}</td>
                    <td class="px-2 py-1 text-right">${r.remaining_mh}</td>
                    <td class="px-2 py-1 text-right text-gray-500">${r.closed_mh}</td>
                    <td class="px-2 py-1 text-right">${r.capacity_mh_per_week}</td>
                    <td class="px-2 py-1 text-right font-mono">${r.weeks_needed ?? "—"}</td>
                    <td class="px-2 py-1 text-center">${r.overload
                        ? `<span class="text-[10px] font-bold bg-red-100 text-red-700 px-2 py-0.5 rounded">OVERLOAD</span>`
                        : `<span class="text-[10px] bg-emerald-100 text-emerald-700 px-2 py-0.5 rounded">OK</span>`}</td>
                </tr>`).join("")}
            </tbody>
        </table>`;
    renderPager("capacityPagerWrap", "capacity", allRows.length,
        () => renderCapacitySection(_lastCapacityData));
}

function renderSlowHeatmapSection(slow) {
    _lastSlowData = slow;
    const section = document.getElementById("section-slow");
    if (!section) return;
    const pics = slow?.pics || [];
    const phases = slow?.phases || [];
    if (pics.length === 0 || phases.length === 0) {
        section.classList.add("hidden");
        return;
    }
    section.classList.remove("hidden");
    document.getElementById("slowTotal").textContent = slow.total_slow ?? 0;

    // Sort PIC theo tổng row-slow giảm dần để user thấy "chậm nhất" ở đầu
    const picsSorted = [...pics].sort((a, b) => {
        const ta = phases.reduce((s, ph) => s + (slow.heatmap[a][ph] || 0), 0);
        const tb = phases.reduce((s, ph) => s + (slow.heatmap[b][ph] || 0), 0);
        return tb - ta;
    });
    const { pageItems: picsPage } = _pageSlice("slow", picsSorted);

    // Tìm max để scale màu (theo toàn bộ, không theo page)
    let max = 0;
    picsSorted.forEach(p => phases.forEach(ph => {
        const v = slow.heatmap[p][ph] || 0;
        if (v > max) max = v;
    }));
    const cell = (v) => {
        if (v === 0) return `<td class="px-2 py-1 text-center text-gray-300">·</td>`;
        const ratio = max > 0 ? v / max : 0;
        const bg = `rgba(239, 68, 68, ${0.15 + ratio * 0.75})`;
        const txt = ratio > 0.5 ? "text-white" : "text-red-900";
        return `<td class="px-2 py-1 text-center font-bold ${txt}" style="background:${bg}">${v}</td>`;
    };
    const wrap = document.getElementById("slowHeatmapWrap");
    if (!wrap) return;
    wrap.innerHTML = `
        <table class="w-full text-xs border-collapse">
            <thead class="bg-gray-100 text-gray-700">
                <tr>
                    <th class="px-2 py-1 text-left sticky left-0 bg-gray-100">PIC \\ Phase</th>
                    ${phases.map(ph => `<th class="px-2 py-1 text-center min-w-[70px]">${escapeHtml(ph)}</th>`).join("")}
                    <th class="px-2 py-1 text-center">Tổng</th>
                </tr>
            </thead>
            <tbody>${picsPage.map(p => {
                const total = phases.reduce((s, ph) => s + (slow.heatmap[p][ph] || 0), 0);
                return `
                <tr class="border-b">
                    <td class="px-2 py-1 font-medium sticky left-0 bg-white">${escapeHtml(p)}</td>
                    ${phases.map(ph => cell(slow.heatmap[p][ph] || 0)).join("")}
                    <td class="px-2 py-1 text-center font-bold text-gray-700">${total}</td>
                </tr>`;
            }).join("")}
            </tbody>
        </table>`;
    renderPager("slowPagerWrap", "slow", picsSorted.length,
        () => renderSlowHeatmapSection(_lastSlowData));
}

// ------------------------------------------------------------------
// P5 — Dependency + Baseline
// ------------------------------------------------------------------

function renderDependencySection(deps) {
    _lastDepsData = deps;
    const section = document.getElementById("section-deps");
    if (!section) return;
    if (!deps || (deps.edges_count === 0 && deps.blocker_count === 0)) {
        section.classList.add("hidden");
        return;
    }
    section.classList.remove("hidden");
    document.getElementById("depsEdges").textContent = deps.edges_count ?? 0;
    document.getElementById("depsBlockers").textContent = deps.blocker_count ?? 0;

    const allRows = deps.blockers || [];
    const wrap = document.getElementById("depsTableWrap");
    if (!wrap) return;
    if (allRows.length === 0) {
        wrap.innerHTML = `<div class="text-emerald-700 text-sm p-3 bg-emerald-50 rounded border border-emerald-200">
            ✅ Không có Must-have nào đang bị block bởi function khác
        </div>`;
        document.getElementById("depsPagerWrap").innerHTML = "";
        return;
    }
    const { pageItems } = _pageSlice("deps", allRows);
    wrap.innerHTML = `
        <table class="w-full text-xs">
            <thead class="bg-gray-100 text-gray-700">
                <tr>
                    <th class="px-2 py-1 text-left">Mã CN bị block</th>
                    <th class="px-2 py-1 text-left">Tên</th>
                    <th class="px-2 py-1 text-left">Module</th>
                    <th class="px-2 py-1 text-left">Priority</th>
                    <th class="px-2 py-1 text-left">Bị chặn bởi</th>
                    <th class="px-2 py-1 text-left">Tên (blocker)</th>
                    <th class="px-2 py-1 text-left">Module (blocker)</th>
                </tr>
            </thead>
            <tbody>${pageItems.map(r => `
                <tr class="border-b hover:bg-red-50">
                    <td class="px-2 py-1 font-mono">${escapeHtml(r.ma_cn)}</td>
                    <td class="px-2 py-1">${escapeHtml(r.ten_cn)}</td>
                    <td class="px-2 py-1">${escapeHtml(r.module)}</td>
                    <td class="px-2 py-1"><span class="text-[10px] font-bold bg-red-100 text-red-700 px-2 py-0.5 rounded">${escapeHtml(r.priority)}</span></td>
                    <td class="px-2 py-1 font-mono text-red-700">${escapeHtml(r.blocked_by)}</td>
                    <td class="px-2 py-1 text-gray-600">${escapeHtml(r.blocked_by_name)}</td>
                    <td class="px-2 py-1 text-gray-600">${escapeHtml(r.blocked_by_module)}</td>
                </tr>`).join("")}
            </tbody>
        </table>`;
    renderPager("depsPagerWrap", "deps", allRows.length,
        () => renderDependencySection(_lastDepsData));
}

// ------------------------------------------------------------------
// P6 — Upload history list
// ------------------------------------------------------------------

function renderUploadHistorySection(hist) {
    _lastHistoryData = hist;
    const section = document.getElementById("section-history");
    if (!section) return;
    const items = hist?.items || [];
    if (items.length === 0) {
        section.classList.add("hidden");
        return;
    }
    section.classList.remove("hidden");
    document.getElementById("historyTotal").textContent = items.length;

    const wrap = document.getElementById("uploadHistoryTableWrap");
    if (!wrap) return;
    // Tính delta row_count so với upload trước đó (items sort desc: mới nhất index 0)
    const withDelta = items.map((it, i) => {
        const prev = items[i + 1];
        const delta = prev ? (it.row_count - prev.row_count) : null;
        return { ...it, delta };
    });
    const { pageItems, start } = _pageSlice("history", withDelta);
    wrap.innerHTML = `
        <table class="w-full text-xs">
            <thead class="bg-gray-100 text-gray-700">
                <tr>
                    <th class="px-2 py-1 text-left">Thời gian</th>
                    <th class="px-2 py-1 text-left">Filename</th>
                    <th class="px-2 py-1 text-right">Số function</th>
                    <th class="px-2 py-1 text-right">Δ so với lần trước</th>
                    <th class="px-2 py-1 text-right">Modules</th>
                    <th class="px-2 py-1 text-right">Phases</th>
                    <th class="px-2 py-1 text-left">Checksum</th>
                </tr>
            </thead>
            <tbody>${pageItems.map((it, i) => {
                const globalIdx = start + i;
                const deltaTxt = it.delta === null
                    ? `<span class="text-gray-400">—</span>`
                    : it.delta > 0
                        ? `<span class="text-emerald-600 font-bold">+${it.delta}</span>`
                        : it.delta < 0
                            ? `<span class="text-red-600 font-bold">${it.delta}</span>`
                            : `<span class="text-gray-500">0</span>`;
                const timeTxt = it.time
                    ? new Date(it.time).toLocaleString("vi-VN")
                    : "—";
                return `
                <tr class="border-b ${globalIdx === 0 ? "bg-blue-50" : "hover:bg-gray-50"}">
                    <td class="px-2 py-1 whitespace-nowrap">${escapeHtml(timeTxt)} ${globalIdx === 0 ? '<span class="text-[10px] bg-blue-200 text-blue-800 px-1 rounded ml-1">mới nhất</span>' : ""}</td>
                    <td class="px-2 py-1 font-mono text-[11px]">${escapeHtml(it.filename)}</td>
                    <td class="px-2 py-1 text-right font-bold">${it.row_count}</td>
                    <td class="px-2 py-1 text-right">${deltaTxt}</td>
                    <td class="px-2 py-1 text-right text-gray-500">${it.modules ?? "—"}</td>
                    <td class="px-2 py-1 text-right text-gray-500">${it.phases ?? "—"}</td>
                    <td class="px-2 py-1 font-mono text-[10px] text-gray-400">${escapeHtml((it.checksum || "").slice(0, 8))}</td>
                </tr>`;
            }).join("")}
            </tbody>
        </table>`;
    renderPager("historyPagerWrap", "history", withDelta.length,
        () => renderUploadHistorySection(_lastHistoryData));
}

function renderBaselineSection(bsl) {
    _lastBaselineData = bsl;
    const section = document.getElementById("section-baseline");
    if (!section) return;
    if (!bsl || bsl.total_compared === 0) {
        section.classList.add("hidden");
        return;
    }
    section.classList.remove("hidden");
    document.getElementById("bslTotal").textContent = bsl.total_compared ?? 0;
    document.getElementById("bslLate").textContent = bsl.late_count ?? 0;
    document.getElementById("bslAvg").textContent = bsl.avg_variance_days ?? 0;

    const allRows = bsl.items || [];
    const { pageItems } = _pageSlice("baseline", allRows);
    const wrap = document.getElementById("baselineTableWrap");
    if (!wrap) return;
    wrap.innerHTML = `
        <table class="w-full text-xs">
            <thead class="bg-gray-100 text-gray-700">
                <tr>
                    <th class="px-2 py-1 text-left">Mã CN</th>
                    <th class="px-2 py-1 text-left">Tên</th>
                    <th class="px-2 py-1 text-left">Module</th>
                    <th class="px-2 py-1 text-left">Phase</th>
                    <th class="px-2 py-1 text-right">Plan</th>
                    <th class="px-2 py-1 text-right">Actual</th>
                    <th class="px-2 py-1 text-right">Variance (ngày)</th>
                    <th class="px-2 py-1 text-left">Status</th>
                </tr>
            </thead>
            <tbody>${pageItems.map(r => `
                <tr class="border-b ${r.late ? "hover:bg-red-50" : "hover:bg-gray-50"}">
                    <td class="px-2 py-1 font-mono">${escapeHtml(r.ma_cn)}</td>
                    <td class="px-2 py-1">${escapeHtml(r.ten_cn)}</td>
                    <td class="px-2 py-1">${escapeHtml(r.module)}</td>
                    <td class="px-2 py-1">${escapeHtml(r.phase)}</td>
                    <td class="px-2 py-1 text-right">${escapeHtml(r.plan_date)}</td>
                    <td class="px-2 py-1 text-right">${escapeHtml(r.actual_date)}</td>
                    <td class="px-2 py-1 text-right font-bold ${r.late ? "text-red-600" : "text-emerald-600"}">${r.variance_days > 0 ? "+" : ""}${r.variance_days}</td>
                    <td class="px-2 py-1">${escapeHtml(r.status)}</td>
                </tr>`).join("")}
            </tbody>
        </table>`;
    renderPager("baselinePagerWrap", "baseline", allRows.length,
        () => renderBaselineSection(_lastBaselineData));
}


// ========================================================================
// PHASE 3 — SAVED VIEWS + DEEP-LINK URL
// ========================================================================

let _savedViewsCache = [];  // [{id, name, modules, processes, pics}]

async function loadSavedViews() {
    if (!currentProjectSlug) return;
    try {
        const r = await fetch(_apiUrl("saved-views"));
        if (!r.ok) return;
        const data = await r.json();
        _savedViewsCache = data.views || [];
        _renderSavedViewsSelect();
        // Show wrap khi có views (hoặc luôn show để user có thể save)
        const wrap = document.getElementById("savedViewsWrap");
        if (wrap) wrap.classList.remove("hidden");
    } catch (err) {
        console.error("[loadSavedViews]", err);
    }
}

function _renderSavedViewsSelect() {
    const sel = document.getElementById("savedViewSelect");
    if (!sel) return;
    const current = sel.value;
    sel.innerHTML = `<option value="">📂 View đã lưu…</option>` +
        _savedViewsCache.map(v =>
            `<option value="${escapeAttr(v.id)}">${escapeHtml(v.name)}</option>`
        ).join("");
    if (current && _savedViewsCache.some(v => v.id === current)) {
        sel.value = current;
    }
}

window.applySavedView = function (viewId) {
    if (!viewId) return;
    const v = _savedViewsCache.find(x => x.id === viewId);
    if (!v) {
        showToast("View không tồn tại", "red");
        return;
    }
    // Áp filter vào 3 multi-select, silent để chỉ trigger 1 fetch cuối
    globalFilters = {
        modules: [...(v.modules || [])],
        processes: [...(v.processes || [])],
        pics: [...(v.pics || [])],
    };
    if (_msInstances.modules) _msInstances.modules.setSelected(globalFilters.modules, true);
    if (_msInstances.processes) _msInstances.processes.setSelected(globalFilters.processes, true);
    if (_msInstances.pics) _msInstances.pics.setSelected(globalFilters.pics, true);
    _refreshProcessOptions();
    _refreshPicOptions();
    onGlobalFilterChange();
    _updateDeepLink();
    // Task 4b: Nếu view kèm section_order → apply reorder (không post lên server,
    // đây là layout tạm thời của view, project global order không đổi).
    if (Array.isArray(v.section_order) && v.section_order.length) {
        applySectionOrderToDom(v.section_order);
    }
    // Task 6: view có thể override chart_configs — apply chồng lên default
    if (v.chart_configs && typeof applyChartConfigsToDom === "function") {
        applyChartConfigsToDom(v.chart_configs);
    } else if (typeof applyChartConfigsToDom === "function") {
        applyChartConfigsToDom(); // reset về default
    }
    showToast(`Đã áp view "${v.name}"`);
};

window.saveCurrentView = async function () {
    if (!currentProjectSlug) {
        showToast("Chưa chọn project", "red");
        return;
    }
    const name = prompt("Tên view (VD: PR - Tháng 8, Sếp xem GAP...):", "");
    if (!name || !name.trim()) return;
    const payload = {
        id: name.trim(),
        name: name.trim(),
        modules: globalFilters.modules,
        processes: globalFilters.processes,
        pics: globalFilters.pics,
        // Task 4b: kèm section_order hiện tại vào view (nếu user đã customize)
        section_order: _readCurrentSectionOrderFromDom(),
        // Task 6: kèm chart_configs hiện tại vào view — cho phép mỗi view có
        // config title/caption/hidden riêng.
        chart_configs: Object.assign({}, _chartConfigsCache),
    };
    try {
        const r = await fetch(_apiUrl("saved-views"), {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload),
        });
        if (!r.ok) throw new Error(await r.text());
        const data = await r.json();
        _savedViewsCache = data.views || [];
        _renderSavedViewsSelect();
        const sel = document.getElementById("savedViewSelect");
        if (sel) sel.value = payload.id;
        showToast(`Đã lưu view "${name.trim()}"`);
    } catch (err) {
        showToast("Lưu view thất bại: " + err.message, "red");
    }
};

window.deleteCurrentSavedView = async function () {
    const sel = document.getElementById("savedViewSelect");
    const viewId = sel?.value;
    if (!viewId) {
        showToast("Chưa chọn view nào", "red");
        return;
    }
    if (!confirm(`Xóa view "${viewId}"?`)) return;
    try {
        const r = await fetch(_apiUrl(`saved-views/${encodeURIComponent(viewId)}`), {
            method: "DELETE",
        });
        if (!r.ok) throw new Error(await r.text());
        const data = await r.json();
        _savedViewsCache = data.views || [];
        _renderSavedViewsSelect();
        showToast("Đã xóa view");
    } catch (err) {
        showToast("Xóa view thất bại: " + err.message, "red");
    }
};

// --- Deep-link: sync globalFilters ↔ URL query -----------------------

/**
 * Đọc URL params khi load app: ?project=, modules=, processes=, pics=, view=
 * Return {project, modules, processes, pics, view} — chỉ khi có ít nhất 1.
 */
function _readDeepLinkFromUrl() {
    const p = new URLSearchParams(location.search);
    const out = { project: p.get("project") };
    const list = (k) => (p.get(k) || "").split(",").map(s => s.trim()).filter(Boolean);
    out.modules = list("modules");
    out.processes = list("processes");
    out.pics = list("pics");
    out.view = p.get("view");
    return out;
}

/** Cập nhật URL bar mà không reload — dùng history.replaceState. */
function _updateDeepLink() {
    const p = new URLSearchParams(location.search);
    if (currentProjectSlug) p.set("project", currentProjectSlug); else p.delete("project");
    const setOrDel = (k, arr) => {
        if (arr && arr.length) p.set(k, arr.join(",")); else p.delete(k);
    };
    setOrDel("modules", globalFilters.modules);
    setOrDel("processes", globalFilters.processes);
    setOrDel("pics", globalFilters.pics);
    const qs = p.toString();
    const newUrl = location.pathname + (qs ? "?" + qs : "");
    history.replaceState(null, "", newUrl);
}

// Hook loadSavedViews + _updateDeepLink đã inline vào applyDashboardResponse.

// Apply deep-link filters sau khi load xong dashboard đầu tiên
document.addEventListener("DOMContentLoaded", () => {
    const dl = _readDeepLinkFromUrl();
    if (!dl.modules.length && !dl.processes.length && !dl.pics.length && !dl.view) return;
    // Delay để chờ switchProject + populateGlobalFilters chạy xong
    setTimeout(() => {
        if (dl.view && _savedViewsCache.length) {
            window.applySavedView(dl.view);
            return;
        }
        if (dl.modules.length || dl.processes.length || dl.pics.length) {
            globalFilters = {
                modules: dl.modules,
                processes: dl.processes,
                pics: dl.pics,
            };
            if (_msInstances.modules) _msInstances.modules.setSelected(dl.modules, true);
            if (_msInstances.processes) _msInstances.processes.setSelected(dl.processes, true);
            if (_msInstances.pics) _msInstances.pics.setSelected(dl.pics, true);
            onGlobalFilterChange();
        }
    }, 800);
});


// ========================================================================
// TASK 10 — KANBAN THEO TUẦN + PIC → ROLE MAP
// ========================================================================

let _kanbanWeekOffset = 0;
let _kanbanReloadTimer = null;
let _kanbanSortables = [];
let _kanbanRoleMap = {};   // {pic: role}
let _kanbanAllPics = [];   // list unique PIC từ backend
let _kanbanAllRoles = [];

async function loadKanban() {
    if (!currentProjectSlug) return;
    const params = new URLSearchParams();
    params.set("week_offset", String(_kanbanWeekOffset));
    const q = document.getElementById("kanbanSearch")?.value?.trim();
    if (q) params.set("search", q);

    // Merge global filter (top bar) + local Kanban filter — nếu 2 nguồn cùng
    // set 1 field, hợp union (comma-sep). Backend _parse_multi_arg đã tách
    // được đa giá trị.
    // Task 15: Module + Quy trình đã đổi sang multi-select → đọc từ
    // _msInstances.kanbanModule / .kanbanProcess (array).
    const mergeArray = (globalArr, localArr, paramName) => {
        const combined = new Set([...(globalArr || []), ...(localArr || [])].filter(Boolean));
        if (combined.size) params.set(paramName, [...combined].join(","));
    };
    mergeArray(globalFilters?.modules,   _msInstances.kanbanModule?.getSelected?.()  || [], "module");
    mergeArray(globalFilters?.processes, _msInstances.kanbanProcess?.getSelected?.() || [], "process");
    const localPic = document.getElementById("kanbanFilterPic")?.value?.trim();
    mergeArray(globalFilters?.pics, localPic ? [localPic] : [], "pic");

    const role = document.getElementById("kanbanFilterRole")?.value;
    if (role) params.set("role", role);
    try {
        const r = await fetch(_apiUrl("kanban") + "?" + params.toString());
        if (!r.ok) return;
        const data = await r.json();
        _renderKanban(data);
    } catch (err) {
        console.error("[loadKanban]", err);
    }
}

function _renderKanban(data) {
    const sec = document.getElementById("section-kanban");
    if (!sec) return;
    sec.classList.remove("hidden");
    const sub = document.getElementById("kanbanSubtitle");
    if (sub) {
        sub.textContent = `Tuần ${data.week.monday_iso} → ${data.week.sunday_iso} · Hôm nay ${data.week.today_iso} · ${data.total_after_filter} function`;
    }
    const wl = document.getElementById("kanbanWeekLabel");
    if (wl) {
        wl.textContent = _kanbanWeekOffset === 0 ? "Tuần này"
            : _kanbanWeekOffset > 0 ? `+${_kanbanWeekOffset} tuần`
            : `${_kanbanWeekOffset} tuần`;
    }

    // Populate filter dropdowns (chỉ lần đầu)
    _kanbanEnsureFilterOptions();

    const board = document.getElementById("kanbanBoard");
    if (!board) return;
    board.innerHTML = data.columns.map(col => `
        <div class="kanban-col border rounded-lg bg-slate-50 dark:bg-slate-900 flex flex-col" data-col="${col.key}">
            <div class="px-3 py-2 border-b bg-white dark:bg-slate-800 sticky top-0 rounded-t-lg z-10">
                <div class="font-semibold text-sm">${escapeHtml(col.title)}</div>
                <div class="text-[10px] text-gray-500">${col.count} function</div>
            </div>
            <div class="kanban-col-body p-2 space-y-2 flex-1 overflow-y-auto" data-col-key="${col.key}"
                 style="max-height: 60vh; min-height: 200px;">
                ${col.cards.map(_kanbanCardHtml).join("") ||
                  `<div class="text-xs text-gray-400 italic text-center py-4">Trống</div>`}
            </div>
        </div>
    `).join("");

    _kanbanBindCardClicks();
    _kanbanInitSortables();
}

function _kanbanCardHtml(c) {
    const prio = c.priority || "";
    let prioIcon = "";
    if (/must|high/i.test(prio)) prioIcon = "🔴";
    else if (/should|med/i.test(prio)) prioIcon = "🟡";
    else if (prio) prioIcon = "🟢";
    const statusClass = _fnStatusBadgeClass ? _fnStatusBadgeClass(c.phase_status) : "bg-gray-200 text-gray-700";
    const dl = c.deadline_iso ? c.deadline_iso.slice(5).replace("-", "/") : "";
    // Task 14: chip role auto-detect — BA=tím, Dev=xanh dương.
    const roleChip = (r) => {
        const cls = r === "Dev" ? "bg-blue-100 text-blue-700"
                   : r === "BA" ? "bg-purple-100 text-purple-700"
                   : "bg-indigo-100 text-indigo-700";
        return `<span class="text-[9px] ${cls} px-1 rounded">${escapeHtml(r)}</span>`;
    };
    const roles = c.roles?.length ? c.roles.map(roleChip).join(" ") : "";
    const aging = c.aging_days
        ? `<span class="text-[10px] font-semibold ${c.aging_days > 7 ? 'text-red-600' : 'text-amber-600'}">⏱️ ${c.aging_days}d</span>` : "";
    return `
        <div class="kanban-card border rounded p-2 bg-white dark:bg-slate-800 cursor-pointer hover:shadow-md text-xs"
             data-row-num="${c.row_num}">
            <div class="flex items-start justify-between gap-1 mb-1">
                <div class="font-mono text-[10px] text-gray-500">${escapeHtml(c.ma_cn)}</div>
                <span>${prioIcon}</span>
            </div>
            <div class="font-semibold text-[11px] leading-tight mb-1" title="${escapeAttr(c.ten_cn)}">
                ${escapeHtml(c.ten_cn.substring(0, 60))}${c.ten_cn.length > 60 ? "…" : ""}
            </div>
            <div class="flex flex-wrap gap-1 mb-1 text-[9px]">
                ${c.module ? `<span class="bg-blue-100 text-blue-700 px-1 rounded">${escapeHtml(c.module)}</span>` : ""}
                ${c.process ? `<span class="bg-purple-100 text-purple-700 px-1 rounded">${escapeHtml(c.process.substring(0, 20))}</span>` : ""}
            </div>
            ${c.phase ? `<div class="flex items-center gap-1 mb-1">
                <span class="text-[9px] px-1 rounded ${statusClass}">${escapeHtml(c.phase)} · ${escapeHtml(c.phase_status || "?")}</span>
            </div>` : ""}
            <div class="flex items-center justify-between text-[10px]">
                <span class="text-gray-600 dark:text-gray-400">
                    ${c.pics?.length ? "👤 " + escapeHtml(c.pics.slice(0, 2).join(", ")) + (c.pics.length > 2 ? " +" + (c.pics.length - 2) : "") : "🚫 chưa PIC"}
                    ${roles}
                </span>
                <span class="text-gray-500">${dl ? "📅 " + dl : ""} ${aging}</span>
            </div>
        </div>
    `;
}

function _kanbanEnsureFilterOptions() {
    const structure = structureCache || {};
    // Task 15: Module + Quy trình dùng multi-select (createMultiSelect).
    // Init 1 lần rồi setOptions mỗi lần structure đổi.
    if (!_msInstances.kanbanModule) {
        createMultiSelect({
            el: "#kanbanFilterModuleMS",
            key: "kanbanModule",
            label: "Module",
            options: structure.all_modules || [],
            selected: [],
            allText: "Tất cả Module",
            onChange: () => _kanbanScheduleReload(),
        });
    } else {
        _msInstances.kanbanModule.setOptions(structure.all_modules || [], /*dropInvalid=*/false);
    }
    if (!_msInstances.kanbanProcess) {
        createMultiSelect({
            el: "#kanbanFilterProcessMS",
            key: "kanbanProcess",
            label: "Quy trình",
            options: structure.all_processes || [],
            selected: [],
            allText: "Tất cả Quy trình",
            onChange: () => _kanbanScheduleReload(),
        });
    } else {
        _msInstances.kanbanProcess.setOptions(structure.all_processes || [], /*dropInvalid=*/false);
    }
    // PIC + Role vẫn single-select
    const fillSelect = (id, values) => {
        const sel = document.getElementById(id);
        if (!sel || sel.options.length > 1) return;
        values.forEach(v => {
            const opt = document.createElement("option");
            opt.value = v;
            opt.textContent = v;
            sel.appendChild(opt);
        });
    };
    fillSelect("kanbanFilterPic", structure.all_pics || _kanbanAllPics || []);
}

function _kanbanBindCardClicks() {
    document.querySelectorAll("#kanbanBoard .kanban-card").forEach(card => {
        card.onclick = () => {
            const rowNum = parseInt(card.dataset.rowNum, 10);
            if (typeof openFunctionDetail === "function") {
                openFunctionDetail(rowNum);
            }
        };
    });
}

function _kanbanInitSortables() {
    // Destroy old
    _kanbanSortables.forEach(s => { try { s.destroy(); } catch(e){} });
    _kanbanSortables = [];
    if (typeof Sortable === "undefined") return;
    document.querySelectorAll("#kanbanBoard .kanban-col-body").forEach(body => {
        const s = Sortable.create(body, {
            group: "kanban",
            animation: 150,
            ghostClass: "kanban-ghost",
            onEnd: (evt) => {
                if (evt.from === evt.to) return; // reorder cùng cột — skip
                const cardEl = evt.item;
                const rowNum = cardEl.dataset.rowNum;
                const toCol = evt.to.dataset.colKey;
                const colTitle = evt.to.closest(".kanban-col")?.querySelector(".font-semibold")?.textContent?.trim() || toCol;
                const ten = cardEl.querySelector(".font-semibold")?.textContent?.trim() || rowNum;
                showToast(`⚠️ Ghi nhận đề xuất chuyển "${ten}" → "${colTitle}". Không cập nhật file gốc, chỉ hiển thị.`, "amber");
            },
        });
        _kanbanSortables.push(s);
    });
}

window._kanbanScheduleReload = function () {
    clearTimeout(_kanbanReloadTimer);
    _kanbanReloadTimer = setTimeout(loadKanban, 350);
};

window._kanbanShiftWeek = function (delta) {
    if (delta === 0) _kanbanWeekOffset = 0;
    else _kanbanWeekOffset += delta;
    loadKanban();
};

// --- PIC → Role auto-detect (Task 14) ---
// Role được suy ra từ phase mà PIC xuất hiện (BA/Dev). UI map tay đã bỏ.
// Function này chỉ fetch derived map từ backend để hiển thị chip trên card.

async function loadPicRoles() {
    if (!currentProjectSlug) return;
    try {
        const r = await fetch(_apiUrl("pic-roles"));
        if (!r.ok) return;
        const d = await r.json();
        _kanbanRoleMap = d.map || {};
        _kanbanAllPics = d.all_pics || [];
        _kanbanAllRoles = d.all_roles || ["BA", "Dev"];
    } catch (err) {
        console.error("[loadPicRoles]", err);
    }
}

// ========================================================================
// TASK 9 — DYNAMIC DASHBOARD BUILDER
// ========================================================================
//
// User có thể tạo chart mới qua 2 mode:
//   - Chat: nhập tiếng Việt tự do, parseNaturalQuery → draft config
//   - Wizard: điền form 3 phần (loại chart / trục + measure / filter + title)
// Custom charts lưu ở /custom-dashboard endpoint, render trong
// section-custom-dashboards. Mỗi card có nút ⚙️ (edit) / 🗑️ (delete) /
// 📥 (export) / ⛶ (fullscreen).
// ========================================================================

let _customDashItems = [];
let _cdPreviewChart = null;
let _cdEditingId = null;   // null = tạo mới; string = đang edit

async function loadCustomDashboards() {
    if (!currentProjectSlug) return;
    try {
        const r = await fetch(_apiUrl("custom-dashboard"));
        if (!r.ok) return;
        const data = await r.json();
        _customDashItems = data.items || [];
        _renderCustomDashSection();
    } catch (err) {
        console.error("[loadCustomDashboards]", err);
    }
}

function _renderCustomDashSection() {
    const sec = document.getElementById("section-custom-dashboards");
    const wrap = document.getElementById("customDashList");
    if (!sec || !wrap) return;
    if (!_customDashItems.length) {
        sec.classList.add("hidden");
        wrap.innerHTML = "";
        return;
    }
    sec.classList.remove("hidden");
    wrap.innerHTML = _customDashItems.map(item => `
        <div class="border rounded-lg p-3 dashboard-card bg-slate-50 dark:bg-slate-900" data-cd-id="${escapeAttr(item.id)}">
            <div class="flex items-start justify-between gap-2 mb-2">
                <div class="flex-1 min-w-0">
                    <h4 class="font-semibold text-sm truncate">${escapeHtml(item.title)}</h4>
                    ${item.caption ? `<p class="text-xs text-gray-500 mt-0.5">${escapeHtml(item.caption)}</p>` : ""}
                </div>
                <div class="flex items-center gap-1 shrink-0">
                    <button onclick="_cdEditItem('${escapeAttr(item.id)}')" class="text-blue-600 hover:bg-blue-50 dark:hover:bg-slate-800 rounded p-1 text-sm" title="Sửa">⚙️</button>
                    <button onclick="_cdExportItem('${escapeAttr(item.id)}')" class="text-emerald-600 hover:bg-emerald-50 dark:hover:bg-slate-800 rounded p-1 text-sm" title="Xuất Excel">📥</button>
                    <button onclick="_cdDeleteItem('${escapeAttr(item.id)}')" class="text-red-600 hover:bg-red-50 dark:hover:bg-slate-800 rounded p-1 text-sm" title="Xoá">🗑️</button>
                </div>
            </div>
            <div style="height: 220px;">
                <canvas id="cdChart_${escapeAttr(item.id)}"></canvas>
            </div>
            <div class="text-[10px] text-gray-400 mt-1">${escapeHtml(item.chart_type)} · X: ${escapeHtml(item.x_field)} · Y: ${escapeHtml(item.y_measure)}${item.series_field ? " · Group: " + escapeHtml(item.series_field) : ""}</div>
        </div>
    `).join("");
    // Render each chart
    _customDashItems.forEach(item => _cdRenderChart(item));
}

async function _cdRenderChart(item) {
    try {
        const r = await fetch(_apiUrl(`custom-dashboard/${encodeURIComponent(item.id)}/data`));
        if (!r.ok) return;
        const agg = await r.json();
        const canvas = document.getElementById(`cdChart_${item.id}`);
        if (!canvas) return;
        _cdBuildChart(canvas, agg, item);
    } catch (err) {
        console.error("[cdRenderChart]", err);
    }
}

/** Build Chart.js instance từ aggregated data + item config. Shared với preview. */
function _cdBuildChart(canvas, agg, cfg) {
    const existing = Chart.getChart(canvas);
    if (existing) existing.destroy();

    const fields = _chartFieldsCache || { palettes: {} };
    let colors = fields.palettes[cfg.palette] || fields.palettes.default ||
        ["#3b82f6", "#10b981", "#f59e0b", "#ef4444", "#8b5cf6", "#ec4899"];

    const ut = cfg.chart_type || "bar";
    let chartType = "bar";
    let extraOpts = { responsive: true, maintainAspectRatio: false,
        plugins: { legend: { position: "bottom", labels: { font: { size: 10 } } } } };
    let stacked = false;
    if (ut === "horizontalBar") { chartType = "bar"; extraOpts.indexAxis = "y"; }
    else if (ut === "line") chartType = "line";
    else if (ut === "area") chartType = "line";
    else if (ut === "pie") chartType = "pie";
    else if (ut === "doughnut") chartType = "doughnut";
    else if (ut === "stackedBar") { chartType = "bar"; stacked = true; }
    else if (ut === "groupedBar") chartType = "bar";

    const datasets = agg.datasets.map((ds, i) => ({
        label: ds.label,
        data: ds.data,
        backgroundColor: (chartType === "pie" || chartType === "doughnut")
            ? ds.data.map((_, j) => colors[j % colors.length])
            : colors[i % colors.length],
        borderColor: colors[i % colors.length],
        borderWidth: chartType === "line" ? 2 : 0,
        fill: ut === "area",
        tension: chartType === "line" ? 0.3 : 0,
    }));
    if (stacked) {
        extraOpts.scales = { x: { stacked: true }, y: { stacked: true, beginAtZero: true } };
    } else if (chartType === "bar") {
        extraOpts.scales = { y: { beginAtZero: true } };
    }
    try {
        new Chart(canvas, {
            type: chartType,
            data: { labels: agg.labels, datasets },
            options: extraOpts,
        });
    } catch (err) {
        console.error("[cdBuildChart]", err);
    }
}

// --- Modal management ---

window.openCustomDashModal = async function () {
    _cdEditingId = null;
    _cdResetForm();
    await _ensureChartFields();
    _cdPopulateWizardDropdowns();
    const modal = document.getElementById("customDashModal");
    if (modal) {
        modal.classList.remove("hidden");
        modal.classList.add("flex");
    }
};

window.closeCustomDashModal = function () {
    const modal = document.getElementById("customDashModal");
    if (modal) {
        modal.classList.add("hidden");
        modal.classList.remove("flex");
    }
    if (_cdPreviewChart) { _cdPreviewChart.destroy(); _cdPreviewChart = null; }
};

function _cdResetForm() {
    ["cdTitle", "cdCaption", "cdChatInput", "cdFilterModules", "cdFilterFitgaps"].forEach(id => {
        const el = document.getElementById(id);
        if (el) el.value = "";
    });
    ["cdFilterOverdue", "cdFilterOpenOnly"].forEach(id => {
        const el = document.getElementById(id);
        if (el) el.checked = false;
    });
    document.getElementById("cdPreviewWrap")?.classList.add("hidden");
    document.getElementById("cdChatSuggestion")?.classList.add("hidden");
}

function _cdPopulateWizardDropdowns() {
    const fields = _chartFieldsCache || {};
    const optHtml = (map) => Object.entries(map || {}).map(
        ([k, v]) => `<option value="${escapeAttr(k)}">${escapeHtml(v)}</option>`
    ).join("");
    const setSel = (id, opts, prependEmpty = false, defaultVal = "") => {
        const el = document.getElementById(id);
        if (!el) return;
        el.innerHTML = (prependEmpty ? `<option value="">— Không —</option>` : "") + opts;
        if (defaultVal) el.value = defaultVal;
    };
    setSel("cdXField", optHtml(fields.fields), true);
    setSel("cdYMeasure", optHtml(fields.measures), false, "count");
    setSel("cdSeriesField", optHtml(fields.fields), true);
    const palOpts = Object.keys(fields.palettes || {}).map(p =>
        `<option value="${p}">${p}</option>`
    ).join("");
    setSel("cdPalette", palOpts, false, "default");
    // Chart type icons
    const grid = document.getElementById("cdTypeGrid");
    if (grid) {
        const ICONS = { bar: "📊", horizontalBar: "📊", line: "📈", area: "📉", pie: "🥧", doughnut: "🍩", stackedBar: "🧱", groupedBar: "🎯" };
        grid.innerHTML = Object.entries(fields.chart_types || {}).map(
            ([k, v]) => `<label class="border rounded p-2 cursor-pointer hover:bg-purple-50 dark:hover:bg-slate-700 flex items-center gap-2">
                <input type="radio" name="cdChartType" value="${k}" ${k === "bar" ? "checked" : ""}>
                <span class="text-lg">${ICONS[k] || "📊"}</span>
                <span class="text-xs">${escapeHtml(v)}</span>
            </label>`
        ).join("");
    }
}

window._cdSetMode = function (mode) {
    document.getElementById("cdPane-chat")?.classList.toggle("hidden", mode !== "chat");
    document.getElementById("cdPane-wizard")?.classList.toggle("hidden", mode !== "wizard");
    document.getElementById("cdMode-chat")?.classList.toggle("border-blue-500", mode === "chat");
    document.getElementById("cdMode-chat")?.classList.toggle("text-blue-600", mode === "chat");
    document.getElementById("cdMode-chat")?.classList.toggle("border-transparent", mode !== "chat");
    document.getElementById("cdMode-chat")?.classList.toggle("text-gray-500", mode !== "chat");
    document.getElementById("cdMode-wizard")?.classList.toggle("border-blue-500", mode === "wizard");
    document.getElementById("cdMode-wizard")?.classList.toggle("text-blue-600", mode === "wizard");
    document.getElementById("cdMode-wizard")?.classList.toggle("border-transparent", mode !== "wizard");
    document.getElementById("cdMode-wizard")?.classList.toggle("text-gray-500", mode !== "wizard");
};

// --- NL parser rule-based ---

function _cdParseNaturalQuery(text) {
    if (!text) return null;
    const t = text.toLowerCase();
    const cfg = {
        title: text.trim(),
        chart_type: "bar",
        x_field: null, y_measure: "count", series_field: null,
        filters: {},
    };
    // Chart type keywords
    if (/(so sánh|so sanh|by|vs)/.test(t)) cfg.chart_type = "bar";
    if (/(tỷ lệ|ty le|phân bố|phan bo)/.test(t)) cfg.chart_type = "doughnut";
    if (/(xu hướng|xu huong|trend|theo tuần|theo tuan)/.test(t)) cfg.chart_type = "line";
    if (/(stacked|xếp chồng|xep chong)/.test(t)) cfg.chart_type = "stackedBar";
    // X field
    if (/(theo module|by module|per module|phân hệ|phan he)/.test(t)) cfg.x_field = "module";
    else if (/(theo pic|by pic|theo người|theo nguoi|nhân sự|nhan su|người phụ trách|nguoi phu trach)/.test(t)) cfg.x_field = "pic";
    else if (/(theo phase|per phase|by phase|giai đoạn|giai doan)/.test(t)) cfg.x_field = "phase";
    else if (/(theo quy trình|theo quy trinh|by process|per process)/.test(t)) cfg.x_field = "process";
    else if (/(theo priority|theo ưu tiên|theo uu tien|by priority)/.test(t)) cfg.x_field = "priority";
    else if (/(theo complexity|theo độ phức tạp|theo do phuc tap)/.test(t)) cfg.x_field = "complexity";
    else if (/(theo fit\/gap|theo fitgap|by fitgap)/.test(t)) cfg.x_field = "fitgap";
    else if (/(theo status|theo trạng thái|theo trang thai)/.test(t)) cfg.x_field = "status";
    else if (/(theo task type|theo loại|theo loai)/.test(t)) cfg.x_field = "task_type";
    else if (/(theo tuần|theo tuan|by week)/.test(t)) cfg.x_field = "week_start";
    // Measure
    if (/(workload|khối lượng|khoi luong|man\.?hours|mh|md|hours)/.test(t)) cfg.y_measure = "sum_mh";
    if (/(tỷ lệ closed|ty le closed|% closed|percent closed)/.test(t)) cfg.y_measure = "pct_closed";
    if (/(tỷ lệ trễ|ty le tre|% overdue|percent overdue)/.test(t)) cfg.y_measure = "pct_overdue";
    if (/(duration trung bình|duration trung binh|avg duration|trung bình ngày|trung binh ngay)/.test(t)) cfg.y_measure = "avg_duration";
    // Filters
    if (/(gap|đang mở gap|dang mo gap)/.test(t) && !/fit\/gap/.test(t)) cfg.filters.fitgaps = ["GAP"];
    if (/(overdue|trễ|tre|quá hạn|qua han)/.test(t)) cfg.filters.overdue_only = true;
    if (/(chưa closed|chua closed|chưa xong|chua xong|đang mở|dang mo)/.test(t)) cfg.filters.open_only = true;
    // Fallback x_field
    if (!cfg.x_field) cfg.x_field = "module";
    return cfg;
}

window._cdOnChatInput = function () {
    const text = document.getElementById("cdChatInput")?.value || "";
    if (text.trim().length < 5) {
        document.getElementById("cdChatSuggestion")?.classList.add("hidden");
        return;
    }
    const draft = _cdParseNaturalQuery(text);
    if (!draft) return;
    const box = document.getElementById("cdChatSuggestion");
    const content = document.getElementById("cdChatDraftContent");
    if (!box || !content) return;
    const fields = _chartFieldsCache || {};
    const flabel = (k) => fields.fields?.[k] || k;
    const mlabel = (k) => fields.measures?.[k] || k;
    content.innerHTML = `
        <div>• <b>Loại:</b> ${escapeHtml(fields.chart_types?.[draft.chart_type] || draft.chart_type)}</div>
        <div>• <b>Trục X:</b> ${escapeHtml(flabel(draft.x_field))}</div>
        <div>• <b>Measure Y:</b> ${escapeHtml(mlabel(draft.y_measure))}</div>
        ${draft.series_field ? `<div>• <b>Group:</b> ${escapeHtml(flabel(draft.series_field))}</div>` : ""}
        ${Object.keys(draft.filters).length ? `<div>• <b>Filter:</b> ${escapeHtml(JSON.stringify(draft.filters))}</div>` : ""}
    `;
    box.classList.remove("hidden");
    box._cdDraft = draft;
};

window._cdApplyChatDraft = function () {
    const box = document.getElementById("cdChatSuggestion");
    const draft = box?._cdDraft;
    if (!draft) return;
    _cdSetMode("wizard");
    document.querySelector(`input[name="cdChartType"][value="${draft.chart_type}"]`)?.click();
    if (draft.x_field) document.getElementById("cdXField").value = draft.x_field;
    if (draft.y_measure) document.getElementById("cdYMeasure").value = draft.y_measure;
    if (draft.series_field) document.getElementById("cdSeriesField").value = draft.series_field;
    document.getElementById("cdTitle").value = draft.title.slice(0, 100);
    document.getElementById("cdFilterOverdue").checked = !!draft.filters.overdue_only;
    document.getElementById("cdFilterOpenOnly").checked = !!draft.filters.open_only;
    if (draft.filters.fitgaps) document.getElementById("cdFilterFitgaps").value = draft.filters.fitgaps.join(",");
};

// --- Read form → payload ---

function _cdReadForm() {
    const chartType = document.querySelector('input[name="cdChartType"]:checked')?.value || "bar";
    const filters = {};
    const mods = document.getElementById("cdFilterModules")?.value.trim();
    if (mods) filters.modules = mods.split(",").map(s => s.trim()).filter(Boolean);
    const fg = document.getElementById("cdFilterFitgaps")?.value.trim();
    if (fg) filters.fitgaps = fg.split(",").map(s => s.trim()).filter(Boolean);
    if (document.getElementById("cdFilterOverdue")?.checked) filters.overdue_only = true;
    if (document.getElementById("cdFilterOpenOnly")?.checked) filters.open_only = true;
    return {
        id: _cdEditingId || undefined,
        title: document.getElementById("cdTitle")?.value.trim() || "",
        caption: document.getElementById("cdCaption")?.value.trim() || "",
        chart_type: chartType,
        x_field: document.getElementById("cdXField")?.value || "",
        y_measure: document.getElementById("cdYMeasure")?.value || "count",
        series_field: document.getElementById("cdSeriesField")?.value || null,
        palette: document.getElementById("cdPalette")?.value || "default",
        filters,
    };
}

window._cdPreview = async function () {
    const payload = _cdReadForm();
    if (!payload.x_field) {
        showToast("Chọn trục X trước", "red");
        return;
    }
    try {
        const r = await fetch(_apiUrl("chart-aggregate"), {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                x_field: payload.x_field,
                y_measure: payload.y_measure,
                series_field: payload.series_field,
                filters: payload.filters,
            }),
        });
        if (!r.ok) throw new Error(await r.text());
        const agg = await r.json();
        document.getElementById("cdPreviewWrap")?.classList.remove("hidden");
        const canvas = document.getElementById("cdPreviewCanvas");
        _cdBuildChart(canvas, agg, payload);
    } catch (err) {
        showToast("Preview thất bại: " + err.message, "red");
    }
};

window._cdSave = async function () {
    const payload = _cdReadForm();
    if (!payload.title || !payload.x_field) {
        showToast("Cần nhập Title + chọn Trục X", "red");
        return;
    }
    try {
        const method = _cdEditingId ? "PUT" : "POST";
        const url = _cdEditingId
            ? _apiUrl(`custom-dashboard/${encodeURIComponent(_cdEditingId)}`)
            : _apiUrl("custom-dashboard");
        const r = await fetch(url, {
            method,
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload),
        });
        if (!r.ok) throw new Error(await r.text());
        showToast(`Đã ${_cdEditingId ? "cập nhật" : "tạo"} dashboard`);
        closeCustomDashModal();
        await loadCustomDashboards();
    } catch (err) {
        showToast("Lưu dashboard thất bại: " + err.message, "red");
    }
};

window._cdEditItem = function (id) {
    const item = _customDashItems.find(i => i.id === id);
    if (!item) return;
    _cdEditingId = id;
    _ensureChartFields().then(() => {
        _cdPopulateWizardDropdowns();
        _cdSetMode("wizard");
        document.querySelector(`input[name="cdChartType"][value="${item.chart_type}"]`)?.click();
        document.getElementById("cdXField").value = item.x_field;
        document.getElementById("cdYMeasure").value = item.y_measure;
        document.getElementById("cdSeriesField").value = item.series_field || "";
        document.getElementById("cdPalette").value = item.palette || "default";
        document.getElementById("cdTitle").value = item.title;
        document.getElementById("cdCaption").value = item.caption || "";
        const f = item.filters || {};
        document.getElementById("cdFilterModules").value = (f.modules || []).join(",");
        document.getElementById("cdFilterFitgaps").value = (f.fitgaps || []).join(",");
        document.getElementById("cdFilterOverdue").checked = !!f.overdue_only;
        document.getElementById("cdFilterOpenOnly").checked = !!f.open_only;
        const modal = document.getElementById("customDashModal");
        modal?.classList.remove("hidden");
        modal?.classList.add("flex");
    });
};

window._cdDeleteItem = async function (id) {
    const item = _customDashItems.find(i => i.id === id);
    if (!item) return;
    if (!confirm(`Xoá custom chart "${item.title}"?`)) return;
    try {
        const r = await fetch(_apiUrl(`custom-dashboard/${encodeURIComponent(id)}`), {
            method: "DELETE",
        });
        if (!r.ok) throw new Error(await r.text());
        showToast("Đã xoá");
        await loadCustomDashboards();
    } catch (err) {
        showToast("Xoá thất bại: " + err.message, "red");
    }
};

window._cdExportItem = function (id) {
    window.open(_apiUrl(`custom-dashboard/${encodeURIComponent(id)}/export`), "_blank");
};


// ========================================================================
// TASK 7 — XUẤT PDF BÁO CÁO TUẦN (client-side html2canvas + jsPDF)
// ========================================================================

// Preset content — union PM + BA cho "Full", user chọn tay cho "Custom"
const _PDF_PRESET_SECTIONS = {
    pm: [
        "section-summary", "section-overdue", "section-module", "section-pic",
        "section-effort", "section-giaidoan", "section-burndown",
        "section-gantt", "section-risk",
    ],
    ba: [
        "section-summary", "section-fitgap-dashboard", "section-priority",
        "section-process", "section-function-diff", "section-matrix",
        "section-unassigned",
    ],
};

window.openPdfExportModal = function () {
    const modal = document.getElementById("pdfExportModal");
    if (!modal) return;
    if (typeof html2canvas === "undefined" || !window.jspdf?.jsPDF) {
        showToast("PDF library chưa load — thử reload trang", "red");
        return;
    }
    // Default date = today
    const today = new Date();
    const dateStr = today.toISOString().slice(0, 10);
    const dateInput = document.getElementById("pdfReportDate");
    if (dateInput && !dateInput.value) dateInput.value = dateStr;
    _pdfOnPresetChange();
    modal.classList.remove("hidden");
    modal.classList.add("flex");
};

window.closePdfExportModal = function () {
    const modal = document.getElementById("pdfExportModal");
    if (!modal) return;
    modal.classList.add("hidden");
    modal.classList.remove("flex");
};

window._pdfOnPresetChange = function () {
    const preset = document.querySelector('input[name="pdfPreset"]:checked')?.value || "pm";
    const wrap = document.getElementById("pdfCustomSections");
    if (!wrap) return;
    if (preset !== "custom") {
        wrap.classList.add("hidden");
        return;
    }
    wrap.classList.remove("hidden");
    // Build checkbox list từ tất cả section trong dashboard
    const secs = Array.from(document.querySelectorAll('#dashboard [id^="section-"]'))
        .filter(s => s.id !== "section-summary-header");
    wrap.innerHTML = secs.map(s => {
        const label = _sectionShortLabel(s.id);
        return `<label class="flex items-center gap-2 py-0.5">
            <input type="checkbox" class="pdf-custom-cb" value="${s.id}">
            <span>${escapeHtml(label)} <span class="text-gray-400">(${s.id})</span></span>
        </label>`;
    }).join("");
};

function _pdfGetSelectedSections() {
    const preset = document.querySelector('input[name="pdfPreset"]:checked')?.value || "pm";
    if (preset === "custom") {
        return Array.from(document.querySelectorAll(".pdf-custom-cb"))
            .filter(cb => cb.checked)
            .map(cb => cb.value);
    }
    if (preset === "full") {
        const set = new Set([..._PDF_PRESET_SECTIONS.pm, ..._PDF_PRESET_SECTIONS.ba]);
        return Array.from(set);
    }
    return _PDF_PRESET_SECTIONS[preset] || [];
}

function _pdfPresetSuffix() {
    const preset = document.querySelector('input[name="pdfPreset"]:checked')?.value || "pm";
    return ({ pm: "PM", ba: "BA", full: "Full", custom: "Custom" })[preset];
}

/**
 * Filter subtitle: hiển thị globalFilters đang active dưới header PDF.
 */
function _pdfFilterSubtitle() {
    const parts = [];
    if (globalFilters.modules?.length) parts.push(`Module: ${globalFilters.modules.join(", ")}`);
    if (globalFilters.processes?.length) parts.push(`Quy trình: ${globalFilters.processes.slice(0, 3).join(", ")}` +
        (globalFilters.processes.length > 3 ? ` +${globalFilters.processes.length - 3}` : ""));
    if (globalFilters.pics?.length) parts.push(`PIC: ${globalFilters.pics.slice(0, 3).join(", ")}` +
        (globalFilters.pics.length > 3 ? ` +${globalFilters.pics.length - 3}` : ""));
    return parts.length ? "Filter: " + parts.join(" · ") : "Filter: (không áp)";
}

function _pdfSetProgress(text, percent) {
    const wrap = document.getElementById("pdfProgress");
    const tx = document.getElementById("pdfProgressText");
    const bar = document.getElementById("pdfProgressBar");
    if (!wrap) return;
    wrap.classList.remove("hidden");
    if (tx) tx.textContent = text;
    if (bar) bar.style.width = `${Math.min(100, Math.max(0, percent))}%`;
}

window.doPdfExport = async function () {
    if (typeof html2canvas === "undefined" || !window.jspdf?.jsPDF) {
        showToast("PDF library chưa load", "red");
        return;
    }
    const ids = _pdfGetSelectedSections();
    if (!ids.length) {
        showToast("Chưa chọn section nào để xuất", "red");
        return;
    }
    const goBtn = document.getElementById("pdfExportGoBtn");
    if (goBtn) { goBtn.disabled = true; goBtn.textContent = "⏳ Đang tạo…"; }

    // Force light mode để capture đẹp
    const htmlEl = document.documentElement;
    const wasDark = htmlEl.classList.contains("dark");
    if (wasDark) htmlEl.classList.remove("dark");
    document.body.classList.add("pdf-capture-mode");

    try {
        const scale = parseFloat(document.getElementById("pdfScale")?.value || "1.5");
        const notes = document.getElementById("pdfNotes")?.value?.trim() || "";
        const dateStr = document.getElementById("pdfReportDate")?.value || new Date().toISOString().slice(0, 10);
        const [yy, mm, dd] = dateStr.split("-");
        const displayDate = `${dd}/${mm}/${yy}`;
        const suffix = _pdfPresetSuffix();

        const { jsPDF } = window.jspdf;
        const pdf = new jsPDF({ unit: "mm", format: "a4", orientation: "portrait" });
        const pageW = pdf.internal.pageSize.getWidth();   // 210
        const pageH = pdf.internal.pageSize.getHeight();  // 297
        const margin = 10;
        const contentW = pageW - margin * 2;

        // ==== HEADER PAGE ====
        pdf.setFillColor(30, 64, 175);
        pdf.rect(0, 0, pageW, 30, "F");
        pdf.setTextColor(255, 255, 255);
        pdf.setFontSize(16);
        pdf.text("📊 Báo cáo tuần iHRP Function List", margin, 14);
        pdf.setFontSize(10);
        pdf.text(displayDate, pageW - margin, 14, { align: "right" });
        pdf.setFontSize(9);
        const projName = window._projectMeta?.project?.name || currentProjectSlug;
        pdf.text(`Project: ${projName} · Preset: ${suffix}`, margin, 23);

        pdf.setTextColor(30, 41, 59);
        pdf.setFontSize(9);
        pdf.text(_pdfFilterSubtitle(), margin, 40);

        let cursorY = 48;
        if (notes) {
            pdf.setFontSize(10);
            pdf.setFont(undefined, "italic");
            const wrapped = pdf.splitTextToSize(notes, contentW);
            pdf.text(wrapped, margin, cursorY);
            cursorY += wrapped.length * 5 + 4;
            pdf.setFont(undefined, "normal");
        }

        // ==== CAPTURE EACH SECTION ====
        let sectionIndex = 0;
        for (const sid of ids) {
            sectionIndex += 1;
            const sec = document.getElementById(sid);
            if (!sec) continue;
            // Nếu section đang hidden (user hoặc mặc định) → tạm show để capture
            const wasHidden = sec.classList.contains("hidden");
            if (wasHidden) sec.classList.remove("hidden");
            const label = _sectionShortLabel(sid);
            _pdfSetProgress(`(${sectionIndex}/${ids.length}) ${label}…`, (sectionIndex / (ids.length + 1)) * 100);

            // Wait 1 frame để layout ổn định
            await new Promise(r => requestAnimationFrame(() => setTimeout(r, 50)));

            let canvas;
            try {
                canvas = await html2canvas(sec, {
                    scale,
                    backgroundColor: "#ffffff",
                    logging: false,
                    useCORS: true,
                    ignoreElements: (el) => {
                        // Bỏ qua gear config, drag handle, các nút no-print
                        if (el.classList?.contains?.("chart-config-gear")) return true;
                        if (el.classList?.contains?.("no-print")) return true;
                        return false;
                    },
                });
            } catch (err) {
                console.warn(`[pdfExport] capture failed for ${sid}:`, err);
                if (wasHidden) sec.classList.add("hidden");
                continue;
            }
            if (wasHidden) sec.classList.add("hidden");

            const imgW = contentW;
            const imgH = (canvas.height * imgW) / canvas.width;

            // Nếu section quá cao (> nửa trang), start ở page mới
            const remainH = pageH - cursorY - margin;
            if (imgH > remainH || cursorY > pageH - 60) {
                pdf.addPage();
                cursorY = margin;
            }

            // Nếu section vẫn cao hơn 1 trang trọn → cắt slice
            if (imgH <= pageH - cursorY - margin) {
                pdf.addImage(canvas.toDataURL("image/jpeg", 0.85),
                    "JPEG", margin, cursorY, imgW, imgH);
                cursorY += imgH + 4;
            } else {
                // Slice canvas theo trang
                let srcY = 0;
                const srcHPerPage = (canvas.width * (pageH - margin * 2)) / imgW;
                while (srcY < canvas.height) {
                    const sliceH = Math.min(srcHPerPage, canvas.height - srcY);
                    const tmp = document.createElement("canvas");
                    tmp.width = canvas.width;
                    tmp.height = sliceH;
                    tmp.getContext("2d").drawImage(canvas, 0, srcY, canvas.width, sliceH,
                        0, 0, canvas.width, sliceH);
                    const dispH = (sliceH * imgW) / canvas.width;
                    pdf.addImage(tmp.toDataURL("image/jpeg", 0.85),
                        "JPEG", margin, margin, imgW, dispH);
                    srcY += sliceH;
                    if (srcY < canvas.height) pdf.addPage();
                }
                cursorY = pageH; // buộc trang sau bắt đầu mới
            }
        }

        // ==== FOOTER: Trang X/Y ====
        const totalPages = pdf.internal.getNumberOfPages();
        for (let p = 1; p <= totalPages; p++) {
            pdf.setPage(p);
            pdf.setFontSize(8);
            pdf.setTextColor(100, 116, 139);
            pdf.text(`Trang ${p} / ${totalPages}`, pageW - margin, pageH - 5, { align: "right" });
            pdf.text(`Generate: ${new Date().toLocaleString("vi-VN")}`, margin, pageH - 5);
        }

        _pdfSetProgress("Đang lưu file…", 98);

        // ==== Save ====
        const dateSlug = dateStr.replace(/-/g, "");
        const fname = `iHRP_Report_${dateSlug}_${suffix}.pdf`;
        pdf.save(fname);
        _pdfSetProgress("✅ Xuất PDF xong!", 100);
        showToast(`Đã tạo ${fname}`);
        setTimeout(() => {
            document.getElementById("pdfProgress")?.classList.add("hidden");
            closePdfExportModal();
        }, 900);
    } catch (err) {
        console.error("[doPdfExport]", err);
        showToast("Xuất PDF thất bại: " + err.message, "red");
    } finally {
        if (wasDark) htmlEl.classList.add("dark");
        document.body.classList.remove("pdf-capture-mode");
        if (goBtn) { goBtn.disabled = false; goBtn.textContent = "📥 Xuất PDF"; }
    }
};


// ========================================================================
// TASK 6 — CHART CONFIG PHASE A (title / caption / hide-show per section)
// ========================================================================
//
// Concept:
//   - Config target = section id (tất cả section top-level có heading + chart).
//   - Config schema: { title?: string, caption?: string, hidden?: boolean }
//   - Lưu 2 tầng:
//       (a) project_default (chart_configs.json)
//       (b) per_view (chart_configs field trong 1 saved view)
//     FE apply: default → view override → DOM.
//   - UI: gear ⚙️ float ở góc phải-trên mỗi section. Click → popover.
// ========================================================================

// Danh sách section được phép cấu hình (bỏ những section admin/không có title)
const _CHART_CFG_SKIP_SECTIONS = new Set([
    "section-summary",
    "section-summary-header",
    "section-globalfilter",
    "section-compare",       // compare có UI riêng
    "section-digest",        // digest có UI riêng
]);

let _chartConfigsCache = {};   // { target_id: {title, caption, hidden} }
let _chartConfigsPopoverEl = null;

async function loadChartConfigs() {
    if (!currentProjectSlug) return;
    try {
        const r = await fetch(_apiUrl("chart-config"));
        if (!r.ok) return;
        const data = await r.json();
        _chartConfigsCache = data.configs || {};
        applyChartConfigsToDom();
        // Phase B: apply type/axes/palette overrides cho canvas nào có cấu hình
        _ensureChartFields().then(() => {
            Object.entries(_chartConfigsCache).forEach(([tid, cfg]) => {
                if (tid.startsWith("chart") && (cfg.type || cfg.x_field || cfg.palette)) {
                    // Cho chart render default xong (setTimeout) rồi rerender với config
                    setTimeout(() => rerenderChartWithConfig(tid, cfg), 200);
                }
            });
        });
    } catch (err) {
        console.error("[loadChartConfigs]", err);
    }
}

/**
 * Apply toàn bộ config (default + view override) vào DOM.
 * Gọi mỗi khi:
 *   - Load dashboard xong
 *   - User save 1 config qua popover
 *   - User apply saved view (view có thể có chart_configs override)
 */
function applyChartConfigsToDom(viewOverride = null) {
    const merged = Object.assign({}, _chartConfigsCache, viewOverride || {});
    // Loop qua tất cả section có id
    document.querySelectorAll('#dashboard [id^="section-"]').forEach(sec => {
        const sid = sec.id;
        if (_CHART_CFG_SKIP_SECTIONS.has(sid)) return;
        _applyOneChartConfig(sec, merged[sid] || null);
    });
    _renderHiddenSectionPills();
}

function _applyOneChartConfig(sec, cfg) {
    const sid = sec.id;

    // --- Title override ---
    const titleEl = sec.querySelector("h2, h3, .section-title");
    if (titleEl) {
        // Lưu title gốc lần đầu để reset (dataset không mất qua render)
        if (!titleEl.dataset.origTitle) {
            titleEl.dataset.origTitle = titleEl.innerHTML;
        }
        if (cfg && cfg.title) {
            titleEl.textContent = cfg.title;
        } else {
            titleEl.innerHTML = titleEl.dataset.origTitle;
        }
    }

    // --- Caption override (thêm div dưới section body) ---
    let capEl = sec.querySelector(":scope > .chart-config-caption");
    if (cfg && cfg.caption) {
        if (!capEl) {
            capEl = document.createElement("div");
            capEl.className = "chart-config-caption text-xs text-gray-500 italic mt-3 pt-2 border-t border-gray-100 dark:border-gray-700";
            sec.appendChild(capEl);
        }
        capEl.textContent = cfg.caption;
    } else if (capEl) {
        capEl.remove();
    }

    // --- Hidden override ---
    // Note: KHÔNG đè hidden gốc từ HTML default (compare/digest/burndown/sla/...).
    // Chỉ track "user_hidden" attribute để tách bạch.
    if (cfg && cfg.hidden) {
        sec.classList.add("hidden");
        sec.dataset.userHidden = "1";
    } else if (sec.dataset.userHidden === "1") {
        sec.classList.remove("hidden");
        delete sec.dataset.userHidden;
    }
}

/** Hiển thị pills trong header cho các section user đã ẩn — click để hiện lại. */
function _renderHiddenSectionPills() {
    let wrap = document.getElementById("hiddenSectionsPills");
    if (!wrap) {
        // Tạo wrapper 1 lần, chèn cạnh nút btnLayoutReset
        const btnReset = document.getElementById("btnLayoutReset");
        if (!btnReset) return;
        wrap = document.createElement("div");
        wrap.id = "hiddenSectionsPills";
        wrap.className = "hidden flex-wrap gap-1 items-center text-xs no-print";
        btnReset.parentElement.appendChild(wrap);
    }
    const userHidden = document.querySelectorAll('#dashboard [data-user-hidden="1"]');
    if (!userHidden.length) {
        wrap.classList.add("hidden");
        wrap.classList.remove("flex");
        wrap.innerHTML = "";
        return;
    }
    wrap.classList.remove("hidden");
    wrap.classList.add("flex");
    wrap.innerHTML = `<span class="text-blue-200">Ẩn:</span>` +
        Array.from(userHidden).map(el => {
            const label = _sectionShortLabel(el.id);
            return `<button onclick="_unhideSection('${el.id}')"
                class="bg-white/10 hover:bg-white/25 px-2 py-0.5 rounded"
                title="Bấm để hiện lại ${escapeAttr(label)}">
                ${escapeHtml(label)} ✕
            </button>`;
        }).join("");
}

function _sectionShortLabel(sid) {
    const map = {
        "section-module": "Module", "section-tasktype": "Task type",
        "section-matrix": "Matrix", "section-phase": "Phase",
        "section-pic": "PIC", "section-effort": "Effort",
        "section-priority": "Priority/Complexity/GAP",
        "section-fitgap-dashboard": "FIT/GAP",
        "section-function-diff": "Diff",
        "section-giaidoan": "Giai đoạn", "section-process": "Quy trình",
        "section-gantt": "Gantt", "section-duration": "Duration",
        "section-burndown": "Burndown", "section-slow": "Slow",
        "section-sla": "SLA", "section-capacity": "Capacity",
        "section-deps": "Deps", "section-baseline": "Baseline",
        "section-history": "History", "section-overdue": "Overdue",
        "section-unassigned": "Unassigned", "section-risk": "Risk",
        "section-stalled": "Đình trệ",
    };
    return map[sid] || sid.replace("section-", "");
}

window._unhideSection = async function (sid) {
    // Xoá config hidden cho section này
    const cur = _chartConfigsCache[sid] || {};
    const next = Object.assign({}, cur, { hidden: false });
    // Gọi upsert; nếu title/caption đều rỗng → backend sẽ xoá entry
    await _saveChartConfig(sid, next.title || "", next.caption || "", false);
};

async function _saveChartConfig(target_id, title, caption, hidden) {
    try {
        const r = await fetch(_apiUrl("chart-config"), {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ target_id, title, caption, hidden }),
        });
        if (!r.ok) throw new Error(await r.text());
        const data = await r.json();
        _chartConfigsCache = data.configs || {};
        applyChartConfigsToDom();
        showToast("Đã lưu cấu hình chart");
    } catch (err) {
        console.error("[_saveChartConfig]", err);
        showToast("Lưu cấu hình thất bại: " + err.message, "red");
    }
}

async function _resetChartConfig(target_id) {
    try {
        const r = await fetch(
            _apiUrl(`chart-config?target=${encodeURIComponent(target_id)}`),
            { method: "DELETE" }
        );
        if (!r.ok) throw new Error(await r.text());
        const data = await r.json();
        _chartConfigsCache = data.configs || {};
        applyChartConfigsToDom();
        showToast("Đã reset về mặc định");
    } catch (err) {
        showToast("Reset thất bại: " + err.message, "red");
    }
}

/** Inject gear button vào mỗi section (chạy 1 lần sau khi apply config). */
function injectChartConfigGears() {
    document.querySelectorAll('#dashboard [id^="section-"]').forEach(sec => {
        if (_CHART_CFG_SKIP_SECTIONS.has(sec.id)) return;
        if (sec.querySelector(":scope > .chart-config-gear")) return; // đã inject
        // Ensure relative positioning để absolute gear đứng đúng
        const cs = getComputedStyle(sec);
        if (cs.position === "static") sec.style.position = "relative";
        const btn = document.createElement("button");
        btn.className = "chart-config-gear no-print";
        btn.type = "button";
        btn.title = "Cấu hình title / caption / ẩn chart này";
        btn.setAttribute("aria-label", "Cấu hình chart");
        btn.innerHTML = "⚙️";
        btn.onclick = (e) => {
            e.stopPropagation();
            openChartConfigPopover(sec.id, btn);
        };
        sec.appendChild(btn);
    });
}

// Phase B: mapping section id → canvas id primary (chart mà Phase B config apply
// vào). Section không có canvas hoặc canvas đặc thù (Gantt, Burndown, Deps...)
// → SKIP list, không hiện tab Phase B.
const _SECTION_CANVAS_MAP = {
    "section-tasktype": "chartTaskType",
    "section-phase": "chartPhaseStacked",
    "section-pic": "chartPIC",
    "section-effort": "chartPICEffort",
    "section-giaidoan": "chartGiaidoan",
    "section-priority": "chartPriority",
    "section-fitgap-dashboard": "chartFitGapModule",
};
const _CHART_TYPES_ORDER = ["bar", "horizontalBar", "line", "area", "pie", "doughnut", "stackedBar", "groupedBar"];
let _chartFieldsCache = null;   // cache field list từ backend

async function _ensureChartFields() {
    if (_chartFieldsCache) return _chartFieldsCache;
    try {
        const r = await fetch(_apiUrl("chart-fields"));
        if (r.ok) _chartFieldsCache = await r.json();
    } catch (e) { console.error("[chart-fields]", e); }
    return _chartFieldsCache || { fields: {}, measures: {}, chart_types: {}, palettes: {} };
}

function openChartConfigPopover(target_id, anchorEl) {
    closeChartConfigPopover();
    _ensureChartFields().then(fields => _openChartConfigPopoverImpl(target_id, anchorEl, fields));
}

function _openChartConfigPopoverImpl(target_id, anchorEl, fields) {
    const cur = _chartConfigsCache[target_id] || {};
    const canvasId = _SECTION_CANVAS_MAP[target_id];
    // Config Phase B lưu dưới key = canvasId (nếu có), tách rời với Phase A
    const curB = canvasId ? (_chartConfigsCache[canvasId] || {}) : {};
    const label = _sectionShortLabel(target_id);
    const hasPhaseB = !!canvasId;

    const pop = document.createElement("div");
    pop.className = "chart-config-popover chart-config-popover-large no-print";
    pop.dataset.target = target_id;
    pop.dataset.canvas = canvasId || "";

    const fieldOpts = Object.entries(fields.fields || {}).map(
        ([k, v]) => `<option value="${escapeAttr(k)}">${escapeHtml(v)}</option>`
    ).join("");
    const measureOpts = Object.entries(fields.measures || {}).map(
        ([k, v]) => `<option value="${escapeAttr(k)}">${escapeHtml(v)}</option>`
    ).join("");
    const typeOpts = _CHART_TYPES_ORDER
        .filter(t => fields.chart_types?.[t])
        .map(t => `<option value="${t}">${escapeHtml(fields.chart_types[t])}</option>`).join("");
    const paletteOpts = Object.keys(fields.palettes || {}).map(
        p => `<option value="${p}">${p}</option>`
    ).join("");

    pop.innerHTML = `
        <div class="cc-header">
            <span class="cc-title">⚙️ Cấu hình: ${escapeHtml(label)}</span>
            <button class="cc-close" title="Đóng">✕</button>
        </div>
        <div class="cc-tabs">
            <button class="cc-tab active" data-tab="basic">Cơ bản</button>
            ${hasPhaseB ? `
            <button class="cc-tab" data-tab="type">Loại</button>
            <button class="cc-tab" data-tab="axes">Trục & Field</button>
            <button class="cc-tab" data-tab="colors">Màu</button>
            <button class="cc-tab" data-tab="filter">Filter riêng</button>
            ` : ""}
        </div>
        <div class="cc-body">
            <div class="cc-pane" data-pane="basic">
                <label class="cc-field">
                    <span>Tiêu đề</span>
                    <input type="text" class="cc-input-title" maxlength="200"
                        placeholder="Để trống = dùng title mặc định"
                        value="${escapeAttr(cur.title || "")}">
                </label>
                <label class="cc-field">
                    <span>Caption / ghi chú</span>
                    <textarea class="cc-input-caption" rows="2" maxlength="1000"
                        placeholder="Hiển thị dưới chart (text nhỏ, xám)">${escapeHtml(cur.caption || "")}</textarea>
                </label>
                <label class="cc-field-check">
                    <input type="checkbox" class="cc-input-hidden" ${cur.hidden ? "checked" : ""}>
                    <span>Ẩn chart này khỏi dashboard</span>
                </label>
            </div>
            ${hasPhaseB ? `
            <div class="cc-pane hidden" data-pane="type">
                <label class="cc-field">
                    <span>Loại biểu đồ</span>
                    <select class="cc-input-type">
                        <option value="">— Giữ mặc định —</option>
                        ${typeOpts}
                    </select>
                </label>
                <div class="text-xs text-gray-500 mt-1">
                    Đổi loại chart sẽ dùng data từ Field/Measure ở tab kế tiếp.
                    Nếu để trống Field → giữ nguyên data cũ.
                </div>
            </div>
            <div class="cc-pane hidden" data-pane="axes">
                <label class="cc-field">
                    <span>Trục X (dim)</span>
                    <select class="cc-input-xfield">
                        <option value="">— Giữ mặc định —</option>
                        ${fieldOpts}
                    </select>
                </label>
                <label class="cc-field">
                    <span>Measure Y</span>
                    <select class="cc-input-ymeasure">
                        <option value="count">Số function (count)</option>
                        ${measureOpts}
                    </select>
                </label>
                <label class="cc-field">
                    <span>Group / Stack theo (optional)</span>
                    <select class="cc-input-series">
                        <option value="">— Không group —</option>
                        ${fieldOpts}
                    </select>
                </label>
            </div>
            <div class="cc-pane hidden" data-pane="colors">
                <label class="cc-field">
                    <span>Palette</span>
                    <select class="cc-input-palette">
                        <option value="">— Giữ mặc định —</option>
                        ${paletteOpts}
                    </select>
                </label>
                <div id="ccPalettePreview" class="cc-palette-preview"></div>
            </div>
            <div class="cc-pane hidden" data-pane="filter">
                <label class="cc-field-check">
                    <input type="checkbox" class="cc-input-fo-enable" ${curB.filter_override ? "checked" : ""}>
                    <span>Dùng filter riêng cho chart này (ghi đè global filter)</span>
                </label>
                <div class="cc-fo-body ${curB.filter_override ? "" : "hidden"}">
                    <label class="cc-field">
                        <span>Chỉ lấy status</span>
                        <input type="text" class="cc-input-fo-statuses" placeholder="VD: Open,In-progress (phân cách ,)">
                    </label>
                    <label class="cc-field">
                        <span>Chỉ FIT/GAP</span>
                        <input type="text" class="cc-input-fo-fitgaps" placeholder="VD: GAP hoặc FIT,GAP">
                    </label>
                    <label class="cc-field-check">
                        <input type="checkbox" class="cc-input-fo-overdue">
                        <span>Chỉ overdue</span>
                    </label>
                </div>
            </div>
            ` : ""}
        </div>
        <div class="cc-footer">
            <button class="cc-btn cc-btn-reset">↺ Reset</button>
            <button class="cc-btn cc-btn-save">💾 Lưu</button>
        </div>
    `;
    document.body.appendChild(pop);
    _chartConfigsPopoverEl = pop;

    // Fill Phase B pre-values
    if (hasPhaseB) {
        pop.querySelector(".cc-input-type").value = curB.type || "";
        pop.querySelector(".cc-input-xfield").value = curB.x_field || "";
        pop.querySelector(".cc-input-ymeasure").value = curB.y_measure || "count";
        pop.querySelector(".cc-input-series").value = curB.series_field || "";
        pop.querySelector(".cc-input-palette").value =
            typeof curB.palette === "string" ? curB.palette : "";
        _renderPalettePreview(pop, fields);
        pop.querySelector(".cc-input-palette").addEventListener("change",
            () => _renderPalettePreview(pop, fields));
        const fo = curB.filter_override || {};
        pop.querySelector(".cc-input-fo-statuses").value = (fo.statuses || []).join(",");
        pop.querySelector(".cc-input-fo-fitgaps").value = (fo.fitgaps || []).join(",");
        pop.querySelector(".cc-input-fo-overdue").checked = !!fo.overdue_only;
        pop.querySelector(".cc-input-fo-enable").addEventListener("change", e => {
            pop.querySelector(".cc-fo-body").classList.toggle("hidden", !e.target.checked);
        });
    }

    // Tab switching
    pop.querySelectorAll(".cc-tab").forEach(btn => {
        btn.onclick = () => {
            pop.querySelectorAll(".cc-tab").forEach(b => b.classList.remove("active"));
            btn.classList.add("active");
            const tab = btn.dataset.tab;
            pop.querySelectorAll(".cc-pane").forEach(p => {
                p.classList.toggle("hidden", p.dataset.pane !== tab);
            });
        };
    });

    // Position (large: 400px)
    const r = anchorEl.getBoundingClientRect();
    const popW = 400;
    let left = r.right - popW;
    if (left < 8) left = 8;
    if (left + popW > window.innerWidth - 8) left = window.innerWidth - popW - 8;
    pop.style.left = `${left}px`;
    pop.style.top = `${r.bottom + window.scrollY + 6}px`;
    pop.style.width = `${popW}px`;

    // Handlers
    pop.querySelector(".cc-close").onclick = closeChartConfigPopover;
    pop.querySelector(".cc-btn-reset").onclick = async () => {
        // Reset cả section (Phase A) + canvas (Phase B) nếu có
        await _resetChartConfig(target_id);
        if (canvasId && _chartConfigsCache[canvasId]) {
            await _resetChartConfig(canvasId);
        }
        closeChartConfigPopover();
    };
    pop.querySelector(".cc-btn-save").onclick = async () => {
        // Phase A: save section
        const title = pop.querySelector(".cc-input-title").value.trim();
        const caption = pop.querySelector(".cc-input-caption").value.trim();
        const hidden = pop.querySelector(".cc-input-hidden").checked;
        await _saveChartConfig(target_id, title, caption, hidden);

        // Phase B: save canvas (nếu có canvas mapping)
        if (hasPhaseB) {
            const ctype = pop.querySelector(".cc-input-type").value.trim();
            const xf = pop.querySelector(".cc-input-xfield").value.trim();
            const ym = pop.querySelector(".cc-input-ymeasure").value.trim();
            const sf = pop.querySelector(".cc-input-series").value.trim();
            const pal = pop.querySelector(".cc-input-palette").value.trim();
            const foOn = pop.querySelector(".cc-input-fo-enable").checked;
            let filterOverride = null;
            if (foOn) {
                filterOverride = {};
                const st = pop.querySelector(".cc-input-fo-statuses").value.trim();
                if (st) filterOverride.statuses = st.split(",").map(s => s.trim()).filter(Boolean);
                const fg = pop.querySelector(".cc-input-fo-fitgaps").value.trim();
                if (fg) filterOverride.fitgaps = fg.split(",").map(s => s.trim()).filter(Boolean);
                if (pop.querySelector(".cc-input-fo-overdue").checked) filterOverride.overdue_only = true;
            }
            const bodyB = {
                target_id: canvasId,
                type: ctype || undefined,
                x_field: xf || undefined,
                y_measure: ym || undefined,
                series_field: sf || undefined,
                palette: pal || undefined,
                filter_override: filterOverride,
            };
            try {
                const r = await fetch(_apiUrl("chart-config"), {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify(bodyB),
                });
                if (r.ok) {
                    const d = await r.json();
                    _chartConfigsCache = d.configs || {};
                    // Rerender chart nếu có type / axes / palette / filter
                    if (ctype || xf || pal || foOn) {
                        rerenderChartWithConfig(canvasId, _chartConfigsCache[canvasId] || {});
                    }
                }
            } catch (err) {
                console.error("[savePhaseB]", err);
                showToast("Lưu cấu hình Phase B thất bại: " + err.message, "red");
            }
        }
        closeChartConfigPopover();
    };

    setTimeout(() => document.addEventListener("mousedown", _closePopOutside), 10);
}

function _renderPalettePreview(pop, fields) {
    const wrap = pop.querySelector("#ccPalettePreview");
    if (!wrap) return;
    const key = pop.querySelector(".cc-input-palette").value;
    const colors = fields.palettes?.[key] || fields.palettes?.default || [];
    wrap.innerHTML = colors.map(c =>
        `<span class="cc-swatch" style="background:${c}" title="${c}"></span>`
    ).join("");
}


/**
 * Rerender 1 chart theo cấu hình Phase B (type / axes / palette / filter).
 * Gọi POST /chart-aggregate để lấy data đã aggregate, destroy + create Chart mới.
 */
async function rerenderChartWithConfig(canvasId, cfg) {
    const canvas = document.getElementById(canvasId);
    if (!canvas) {
        console.warn(`[rerenderChart] canvas ${canvasId} not found`);
        return;
    }
    // Nếu không có x_field override → không có gì để aggregate (chỉ đổi type
    // mà không có data reshape ít khi hữu ích) → skip.
    if (!cfg.x_field) {
        showToast("Cần chọn Trục X ở tab 'Trục & Field' để đổi loại chart", "amber");
        return;
    }
    const payload = {
        x_field: cfg.x_field,
        y_measure: cfg.y_measure || "count",
        series_field: cfg.series_field || null,
        filters: cfg.filter_override || {},
        apply_global_filter: !cfg.filter_override,   // nếu ko có filter riêng → merge global
    };
    let agg;
    try {
        const r = await fetch(_apiUrl("chart-aggregate"), {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload),
        });
        if (!r.ok) throw new Error(await r.text());
        agg = await r.json();
    } catch (err) {
        console.error("[chart-aggregate]", err);
        showToast("Aggregate thất bại: " + err.message, "red");
        return;
    }

    const existing = Chart.getChart(canvas);
    if (existing) existing.destroy();

    // Palette lookup
    const fields = _chartFieldsCache || {};
    let colors = fields.palettes?.default || ["#3b82f6", "#10b981", "#f59e0b", "#ef4444"];
    if (typeof cfg.palette === "string" && fields.palettes?.[cfg.palette]) {
        colors = fields.palettes[cfg.palette];
    } else if (Array.isArray(cfg.palette) && cfg.palette.length) {
        colors = cfg.palette;
    }

    // Map user-friendly type → Chart.js real type + options
    const userType = cfg.type || "bar";
    let chartType = "bar";
    let extraOpts = { responsive: true, maintainAspectRatio: false, plugins: { legend: { position: "bottom" } } };
    let stacked = false;
    if (userType === "horizontalBar") { chartType = "bar"; extraOpts.indexAxis = "y"; }
    else if (userType === "line") { chartType = "line"; }
    else if (userType === "area") { chartType = "line"; }
    else if (userType === "pie") { chartType = "pie"; }
    else if (userType === "doughnut") { chartType = "doughnut"; }
    else if (userType === "stackedBar") { chartType = "bar"; stacked = true; }
    else if (userType === "groupedBar") { chartType = "bar"; }
    else { chartType = "bar"; }

    // Datasets: colors mapping
    const datasets = agg.datasets.map((ds, i) => {
        const c = colors[i % colors.length];
        const base = {
            label: ds.label,
            data: ds.data,
            backgroundColor: (chartType === "pie" || chartType === "doughnut")
                ? ds.data.map((_, j) => colors[j % colors.length])
                : c,
            borderColor: c,
            borderWidth: chartType === "line" ? 2 : 0,
            fill: userType === "area",
            tension: chartType === "line" ? 0.3 : 0,
        };
        return base;
    });

    if (stacked || userType === "stackedBar") {
        extraOpts.scales = {
            x: { stacked: true },
            y: { stacked: true, beginAtZero: true },
        };
    } else if (chartType === "bar") {
        extraOpts.scales = { y: { beginAtZero: true } };
    }

    try {
        new Chart(canvas, {
            type: chartType,
            data: { labels: agg.labels, datasets },
            options: extraOpts,
        });
    } catch (err) {
        console.error("[rerender Chart.js]", err);
        showToast("Render chart mới thất bại: " + err.message, "red");
    }
}

function _closePopOutside(e) {
    if (!_chartConfigsPopoverEl) return;
    if (!_chartConfigsPopoverEl.contains(e.target)) closeChartConfigPopover();
}

function closeChartConfigPopover() {
    if (_chartConfigsPopoverEl) {
        _chartConfigsPopoverEl.remove();
        _chartConfigsPopoverEl = null;
    }
    document.removeEventListener("mousedown", _closePopOutside);
}


// ========================================================================
// TASK 5 — STICKY GLOBAL FILTER: đo header height + shadow khi scroll
// ========================================================================

function _updateStickyHeaderVar() {
    const header = document.querySelector("header.no-print");
    if (!header) return;
    const h = header.offsetHeight;
    if (h > 0) {
        document.documentElement.style.setProperty("--header-h", `${h}px`);
    }
}

function _updateFilterScrolledClass() {
    const filter = document.getElementById("section-globalfilter");
    if (!filter) return;
    // Thêm shadow đậm khi user đã scroll xuống > 40px
    filter.classList.toggle("is-scrolled", window.scrollY > 40);
}

// Init 1 lần khi DOM ready + mỗi resize (header có thể wrap trên mobile)
window.addEventListener("DOMContentLoaded", () => {
    _updateStickyHeaderVar();
    _updateFilterScrolledClass();
});
window.addEventListener("resize", _updateStickyHeaderVar);
window.addEventListener("scroll", _updateFilterScrolledClass, { passive: true });


// ========================================================================
// TASK 18 — Sticky top block với auto-collapse compact mode khi scroll
// ========================================================================
// Threshold: 200px. Manual toggle (nút 🔼/🔽) override auto — nếu user
// force-compact hoặc force-full, ignore scroll cho đến khi user nhấn lại.

let _stickyManualState = null;   // null = auto; "compact" | "full" = manual

function _stickyApplyMode(mode) {
    const block = document.getElementById("stickyTopBlock");
    if (!block) return;
    const uploadBtn = document.getElementById("stickyUploadBtn");
    if (mode === "compact") {
        block.classList.add("compact", "scrolled");
        if (uploadBtn) uploadBtn.classList.remove("hidden");
    } else {
        block.classList.remove("compact");
        // Chỉ giữ shadow nếu đã scroll xuống thật (auto-detect)
        block.classList.toggle("scrolled", window.scrollY > 40);
        if (uploadBtn) uploadBtn.classList.add("hidden");
    }
    const btn = document.getElementById("stickyToggleBtn");
    if (btn) btn.textContent = mode === "compact" ? "🔽" : "🔼";
    // Update CSS var --header-h dùng cho sticky offset các phần tử khác
    if (typeof _updateStickyHeaderVar === "function") _updateStickyHeaderVar();
}

function _stickyAutoUpdate() {
    if (_stickyManualState) return;  // manual override
    const mode = window.scrollY >= 200 ? "compact" : "full";
    _stickyApplyMode(mode);
}

window._toggleStickyCompact = function () {
    const block = document.getElementById("stickyTopBlock");
    if (!block) return;
    const currentlyCompact = block.classList.contains("compact");
    _stickyManualState = currentlyCompact ? "full" : "compact";
    _stickyApplyMode(_stickyManualState);
    // Sau 5s không hoạt động manual → cho phép auto tiếp tục
    clearTimeout(window._stickyManualTimer);
    window._stickyManualTimer = setTimeout(() => {
        _stickyManualState = null;
        _stickyAutoUpdate();
    }, 5000);
};

window._scrollToUpload = function () {
    const uz = document.getElementById("uploadZone");
    if (uz) uz.scrollIntoView({ behavior: "smooth", block: "start" });
};

window.addEventListener("scroll", _stickyAutoUpdate, { passive: true });
window.addEventListener("DOMContentLoaded", _stickyAutoUpdate);


// ========================================================================
// TASK 4b — DRAG-DROP REORDER SECTION + PERSIST
// ========================================================================
//
// Cơ chế:
// - Dashboard root = <div id="dashboard">. Bên trong có 2 loại top-level element:
//   (a) <section id="section-XYZ">     (direct child)
//   (b) <section class="grid ..."> wrapper chứa <div id="section-XYZ"> con.
//   Drag-drop chỉ áp cho TOP-LEVEL children của #dashboard → đảm bảo giữ
//   nguyên cấu trúc grid (module+tasktype, pic+effort).
// - Section order lưu là "top-level id" — với grid wrapper, id = "grid:<child1>+<child2>"
//   để có thể restore đúng ngay cả khi user drag qua các grid.
//   (Cơ chế đơn giản: khi save, dùng data-section-key attribute; khi load, match theo key.)
// ========================================================================

let _sortableInstance = null;
let _originalDashboardHtml = null;

/** Lấy "key" ổn định cho top-level element trong dashboard. */
function _topLevelKey(el) {
    if (!el) return "";
    if (el.id && el.id.startsWith("section-")) return el.id;
    // Grid wrapper: build key từ id của các con trực tiếp
    const children = Array.from(el.querySelectorAll(":scope > [id^='section-']"))
        .map(c => c.id).filter(Boolean);
    if (children.length) return "grid:" + children.join("+");
    return "";
}

/** Đọc thứ tự top-level hiện tại từ DOM. */
function _readCurrentSectionOrderFromDom() {
    const dash = document.getElementById("dashboard");
    if (!dash) return [];
    // Bỏ qua section-summary-header (là <div> nội bộ, không phải section top-level cần reorder)
    return Array.from(dash.children)
        .filter(el => el.id !== "section-summary-header")
        .map(_topLevelKey)
        .filter(Boolean);
}

/** Reorder DOM top-level theo `order` (list of keys). */
function applySectionOrderToDom(order) {
    const dash = document.getElementById("dashboard");
    if (!dash || !Array.isArray(order) || !order.length) return;
    const byKey = new Map();
    Array.from(dash.children).forEach(el => {
        const k = _topLevelKey(el);
        if (k) byKey.set(k, el);
    });
    // Append theo order (bỏ những key không match); những element không nằm trong
    // order → giữ nguyên ở cuối (tránh mất hoàn toàn nếu có section mới sau upgrade).
    const seen = new Set();
    order.forEach(k => {
        const el = byKey.get(k);
        if (el) { dash.appendChild(el); seen.add(k); }
    });
    byKey.forEach((el, k) => {
        if (!seen.has(k)) dash.appendChild(el);
    });
}

/** Load custom order từ backend + apply nếu có. */
async function loadSectionOrder() {
    if (!currentProjectSlug) return;
    // Snapshot HTML gốc lần đầu tiên (cho reset)
    if (_originalDashboardHtml === null) {
        const dash = document.getElementById("dashboard");
        if (dash) _originalDashboardHtml = dash.innerHTML;
    }
    try {
        const r = await fetch(_apiUrl("section-order"));
        if (!r.ok) return;
        const data = await r.json();
        if (Array.isArray(data.order) && data.order.length) {
            applySectionOrderToDom(data.order);
            // Show nút reset khi có custom order
            const btnReset = document.getElementById("btnLayoutReset");
            if (btnReset) btnReset.classList.remove("hidden");
        }
    } catch (err) {
        console.error("[loadSectionOrder]", err);
    }
}

/** Persist order lên backend. */
async function saveSectionOrder() {
    if (!currentProjectSlug) return;
    const order = _readCurrentSectionOrderFromDom();
    try {
        const r = await fetch(_apiUrl("section-order"), {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ order }),
        });
        if (!r.ok) throw new Error(await r.text());
        const btnReset = document.getElementById("btnLayoutReset");
        if (btnReset) btnReset.classList.remove("hidden");
        showToast("Đã lưu thứ tự section");
    } catch (err) {
        console.error("[saveSectionOrder]", err);
        showToast("Lưu thứ tự thất bại: " + err.message, "red");
    }
}

/** Toggle chế độ chỉnh thứ tự (bật/tắt drag-drop). */
window.toggleLayoutEditMode = function () {
    const on = !document.body.classList.contains("layout-edit");
    document.body.classList.toggle("layout-edit", on);
    const label = document.getElementById("layoutEditLabel");
    if (label) label.textContent = on ? "✅ Xong" : "🔧 Chỉnh thứ tự";
    if (on) {
        _initSortable();
        showToast("Đang bật chế độ kéo thả — kéo section để đổi thứ tự");
    } else {
        _destroySortable();
        showToast("Đã tắt chế độ chỉnh thứ tự");
    }
};

function _initSortable() {
    if (_sortableInstance) return;
    if (typeof Sortable === "undefined") {
        showToast("SortableJS chưa load — reload trang.", "red");
        return;
    }
    const dash = document.getElementById("dashboard");
    if (!dash) return;
    _sortableInstance = Sortable.create(dash, {
        animation: 180,
        ghostClass: "sortable-ghost",
        chosenClass: "sortable-chosen",
        dragClass: "sortable-drag",
        // Không drag section-summary-header (div nội bộ, không phải section top-level)
        filter: "#section-summary-header",
        preventOnFilter: false,
        onEnd: () => {
            saveSectionOrder();
        },
    });
}

function _destroySortable() {
    if (_sortableInstance) {
        _sortableInstance.destroy();
        _sortableInstance = null;
    }
}

/** Reset về default HTML (xoá custom order). */
window.resetSectionOrder = async function () {
    if (!confirm("Reset về thứ tự mặc định?")) return;
    try {
        const r = await fetch(_apiUrl("section-order/reset"), { method: "POST" });
        if (!r.ok) throw new Error(await r.text());
        // Restore HTML gốc từ snapshot
        if (_originalDashboardHtml !== null) {
            const dash = document.getElementById("dashboard");
            if (dash) {
                // Note: không reload innerHTML để tránh mất Chart.js instances.
                // Thay vào đó → reload page giữ scroll top.
                location.reload();
                return;
            }
        }
        location.reload();
    } catch (err) {
        console.error("[resetSectionOrder]", err);
        showToast("Reset thất bại: " + err.message, "red");
    }
};

// ========================================================================
// T21 — DATA QUALITY PANEL
// ========================================================================
let _dqState = {
    issues: [],
    summary: null,
    filterSeverity: "all",
    filterCode: "all",
    page: 1,
    pageSize: 30,
};

async function loadDataQuality() {
    const section = document.getElementById("section-dataquality");
    if (!section) return;
    try {
        const qsFilter = _buildFilterQuery();
        const url = `/api/projects/${currentProjectSlug}/data-quality${qsFilter ? "?" + qsFilter : ""}`;
        const r = await fetch(url);
        if (!r.ok) throw new Error(await r.text());
        const d = await r.json();
        _dqState.issues = d.issues || [];
        _dqState.summary = d.summary || null;
        _dqState.page = 1;

        // Populate code filter dropdown
        _dqPopulateCodeFilter();
        // Bind filter events (idempotent)
        _dqBindEvents();

        // Show section (dù có 0 issue vẫn hiện — user cần biết dữ liệu clean)
        section.classList.remove("hidden");
        _dqRenderSummaryCards();
        _dqRenderTable();
    } catch (err) {
        console.error("[loadDataQuality]", err);
        section.classList.add("hidden");
    }
}

function _dqPopulateCodeFilter() {
    const sel = document.getElementById("dqCodeFilter");
    if (!sel) return;
    const codes = Object.keys((_dqState.summary?.by_code) || {}).sort();
    // Labels map (đồng bộ với ISSUE_META tiếng Việt)
    const labelMap = {};
    for (const it of _dqState.issues) labelMap[it.code] = it.label;
    sel.innerHTML = '<option value="all">Tất cả loại</option>' +
        codes.map(c => `<option value="${escapeAttr(c)}">${escapeHtml(labelMap[c] || c)} (${_dqState.summary.by_code[c]})</option>`).join("");
    sel.value = _dqState.filterCode;
}

function _dqBindEvents() {
    const sev = document.getElementById("dqSeverityFilter");
    const code = document.getElementById("dqCodeFilter");
    if (sev && !sev._dqBound) {
        sev._dqBound = true;
        sev.addEventListener("change", () => {
            _dqState.filterSeverity = sev.value;
            _dqState.page = 1;
            _dqRenderTable();
        });
    }
    if (code && !code._dqBound) {
        code._dqBound = true;
        code.addEventListener("change", () => {
            _dqState.filterCode = code.value;
            _dqState.page = 1;
            _dqRenderTable();
        });
    }
}

function _dqRenderSummaryCards() {
    const wrap = document.getElementById("dqSummaryCards");
    if (!wrap) return;
    const s = _dqState.summary || {};
    const sev = s.by_severity || {};
    const cleanPct = s.clean_pct ?? 100;
    const cleanColor = cleanPct >= 95 ? "text-green-700" : cleanPct >= 80 ? "text-yellow-700" : "text-red-700";
    wrap.innerHTML = `
        <div class="bg-slate-50 rounded-lg p-3 border">
            <div class="text-xs text-gray-500">Tổng function</div>
            <div class="text-2xl font-bold text-gray-800">${s.total_rows || 0}</div>
        </div>
        <div class="bg-green-50 rounded-lg p-3 border border-green-200">
            <div class="text-xs text-green-700">Function clean</div>
            <div class="text-2xl font-bold ${cleanColor}">${s.clean_rows || 0} <span class="text-sm font-normal">(${cleanPct}%)</span></div>
        </div>
        <div class="bg-red-50 rounded-lg p-3 border border-red-200">
            <div class="text-xs text-red-700">🔴 High</div>
            <div class="text-2xl font-bold text-red-700">${sev.high || 0}</div>
        </div>
        <div class="bg-orange-50 rounded-lg p-3 border border-orange-200">
            <div class="text-xs text-orange-700">🟠 Medium</div>
            <div class="text-2xl font-bold text-orange-700">${sev.medium || 0}</div>
        </div>
        <div class="bg-yellow-50 rounded-lg p-3 border border-yellow-200">
            <div class="text-xs text-yellow-700">🟡 Low</div>
            <div class="text-2xl font-bold text-yellow-700">${sev.low || 0}</div>
        </div>
    `;
}

function _dqFilteredIssues() {
    const s = _dqState.filterSeverity;
    const c = _dqState.filterCode;
    return _dqState.issues.filter(it => {
        if (s !== "all" && it.severity !== s) return false;
        if (c !== "all" && it.code !== c) return false;
        return true;
    });
}

function _dqRenderTable() {
    const tbody = document.getElementById("dqTable");
    if (!tbody) return;
    const items = _dqFilteredIssues();
    if (!items.length) {
        tbody.innerHTML = `<tr><td colspan="8" class="text-center py-6 text-green-600">
            ✅ Không có issue nào phù hợp filter. Dữ liệu clean!
        </td></tr>`;
        const pager = document.getElementById("dqPagerWrap");
        if (pager) pager.innerHTML = "";
        return;
    }
    const start = (_dqState.page - 1) * _dqState.pageSize;
    const pageItems = items.slice(start, start + _dqState.pageSize);
    // Badge màu severity
    const sevBadge = (sev) => {
        const map = {
            high: "bg-red-100 text-red-700 border-red-300",
            medium: "bg-orange-100 text-orange-700 border-orange-300",
            low: "bg-yellow-100 text-yellow-700 border-yellow-300",
        };
        return `<span class="inline-block text-xs px-2 py-0.5 rounded border ${map[sev] || ""}">${sev.toUpperCase()}</span>`;
    };
    tbody.innerHTML = pageItems.map(it => `
        <tr class="border-b hover:bg-slate-50">
            <td class="px-2 py-1.5 text-gray-500">${it.row_num}</td>
            <td class="px-2 py-1.5 font-mono text-xs">${escapeHtml(it.ma_cn || "—")}</td>
            <td class="px-2 py-1.5">${escapeHtml(it.ten_cn || "")}</td>
            <td class="px-2 py-1.5 text-blue-700">${escapeHtml(it.module || "")}</td>
            <td class="px-2 py-1.5 text-xs">${escapeHtml(it.phase || "")}</td>
            <td class="px-2 py-1.5">${sevBadge(it.severity)} ${escapeHtml(it.label)}</td>
            <td class="px-2 py-1.5 text-xs text-gray-600">${escapeHtml(it.detail)}</td>
            <td class="px-2 py-1.5 text-xs text-gray-700">${escapeHtml(it.suggestion)}</td>
        </tr>
    `).join("");
    // Pager đơn giản
    const totalPages = Math.max(1, Math.ceil(items.length / _dqState.pageSize));
    const pager = document.getElementById("dqPagerWrap");
    if (pager) {
        pager.innerHTML = `
            <div class="flex items-center justify-between text-xs text-gray-600">
                <div>Hiển thị ${start + 1}–${Math.min(start + pageItems.length, items.length)} / ${items.length} issue</div>
                <div class="flex items-center gap-1">
                    <button onclick="_dqGoPage(${_dqState.page - 1})" class="px-2 py-0.5 border rounded ${_dqState.page <= 1 ? "opacity-40 cursor-not-allowed" : "hover:bg-slate-100"}" ${_dqState.page <= 1 ? "disabled" : ""}>◀</button>
                    <span>Trang ${_dqState.page}/${totalPages}</span>
                    <button onclick="_dqGoPage(${_dqState.page + 1})" class="px-2 py-0.5 border rounded ${_dqState.page >= totalPages ? "opacity-40 cursor-not-allowed" : "hover:bg-slate-100"}" ${_dqState.page >= totalPages ? "disabled" : ""}>▶</button>
                </div>
            </div>
        `;
    }
}

window._dqGoPage = function (p) {
    const items = _dqFilteredIssues();
    const totalPages = Math.max(1, Math.ceil(items.length / _dqState.pageSize));
    _dqState.page = Math.max(1, Math.min(p, totalPages));
    _dqRenderTable();
};

window.exportDataQuality = function () {
    const qs = _buildFilterQuery();
    const url = `/api/projects/${currentProjectSlug}/export-data-quality${qs ? "?" + qs : ""}`;
    window.location.href = url;
};

// ========================================================================
// T22 — AGING WIP TRACKING
// ========================================================================
let _agingState = {
    threshold: 14,
    items: [],
    summary: null,
    page: 1,
    pageSize: 30,
    sortBy: "aging_days",
    sortDesc: true,
};

const _AGING_KEY = () => `aging_threshold_${currentProjectSlug || "default"}`;

async function loadAgingWip() {
    const section = document.getElementById("section-aging-wip");
    if (!section) return;
    // Restore threshold từ localStorage (per-project)
    try {
        const saved = parseInt(localStorage.getItem(_AGING_KEY()) || "");
        if (saved && saved > 0) _agingState.threshold = saved;
    } catch (e) {}

    _agingBindEvents();
    // Set slider display sync
    const slider = document.getElementById("agingThreshold");
    const label = document.getElementById("agingThresholdVal");
    if (slider) slider.value = _agingState.threshold;
    if (label) label.textContent = `${_agingState.threshold} ngày`;

    await _agingFetch();
    section.classList.remove("hidden");
}

async function _agingFetch() {
    try {
        const qs = _buildFilterQuery();
        const url = `/api/projects/${currentProjectSlug}/aging-wip?threshold=${_agingState.threshold}${qs ? "&" + qs : ""}`;
        const r = await fetch(url);
        if (!r.ok) throw new Error(await r.text());
        const d = await r.json();
        _agingState.items = d.items || [];
        _agingState.summary = d.summary || null;
        _agingState.page = 1;
        _agingRenderSummary();
        _agingRenderTable();
    } catch (err) {
        console.error("[agingWip]", err);
    }
}

function _agingBindEvents() {
    const slider = document.getElementById("agingThreshold");
    if (slider && !slider._agingBound) {
        slider._agingBound = true;
        // Debounce input event để tránh spam request
        let timer = null;
        slider.addEventListener("input", (e) => {
            const v = parseInt(e.target.value);
            _agingState.threshold = v;
            const label = document.getElementById("agingThresholdVal");
            if (label) label.textContent = `${v} ngày`;
            try { localStorage.setItem(_AGING_KEY(), String(v)); } catch (e) {}
            if (timer) clearTimeout(timer);
            timer = setTimeout(() => _agingFetch(), 250);
        });
    }
}

function _agingRenderSummary() {
    const wrap = document.getElementById("agingSummary");
    if (!wrap || !_agingState.summary) return;
    const s = _agingState.summary;
    const pctAging = s.total_wip ? Math.round(100 * s.total_aging / s.total_wip) : 0;
    wrap.innerHTML = `
        <div class="bg-slate-50 rounded-lg p-3 border">
            <div class="text-xs text-gray-500">Tổng WIP (In-progress)</div>
            <div class="text-2xl font-bold text-gray-800">${s.total_wip}</div>
        </div>
        <div class="bg-orange-50 rounded-lg p-3 border border-orange-200">
            <div class="text-xs text-orange-700">Aging (> ${_agingState.threshold}d)</div>
            <div class="text-2xl font-bold text-orange-700">${s.total_aging} <span class="text-sm font-normal">(${pctAging}%)</span></div>
        </div>
        <div class="bg-yellow-50 rounded-lg p-3 border border-yellow-200">
            <div class="text-xs text-yellow-700">Avg aging</div>
            <div class="text-2xl font-bold text-yellow-700">${s.avg_aging_days} <span class="text-sm font-normal">ngày</span></div>
        </div>
        <div class="bg-red-50 rounded-lg p-3 border border-red-200">
            <div class="text-xs text-red-700">Max aging</div>
            <div class="text-2xl font-bold text-red-700">${s.max_aging_days} <span class="text-sm font-normal">ngày</span></div>
        </div>
    `;
}

function _agingRenderTable() {
    const tbody = document.getElementById("agingTable");
    if (!tbody) return;
    const items = _agingState.items.slice().sort((a, b) => {
        const av = a[_agingState.sortBy], bv = b[_agingState.sortBy];
        const cmp = (av > bv ? 1 : av < bv ? -1 : 0);
        return _agingState.sortDesc ? -cmp : cmp;
    });
    if (!items.length) {
        tbody.innerHTML = `<tr><td colspan="9" class="text-center py-6 text-green-600">
            ✅ Không có WIP nào vượt ngưỡng ${_agingState.threshold} ngày!
        </td></tr>`;
        const pager = document.getElementById("agingPagerWrap");
        if (pager) pager.innerHTML = "";
        return;
    }
    const start = (_agingState.page - 1) * _agingState.pageSize;
    const pageItems = items.slice(start, start + _agingState.pageSize);
    const overColor = (over) => over > 30 ? "text-red-700 font-bold" : over >= 7 ? "text-orange-700 font-semibold" : "text-yellow-700";
    tbody.innerHTML = pageItems.map(it => `
        <tr class="border-b hover:bg-slate-50">
            <td class="px-2 py-1.5 font-mono text-xs">${escapeHtml(it.ma_cn || "—")}</td>
            <td class="px-2 py-1.5">${escapeHtml(it.ten_cn || "")}</td>
            <td class="px-2 py-1.5 text-blue-700">${escapeHtml(it.module || "")}</td>
            <td class="px-2 py-1.5 text-xs">${escapeHtml(it.phase || "")}</td>
            <td class="px-2 py-1.5 text-xs">${escapeHtml(it.pic || "—")}</td>
            <td class="px-2 py-1.5 text-xs">${escapeHtml(it.start_date || "—")}</td>
            <td class="px-2 py-1.5 text-right font-semibold">${it.aging_days}d</td>
            <td class="px-2 py-1.5 text-right ${overColor(it.over_by_days)}">+${it.over_by_days}d</td>
            <td class="px-2 py-1.5 text-xs">${escapeHtml(it.priority || "")}</td>
        </tr>
    `).join("");
    const totalPages = Math.max(1, Math.ceil(items.length / _agingState.pageSize));
    const pager = document.getElementById("agingPagerWrap");
    if (pager) {
        pager.innerHTML = `
            <div class="flex items-center justify-between text-xs text-gray-600">
                <div>Hiển thị ${start + 1}–${Math.min(start + pageItems.length, items.length)} / ${items.length}</div>
                <div class="flex items-center gap-1">
                    <button onclick="_agingGoPage(${_agingState.page - 1})" class="px-2 py-0.5 border rounded ${_agingState.page <= 1 ? "opacity-40 cursor-not-allowed" : "hover:bg-slate-100"}" ${_agingState.page <= 1 ? "disabled" : ""}>◀</button>
                    <span>Trang ${_agingState.page}/${totalPages}</span>
                    <button onclick="_agingGoPage(${_agingState.page + 1})" class="px-2 py-0.5 border rounded ${_agingState.page >= totalPages ? "opacity-40 cursor-not-allowed" : "hover:bg-slate-100"}" ${_agingState.page >= totalPages ? "disabled" : ""}>▶</button>
                </div>
            </div>
        `;
    }
}

window._agingSort = function (col) {
    if (_agingState.sortBy === col) _agingState.sortDesc = !_agingState.sortDesc;
    else { _agingState.sortBy = col; _agingState.sortDesc = true; }
    _agingRenderTable();
};

window._agingGoPage = function (p) {
    const totalPages = Math.max(1, Math.ceil(_agingState.items.length / _agingState.pageSize));
    _agingState.page = Math.max(1, Math.min(p, totalPages));
    _agingRenderTable();
};

window.exportAgingWip = function () {
    const qs = _buildFilterQuery();
    const url = `/api/projects/${currentProjectSlug}/export-aging-wip?threshold=${_agingState.threshold}${qs ? "&" + qs : ""}`;
    window.location.href = url;
};

// ========================================================================
// T23 — COMMAND PALETTE (Ctrl+K / Cmd+K / /)
// ========================================================================
// Danh sách "sections" lấy từ sidebar (auto-detect, không hardcode).
// Danh sách "actions" cứng: export PDF, export Excel, apply filter reset...
// Danh sách "functions" fetch từ /api/projects/<slug>/search với query hiện tại.

const _cmdState = {
    query: "",
    items: [],       // filtered items hiện tại
    selectedIdx: 0,
    functionResults: [],
};

const _CMD_ACTIONS = [
    { id: "act.reset-filter", label: "🔄 Reset tất cả filter global", kind: "action",
      run: () => { globalFilters = { modules: [], processes: [], pics: [] };
                   tryLoadDashboardForCurrent(true);
                   showToast("Đã reset filter"); } },
    { id: "act.export-pdf", label: "📄 Xuất PDF báo cáo tuần", kind: "action",
      run: () => { if (typeof openPdfExportModal === "function") openPdfExportModal();
                   else showToast("Chưa sẵn sàng"); } },
    { id: "act.export-overdue", label: "📥 Xuất Excel Overdue", kind: "action",
      run: () => { if (typeof exportOverdue === "function") exportOverdue();
                   else showToast("Chưa sẵn sàng"); } },
    { id: "act.export-dq", label: "🩺 Xuất Excel Data Quality", kind: "action",
      run: () => exportDataQuality() },
    { id: "act.export-aging", label: "⏳ Xuất Excel Aging WIP", kind: "action",
      run: () => exportAgingWip() },
    { id: "act.toggle-theme", label: "🌓 Đổi theme (Light/Dark)", kind: "action",
      run: () => { if (typeof toggleTheme === "function") toggleTheme();
                   else document.documentElement.classList.toggle("dark"); } },
    { id: "act.layout-edit", label: "🔧 Bật/tắt drag-drop sắp xếp section", kind: "action",
      run: () => { if (typeof toggleLayoutEditMode === "function") toggleLayoutEditMode(); } },
    { id: "act.print", label: "🖨️ In dashboard hiện tại", kind: "action",
      run: () => window.print() },
];

function _cmdCollectSections() {
    // Auto-detect từ sidebar nav — mọi <a href="#section-*">
    const anchors = document.querySelectorAll('#sidebarNav a[href^="#section-"]');
    return Array.from(anchors).map(a => ({
        id: "sec." + a.getAttribute("href"),
        label: `📍 ${a.textContent.trim()}`,
        kind: "section",
        target: a.getAttribute("href"),
        run: () => {
            const el = document.querySelector(a.getAttribute("href"));
            if (el) el.scrollIntoView({ behavior: "smooth", block: "start" });
        },
    }));
}

function _cmdFuzzyScore(text, q) {
    // Simple fuzzy: mỗi ký tự q phải xuất hiện theo thứ tự trong text.
    // Score = số ký tự match liên tiếp / khoảng cách.
    if (!q) return 1;
    text = text.toLowerCase();
    q = q.toLowerCase();
    // Exact substring match ưu tiên cao nhất
    if (text.includes(q)) return 1000 + (100 - text.indexOf(q));
    let ti = 0, qi = 0, score = 0, streak = 0;
    while (ti < text.length && qi < q.length) {
        if (text[ti] === q[qi]) {
            streak++;
            score += streak;
            qi++;
        } else {
            streak = 0;
        }
        ti++;
    }
    return qi === q.length ? score : 0;
}

async function _cmdFetchFunctions(q) {
    if (!q || q.length < 2 || !currentProjectSlug) {
        _cmdState.functionResults = [];
        return;
    }
    try {
        const r = await fetch(`/api/projects/${currentProjectSlug}/function-search?q=${encodeURIComponent(q)}&limit=8`);
        if (!r.ok) return;
        const d = await r.json();
        _cmdState.functionResults = (d.items || []).map(fn => ({
            id: "fn." + (fn.row_num || fn.ma_cn),
            label: `🧩 ${fn.ma_cn || "?"} — ${fn.ten_cn || ""}`,
            sub: `${fn.module || ""} · ${fn.quy_trinh || ""}`,
            kind: "function",
            run: () => {
                if (typeof openFunctionDetail === "function" && fn.row_num) {
                    openFunctionDetail(fn.row_num);
                } else {
                    showToast(`Không mở được modal cho ${fn.ma_cn}`);
                }
            },
        }));
    } catch (err) {
        console.error("[cmd fetchFunctions]", err);
    }
}

function _cmdBuildItems() {
    const q = _cmdState.query.trim();
    // Nhóm 3: sections + actions (static) + functions (dynamic)
    const staticItems = [..._cmdCollectSections(), ..._CMD_ACTIONS];
    let items;
    if (!q) {
        items = staticItems.slice(0, 20);
    } else {
        // Fuzzy filter + score
        const scored = staticItems.map(it => ({ it, s: _cmdFuzzyScore(it.label, q) }))
            .filter(x => x.s > 0)
            .sort((a, b) => b.s - a.s);
        items = scored.slice(0, 15).map(x => x.it);
        // Prepend function search results (đã fetch async ở input handler)
        items = [..._cmdState.functionResults, ...items];
    }
    _cmdState.items = items;
    _cmdState.selectedIdx = Math.min(_cmdState.selectedIdx, Math.max(0, items.length - 1));
}

function _cmdRender() {
    const list = document.getElementById("cmdPaletteList");
    if (!list) return;
    if (!_cmdState.items.length) {
        list.innerHTML = `<div class="px-4 py-6 text-center text-gray-400">Không có kết quả</div>`;
        return;
    }
    list.innerHTML = _cmdState.items.map((it, i) => `
        <div class="cmd-item px-4 py-2 cursor-pointer flex items-center justify-between ${i === _cmdState.selectedIdx ? "bg-blue-50 border-l-2 border-blue-500" : "hover:bg-slate-50"}"
             data-idx="${i}">
            <div>
                <div class="text-sm text-gray-800">${escapeHtml(it.label)}</div>
                ${it.sub ? `<div class="text-xs text-gray-500">${escapeHtml(it.sub)}</div>` : ""}
            </div>
            <span class="text-xs text-gray-400">${it.kind === "section" ? "Section" : it.kind === "action" ? "Action" : "Function"}</span>
        </div>
    `).join("");
    // Bind click
    list.querySelectorAll(".cmd-item").forEach(el => {
        el.addEventListener("click", () => {
            _cmdState.selectedIdx = parseInt(el.dataset.idx);
            _cmdExecute();
        });
    });
    // Scroll selected into view
    const sel = list.querySelector(`.cmd-item[data-idx="${_cmdState.selectedIdx}"]`);
    if (sel) sel.scrollIntoView({ block: "nearest" });
}

function _cmdExecute() {
    const it = _cmdState.items[_cmdState.selectedIdx];
    if (!it) return;
    closeCmdPalette();
    try { it.run(); } catch (err) { console.error("[cmd run]", err); }
}

window.openCmdPalette = function () {
    const m = document.getElementById("cmdPaletteModal");
    if (!m) return;
    m.classList.remove("hidden");
    m.classList.add("flex");
    _cmdState.query = "";
    _cmdState.selectedIdx = 0;
    _cmdState.functionResults = [];
    _cmdBuildItems();
    _cmdRender();
    const input = document.getElementById("cmdPaletteInput");
    if (input) { input.value = ""; setTimeout(() => input.focus(), 50); }
};

window.closeCmdPalette = function () {
    const m = document.getElementById("cmdPaletteModal");
    if (!m) return;
    m.classList.add("hidden");
    m.classList.remove("flex");
};

// Bind global hotkeys + input + arrow keys
document.addEventListener("DOMContentLoaded", () => {
    const input = document.getElementById("cmdPaletteInput");
    const modal = document.getElementById("cmdPaletteModal");
    if (!input || !modal) return;

    // Debounced function search
    let fetchTimer = null;
    input.addEventListener("input", (e) => {
        _cmdState.query = e.target.value;
        _cmdState.selectedIdx = 0;
        _cmdBuildItems();
        _cmdRender();
        if (fetchTimer) clearTimeout(fetchTimer);
        fetchTimer = setTimeout(async () => {
            await _cmdFetchFunctions(_cmdState.query.trim());
            _cmdBuildItems();
            _cmdRender();
        }, 200);
    });

    // Keyboard nav trong input
    input.addEventListener("keydown", (e) => {
        if (e.key === "ArrowDown") {
            e.preventDefault();
            _cmdState.selectedIdx = Math.min(_cmdState.selectedIdx + 1, _cmdState.items.length - 1);
            _cmdRender();
        } else if (e.key === "ArrowUp") {
            e.preventDefault();
            _cmdState.selectedIdx = Math.max(_cmdState.selectedIdx - 1, 0);
            _cmdRender();
        } else if (e.key === "Enter") {
            e.preventDefault();
            _cmdExecute();
        } else if (e.key === "Escape") {
            e.preventDefault();
            closeCmdPalette();
        }
    });

    // Global hotkey: Ctrl+K / Cmd+K / /
    document.addEventListener("keydown", (e) => {
        // Không kích hoạt nếu đang gõ trong ô input khác (trừ khi Ctrl/Cmd+K)
        const inField = /^(INPUT|TEXTAREA|SELECT)$/.test(document.activeElement?.tagName || "");
        const ctrlK = (e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k";
        const slash = e.key === "/" && !inField;
        if (ctrlK || slash) {
            e.preventDefault();
            openCmdPalette();
        } else if (e.key === "Escape" && !modal.classList.contains("hidden")) {
            e.preventDefault();
            closeCmdPalette();
        }
    });
});

// ========================================================================
// T24 — BOOKMARK + NOTES (per-function)
// ========================================================================
let _currentFnMaCn = "";     // Mã CN đang mở trong functionDetailModal
let _bookmarksCache = new Set();
let _notesCache = {};        // { ma_cn: {note, updated_at} }

async function loadBookmarks() {
    if (!currentProjectSlug) return;
    try {
        const r = await fetch(`/api/projects/${currentProjectSlug}/bookmarks`);
        if (!r.ok) return;
        const d = await r.json();
        _bookmarksCache = new Set((d.items || []).map(it => it.ma_cn));
        _notesCache = {};
        for (const it of (d.items || [])) {
            if (it.note) _notesCache[it.ma_cn] = { note: it.note, updated_at: it.note_updated_at };
        }
        _renderBookmarkSection(d.items || []);
    } catch (err) {
        console.error("[loadBookmarks]", err);
    }
}

function _renderBookmarkSection(items) {
    const section = document.getElementById("section-my-bookmarks");
    const list = document.getElementById("bmList");
    const total = document.getElementById("bmTotal");
    if (!section || !list) return;
    if (total) total.textContent = items.length;
    if (!items.length) {
        section.classList.add("hidden");
        return;
    }
    section.classList.remove("hidden");
    list.innerHTML = items.map(it => `
        <div class="border rounded-lg p-3 bg-yellow-50 hover:bg-yellow-100 cursor-pointer transition"
             onclick="openFunctionDetailByMaCn('${escapeAttr(it.ma_cn)}')">
            <div class="flex items-start justify-between gap-2">
                <div class="flex-1 min-w-0">
                    <div class="text-xs font-mono text-gray-500">${escapeHtml(it.ma_cn)}</div>
                    <div class="text-sm font-semibold text-gray-800 truncate">${escapeHtml(it.ten_cn || "")}</div>
                    <div class="text-xs text-blue-700 mt-0.5">${escapeHtml(it.module || "")} · ${escapeHtml(it.quy_trinh || "")}</div>
                    ${it.note ? `<div class="text-xs text-gray-700 mt-2 line-clamp-2 border-l-2 border-yellow-400 pl-2 italic">📝 ${escapeHtml(it.note)}</div>` : ""}
                </div>
                <button onclick="event.stopPropagation(); toggleBookmarkByMaCn('${escapeAttr(it.ma_cn)}')"
                        class="text-yellow-600 hover:text-red-500 text-lg" title="Bỏ bookmark">⭐</button>
            </div>
        </div>
    `).join("");
}

async function openFunctionDetailByMaCn(maCn) {
    // Tra row_num từ metricsData (nếu có), fallback gọi function-search
    let rowNum = null;
    try {
        const r = await fetch(`/api/projects/${currentProjectSlug}/function-search?q=${encodeURIComponent(maCn)}&limit=5`);
        if (r.ok) {
            const d = await r.json();
            const match = (d.items || []).find(x => String(x.ma_cn).trim() === maCn);
            if (match) rowNum = match.row_num;
        }
    } catch (e) {}
    if (!rowNum) {
        showToast(`Không tìm thấy function ${maCn}`, "red");
        return;
    }
    openFunctionDetail(rowNum);
}

function _syncBookmarkNoteUi() {
    if (!_currentFnMaCn) return;
    const isBm = _bookmarksCache.has(_currentFnMaCn);
    const btn = document.getElementById("fnDetailBookmarkBtn");
    if (btn) {
        btn.textContent = isBm ? "⭐" : "☆";
        btn.title = isBm ? "Bỏ bookmark" : "Bookmark chức năng này";
    }
    // Note preload vào textarea (chưa mở editor)
    const ta = document.getElementById("fnDetailNoteTextarea");
    const noteInfo = document.getElementById("fnDetailNoteUpdatedAt");
    const noteBtn = document.getElementById("fnDetailNoteBtn");
    const cached = _notesCache[_currentFnMaCn];
    if (ta) ta.value = cached?.note || "";
    if (noteInfo) noteInfo.textContent = cached?.updated_at ? `Cập nhật: ${cached.updated_at}` : "";
    if (noteBtn) {
        noteBtn.textContent = cached?.note ? "📝" : "🗒️";
        noteBtn.title = cached?.note ? "Sửa ghi chú (đã có)" : "Thêm ghi chú";
    }
}

window.toggleBookmarkCurrent = async function () {
    if (!_currentFnMaCn) { showToast("Không có mã CN để bookmark", "red"); return; }
    return toggleBookmarkByMaCn(_currentFnMaCn);
};

window.toggleBookmarkByMaCn = async function (maCn) {
    try {
        const r = await fetch(`/api/projects/${currentProjectSlug}/bookmarks/toggle`, {
            method: "POST",
            headers: {"Content-Type": "application/json"},
            body: JSON.stringify({ ma_cn: maCn }),
        });
        if (!r.ok) throw new Error(await r.text());
        const d = await r.json();
        if (d.bookmarked) _bookmarksCache.add(maCn);
        else _bookmarksCache.delete(maCn);
        showToast(d.bookmarked ? `⭐ Đã bookmark ${maCn}` : `☆ Bỏ bookmark ${maCn}`);
        _syncBookmarkNoteUi();
        loadBookmarks();  // Refresh section
    } catch (err) {
        console.error("[toggleBookmark]", err);
        showToast("Lỗi bookmark: " + err.message, "red");
    }
};

window.openNoteEditor = function () {
    if (!_currentFnMaCn) { showToast("Không có mã CN", "red"); return; }
    const editor = document.getElementById("fnDetailNoteEditor");
    if (!editor) return;
    editor.classList.remove("hidden");
    const ta = document.getElementById("fnDetailNoteTextarea");
    if (ta) setTimeout(() => ta.focus(), 50);
};

window.closeNoteEditor = function () {
    const editor = document.getElementById("fnDetailNoteEditor");
    if (editor) editor.classList.add("hidden");
};

window.saveCurrentNote = async function () {
    if (!_currentFnMaCn) return;
    const ta = document.getElementById("fnDetailNoteTextarea");
    const note = (ta?.value || "").trim();
    try {
        const r = await fetch(`/api/projects/${currentProjectSlug}/notes/${encodeURIComponent(_currentFnMaCn)}`, {
            method: "PUT",
            headers: {"Content-Type": "application/json"},
            body: JSON.stringify({ note }),
        });
        if (!r.ok) throw new Error(await r.text());
        if (note) _notesCache[_currentFnMaCn] = { note, updated_at: new Date().toISOString().slice(0, 19) };
        else delete _notesCache[_currentFnMaCn];
        showToast("💾 Đã lưu ghi chú");
        _syncBookmarkNoteUi();
        closeNoteEditor();
        loadBookmarks();
    } catch (err) {
        showToast("Lỗi lưu note: " + err.message, "red");
    }
};

window.deleteCurrentNote = async function () {
    if (!_currentFnMaCn) return;
    if (!confirm(`Xóa ghi chú của ${_currentFnMaCn}?`)) return;
    try {
        const r = await fetch(`/api/projects/${currentProjectSlug}/notes/${encodeURIComponent(_currentFnMaCn)}`, {
            method: "DELETE",
        });
        if (!r.ok) throw new Error(await r.text());
        delete _notesCache[_currentFnMaCn];
        showToast("🗑️ Đã xóa ghi chú");
        _syncBookmarkNoteUi();
        closeNoteEditor();
        loadBookmarks();
    } catch (err) {
        showToast("Lỗi xóa: " + err.message, "red");
    }
};

// Ctrl+Enter trong textarea = save; Esc = close editor
document.addEventListener("DOMContentLoaded", () => {
    const ta = document.getElementById("fnDetailNoteTextarea");
    if (!ta) return;
    ta.addEventListener("keydown", (e) => {
        if ((e.ctrlKey || e.metaKey) && e.key === "Enter") {
            e.preventDefault();
            saveCurrentNote();
        } else if (e.key === "Escape") {
            e.preventDefault();
            closeNoteEditor();
        }
    });
});
