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

    // T32: restore "Bỏ qua Column Mapping wizard" checkbox từ localStorage
    if (typeof _uploadInitSkipWizardChk === "function") {
        _uploadInitSkipWizardChk();
    }

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
    // T34 Task 4: attach unified help buttons + gợi onboarding tour lần đầu
    try {
        if (typeof window.attachUnifiedSectionHelp === "function") {
            setTimeout(() => window.attachUnifiedSectionHelp(), 600);
        }
        if (typeof window.maybeStartOnboardingTour === "function") {
            setTimeout(() => window.maybeStartOnboardingTour(), 1500);
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
        // b9: reset matrix cache khi filter đổi — nếu user đang xem mode
        // process, sẽ auto re-fetch qua renderPhaseMatrix; nếu mode module
        // → dùng data mới từ /dashboard.
        _matrixCache = null;
        const url = _buildDashboardUrl();
        const r = await fetch(url);
        if (!r.ok) {
            showToast("Không tải được dashboard", "red");
            return;
        }
        const data = await r.json();
        applyDashboardResponse(data);
        // Nếu user đang ở mode process, refetch matrix với filter mới.
        if (_matrixGroupBy === "process") {
            setMatrixGroupBy("process", /*force=*/true);
        }
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

/**
 * UX7: Cell "👁 Xem" cho các bảng lưới (Overdue, Unassigned, Stalled, Risk,
 * Effort, Duration, Aging WIP, Bookmark, custom drill result). Thay vì cả
 * row bắt click, chỉ icon 👁 ở cột cuối bắt click. Gọi
 * openFunctionDetailByMaCn(maCn) để mở modal chi tiết function.
 * - `title` mặc định "Xem chi tiết".
 * - Nếu không có maCn hợp lệ → render ô rỗng.
 */
function _viewIconCell(maCn, opts) {
    const s = String(maCn || "").trim();
    if (!s) return `<td class="px-2 py-1 text-center text-gray-300">—</td>`;
    const title = (opts && opts.title) || "Xem chi tiết function";
    const cls = (opts && opts.cls) || "px-2 py-1 text-center";
    return `<td class="${cls}"><button type="button" class="view-icon-btn" 
        onclick="event.stopPropagation();openFunctionDetailByMaCn('${escapeAttr(s)}')"
        title="${escapeHtml(title)}">👁</button></td>`;
}

// ========================================================================
// UPLOAD
// ========================================================================
//
// T32: Mặc định upload đi qua Column Mapping Wizard (preview → user confirm
// mapping → upload-confirm). Checkbox "Bỏ qua wizard" trong upload zone
// (persist localStorage) cho user chuyên nghiệp bypass — dùng flow cũ.

async function handleFile(file) {
    if (!file.name.toLowerCase().endsWith(".xlsx") && !file.name.toLowerCase().endsWith(".xls")) {
        showToast("Chỉ hỗ trợ file .xlsx", "red");
        return;
    }
    const skipWizard = _uploadReadSkipWizardPref();
    if (skipWizard) {
        return _uploadLegacyFlow(file);
    }
    return _uploadWithWizard(file);
}

async function _uploadLegacyFlow(file) {
    document.getElementById("uploadProgress").classList.remove("hidden");
    const formData = new FormData();
    formData.append("file", file);
    const threshold = document.getElementById("durationThreshold")?.value || 3;
    try {
        const url = `/api/projects/${currentProjectSlug}/upload?threshold=${threshold}`;
        const resp = await fetch(url, { method: "POST", body: formData });
        const data = await resp.json();
        if (data.error) {
            showToast("Lỗi: " + data.error, "red");
            return;
        }
        applyDashboardResponse(data);
        await loadProjectList();
        showToast(`Đã tải ${data.rows_count} chức năng vào project "${data.project.name}"!`);
    } catch (err) {
        showToast("Lỗi kết nối server: " + err.message, "red");
    } finally {
        document.getElementById("uploadProgress").classList.add("hidden");
    }
}

// ------------------------------------------------------------
// T32: Column Mapping Wizard
// ------------------------------------------------------------

const _UCM_PREF_KEY = "ihrp_upload_skip_wizard";

const _ucmState = {
    tmpId: null,
    filename: null,
    headers: [],
    ihrpColumns: [],
    autoSuggest: {},        // {ihrp_col: [{header, score}, ...]}
    currentMapping: {},     // {ihrp_col: actual_header} — user pick
    presets: [],
    columnTypes: {},        // T34 Task 3B — {header: {type, badge, samples}}
    showIncompatible: false,// T34 Task 3B — checkbox "Hiện tất cả (bỏ filter kiểu)"
    dryRunResult: null,     // T34 Task 3E — kết quả validate-mapping gần nhất
};

function _uploadReadSkipWizardPref() {
    try {
        return localStorage.getItem(_UCM_PREF_KEY) === "1";
    } catch (e) { return false; }
}

function _uploadSaveSkipWizardPref() {
    const el = document.getElementById("uploadSkipWizardChk");
    try {
        localStorage.setItem(_UCM_PREF_KEY, el?.checked ? "1" : "0");
    } catch (e) { /* localStorage disabled */ }
}

/** Restore checkbox state khi trang load (được gọi trong initial setup). */
function _uploadInitSkipWizardChk() {
    const el = document.getElementById("uploadSkipWizardChk");
    if (el) el.checked = _uploadReadSkipWizardPref();
}

async function _uploadWithWizard(file) {
    document.getElementById("uploadProgress").classList.remove("hidden");
    const formData = new FormData();
    formData.append("file", file);
    try {
        const url = `/api/upload-preview?project_slug=${encodeURIComponent(currentProjectSlug || "default")}`;
        const resp = await fetch(url, { method: "POST", body: formData });
        const data = await resp.json();
        if (data.error) {
            showToast("Lỗi: " + data.error, "red");
            return;
        }
        _ucmState.tmpId = data.tmp_id;
        _ucmState.filename = data.filename;
        _ucmState.headers = data.headers || [];
        _ucmState.ihrpColumns = data.ihrp_columns || [];
        _ucmState.autoSuggest = data.auto_suggest || {};
        _ucmState.presets = data.presets || [];
        // T34 Task 3B — column type info cho badge + filter
        _ucmState.columnTypes = data.column_types || {};
        _ucmState.dryRunResult = null;
        // Pre-fill mapping bằng top suggestion (score cao) — user có thể sửa
        _ucmState.currentMapping = {};
        for (const ihrp of _ucmState.ihrpColumns) {
            const cands = _ucmState.autoSuggest[ihrp] || [];
            if (cands.length > 0 && cands[0].score >= 0.7) {
                _ucmState.currentMapping[ihrp] = cands[0].header;
            }
        }
        _ucmOpenModal(data);
    } catch (err) {
        showToast("Lỗi kết nối server: " + err.message, "red");
    } finally {
        document.getElementById("uploadProgress").classList.add("hidden");
    }
}

function _ucmOpenModal(previewData) {
    const modal = document.getElementById("uploadMappingModal");
    if (!modal) return;
    document.getElementById("ucmFilename").textContent = previewData.filename || "—";
    document.getElementById("ucmSheetName").textContent = previewData.sheet_name || "—";
    _ucmRenderPreviewTable(previewData.headers, previewData.preview_rows);
    _ucmRenderPresetSelect();
    _ucmRenderMappingTable();
    _ucmUpdateStats();
    modal.classList.remove("hidden");
    modal.classList.add("flex");
}

function closeUploadMappingModal() {
    const modal = document.getElementById("uploadMappingModal");
    if (!modal) return;
    modal.classList.add("hidden");
    modal.classList.remove("flex");
    _ucmState.tmpId = null;
}
window.closeUploadMappingModal = closeUploadMappingModal;

function _ucmRenderPreviewTable(headers, rows) {
    const thead = document.querySelector("#ucmPreviewTable thead");
    const tbody = document.querySelector("#ucmPreviewTable tbody");
    if (!thead || !tbody) return;
    thead.innerHTML = "<tr>" + (headers || []).map(h =>
        `<th class="px-2 py-1 text-left border-b whitespace-nowrap">${escapeHtml(h || "")}</th>`
    ).join("") + "</tr>";
    tbody.innerHTML = (rows || []).map(row =>
        `<tr class="border-b hover:bg-slate-50 dark:hover:bg-slate-700/50">${
            (row || []).map(cell =>
                `<td class="px-2 py-1 whitespace-nowrap max-w-xs truncate">${escapeHtml(cell == null ? "" : String(cell))}</td>`
            ).join("")
        }</tr>`
    ).join("");
}

function _ucmRenderPresetSelect() {
    const sel = document.getElementById("ucmPresetSelect");
    if (!sel) return;
    sel.innerHTML = '<option value="">— chọn preset —</option>';
    for (const p of (_ucmState.presets || [])) {
        const opt = document.createElement("option");
        opt.value = p.name;
        opt.textContent = `${p.name} (${Object.keys(p.mapping || {}).length} cột)`;
        sel.appendChild(opt);
    }
}

function _ucmRenderMappingTable() {
    const tbody = document.getElementById("ucmMappingTbody");
    if (!tbody) return;
    const ihrpCols = _ucmState.ihrpColumns || [];
    const headers = _ucmState.headers || [];
    const rows = [];
    for (const ihrp of ihrpCols) {
        const cands = _ucmState.autoSuggest[ihrp] || [];
        const top = cands[0];
        const current = _ucmState.currentMapping[ihrp] || "";
        const topScore = top ? top.score : 0;
        const isMapped = !!current;
        const rowClass = isMapped
            ? (topScore >= 0.7 && current === top?.header
                ? "bg-emerald-50 dark:bg-emerald-900/20"
                : "")
            : "bg-slate-50 dark:bg-slate-900/20 text-gray-400";

        // T34 Task 3B — Compatible type filter: xác định các type iHRP col này expect
        const ihrpExpectedTypes = _ucmIhrpExpectedTypes(ihrp);

        // Options: "(không có)" + tất cả header trong file, filter theo type compatibility
        let optsHtml = `<option value="">— không có —</option>`;
        for (const h of headers) {
            if (!h) continue;
            const info = _ucmState.columnTypes[h] || {};
            const type = info.type || "string";
            // Ẩn header có kiểu không phù hợp — trừ khi user check "hiện tất cả"
            const compatible = _ucmState.showIncompatible ||
                              ihrpExpectedTypes.length === 0 ||
                              ihrpExpectedTypes.includes(type) ||
                              type === "string" ||  // string luôn cho phép
                              type === "empty";     // empty cũng cho phép
            if (!compatible) continue;
            const selected = h === current ? "selected" : "";
            // Thêm badge type + sample vào label option
            const samples = (info.samples || []).slice(0, 1);
            const sampleHint = samples.length ? ` — "${samples[0]}"`.slice(0, 40) : "";
            const badgeIcon = info.badge?.icon || "";
            optsHtml += `<option value="${escapeAttr(h)}" ${selected}>${badgeIcon} ${escapeHtml(h)}${escapeHtml(sampleHint)}</option>`;
        }

        const scoreLabel = current && top && current === top.header
            ? `${Math.round(topScore * 100)}%`
            : (isMapped ? "manual" : "—");

        // T34 Task 3B — Badge inferred type cho HEADER được chọn (không phải iHRP col)
        const currInfo = current ? (_ucmState.columnTypes[current] || {}) : {};
        const badgeHtml = currInfo.badge ? _ucmBadgeHtml(currInfo.badge, currInfo.type) : "";
        // Sample values dưới header
        const samples = (currInfo.samples || []).slice(0, 3);
        const sampleRow = samples.length
            ? `<div class="text-[10px] text-gray-500 italic mt-0.5 font-mono truncate max-w-xs" title="${escapeAttr(samples.join(' | '))}">${escapeHtml(samples.join(' • '))}</div>`
            : "";

        rows.push(`
            <tr class="border-b ${rowClass}">
                <td class="px-2 py-1 font-medium">${escapeHtml(ihrp)}</td>
                <td class="px-2 py-1">
                    <select data-ucm-ihrp="${escapeAttr(ihrp)}"
                            onchange="_ucmOnMappingChange(this)"
                            class="w-full border rounded p-1 text-xs dark:bg-slate-700 dark:border-slate-600">
                        ${optsHtml}
                    </select>
                    ${sampleRow}
                </td>
                <td class="px-2 py-1 text-center text-[11px]">${badgeHtml}</td>
                <td class="px-2 py-1 text-center text-[11px]">${scoreLabel}</td>
            </tr>
        `);
    }
    tbody.innerHTML = rows.join("");
}

// T34 Task 3B — Xác định các type expected cho iHRP col (dựa tên cột).
function _ucmIhrpExpectedTypes(ihrpCol) {
    if (!ihrpCol) return [];
    if (ihrpCol.endsWith(" - Start") || ihrpCol.endsWith(" - End") || ihrpCol === "Last Updated Date") {
        return ["date_iso", "date_dmy", "date_excel_serial"];
    }
    if (ihrpCol.endsWith(" - PIC")) {
        return ["pic_list"];
    }
    if (ihrpCol.endsWith(" - Status")) {
        return ["status_enum"];
    }
    if (ihrpCol.endsWith(" - Estimate MH")) {
        return ["integer", "decimal"];
    }
    // Meta cols (Mã CN, Tên chức năng, Module...) accept mọi type
    return [];
}

function _ucmBadgeHtml(badge, type) {
    if (!badge) return "";
    const colorMap = {
        blue: "bg-blue-100 text-blue-800",
        purple: "bg-purple-100 text-purple-800",
        orange: "bg-orange-100 text-orange-800",
        green: "bg-green-100 text-green-800",
        gray: "bg-slate-100 text-slate-700",
    };
    const cls = colorMap[badge.color] || colorMap.gray;
    return `<span class="inline-block px-1.5 py-0.5 rounded text-[10px] ${cls}" title="Type: ${escapeAttr(type)}">${badge.icon || ""} ${escapeHtml(badge.label || "")}</span>`;
}

// T34 Task 3B — Toggle "Hiện tất cả (bỏ filter kiểu)".
function _ucmToggleShowIncompatible(chk) {
    _ucmState.showIncompatible = !!chk.checked;
    _ucmRenderMappingTable();
}
window._ucmToggleShowIncompatible = _ucmToggleShowIncompatible;

function _ucmOnMappingChange(sel) {
    const ihrp = sel.dataset.ucmIhrp;
    const value = sel.value;
    if (value) {
        _ucmState.currentMapping[ihrp] = value;
    } else {
        delete _ucmState.currentMapping[ihrp];
    }
    _ucmUpdateStats();
    // Re-render row với style mới (mapped/not)
    _ucmRenderMappingTable();
}
window._ucmOnMappingChange = _ucmOnMappingChange;

function _ucmUpdateStats() {
    const total = (_ucmState.ihrpColumns || []).length;
    const mapped = Object.keys(_ucmState.currentMapping).length;
    const el = document.getElementById("ucmMatchStats");
    if (el) el.textContent = `Đã map ${mapped}/${total} cột iHRP`;
}

function _ucmApplyAllSuggestions() {
    _ucmState.currentMapping = {};
    for (const ihrp of _ucmState.ihrpColumns) {
        const cands = _ucmState.autoSuggest[ihrp] || [];
        if (cands.length > 0 && cands[0].score >= 0.5) {
            _ucmState.currentMapping[ihrp] = cands[0].header;
        }
    }
    _ucmRenderMappingTable();
    _ucmUpdateStats();
    showToast(`Đã áp dụng ${Object.keys(_ucmState.currentMapping).length} suggestion`, "");
}
window._ucmApplyAllSuggestions = _ucmApplyAllSuggestions;

function _ucmClearAll() {
    _ucmState.currentMapping = {};
    _ucmRenderMappingTable();
    _ucmUpdateStats();
}
window._ucmClearAll = _ucmClearAll;

function _ucmApplyPreset(presetName) {
    if (!presetName) return;
    const preset = (_ucmState.presets || []).find(p => p.name === presetName);
    if (!preset) return;
    _ucmState.currentMapping = { ...(preset.mapping || {}) };
    _ucmRenderMappingTable();
    _ucmUpdateStats();
    showToast(`Đã load preset "${presetName}"`, "");
}
window._ucmApplyPreset = _ucmApplyPreset;

async function _ucmSavePreset() {
    const name = prompt("Tên preset (để tái sử dụng cho file cùng vendor):");
    if (!name || !name.trim()) return;
    try {
        const r = await fetch(`/api/projects/${currentProjectSlug}/mapping-presets`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ name: name.trim(), mapping: _ucmState.currentMapping }),
        });
        const data = await r.json();
        if (!r.ok) throw new Error(data.error || `HTTP ${r.status}`);
        _ucmState.presets = data.presets || [];
        _ucmRenderPresetSelect();
        showToast(`Đã lưu preset "${name.trim()}"`);
    } catch (err) {
        showToast("Lỗi lưu preset: " + err.message, "red");
    }
}
window._ucmSavePreset = _ucmSavePreset;

async function _ucmDeletePreset() {
    const sel = document.getElementById("ucmPresetSelect");
    const name = sel?.value;
    if (!name) {
        showToast("Chọn preset cần xoá từ dropdown", "red");
        return;
    }
    if (!confirm(`Xoá preset "${name}"?`)) return;
    try {
        const r = await fetch(
            `/api/projects/${currentProjectSlug}/mapping-presets/${encodeURIComponent(name)}`,
            { method: "DELETE" }
        );
        const data = await r.json();
        if (!r.ok) throw new Error(data.error || `HTTP ${r.status}`);
        _ucmState.presets = data.presets || [];
        _ucmRenderPresetSelect();
        showToast(`Đã xoá preset "${name}"`);
    } catch (err) {
        showToast("Lỗi xoá preset: " + err.message, "red");
    }
}
window._ucmDeletePreset = _ucmDeletePreset;

/**
 * Submit mapping → gọi /upload-confirm → apply dashboard response.
 * @param {boolean} skipMapping - true = bỏ qua mapping (dùng auto-detect).
 */
async function _ucmSubmit(skipMapping) {
    if (!_ucmState.tmpId) {
        showToast("Không có file preview để confirm", "red");
        return;
    }
    document.getElementById("uploadProgress").classList.remove("hidden");
    const mappingToSend = skipMapping ? {} : _ucmState.currentMapping;
    try {
        const r = await fetch("/api/upload-confirm", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                tmp_id: _ucmState.tmpId,
                project_slug: currentProjectSlug,
                filename: _ucmState.filename,
                column_mapping: mappingToSend,
                threshold: parseInt(document.getElementById("durationThreshold")?.value || "3", 10),
            }),
        });
        const data = await r.json();
        if (data.error) {
            showToast("Lỗi: " + data.error, "red");
            return;
        }
        closeUploadMappingModal();
        applyDashboardResponse(data);
        await loadProjectList();
        const suffix = data.column_mapping_applied
            ? ` (áp dụng mapping cho ${data.column_mapping_count} cột)`
            : " (auto-detect)";
        showToast(`Đã tải ${data.rows_count} chức năng${suffix}!`);
    } catch (err) {
        showToast("Lỗi kết nối server: " + err.message, "red");
    } finally {
        document.getElementById("uploadProgress").classList.add("hidden");
    }
}
window._ucmSubmit = _ucmSubmit;


// ==========================================================================
// T34 Task 3E — Validate mapping dry-run
// ==========================================================================

async function _ucmRunDryRun() {
    if (!_ucmState.tmpId) {
        showToast("Không có file preview để test", "red");
        return;
    }
    const mapping = _ucmState.currentMapping || {};
    if (!Object.keys(mapping).length) {
        showToast("Chưa map cột nào — thử áp dụng auto suggest trước", "orange");
        return;
    }
    try {
        const r = await fetch("/api/validate-mapping", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                tmp_id: _ucmState.tmpId,
                column_mapping: mapping,
                n_rows: 5,
            }),
        });
        const d = await r.json();
        _ucmState.dryRunResult = d;
        _ucmRenderDryRunResult(d);
    } catch (err) {
        showToast("Lỗi test parse: " + err.message, "red");
    }
}
window._ucmRunDryRun = _ucmRunDryRun;

function _ucmRenderDryRunResult(d) {
    const resultEl = document.getElementById("ucmDryRunResult");
    const summaryEl = document.getElementById("ucmDryRunSummary");
    const errorsEl = document.getElementById("ucmDryRunErrors");
    const warningsEl = document.getElementById("ucmDryRunWarnings");
    const thead = document.getElementById("ucmDryRunThead");
    const tbody = document.getElementById("ucmDryRunTbody");
    if (!resultEl) return;

    resultEl.classList.remove("hidden");

    // Summary
    const success = d.success !== false;
    const rowCount = d.row_count_scanned || (d.rows || []).length;
    summaryEl.innerHTML = `
        <span class="inline-block px-2 py-0.5 rounded ${success ? 'bg-green-100 text-green-800' : 'bg-red-100 text-red-800'} font-semibold">
            ${success ? '✓ Success' : '✗ Failed'}
        </span>
        · Đã scan ${rowCount} record
        · ${d.errors?.length || 0} lỗi
        · ${d.warnings?.length || 0} cảnh báo
    `;

    // Errors
    const errors = d.errors || [];
    if (errors.length) {
        errorsEl.innerHTML = `
            <div class="bg-red-50 border border-red-200 rounded p-2">
                <div class="font-semibold text-red-800 mb-1">⚠ Lỗi:</div>
                <ul class="list-disc pl-4 text-red-700 space-y-0.5">
                    ${errors.slice(0, 10).map(e =>
                        `<li>Row ${e.row_idx}, cột <code>${escapeHtml(e.col || '')}</code>: ${escapeHtml(e.msg || '')}</li>`
                    ).join("")}
                    ${errors.length > 10 ? `<li class="italic text-gray-500">…và ${errors.length - 10} lỗi khác</li>` : ""}
                </ul>
            </div>
        `;
    } else {
        errorsEl.innerHTML = "";
    }

    // Warnings
    const warnings = d.warnings || [];
    if (warnings.length) {
        warningsEl.innerHTML = `
            <div class="bg-amber-50 border border-amber-200 rounded p-2">
                <div class="font-semibold text-amber-800 mb-1">⚠ Cảnh báo:</div>
                <ul class="list-disc pl-4 text-amber-700 space-y-0.5">
                    ${warnings.map(w => `<li>${escapeHtml(w)}</li>`).join("")}
                </ul>
            </div>
        `;
    } else {
        warningsEl.innerHTML = "";
    }

    // Preview table
    const rows = d.rows || [];
    if (!rows.length) {
        thead.innerHTML = "";
        tbody.innerHTML = `<tr><td class="px-2 py-2 text-center text-gray-400 italic">Không có record nào parse được</td></tr>`;
        return;
    }
    // Header: Mã CN, Tên CN, Module, phases (dynamic)
    const phaseNames = new Set();
    for (const r of rows) {
        for (const ph of Object.keys(r.phases || {})) phaseNames.add(ph);
    }
    const phasesList = Array.from(phaseNames);
    const cols = ["Mã CN", "Tên chức năng", "Module", "Priority", ...phasesList.map(p => `${p} status`)];
    thead.innerHTML = cols.map(c =>
        `<th class="px-2 py-1 text-left border-b whitespace-nowrap">${escapeHtml(c)}</th>`
    ).join("");

    // Errors by row for highlighting
    const errorsByRow = {};
    for (const e of errors) {
        errorsByRow[e.row_idx] = errorsByRow[e.row_idx] || [];
        errorsByRow[e.row_idx].push(e);
    }

    tbody.innerHTML = rows.map(r => {
        const hasError = errorsByRow[r.row_num];
        const rowCls = hasError ? "bg-red-50" : "";
        const cellStyle = "px-2 py-1 border-b whitespace-nowrap";
        const cells = [
            `<td class="${cellStyle}"><code>${escapeHtml(r.ma_cn || "")}</code></td>`,
            `<td class="${cellStyle} truncate max-w-xs">${escapeHtml(r.ten_cn || "")}</td>`,
            `<td class="${cellStyle}">${escapeHtml(r.module || "")}</td>`,
            `<td class="${cellStyle}">${escapeHtml(r.priority || "")}</td>`,
        ];
        for (const p of phasesList) {
            const ph = (r.phases || {})[p] || {};
            cells.push(`<td class="${cellStyle}">${escapeHtml(ph.status || "-")}</td>`);
        }
        return `<tr class="${rowCls}" title="${hasError ? 'Row có lỗi parse' : ''}">${cells.join("")}</tr>`;
    }).join("");
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
    // Gantt Calendar (Excel-style, 3-tier header) — fetch riêng qua API
    _safe("ganttCalendar", loadGanttCalendar);

    // Compare section (chỉ hiện nếu có >= 2 snapshots)
    _safe("compare", renderCompareSection);

    // T21: Data Quality panel (lazy fetch — không block render chính)
    _safe("dataQuality", loadDataQuality);

    // T22: Aging WIP tracking
    _safe("agingWip", loadAgingWip);

    // T24: Bookmarks section
    _safe("bookmarks", loadBookmarks);

    // T26: Weekly Digest archive
    _safe("digests", loadDigests);

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
// b9: Matrix group_by state — chỉ session, không persist (đơn giản như Gantt).
let _matrixGroupBy = "module";
let _matrixCache = null;  // Cache dữ liệu group_by=process khi user toggle qua/lại

function renderPhaseMatrix() {
    // Nếu đang ở mode process và đã có cache → render từ cache; ngược lại
    // render từ metricsData (mode module là default). Không tự gọi backend
    // ở đây (renderPhaseMatrix chạy trong pipeline renderDashboard) — chuyển
    // mode qua nút → setMatrixGroupBy fetch riêng.
    const m = (_matrixGroupBy === "process" && _matrixCache)
        ? _matrixCache
        : metricsData.phase_status_matrix;
    if (!m) return;
    _renderPhaseMatrixFrom(m);
}

/** Toggle Module/Quy trình cho matrix (public — dùng qua onclick). */
window.setMatrixGroupBy = async function (gb, force = false) {
    gb = (gb === "process") ? "process" : "module";
    if (!force && gb === _matrixGroupBy && _matrixGroupBy === "module") return;
    // Cho phép re-fetch mode 'process' khi filter đổi
    if (!force && gb === _matrixGroupBy && gb === "process" && _matrixCache) return;
    _matrixGroupBy = gb;
    _syncMatrixToggleBtns();
    if (gb === "module") {
        _renderPhaseMatrixFrom(metricsData.phase_status_matrix);
        return;
    }
    try {
        const url = new URL(`/api/projects/${currentProjectSlug}/phase-matrix`, window.location.origin);
        url.searchParams.set("group_by", "process");
        (globalFilters.modules || []).forEach(v => url.searchParams.append("module", v));
        (globalFilters.processes || []).forEach(v => url.searchParams.append("process", v));
        (globalFilters.pics || []).forEach(v => url.searchParams.append("pic", v));
        const r = await fetch(url.toString());
        if (!r.ok) throw new Error(await r.text());
        _matrixCache = await r.json();
        _renderPhaseMatrixFrom(_matrixCache);
    } catch (err) {
        showToast("Lỗi tải Phase × Quy trình: " + err.message, "red");
    }
};

function _syncMatrixToggleBtns() {
    const bMod = document.getElementById("matrixGroupModule");
    const bProc = document.getElementById("matrixGroupProcess");
    const label = document.getElementById("matrixModeLabel");
    const active = "bg-blue-600 text-white border-blue-600";
    const inactive = "bg-white text-gray-700 border-gray-300 hover:bg-gray-50";
    if (bMod && bProc) {
        bMod.className = `text-xs px-3 py-1 rounded border ${_matrixGroupBy === "module" ? active : inactive}`;
        bProc.className = `text-xs px-3 py-1 rounded border ${_matrixGroupBy === "process" ? active : inactive}`;
    }
    if (label) label.textContent = _matrixGroupBy === "process" ? "Quy trình" : "Module";
}

function _renderPhaseMatrixFrom(m) {
    const phases = m.phases || [];
    // row_labels ưu tiên (mới), fallback modules (cũ) cho backward compat
    const rowLabels = m.row_labels || m.modules || [];
    const gb = m.group_by || "module";
    const rowHeader = gb === "process" ? "Quy trình" : "Module";

    const thead = document.getElementById("matrixHead");
    thead.innerHTML = `<tr class="bg-gray-800 text-white text-xs">
        <th class="px-2 py-2 text-left">${rowHeader}</th>
        ${phases.map(p => `<th class="px-2 py-2 text-center">${escapeHtml(p)}</th>`).join("")}
    </tr>`;

    const tbody = document.getElementById("matrixBody");
    tbody.innerHTML = rowLabels.map(label => {
        const cells = phases.map(ph => {
            const cell = m.data[label]?.[ph] || {};
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
                ? `${label} × ${ph} · ${closed}/${total} Closed (${pct}%) · In-prog: ${inprog} · Assign: ${assigned} · Open: ${open}`
                : "Không có dữ liệu";
            // b9: click → drill (phase_matrix). Với mode process, filter dùng
            // process; mode module dùng module. openDrillDown('phase_matrix', ...)
            // supported params: module, phase.
            const clickAttr = total > 0
                ? `data-key="${escapeAttr(label)}" data-ph="${escapeAttr(ph)}" data-gb="${gb}" onclick="_matrixCellClick(this)" style="cursor:pointer"`
                : "";
            return `<td class="px-1 py-1 text-center" ${clickAttr} title="${escapeAttr(tooltip)}">
                <div class="heatmap-cell rounded px-2 py-2 text-xs font-semibold"
                     style="background:${bg};color:${total === 0 ? '#9ca3af' : textColor}">
                    ${total > 0 ? pct + "%" : "-"}
                    <div class="heatmap-tooltip">${escapeHtml(tooltip)}${total > 0 ? "<br>💡 Click để xem chi tiết" : ""}</div>
                </div>
            </td>`;
        }).join("");
        // Cột đầu: tên đầy đủ (không truncate) — với mode process là "PRM.BP.03 - …"
        return `<tr class="border-b"><td class="px-2 py-2 font-semibold text-sm" title="${escapeAttr(label)}">${escapeHtml(label)}</td>${cells}</tr>`;
    }).join("");

    _syncMatrixToggleBtns();
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
            // Fix b10: chặn Chart.js auto-wrap tên phase thành 3 dòng vì
            // fontSize 10 + phase name dài + chart hẹp → labels bị vỡ. Bật
            // autoSkip: false để giữ tất cả label, maxRotation: 20 để nghiêng
            // nhẹ khi thiếu chỗ thay vì wrap dòng.
            x: {
                stacked: true,
                ticks: {
                    font: { size: 11, lineHeight: 1.15 },
                    autoSkip: false,
                    maxRotation: 20,
                    minRotation: 0,
                    padding: 4,
                },
                grid: { display: false },
            },
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
            ${_viewIconCell(item.ma_cn, {title: "Xem chi tiết function trễ deadline"})}
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
    // Local widget filter (trong section Overdue)
    if (fmArr.length) params.set("module", fmArr.join(","));
    if (fp) params.set("pic", fp);
    if (fphArr.length) params.set("phase", fphArr.join(","));
    // Global filter (header dashboard) — dùng key `g_*` để không đè local
    if (globalFilters.modules.length) params.set("g_module", globalFilters.modules.join(","));
    if (globalFilters.processes.length) params.set("g_process", globalFilters.processes.join(","));
    if (globalFilters.pics.length) params.set("g_pic", globalFilters.pics.join(","));
    await downloadFile(`/api/projects/${currentProjectSlug}/export-overdue?` + params.toString(), "Overdue_Report.xlsx");
}


// ========================================================================
// T34 Task 1 — Xuất "Toàn bộ vấn đề" ra 1 Excel workbook (8 sheet)
// ========================================================================
// 1 nút header duy nhất → xuất Cover + 7 loại vấn đề với global filter apply.
async function exportAllIssues() {
    if (!currentProjectSlug) {
        showToast("⚠️ Chưa chọn project");
        return;
    }
    const params = new URLSearchParams();
    if (globalFilters.modules.length) params.set("g_module", globalFilters.modules.join(","));
    if (globalFilters.processes.length) params.set("g_process", globalFilters.processes.join(","));
    if (globalFilters.pics.length) params.set("g_pic", globalFilters.pics.join(","));
    // Threshold aging WIP — dùng theo current slider nếu có, không thì default 14
    const thr = document.getElementById("agingWipThreshold")?.value;
    if (thr) params.set("threshold", thr);

    showToast("📊 Đang tạo file Excel tổng hợp vấn đề…");
    try {
        const url = `/api/projects/${currentProjectSlug}/export-all-issues?` + params.toString();
        await downloadFile(url, `iHRP_Van_De_Tong_Hop_${currentProjectSlug}.xlsx`);
    } catch (err) {
        console.error("[exportAllIssues]", err);
        showToast("❌ Lỗi khi xuất báo cáo tổng hợp");
    }
}
window.exportAllIssues = exportAllIssues;


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
        return `<tr class="${rowCls} border-b">
            <td class="px-2 py-2 text-center">${start + idx + 1}</td>
            <td class="px-2 py-2 font-mono text-xs">${escapeHtml(i.ma_cn)}</td>
            <td class="px-2 py-2">${escapeHtml(i.ten_cn)}</td>
            <td class="px-2 py-2 text-center">${escapeHtml(i.module)}</td>
            <td class="px-2 py-2 text-center text-xs">${escapeHtml(i.phase)}</td>
            <td class="px-2 py-2 text-center">${statusBadge(i.status)}</td>
            <td class="px-2 py-2 text-center text-xs">${escapeHtml(i.priority)}</td>
            <td class="px-2 py-2 text-center text-xs">${i.end_date || "-"}</td>
            <td class="px-2 py-2 text-center ${i.is_overdue ? 'text-red-600 font-bold' : 'text-gray-500'}">${i.days_overdue || 0}</td>
            ${_viewIconCell(i.ma_cn, {title: "Xem chi tiết function chưa có PIC"})}
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
        return `<tr class="${cls} border-b">
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
            ${_viewIconCell(i.ma_cn, {title: "Xem chi tiết function"})}
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
        return `<tr class="${cls} border-b">
            <td class="px-2 py-2 text-center">${start + idx + 1}</td>
            <td class="px-2 py-2 font-mono text-xs">${escapeHtml(i.ma_cn)}</td>
            <td class="px-2 py-2">${escapeHtml(i.ten_cn)}</td>
            <td class="px-2 py-2 text-center">${escapeHtml(i.module)}</td>
            <td class="px-2 py-2 text-center text-xs">${escapeHtml(i.completed_phase)}</td>
            <td class="px-2 py-2 text-center text-xs text-red-500">${escapeHtml(i.waiting_phase)}</td>
            <td class="px-2 py-2 text-center text-xs">${i.completed_date || "-"}</td>
            <td class="px-2 py-2 text-center font-bold">${i.wait_days}</td>
            <td class="px-2 py-2 text-center text-xs">${escapeHtml(i.priority)}</td>
            ${_viewIconCell(i.ma_cn, {title: "Xem chi tiết function đình trệ"})}
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
        return `<tr class="border-b">
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
            ${_viewIconCell(r.ma_cn, {title: "Xem chi tiết function rủi ro"})}
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
                        <th class="px-2 py-1" title="Xem chi tiết">👁</th>
                    </tr></thead>
                    <tbody>${openTasks.length === 0
                        ? `<tr><td colspan="9" class="px-2 py-4 text-center text-gray-500">Không có task mở</td></tr>`
                        : openTasks.map(t => `<tr class="border-b">
                            <td class="px-2 py-1 font-mono">${escapeHtml(t.ma_cn)}</td>
                            <td class="px-2 py-1">${escapeHtml(t.ten_cn)}</td>
                            <td class="px-2 py-1 text-center">${escapeHtml(t.module)}</td>
                            <td class="px-2 py-1 text-center">${escapeHtml(t.phase)}</td>
                            <td class="px-2 py-1">${escapeHtml((t.pic||[]).join(", "))}</td>
                            <td class="px-2 py-1 text-center">${statusBadge(t.status)}</td>
                            <td class="px-2 py-1 text-center">${t.end_date || "-"}</td>
                            <td class="px-2 py-1 text-center font-semibold">${_toEffortUnit(t.estimate_mh)}</td>
                            ${_viewIconCell(t.ma_cn, {title: "Xem chi tiết function open"})}
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
    // b11 (a): badge số quy trình + số function; cập nhật kể cả khi list rỗng.
    const totalFuncs = items.reduce((s, i) => s + (i.total || 0), 0);
    const badge = document.getElementById("processTotalBadge");
    if (badge) {
        badge.textContent = items.length
            ? `${items.length} quy trình · ${totalFuncs} function`
            : "0 quy trình";
    }
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

    // totalFuncs đã tính ở đầu function (dùng cho badge). Dùng lại cho width.
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
        plugins: {
            legend: { position: "top" },
            // b14: data label %; ẩn value = 0.
            datalabels: _labelsForVerticalBar("%", 0),
        },
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

    // Status thô có thể là chuỗi ghép sau dedupe ("In-progress, Open") → hiểu
    // là "có chứa" thay vì bằng chính xác, để summary bar bên footer vẫn có nghĩa.
    const overdue = items.filter(i => i.is_overdue).length;
    const closed = items.filter(i => /closed/i.test(i.status || "")).length;
    const inProgress = items.filter(i => /in-progress|assigned/i.test(i.status || "")).length;
    const { start, end, pageItems } = _pageSlice("drill", items);
    // Footer nhấn mạnh Tổng vs Đang xem để user không hiểu nhầm modal chỉ có N dòng
    // (case B: card 15 → modal show 10 vì pagination default 10/page).
    const st = pageState.drill || { page: 1, size: 10 };
    const totalPages = (!st.size || st.size <= 0) ? 1 : Math.max(1, Math.ceil(items.length / st.size));
    document.getElementById("drillFooter").innerHTML =
        `<b>Tổng ${items.length} function</b> · Trang ${st.page}/${totalPages} · Đang xem ${start + 1}–${end}`
        + ` · <span class="text-green-700">Closed: ${closed}</span>`
        + ` · <span class="text-blue-700">Đang làm: ${inProgress}</span>`
        + ` · <span class="text-red-700">Trễ: ${overdue}</span>`;

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
    // b9: hỗ trợ cả mode module + process (drill 'phase_matrix' chỉ nhận
    // module + phase; với mode process, chuyển key sang param 'process' để
    // FE openDrillDown thêm filter tương ứng qua drill-adapter).
    const gb = el.dataset.gb || "module";
    const key = el.dataset.key ?? el.dataset.mod;
    if (gb === "process") {
        openDrillDown("phase_matrix", {
            process: key,
            phase: el.dataset.ph,
        });
    } else {
        openDrillDown("phase_matrix", {
            module: key,
            phase: el.dataset.ph,
        });
    }
}

/**
 * Drill-down modal cho card "Function trễ deadline".
 *
 * Trước đây gọi `/api/projects/<slug>/overdue` trả về phase-records nên
 * card=47 (distinct function) không khớp modal=85 (phase). Fix: dùng
 * chart drill "overdue" chuẩn — backend đã dedupe theo ma_cn (1 row /
 * function, cột Phase list các phase trễ). Card ↔ drill khớp nhau.
 */
async function openOverdueDrillDown() {
    await openDrillDown("overdue", {}, "⚠️ Chi tiết Function trễ deadline");
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

// b12: state phase filter cho Burndown — session-only, không persist.
let _burndownScopePhase = "";

async function loadBurndownAndSLA() {
    if (!currentProjectSlug || !metricsData) return;
    // Build filter query string chung để mọi endpoint nhận cùng global filter.
    // Upload-history KHÔNG cần filter (là data-quality info per project).
    const qsFilter = _buildFilterQuery();
    try {
        const safeJson = (path, withFilter = true, extraParams = null) => {
            let url = _apiUrl(path);
            const parts = [];
            if (withFilter && qsFilter) parts.push(qsFilter);
            if (extraParams) parts.push(extraParams);
            if (parts.length) url += "?" + parts.join("&");
            return fetch(url).then(r => r.ok ? r.json() : null).catch(() => null);
        };
        const burndownExtras = _burndownScopePhase
            ? "phase=" + encodeURIComponent(_burndownScopePhase) : null;
        const [bd, sla, cap, slow, deps, bsl, hist] = await Promise.all([
            safeJson("burndown", true, burndownExtras),
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
    // b12: luôn hiện section (không hide khi rỗng data) để user thấy phần
    // toggle Phạm vi + biết filter đang chặn. Empty-state hiển thị message.
    section.classList.remove("hidden");
    _populateBurndownPhaseSelector();
    if (!bd || !bd.weeks || bd.weeks.length === 0) {
        document.getElementById("burndownVelocity").textContent = "—";
        document.getElementById("burndownTotal").textContent = "0";
        const ctxEmpty = getCanvas("chartBurndown");
        if (ctxEmpty && ctxEmpty.canvas) {
            const c = ctxEmpty.canvas.getContext("2d");
            c.clearRect(0, 0, ctxEmpty.canvas.width, ctxEmpty.canvas.height);
        }
        return;
    }
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
            // b14: data label — chỉ hiện trên bar (Closed/tuần), ẩn line
            // Lũy kế để tránh trùng lấp. Ẩn value = 0.
            datalabels: {
                display: (ctx) => ctx.dataset.type !== "line"
                    && (Number(ctx.dataset.data[ctx.dataIndex]) || 0) > 0,
                anchor: "end", align: "end", offset: 2,
                color: "#1e40af",
                font: { size: 9, weight: "bold" },
                formatter: (v) => v > 0 ? v : "",
            },
        },
        scales: {
            y: { beginAtZero: true, position: "left", title: { display: true, text: "Closed/tuần" } },
            y1: { beginAtZero: true, position: "right", grid: { display: false }, title: { display: true, text: "Lũy kế" } },
            x: { ticks: { font: { size: 10 } } },
        },
    });
}

/** Populate dropdown phase từ metricsData.structure. Giữ phase đang chọn. */
function _populateBurndownPhaseSelector() {
    const sel = document.getElementById("burndownPhaseSelector");
    if (!sel) return;
    const phases = (metricsData?.structure?.all_phases || []);
    const prev = _burndownScopePhase || sel.value || "";
    sel.innerHTML = `<option value="">Tất cả phase</option>` +
        phases.map(p => `<option value="${escapeAttr(p)}">${escapeHtml(p)}</option>`).join("");
    if (prev && phases.includes(prev)) sel.value = prev;
    else sel.value = "";
}

/** Handler khi user đổi phase scope — refetch burndown. */
window.onBurndownPhaseChange = async function (phase) {
    _burndownScopePhase = (phase || "").trim();
    // Reload chỉ burndown, không đụng SLA/Capacity (không phụ thuộc phase).
    if (!currentProjectSlug) return;
    try {
        const qs = _buildFilterQuery();
        let url = _apiUrl("burndown");
        const parts = [];
        if (qs) parts.push(qs);
        if (_burndownScopePhase) parts.push("phase=" + encodeURIComponent(_burndownScopePhase));
        if (parts.length) url += "?" + parts.join("&");
        const r = await fetch(url);
        if (!r.ok) throw new Error(await r.text());
        const bd = await r.json();
        renderBurndownSection(bd);
    } catch (err) {
        showToast("Lỗi tải Burndown: " + err.message, "red");
    }
};

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
            // b14: reuse helper stacked bar (min 6% để không đè segment nhỏ).
            datalabels: _labelsForStackedBar(6),
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

/** Build Chart.js instance từ aggregated data + item config. Shared với preview.
 *
 * b15 (c)(d): legend + axis title tiếng Việt; data label format theo
 * measure type (pct/int/hour/day) từ agg.meta.y_measure_format.
 */
function _cdBuildChart(canvas, agg, cfg) {
    const existing = Chart.getChart(canvas);
    if (existing) existing.destroy();

    const fields = _chartFieldsCache || { palettes: {} };
    let colors = fields.palettes[cfg.palette] || fields.palettes.default ||
        ["#3b82f6", "#10b981", "#f59e0b", "#ef4444", "#8b5cf6", "#ec4899"];

    const ut = cfg.chart_type || "bar";
    const fmt = agg?.meta?.y_measure_format || "int";
    const yLabel = agg?.meta?.y_measure_label || cfg.y_measure || "";
    const xLabel = (fields.fields || {})[cfg.x_field] || cfg.x_field || "";

    let chartType = "bar";
    let extraOpts = { responsive: true, maintainAspectRatio: false, plugins: {} };
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

    // b15 (c): legend Vietnamese label (đã có sẵn từ backend series_label).
    extraOpts.plugins.legend = { position: "bottom", labels: { font: { size: 10 } } };
    extraOpts.plugins.tooltip = {
        callbacks: {
            label: (c) => {
                const raw = Number(c.parsed?.y ?? c.parsed ?? c.raw ?? 0);
                return `${c.dataset.label}: ${_fmtMeasureValue(raw, fmt)}`;
            },
        },
    };

    // b15 (d): data label — chartjs-plugin-datalabels đã register global.
    // Ẩn label khi giá trị = 0 (bar/line) hoặc segment nhỏ (pie/doughnut).
    const isPct = fmt === "pct";
    const isCircular = (chartType === "pie" || chartType === "doughnut");
    extraOpts.plugins.datalabels = {
        display: (ctx) => {
            const v = Number(ctx.dataset.data[ctx.dataIndex]) || 0;
            if (v === 0) return false;
            if (isCircular) {
                const total = (ctx.dataset.data || []).reduce((s, x) => s + (Number(x) || 0), 0) || 1;
                return (v / total) >= 0.05;   // ẩn segment < 5%
            }
            return true;
        },
        color: isCircular ? "#fff" : "#334155",
        font: { size: 10, weight: "600" },
        anchor: isCircular ? "center" : "end",
        align: isCircular ? "center" : "top",
        offset: isCircular ? 0 : 4,
        formatter: (v) => _fmtMeasureValue(v, fmt),
    };

    // b15 (c): axis title tiếng Việt.
    if (stacked) {
        extraOpts.scales = {
            x: { stacked: true, title: { display: !!xLabel, text: xLabel, font: { size: 11 } } },
            y: { stacked: true, beginAtZero: true, title: { display: !!yLabel, text: yLabel, font: { size: 11 } } },
        };
    } else if (chartType === "bar") {
        if (extraOpts.indexAxis === "y") {
            extraOpts.scales = {
                y: { title: { display: !!xLabel, text: xLabel, font: { size: 11 } } },
                x: { beginAtZero: true, title: { display: !!yLabel, text: yLabel, font: { size: 11 } } },
            };
        } else {
            extraOpts.scales = {
                x: { title: { display: !!xLabel, text: xLabel, font: { size: 11 } } },
                y: { beginAtZero: true, title: { display: !!yLabel, text: yLabel, font: { size: 11 } } },
            };
        }
    } else if (chartType === "line") {
        extraOpts.scales = {
            x: { title: { display: !!xLabel, text: xLabel, font: { size: 11 } } },
            y: { beginAtZero: true, title: { display: !!yLabel, text: yLabel, font: { size: 11 } } },
        };
    }

    // T27 — Drill-down inline: click bar/pie segment → mở modal drill.
    // Chỉ enable khi item có id (chart đã lưu, không phải preview trong wizard).
    if (cfg && cfg.id) {
        extraOpts.onClick = (evt, elements, chart) => {
            if (!elements || !elements.length) return;
            const el = elements[0];
            const label = chart.data.labels[el.index];
            const seriesLabel = cfg.series_field ? chart.data.datasets[el.datasetIndex]?.label : "";
            openCustomDashDrill(cfg, label, seriesLabel);
        };
        // Hover cursor pointer để hint clickable
        extraOpts.onHover = (evt, elements) => {
            evt.native.target.style.cursor = elements && elements.length ? "pointer" : "default";
        };
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

// T27 — Drill-down modal cho custom dashboard.
// Click bar/pie/segment → fetch /custom-dashboard/<id>/drill?x_value=...&series_value=...
// Modal hiển thị bảng function match. Sử dụng lại `_viewIconCell` (UX7) để
// mở function detail modal khi cần deep-dive.
window.openCustomDashDrill = async function (cfg, xValue, seriesValue) {
    if (!cfg || !cfg.id) return;
    const modal = document.getElementById("cdDrillModal");
    if (!modal) return;
    // Show loading state
    const titleEl = document.getElementById("cdDrillTitle");
    const subEl = document.getElementById("cdDrillSubtitle");
    const metaEl = document.getElementById("cdDrillMeta");
    const tbody = document.getElementById("cdDrillTbody");
    const empty = document.getElementById("cdDrillEmpty");
    if (titleEl) titleEl.textContent = cfg.title || "Chi tiết";
    if (subEl) subEl.textContent = `${cfg.x_field || ""} = "${xValue}"` + (seriesValue ? ` · ${cfg.series_field} = "${seriesValue}"` : "");
    if (metaEl) metaEl.innerHTML = `<span class="italic text-gray-500">Đang tải...</span>`;
    if (tbody) tbody.innerHTML = "";
    if (empty) empty.classList.add("hidden");
    modal.classList.remove("hidden");
    modal.classList.add("flex");

    try {
        const params = new URLSearchParams({ x_value: xValue || "" });
        if (seriesValue && cfg.series_field) params.set("series_value", seriesValue);
        const qs = _buildFilterQuery();
        const url = _apiUrl(`custom-dashboard/${encodeURIComponent(cfg.id)}/drill?${params.toString()}${qs ? "&" + qs : ""}`);
        const r = await fetch(url);
        if (!r.ok) {
            const err = await r.json().catch(() => ({}));
            if (metaEl) metaEl.innerHTML = `<span class="text-red-500">Lỗi: ${escapeHtml(err.error || r.statusText)}</span>`;
            return;
        }
        const d = await r.json();
        _renderCdDrillTable(d);
    } catch (err) {
        if (metaEl) metaEl.innerHTML = `<span class="text-red-500">Lỗi mạng: ${escapeHtml(err.message)}</span>`;
    }
};

window.closeCdDrillModal = function () {
    const modal = document.getElementById("cdDrillModal");
    if (!modal) return;
    modal.classList.add("hidden");
    modal.classList.remove("flex");
};

function _renderCdDrillTable(d) {
    const metaEl = document.getElementById("cdDrillMeta");
    const tbody = document.getElementById("cdDrillTbody");
    const empty = document.getElementById("cdDrillEmpty");
    if (!tbody) return;
    const items = d.items || [];
    if (metaEl) {
        const truncNote = d.truncated ? ` <span class="text-orange-600">(hiển thị ${items.length}/${d.total} — cap để giữ UI mượt)</span>` : "";
        metaEl.innerHTML = `Tổng: <b>${d.total}</b> function${truncNote}`;
    }
    if (!items.length) {
        tbody.innerHTML = "";
        if (empty) empty.classList.remove("hidden");
        return;
    }
    if (empty) empty.classList.add("hidden");
    tbody.innerHTML = items.map(it => {
        const overdueCls = it.is_overdue ? "text-red-600 font-semibold" : "";
        return `<tr class="border-b hover:bg-slate-50 dark:hover:bg-slate-700">
            <td class="px-2 py-1.5 font-mono text-xs">${escapeHtml(it.ma_cn)}</td>
            <td class="px-2 py-1.5">${escapeHtml(it.ten_cn)}</td>
            <td class="px-2 py-1.5 text-xs">${escapeHtml(it.module)}</td>
            <td class="px-2 py-1.5 text-xs">${escapeHtml(it.quy_trinh || "")}</td>
            <td class="px-2 py-1.5 text-center text-xs">${escapeHtml(it.priority)}</td>
            <td class="px-2 py-1.5 text-center">${statusBadge(it.status)}</td>
            <td class="px-2 py-1.5 text-center text-xs ${overdueCls}">${escapeHtml(it.end_date || "-")}</td>
            <td class="px-2 py-1.5 text-xs">${escapeHtml((it.pic || []).join(", "))}</td>
            ${_viewIconCell(it.ma_cn, {title: "Xem chi tiết function"})}
        </tr>`;
    }).join("");
}


/** b15 (d): format 1 giá trị theo measure format hint từ backend. */
function _fmtMeasureValue(v, fmt) {
    const n = Number(v) || 0;
    if (fmt === "pct") return n.toFixed(1).replace(/\.0$/, "") + "%";
    if (fmt === "hour") return n.toFixed(1) + "h";
    if (fmt === "day") return n.toFixed(1) + "d";
    // int / default
    return Number.isInteger(n) ? String(n) : n.toFixed(1);
}

// --- Modal management ---

window.openCustomDashModal = async function () {
    _cdEditingId = null;
    await _ensureChartFields();
    _cdPopulateWizardDropdowns();
    _cdInitFilterMs();  // T28 init 7 filter MS
    _cdResetForm();     // reset sau khi init để clear selected
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

// T28 — Chart Config filter multi-select instances (giữ trong closure module).
const _cdMsInstances = {};

function _cdResetForm() {
    ["cdTitle", "cdCaption", "cdChatInput"].forEach(id => {
        const el = document.getElementById(id);
        if (el) el.value = "";
    });
    ["cdFilterOverdue", "cdFilterOpenOnly"].forEach(id => {
        const el = document.getElementById(id);
        if (el) el.checked = false;
    });
    // Reset multi-selects
    Object.values(_cdMsInstances).forEach(ms => ms?.setSelected?.([]));
    document.getElementById("cdPreviewWrap")?.classList.add("hidden");
    document.getElementById("cdChatSuggestion")?.classList.add("hidden");
}

/** T28 — Khởi tạo hoặc refresh option cho 7 multi-select filter trong wizard.
 *  Domain values lấy từ structureCache (đã load lần đầu) fallback về
 *  metricsData.structure. Nếu structure chưa có thì skip (chart chưa load).
 *  Live preview: onChange gọi _cdOnFilterChange -> re-preview nếu wrap visible.
 */
function _cdInitFilterMs() {
    const s = structureCache || (metricsData && metricsData.structure) || {};
    const defs = [
        { key: "cdMsModule",     msKey: "cdModules",     label: "Module",     opts: s.all_modules || [] },
        { key: "cdMsProcess",    msKey: "cdProcesses",   label: "Quy trình",  opts: s.all_processes || [] },
        { key: "cdMsPic",        msKey: "cdPics",        label: "PIC",        opts: s.all_pics || [] },
        { key: "cdMsStatus",     msKey: "cdStatuses",    label: "Status",     opts: s.all_statuses || [] },
        { key: "cdMsPriority",   msKey: "cdPriorities",  label: "Priority",   opts: s.all_priorities || [] },
        { key: "cdMsComplexity", msKey: "cdComplexities", label: "Complexity", opts: s.all_complexities || [] },
        { key: "cdMsFitgap",     msKey: "cdFitgaps",     label: "FIT/GAP",    opts: s.all_fit_gap || ["FIT", "GAP"] },
    ];
    defs.forEach(def => {
        const container = document.getElementById(def.key);
        if (!container) return;
        // Nếu đã init trước → chỉ refresh option (giữ selection)
        if (_cdMsInstances[def.msKey]) {
            _cdMsInstances[def.msKey].setOptions?.(def.opts);
            return;
        }
        _cdMsInstances[def.msKey] = createMultiSelect({
            el: container,
            key: def.msKey,
            label: def.label,
            options: def.opts,
            selected: [],
            allText: `Tất cả ${def.label.toLowerCase()}`,
            onChange: () => _cdOnFilterChange(),
        });
    });
}

/** T28 — Callback khi filter đổi; refresh preview nếu đang show. */
window._cdOnFilterChange = function () {
    const wrap = document.getElementById("cdPreviewWrap");
    if (!wrap || wrap.classList.contains("hidden")) return;
    // Debounce nhẹ để tránh spam khi user click nhanh nhiều option
    if (_cdOnFilterChange._t) clearTimeout(_cdOnFilterChange._t);
    _cdOnFilterChange._t = setTimeout(() => _cdPreview(), 220);
};

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
    _cdInitFilterMs();   // T28 đảm bảo MS đã init trước khi setSelected
    document.querySelector(`input[name="cdChartType"][value="${draft.chart_type}"]`)?.click();
    if (draft.x_field) document.getElementById("cdXField").value = draft.x_field;
    if (draft.y_measure) document.getElementById("cdYMeasure").value = draft.y_measure;
    if (draft.series_field) document.getElementById("cdSeriesField").value = draft.series_field;
    document.getElementById("cdTitle").value = draft.title.slice(0, 100);
    document.getElementById("cdFilterOverdue").checked = !!draft.filters.overdue_only;
    document.getElementById("cdFilterOpenOnly").checked = !!draft.filters.open_only;
    // T28: fitgaps áp vào MS thay vì input plain-text
    if (draft.filters.fitgaps && _cdMsInstances.cdFitgaps) {
        _cdMsInstances.cdFitgaps.setSelected(draft.filters.fitgaps);
    }
};

// --- Read form → payload ---

function _cdReadForm() {
    const chartType = document.querySelector('input[name="cdChartType"]:checked')?.value || "bar";
    // T28: đọc từ 7 multi-select thay vì input plain-text.
    const filters = {};
    const msMap = [
        ["cdModules", "modules"],
        ["cdProcesses", "processes"],
        ["cdPics", "pics"],
        ["cdStatuses", "statuses"],
        ["cdPriorities", "priorities"],
        ["cdComplexities", "complexities"],
        ["cdFitgaps", "fitgaps"],
    ];
    msMap.forEach(([msKey, filterKey]) => {
        const sel = _cdMsInstances[msKey]?.getSelected?.() || [];
        if (sel.length) filters[filterKey] = sel;
    });
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
        _cdInitFilterMs();   // T28 init MS trước khi setSelected
        _cdSetMode("wizard");
        document.querySelector(`input[name="cdChartType"][value="${item.chart_type}"]`)?.click();
        document.getElementById("cdXField").value = item.x_field;
        document.getElementById("cdYMeasure").value = item.y_measure;
        document.getElementById("cdSeriesField").value = item.series_field || "";
        document.getElementById("cdPalette").value = item.palette || "default";
        document.getElementById("cdTitle").value = item.title;
        document.getElementById("cdCaption").value = item.caption || "";
        const f = item.filters || {};
        // T28: set MS instead of input plain
        const msSet = [
            ["cdModules",     f.modules],
            ["cdProcesses",   f.processes],
            ["cdPics",        f.pics],
            ["cdStatuses",    f.statuses],
            ["cdPriorities",  f.priorities],
            ["cdComplexities", f.complexities],
            ["cdFitgaps",     f.fitgaps],
        ];
        msSet.forEach(([msKey, arr]) => {
            _cdMsInstances[msKey]?.setSelected?.(Array.isArray(arr) ? arr : []);
        });
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

// ========================================================================
// T28 — Chart notes / Summary state cho PDF modal
// ========================================================================
// Cache 2 tầng:
//  - _pdfNotesCache.summary: string (tóm tắt chung, max 500)
//  - _pdfNotesCache.notes[section-id] = string (nhận xét per-chart, max 200)
// FE tự đồng bộ với backend qua GET/PUT /api/projects/<slug>/chart-notes.
// User có thể:
//  - Sửa textarea → gõ thẳng → bấm "✓ Lưu nhận xét" để persist (không xuất).
//  - Sửa + bấm "📥 Xuất PDF" → hệ thống auto-lưu trước khi xuất.
const _pdfNotesCache = { summary: "", notes: {} };

async function _pdfLoadChartNotes() {
    if (!currentProjectSlug) return;
    try {
        const r = await fetch(`/api/projects/${currentProjectSlug}/chart-notes`);
        if (!r.ok) throw new Error(await r.text());
        const d = await r.json();
        _pdfNotesCache.summary = String(d.summary || "");
        _pdfNotesCache.notes = (d.notes && typeof d.notes === "object") ? { ...d.notes } : {};
    } catch (err) {
        console.warn("[pdfLoadChartNotes] fetch failed → dùng cache trống:", err);
        _pdfNotesCache.summary = "";
        _pdfNotesCache.notes = {};
    }
}

window.openPdfExportModal = async function () {
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
    // Load persisted notes → pre-fill textarea (Tóm tắt + comment per-chart)
    await _pdfLoadChartNotes();
    const summaryEl = document.getElementById("pdfNotes");
    if (summaryEl) summaryEl.value = _pdfNotesCache.summary || "";
    _pdfUpdateSummaryCounter();
    _pdfOnPresetChange();
    modal.classList.remove("hidden");
    modal.classList.add("flex");
};

/** Update counter "X/500" cho textarea tóm tắt chung. */
window._pdfUpdateSummaryCounter = function () {
    const el = document.getElementById("pdfNotes");
    const cnt = document.getElementById("pdfNotesCounter");
    if (el && cnt) cnt.textContent = String((el.value || "").length);
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
    if (!wrap) { _pdfRenderChartNotesList(); return; }
    if (preset !== "custom") {
        wrap.classList.add("hidden");
        _pdfRenderChartNotesList();
        return;
    }
    wrap.classList.remove("hidden");
    // Build checkbox list từ tất cả section trong dashboard
    const secs = Array.from(document.querySelectorAll('#dashboard [id^="section-"]'))
        .filter(s => s.id !== "section-summary-header");
    wrap.innerHTML = secs.map(s => {
        const label = _sectionShortLabel(s.id);
        return `<label class="flex items-center gap-2 py-0.5">
            <input type="checkbox" class="pdf-custom-cb" value="${s.id}" onchange="_pdfRenderChartNotesList()">
            <span>${escapeHtml(label)} <span class="text-gray-400">(${s.id})</span></span>
        </label>`;
    }).join("");
    _pdfRenderChartNotesList();
};

/**
 * Render textarea "💬 Nhận xét từng chart" cho toàn bộ section đã chọn.
 * Đọc value hiện tại từ _pdfNotesCache.notes (đã load từ backend hoặc gõ
 * thẳng trước đó). Textarea input event → cập nhật ngay vào cache
 * (in-memory) — user cần bấm "✓ Lưu nhận xét" để persist.
 */
window._pdfRenderChartNotesList = function () {
    const wrap = document.getElementById("pdfChartNotesList");
    const cnt = document.getElementById("pdfChartNotesCount");
    if (!wrap) return;
    const ids = _pdfGetSelectedSections();
    if (cnt) cnt.textContent = String(ids.length);
    if (!ids.length) {
        wrap.innerHTML = '<div class="text-xs text-gray-400 italic">Chưa có chart nào được chọn.</div>';
        return;
    }
    wrap.innerHTML = ids.map(sid => {
        const label = _sectionShortLabel(sid);
        const val = _pdfNotesCache.notes[sid] || "";
        const len = val.length;
        return `
            <div class="border rounded p-2 bg-white dark:bg-slate-800">
                <div class="flex items-center justify-between mb-1">
                    <div class="text-xs font-semibold text-gray-700 dark:text-slate-300">
                        📊 ${escapeHtml(label)}
                    </div>
                    <div class="text-[10px] text-gray-400">
                        <span data-note-counter="${escapeAttr(sid)}">${len}</span>/200
                    </div>
                </div>
                <textarea
                    class="w-full border rounded p-1.5 text-xs"
                    rows="2" maxlength="200"
                    data-chart-note="${escapeAttr(sid)}"
                    oninput="_pdfOnChartNoteInput(this)"
                    placeholder="VD: Tuần này overdue giảm 3 case…">${escapeHtml(val)}</textarea>
            </div>
        `;
    }).join("");
};

/** input handler cho textarea comment per-chart → sync in-memory + counter. */
window._pdfOnChartNoteInput = function (el) {
    const sid = el.getAttribute("data-chart-note");
    if (!sid) return;
    const v = el.value || "";
    if (v.trim()) {
        _pdfNotesCache.notes[sid] = v;
    } else {
        delete _pdfNotesCache.notes[sid];
    }
    const cnt = document.querySelector(`[data-note-counter="${CSS.escape(sid)}"]`);
    if (cnt) cnt.textContent = String(v.length);
};

/**
 * Trả về snapshot chart notes cho các section id đang xuất PDF.
 * `doPdfExport` gọi trước khi generate → luôn dùng dữ liệu mới nhất user vừa gõ.
 */
window._pdfReadChartNotes = function (ids) {
    const out = {};
    (ids || []).forEach(sid => {
        const v = _pdfNotesCache.notes[sid];
        if (v && v.trim()) out[sid] = v;
    });
    return out;
};

/**
 * Nút "✓ Lưu nhận xét" — PUT lên backend, không xuất PDF.
 * `doPdfExport` cũng gọi function này (silent) trước khi generate để
 * đảm bảo notes hiện tại đã được persist.
 */
window.savePdfChartNotes = async function (silent) {
    if (!currentProjectSlug) return;
    const btn = document.getElementById("pdfSaveNotesBtn");
    if (btn && !silent) { btn.disabled = true; btn.textContent = "⏳ Đang lưu…"; }
    try {
        const summaryEl = document.getElementById("pdfNotes");
        const summary = (summaryEl?.value || "").slice(0, 500);
        _pdfNotesCache.summary = summary;
        const payload = { summary, notes: _pdfNotesCache.notes };
        const r = await fetch(`/api/projects/${currentProjectSlug}/chart-notes`, {
            method: "PUT",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload),
        });
        if (!r.ok) throw new Error(await r.text());
        const d = await r.json();
        _pdfNotesCache.summary = String(d.summary || "");
        _pdfNotesCache.notes = (d.notes && typeof d.notes === "object") ? { ...d.notes } : {};
        if (!silent) showToast("✓ Đã lưu nhận xét");
    } catch (err) {
        console.error("[savePdfChartNotes]", err);
        if (!silent) showToast("Lưu nhận xét thất bại: " + err.message, "red");
    } finally {
        if (btn && !silent) { btn.disabled = false; btn.textContent = "✓ Lưu nhận xét"; }
    }
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

/**
 * Thu thập comment per-chart cho danh sách section ids đang xuất.
 * Trả về {sectionId: commentText}. Task 2: chưa có UI → luôn empty.
 * Task 3 sẽ override function này để đọc từ textarea trong modal +
 * chart notes cache.
 */
function _pdfCollectChartNotes(_ids) {
    return (typeof window._pdfReadChartNotes === "function")
        ? window._pdfReadChartNotes(_ids) || {}
        : {};
}

/**
 * Render 1 chuỗi HTML thành canvas qua html2canvas (off-screen).
 *
 * Dùng cho PDF export để né bug jsPDF default font (Helvetica) KHÔNG hỗ trợ
 * diacritic tiếng Việt + emoji → text bị mojibake "Ø=ÜÊ&Bào" thay vì
 * "Báo cáo". Approach: mọi text trong PDF (cover, comment per-chart, footer
 * label...) đều render qua html2canvas thành ảnh — font hiển thị đúng
 * y hệt browser (Inter/system font). Trade-off: text không search-able,
 * nhưng đúng > search-able theo yêu cầu user.
 */
async function _pdfCaptureHtml(htmlString, widthPx = 800, scale = 2) {
    if (typeof html2canvas === "undefined") return null;
    const wrapper = document.createElement("div");
    // Off-screen bằng vị trí (KHÔNG dùng display:none — html2canvas cần layout).
    wrapper.style.cssText = `
        position: fixed; left: -20000px; top: 0;
        width: ${widthPx}px; background: #ffffff; color: #0f172a;
        font-family: "Inter", "Segoe UI", "Helvetica Neue", Arial, sans-serif;
        z-index: -1;
    `;
    wrapper.innerHTML = htmlString;
    document.body.appendChild(wrapper);
    try {
        return await html2canvas(wrapper, {
            scale,
            backgroundColor: "#ffffff",
            logging: false,
            useCORS: true,
        });
    } finally {
        wrapper.remove();
    }
}

/**
 * Build HTML cho cover page. Bao gồm banner xanh + title + date + project +
 * filter + tóm tắt chung (nếu có).
 */
function _pdfBuildCoverHtml(ctx) {
    const { title, projName, dateDisplay, preset, filterLine, summary } = ctx;
    const summaryBlock = summary
        ? `<div style="margin-top:16px; padding:12px 14px; background:#f1f5f9;
                      border-left:4px solid #3b82f6; border-radius:6px;
                      font-size:13px; line-height:1.55; color:#1e293b;
                      white-space:pre-wrap;">💬 <b>Tóm tắt báo cáo:</b><br>${escapeHtml(summary)}</div>`
        : "";
    return `
        <div style="padding:0; margin:0;">
            <div style="background:linear-gradient(90deg,#1e40af 0%, #3b82f6 100%);
                        color:#ffffff; padding:22px 28px;
                        border-radius:8px 8px 0 0;
                        display:flex; align-items:center; justify-content:space-between;">
                <div>
                    <div style="font-size:22px; font-weight:700; letter-spacing:0.3px;">
                        ${escapeHtml(title)}
                    </div>
                    <div style="font-size:12px; opacity:0.85; margin-top:4px;">
                        Project: ${escapeHtml(projName)} · Preset: ${escapeHtml(preset)}
                    </div>
                </div>
                <div style="font-size:14px; font-weight:600; text-align:right;">
                    ${escapeHtml(dateDisplay)}
                </div>
            </div>
            <div style="padding:14px 28px; background:#ffffff; border:1px solid #e2e8f0;
                        border-top:none; border-radius:0 0 8px 8px;">
                <div style="font-size:12px; color:#475569;">${escapeHtml(filterLine)}</div>
                ${summaryBlock}
            </div>
        </div>
    `;
}

/**
 * Build HTML cho khối comment 1 chart. Trống comment → return "" (không
 * thêm gì vào PDF).
 */
function _pdfBuildCommentHtml(comment) {
    const trimmed = (comment || "").trim();
    if (!trimmed) return "";
    return `
        <div style="margin-top:6px; padding:8px 12px;
                    border-top:1px dashed #cbd5e1;
                    background:#f8fafc;
                    color:#475569; font-size:12px; font-style:italic;
                    line-height:1.5; white-space:pre-wrap;">
            💬 <b style="font-style:normal; color:#334155;">Nhận xét:</b>
            ${escapeHtml(trimmed)}
        </div>
    `;
}

/**
 * Helper: cắt canvas cao thành nhiều slice vừa 1 trang PDF + addImage lần lượt.
 * Trả về cursorY mới sau khi add xong. Nếu ảnh vừa 1 trang → add trực tiếp.
 */
function _pdfAddCanvas(pdf, canvas, cursorY, opts) {
    const { pageW, pageH, margin, contentW } = opts;
    if (!canvas) return cursorY;
    const imgW = contentW;
    const imgH = (canvas.height * imgW) / canvas.width;
    const remainH = pageH - cursorY - margin;
    // Section quá cao so với chỗ còn lại → sang trang mới
    if (imgH > remainH || cursorY > pageH - 60) {
        pdf.addPage();
        cursorY = margin;
    }
    if (imgH <= pageH - cursorY - margin) {
        pdf.addImage(canvas.toDataURL("image/jpeg", 0.85),
            "JPEG", margin, cursorY, imgW, imgH);
        return cursorY + imgH + 4;
    }
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
    return pageH; // buộc trang sau bắt đầu mới
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

    // Auto-persist notes hiện tại trước khi generate (silent — không toast).
    // Nếu backend fail thì vẫn tiếp tục xuất với dữ liệu in-memory.
    try { await window.savePdfChartNotes(true); } catch (_) {}

    try {
        const scale = parseFloat(document.getElementById("pdfScale")?.value || "1.5");
        // "Tóm tắt chung của báo cáo" — hiển thị ở trang cover (max 500 ký tự).
        const summary = document.getElementById("pdfNotes")?.value?.trim() || "";
        const dateStr = document.getElementById("pdfReportDate")?.value || new Date().toISOString().slice(0, 10);
        const [yy, mm, dd] = dateStr.split("-");
        const displayDate = `${dd}/${mm}/${yy}`;
        const suffix = _pdfPresetSuffix();
        const projName = window._projectMeta?.project?.name || currentProjectSlug;
        // Comment per-chart: đọc từ state, key = section id
        const chartNotes = _pdfCollectChartNotes(ids);

        const { jsPDF } = window.jspdf;
        const pdf = new jsPDF({ unit: "mm", format: "a4", orientation: "portrait" });
        const pageW = pdf.internal.pageSize.getWidth();   // 210
        const pageH = pdf.internal.pageSize.getHeight();  // 297
        const margin = 10;
        const contentW = pageW - margin * 2;
        const addOpts = { pageW, pageH, margin, contentW };

        // ==== COVER PAGE (render qua html2canvas → khắc phục mojibake) ====
        // widthPx=800px tương ứng ~200mm khi scale=2 → font đẹp, không vỡ nét.
        const coverHtml = _pdfBuildCoverHtml({
            title: "📊 Báo cáo iHRP Function List",
            projName, dateDisplay: displayDate, preset: suffix,
            filterLine: _pdfFilterSubtitle(),
            summary,
        });
        const coverCanvas = await _pdfCaptureHtml(coverHtml, 800, 2);
        let cursorY = margin;
        cursorY = _pdfAddCanvas(pdf, coverCanvas, cursorY, addOpts);

        // ==== CAPTURE EACH SECTION (+ optional comment box) ====
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

            cursorY = _pdfAddCanvas(pdf, canvas, cursorY, addOpts);

            // Comment per-chart: render riêng để giữ khả năng cắt trang linh hoạt
            const comment = chartNotes[sid];
            if (comment && comment.trim()) {
                const commentHtml = _pdfBuildCommentHtml(comment);
                const commentCanvas = await _pdfCaptureHtml(commentHtml, 800, 2);
                cursorY = _pdfAddCanvas(pdf, commentCanvas, cursorY, addOpts);
            }
        }

        // ==== FOOTER: "Trang X/Y" — chỉ chứa ASCII an toàn (không diacritic) ====
        const totalPages = pdf.internal.getNumberOfPages();
        for (let p = 1; p <= totalPages; p++) {
            pdf.setPage(p);
            pdf.setFontSize(8);
            pdf.setTextColor(100, 116, 139);
            // "Trang" / "Generate" không có diacritic → helvetica render OK.
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
// T25 — PRESENTATION MODE
// ========================================================================
// Trình chiếu 1 section/lúc. Arrow keys ← → điều hướng, Esc thoát.
// Respect thứ tự hiện tại của DOM (đã apply custom order từ backend) và
// bỏ qua section đang có class 'hidden'. Ẩn header + sidebar để giao diện
// full-screen cho meeting/review.
const _presentState = {
    active: false,
    sections: [],   // array of section IDs eligible
    index: 0,
    prevBodyClass: "",
    keyHandler: null,
};

function _presentCollectSections() {
    const dash = document.getElementById("dashboard");
    if (!dash) return [];
    const out = [];
    Array.from(dash.children).forEach(el => {
        if (!el.id) return;
        if (el.id === "section-summary-header") return;  // header-only
        if (el.classList.contains("hidden")) return;
        // Bỏ qua các section đang bị chart-config ẩn (data-hidden="true")
        if (el.getAttribute("data-hidden") === "true") return;
        out.push(el.id);
    });
    return out;
}

// Mapping section-id → tên function lazy-load (fetch data + render). Chỉ
// trigger 1 lần / section / phiên trình chiếu (đã ghi vào
// _presentState.loaded set). Bug T25: section lazy-load không auto-fetch
// khi enter presentation nếu chưa từng scroll đến → body trắng vì chưa
// có data render.
const _PRESENT_LAZY_LOADERS = {
    "section-gantt-calendar": "loadGanttCalendar",
    "section-dataquality":    "loadDataQuality",
    "section-aging-wip":      "loadAgingWip",
    "section-my-bookmarks":   "loadBookmarks",
    "section-my-digests":     "loadDigests",
    "section-kanban":         "loadKanban",
    "section-burndown":       "loadBurndownAndSLA",
    "section-sla":            "loadBurndownAndSLA",
    "section-fitgap-dashboard": "loadFitgapDashboard",
    "section-function-diff":  "loadFunctionDiff",
    "section-custom-dashboards": "loadCustomDashboards",
};

function _presentApplyIndex() {
    const dash = document.getElementById("dashboard");
    if (!dash || !_presentState.sections.length) return;
    // Ẩn tất cả top-level (dùng class 'present-off'), rồi bỏ ẩn cái đang chọn
    Array.from(dash.children).forEach(el => {
        if (!el.id || el.id === "section-summary-header") {
            el.classList.add("present-off");
            return;
        }
        el.classList.add("present-off");
    });
    const activeId = _presentState.sections[_presentState.index];
    const active = document.getElementById(activeId);
    if (active) {
        active.classList.remove("present-off");
        active.classList.add("present-active");
        // Scroll vào giữa
        try { active.scrollIntoView({ behavior: "smooth", block: "start" }); } catch (_) {}
    }
    // Update HUD (progress + tên section)
    const hud = document.getElementById("presentHud");
    if (hud) {
        const titleEl = active ? active.querySelector("h3, h2") : null;
        const label = titleEl ? titleEl.textContent.trim().slice(0, 80) : (active ? active.id : "");
        hud.innerHTML = `
            <span class="present-hud-index">${_presentState.index + 1} / ${_presentState.sections.length}</span>
            <span class="present-hud-title">${escapeHtml(label)}</span>
            <span class="present-hud-hint">← → điều hướng · Esc thoát</span>
        `;
    }
    // FIX regression T25 (body trắng):
    // - Chart.js canvas cần resize() sau khi container display đổi
    //   (canvas render 0×0 nếu parent lúc init bị 'display:none').
    // - Section lazy-load (Kanban/Burndown/DQ/Aging/Gantt Calendar/...)
    //   phải trigger loader ngay khi first shown trong presentation mode.
    // Dùng 2-tier delay để DOM layout xong trước khi resize (60ms → 200ms).
    _presentLazyLoad(activeId);
    setTimeout(() => _presentResizeActive(activeId), 60);
    setTimeout(() => _presentResizeActive(activeId), 250);
}

/**
 * Trigger lazy loader cho 1 section — mỗi section chỉ chạy 1 lần / phiên
 * trình chiếu (tracked qua Set để tránh re-fetch mỗi lần Next/Prev quay lại).
 */
function _presentLazyLoad(sectionId) {
    if (!sectionId) return;
    _presentState.loaded = _presentState.loaded || new Set();
    if (_presentState.loaded.has(sectionId)) return;
    const fnName = _PRESENT_LAZY_LOADERS[sectionId];
    if (!fnName) {
        _presentState.loaded.add(sectionId);
        return;
    }
    const fn = window[fnName];
    if (typeof fn === "function") {
        try {
            const ret = fn();
            if (ret && typeof ret.then === "function") {
                ret.then(() => _presentResizeActive(sectionId)).catch(() => {});
            }
        } catch (e) {
            console.warn(`[presentLazyLoad] ${fnName} failed:`, e);
        }
    }
    _presentState.loaded.add(sectionId);
}

/**
 * Resize mọi Chart.js instance nằm trong section active. Dùng Chart.getChart()
 * (Chart.js v3+) để lookup instance từ canvas element — không phụ thuộc
 * vào registry `chartInstances` (nhiều chart config custom không lưu vào
 * registry đó).
 */
function _presentResizeActive(sectionId) {
    const active = document.getElementById(sectionId || _presentState.sections[_presentState.index]);
    if (!active) return;
    // Resize từng canvas trong section
    active.querySelectorAll("canvas").forEach(canvas => {
        try {
            if (typeof Chart !== "undefined" && Chart.getChart) {
                const chart = Chart.getChart(canvas);
                if (chart) chart.resize();
            }
        } catch (e) { /* ignore */ }
    });
    // Bell fallback: dispatch window resize để catch chart dùng ResizeObserver
    // hoặc listener riêng (VD Kanban board tính lại column width).
    try { window.dispatchEvent(new Event("resize")); } catch (_) {}
}

function _presentGo(delta) {
    if (!_presentState.active) return;
    const n = _presentState.sections.length;
    if (!n) return;
    _presentState.index = (_presentState.index + delta + n) % n;
    _presentApplyIndex();
}

function _presentEnsureHud() {
    let hud = document.getElementById("presentHud");
    if (!hud) {
        hud = document.createElement("div");
        hud.id = "presentHud";
        hud.className = "present-hud no-print";
        document.body.appendChild(hud);
    }
    return hud;
}

window.togglePresentationMode = function () {
    if (_presentState.active) {
        _presentExit();
    } else {
        _presentEnter();
    }
};

function _presentEnter() {
    const sections = _presentCollectSections();
    if (!sections.length) {
        showToast("Chưa có section nào để trình chiếu", "red");
        return;
    }
    _presentState.active = true;
    _presentState.sections = sections;
    _presentState.index = 0;
    _presentState.loaded = new Set();  // reset lazy-load tracker mỗi phiên trình chiếu
    _presentState.prevBodyClass = document.body.className;
    document.body.classList.add("presentation-mode");
    _presentEnsureHud();
    _presentApplyIndex();
    // Register keys (arrow + esc)
    _presentState.keyHandler = (ev) => {
        // Tránh interfere khi user đang gõ trong input/textarea
        const t = ev.target;
        if (t && (t.tagName === "INPUT" || t.tagName === "TEXTAREA" || t.isContentEditable)) return;
        if (ev.key === "ArrowRight" || ev.key === "PageDown" || ev.key === " ") {
            ev.preventDefault();
            _presentGo(1);
        } else if (ev.key === "ArrowLeft" || ev.key === "PageUp") {
            ev.preventDefault();
            _presentGo(-1);
        } else if (ev.key === "Escape") {
            ev.preventDefault();
            _presentExit();
        } else if (ev.key === "Home") {
            _presentState.index = 0; _presentApplyIndex();
        } else if (ev.key === "End") {
            _presentState.index = _presentState.sections.length - 1; _presentApplyIndex();
        }
    };
    document.addEventListener("keydown", _presentState.keyHandler);
    const btn = document.getElementById("btnPresentMode");
    if (btn) { btn.textContent = "❌ Thoát trình chiếu"; btn.title = "Thoát trình chiếu (Esc)"; }
    showToast("Trình chiếu — ← → điều hướng, Esc thoát");
}

function _presentExit() {
    _presentState.active = false;
    document.body.className = _presentState.prevBodyClass || "";
    document.body.classList.remove("presentation-mode");
    // Restore all sections
    const dash = document.getElementById("dashboard");
    if (dash) {
        Array.from(dash.children).forEach(el => {
            el.classList.remove("present-off");
            el.classList.remove("present-active");
        });
    }
    if (_presentState.keyHandler) {
        document.removeEventListener("keydown", _presentState.keyHandler);
        _presentState.keyHandler = null;
    }
    const hud = document.getElementById("presentHud");
    if (hud) hud.remove();
    const btn = document.getElementById("btnPresentMode");
    if (btn) { btn.textContent = "🎬 Trình chiếu"; btn.title = "Chế độ trình chiếu (1 section/lần, ← → điều hướng, Esc thoát)"; }
}

// ========================================================================
// T21 — DATA QUALITY PANEL
// ========================================================================
let _dqState = {
    issues: [],
    summary: null,
    filterSeverity: "all",
    filterCode: "all",
    filterModules: [],   // T35 Task 3 — local Module filter (client-side)
    page: 1,
    pageSize: 30,
};
let _dqModuleMs = null;  // createMultiSelect instance

async function loadDataQuality() {
    const section = document.getElementById("section-dataquality");
    if (!section) return;
    try {
        // Global filter (module/process/pic) đã được BE áp dụng qua _filtered_data_from_request
        const qsFilter = _buildFilterQuery();
        const url = `/api/projects/${currentProjectSlug}/data-quality${qsFilter ? "?" + qsFilter : ""}`;
        const r = await fetch(url);
        if (!r.ok) throw new Error(await r.text());
        const d = await r.json();
        _dqState.issues = d.issues || [];
        _dqState.summary = d.summary || null;
        _dqState.page = 1;

        // Populate code + module filters
        _dqPopulateCodeFilter();
        _dqPopulateModuleFilter();
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

/**
 * T35 Task 3 — Populate local Module multi-select từ danh sách module
 * xuất hiện trong issues hiện tại (sau global filter).
 */
function _dqPopulateModuleFilter() {
    const el = document.getElementById("dqModuleFilter");
    if (!el || typeof createMultiSelect !== "function") return;
    const mods = [...new Set(
        (_dqState.issues || []).map(it => it.module).filter(Boolean)
    )].sort();
    // Giữ selection còn hợp lệ sau khi data đổi
    const keep = (_dqState.filterModules || []).filter(m => mods.includes(m));
    _dqState.filterModules = keep;
    if (!_dqModuleMs) {
        _dqModuleMs = createMultiSelect({
            el,
            key: "dqModules",
            label: "Module",
            options: mods,
            selected: keep,
            allText: "Tất cả module",
            onChange: (arr) => {
                _dqState.filterModules = arr || [];
                _dqState.page = 1;
                _dqRenderTable();
            },
        });
    } else if (typeof _dqModuleMs.setOptions === "function") {
        _dqModuleMs.setOptions(mods);
        if (typeof _dqModuleMs.setSelected === "function") {
            _dqModuleMs.setSelected(keep);
        }
    }
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
    const mods = _dqState.filterModules || [];
    return _dqState.issues.filter(it => {
        if (s !== "all" && it.severity !== s) return false;
        if (c !== "all" && it.code !== c) return false;
        // T35 Task 3 — local Module filter
        if (mods.length && !mods.includes(it.module || "")) return false;
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
    // T35 Task 3 — Export respect cả global filter + local Module filter.
    // Local modules (nếu chọn) giao với global modules → gửi param `module`.
    const p = new URLSearchParams();
    const localMods = _dqState.filterModules || [];
    const globalMods = (typeof globalFilters !== "undefined" && globalFilters.modules) || [];
    let modules;
    if (localMods.length && globalMods.length) {
        const gSet = new Set(globalMods);
        modules = localMods.filter(m => gSet.has(m));
        if (!modules.length) modules = localMods; // fallback: local thắng nếu giao rỗng
    } else if (localMods.length) {
        modules = localMods;
    } else if (globalMods.length) {
        modules = globalMods;
    }
    if (modules && modules.length) p.set("module", modules.join(","));
    if (typeof globalFilters !== "undefined") {
        if (globalFilters.processes && globalFilters.processes.length) {
            p.set("process", globalFilters.processes.join(","));
        }
        if (globalFilters.pics && globalFilters.pics.length) {
            p.set("pic", globalFilters.pics.join(","));
        }
    }
    const qs = p.toString();
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
        tbody.innerHTML = `<tr><td colspan="10" class="text-center py-6 text-green-600">
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
            ${_viewIconCell(it.ma_cn, {title: "Xem chi tiết function aging"})}
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
    { id: "act.export-all-issues", label: "📊 Xuất toàn bộ vấn đề (Excel multi-sheet)", kind: "action",
      run: () => { if (typeof exportAllIssues === "function") exportAllIssues();
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
// T29 — SETTINGS MODAL (thresholds / aging WIP / reminder / digest schedule)
// ========================================================================
window.openSettingsModal = async function () {
    if (!currentProjectSlug) return;
    const modal = document.getElementById("settingsModal");
    if (!modal) return;
    try {
        const r = await fetch(`/api/projects/${currentProjectSlug}/settings`);
        if (!r.ok) throw new Error(await r.text());
        const s = await r.json();
        _fillSettingsForm(s);
    } catch (err) {
        console.error("[openSettingsModal]", err);
        showToast("Không tải được settings: " + err.message, "red");
    }
    // Render panel Hiển thị dựa trên _chartConfigsCache hiện tại — cache đã
    // load sẵn khi vào dashboard (loadChartConfigs) nên không cần fetch lại.
    _renderVisibilityPanel();
    // T33 Task 2C — load public API tokens (best-effort, không block modal)
    _pubTokRefresh().catch(err => console.warn("[pubtok load]", err));
    // T34 Task 2 — load LAN info + access log (best-effort)
    _lanRefresh().catch(err => console.warn("[lan load]", err));
    modal.classList.remove("hidden");
    modal.classList.add("flex");
};

window.closeSettingsModal = function () {
    const modal = document.getElementById("settingsModal");
    if (!modal) return;
    modal.classList.add("hidden");
    modal.classList.remove("flex");
};

function _fillSettingsForm(s) {
    const set = (id, val) => { const el = document.getElementById(id); if (el != null) el.value = val; };
    const chk = (id, val) => { const el = document.getElementById(id); if (el != null) el.checked = !!val; };
    const pt = s.progress_thresholds || {};
    set("setProgLow", pt.in_progress ?? 30);
    set("setProgHigh", pt.closed_soon ?? 70);
    set("setAgingWip", s.aging_wip_threshold ?? 14);
    set("setReminderDays", s.upload_reminder_days ?? 7);
    const sla = s.sla || {};
    set("setSlaMust", sla.must_have_days ?? 3);
    set("setSlaShould", sla.should_have_days ?? 7);
    const dig = s.digest || {};
    chk("setDigestEnabled", dig.enabled);
    set("setDigestDay", String(dig.day_of_week ?? 0));
    set("setDigestHour", dig.hour ?? 9);
    const last = document.getElementById("setDigestLast");
    if (last) {
        last.textContent = dig.last_generated_date
            ? `Lần sinh gần nhất: ${dig.last_generated_date}`
            : "Chưa từng sinh digest";
    }
}

window.saveSettings = async function () {
    if (!currentProjectSlug) return;
    const int0 = (id, def) => {
        const v = parseInt(document.getElementById(id)?.value, 10);
        return Number.isFinite(v) ? v : def;
    };
    const payload = {
        progress_thresholds: {
            in_progress: int0("setProgLow", 30),
            closed_soon: int0("setProgHigh", 70),
        },
        aging_wip_threshold: int0("setAgingWip", 14),
        upload_reminder_days: int0("setReminderDays", 7),
        sla: {
            must_have_days: int0("setSlaMust", 3),
            should_have_days: int0("setSlaShould", 7),
        },
        digest: {
            enabled: document.getElementById("setDigestEnabled")?.checked,
            day_of_week: int0("setDigestDay", 0),
            hour: int0("setDigestHour", 9),
        },
    };
    // Thu thập state của tab Hiển thị (bulk toggle ẩn/hiện section).
    const visMap = _collectVisibilityMap();
    try {
        // Chạy song song: PUT settings + PUT visibility bulk
        const [rSet, rVis] = await Promise.all([
            fetch(`/api/projects/${currentProjectSlug}/settings`, {
                method: "PUT",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(payload),
            }),
            Object.keys(visMap).length
                ? fetch(`/api/projects/${currentProjectSlug}/chart-config/visibility`, {
                    method: "PUT",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ visibility: visMap }),
                })
                : Promise.resolve(null),
        ]);
        if (!rSet.ok) throw new Error(await rSet.text());
        const s = await rSet.json();
        _fillSettingsForm(s);
        // Cập nhật cache chart_configs từ response bulk visibility (nếu có) và
        // apply ngay lập tức lên DOM — không reload trang, giữ nguyên filter.
        if (rVis && rVis.ok) {
            const d = await rVis.json();
            _chartConfigsCache = d.configs || {};
        }
        _applyVisibilityMapping(visMap);
        showToast("Đã lưu cài đặt", "green");
        // Refresh digest section (badge lịch có thể đổi)
        if (typeof loadDigests === "function") loadDigests();
        // Refresh aging WIP threshold (dùng ngưỡng mới nếu user đang xem section)
        try {
            if (typeof _agingState !== "undefined") {
                _agingState.threshold = s.aging_wip_threshold || 14;
                const slider = document.getElementById("agingThreshold");
                const label = document.getElementById("agingThresholdVal");
                if (slider) slider.value = _agingState.threshold;
                if (label) label.textContent = `${_agingState.threshold} ngày`;
                if (typeof _agingFetch === "function") _agingFetch();
            }
        } catch (e) { /* aging WIP not loaded yet */ }
        closeSettingsModal();
    } catch (err) {
        showToast("Lưu cài đặt lỗi: " + err.message, "red");
    }
};


// ========================================================================
// Tab "Hiển thị" — cấu hình ẩn/hiện section dashboard
// ------------------------------------------------------------------------
// - Metadata gom section theo 5 nhóm (Tổng quan / Tiến độ & Timeline /
//   Phân tích chuyên sâu / Danh sách & Cảnh báo / Tùy chỉnh & Lịch sử).
// - Auto-detect: chỉ render checkbox cho section thực sự tồn tại trong DOM
//   (tránh hiển thị section đã bị xoá / feature-flag off).
// - Persistence: reuse chart_configs.<section_id>.hidden qua endpoint bulk
//   PUT /api/projects/<slug>/chart-config/visibility.
// - Runtime: sau save, gọi applyChartConfigsToDom() để toggle .hidden class
//   ngay lập tức (không reload trang, giữ nguyên filter/pagination state).
// ========================================================================
const _VISIBILITY_GROUPS = [
    {
        name: "📊 Tổng quan",
        items: [
            { id: "section-summary",  label: "Summary cards",         desc: "Các thẻ KPI tổng quan trên đầu trang" },
            { id: "section-module",   label: "Module Overview",       desc: "Bảng tổng quan theo Module/Quy trình" },
            { id: "section-matrix",   label: "Matrix Phase × Module", desc: "Ma trận số function theo Phase × Module/Quy trình" },
            { id: "section-tasktype", label: "Task Type Progress",    desc: "Tiến độ theo loại công việc (Phân tích/Dev/Test/UAT/Golive)" },
            { id: "section-phase",    label: "Tiến độ theo Phase",    desc: "Stacked bar tiến độ status của từng phase" },
        ],
    },
    {
        name: "📈 Tiến độ & Timeline",
        items: [
            { id: "section-gantt",          label: "Gantt",              desc: "Sơ đồ Gantt lộ trình phase theo function" },
            { id: "section-gantt-calendar", label: "Gantt Calendar",     desc: "Timeline Excel-style: header Month/Week/Day, bar tô màu theo phase, marker Today" },
            { id: "section-burndown",       label: "Burndown & Velocity", desc: "Đường burndown + velocity theo tuần" },
            { id: "section-sla",            label: "SLA vi phạm",        desc: "Danh sách task vượt SLA theo priority" },
            { id: "section-duration",       label: "Duration",            desc: "Bảng thời lượng thực tế theo function" },
            { id: "section-giaidoan",       label: "Giai đoạn dự án",    desc: "Gộp phase theo giai đoạn (Phân tích/Phát triển/UAT/Golive)" },
        ],
    },
    {
        name: "🔬 Phân tích chuyên sâu",
        items: [
            { id: "section-pic",              label: "PIC Workload",             desc: "Khối lượng theo người phụ trách" },
            { id: "section-priority",         label: "Priority / Complexity / FIT-GAP mini", desc: "3 doughnut phân bố Priority — Complexity — FIT/GAP" },
            { id: "section-fitgap-dashboard", label: "FIT/GAP Dashboard",        desc: "Dashboard chi tiết cho BA quản lý lifecycle GAP" },
            { id: "section-process",          label: "Heatmap Quy trình",        desc: "Heatmap function theo quy trình × status" },
            { id: "section-effort",           label: "Heatmap Effort",           desc: "Heatmap MH theo Module × Phase" },
            { id: "section-slow",             label: "Heatmap Slow",             desc: "Heatmap function chậm theo module" },
            { id: "section-capacity",         label: "Capacity",                 desc: "So sánh capacity vs load thực tế của PIC" },
            { id: "section-baseline",         label: "Baseline Variance",        desc: "Chênh lệch baseline vs actual date" },
        ],
    },
    {
        name: "🚨 Danh sách & Cảnh báo",
        items: [
            { id: "section-overdue",     label: "Danh sách Overdue",   desc: "Bảng function trễ theo phase" },
            { id: "section-unassigned",  label: "Chưa phân công",      desc: "Bảng task chưa gán PIC" },
            { id: "section-stalled",     label: "Task đình trệ",       desc: "Task lâu không có cập nhật status" },
            { id: "section-risk",        label: "High Risk",           desc: "Function rủi ro cao (Priority × Complexity × Overdue)" },
            { id: "section-aging-wip",   label: "Aging WIP",           desc: "Task In-progress quá lâu (vượt ngưỡng ngày)" },
            { id: "section-dataquality", label: "Data Quality",        desc: "Bảng dữ liệu thiếu / không hợp lệ để dọn dẹp Excel" },
        ],
    },
    {
        name: "🛠️ Tùy chỉnh & Lịch sử",
        items: [
            { id: "section-custom-dashboards", label: "Custom Dashboards", desc: "Các dashboard do user tự cấu hình" },
            { id: "section-kanban",            label: "Kanban",            desc: "Board Kanban tự động theo Dev/BA" },
            { id: "section-my-bookmarks",      label: "Bookmarks ⭐",      desc: "Danh sách function đã đánh dấu sao" },
            { id: "section-my-digests",        label: "Digest lưu trữ",    desc: "Excel digest sinh tự động hàng tuần" },
            { id: "section-compare",           label: "Snapshot Compare",  desc: "So sánh 2 lần upload để phát hiện thay đổi" },
            { id: "section-function-diff",    label: "Function Diff",     desc: "Thay đổi so với snapshot upload trước" },
            { id: "section-deps",              label: "Dependencies",      desc: "Sơ đồ phụ thuộc giữa các function" },
            { id: "section-history",           label: "Lịch sử upload",    desc: "Timeline các lần upload snapshot" },
        ],
    },
];

/** Render checkbox list vào #visibilityPanel dựa trên _chartConfigsCache. */
function _renderVisibilityPanel() {
    const wrap = document.getElementById("visibilityPanel");
    if (!wrap) return;
    const html = _VISIBILITY_GROUPS.map(g => {
        // Auto-detect: chỉ liệt kê section thực sự có trong DOM
        const items = g.items.filter(it => document.getElementById(it.id));
        if (!items.length) return "";
        const rows = items.map(it => {
            const cfg = _chartConfigsCache[it.id] || {};
            const checked = !cfg.hidden;   // default: visible nếu không có cờ hidden
            return `
                <label class="flex items-start gap-2 text-xs cursor-pointer rounded px-1 py-0.5
                              hover:bg-slate-100 dark:hover:bg-slate-700">
                    <input type="checkbox" data-vis-id="${escapeAttr(it.id)}"
                           class="mt-0.5 flex-shrink-0" ${checked ? "checked" : ""}>
                    <span class="flex-1">
                        <span class="font-medium text-gray-800 dark:text-gray-100">${escapeHtml(it.label)}</span>
                        <span class="text-gray-500 dark:text-gray-400"> — ${escapeHtml(it.desc)}</span>
                    </span>
                </label>
            `;
        }).join("");
        return `
            <div class="border rounded-md p-2 bg-white/70 dark:bg-slate-800/40 dark:border-slate-600">
                <div class="text-xs font-semibold text-gray-700 dark:text-gray-100 mb-1">${escapeHtml(g.name)}</div>
                <div class="grid grid-cols-1 md:grid-cols-2 gap-x-3 gap-y-0.5">${rows}</div>
            </div>
        `;
    }).join("");
    wrap.innerHTML = html || `<p class="text-xs text-gray-500">Chưa có section nào để cấu hình.</p>`;
}

window._visSelectAll = function () {
    document.querySelectorAll("#visibilityPanel input[data-vis-id]").forEach(el => { el.checked = true; });
};

window._visClearAll = function () {
    document.querySelectorAll("#visibilityPanel input[data-vis-id]").forEach(el => { el.checked = false; });
};

/**
 * Khôi phục mặc định = tick tất cả (không có override nào).
 * User bấm Lưu → BE sẽ xoá hết cờ hidden cho các section trong panel.
 */
window._visResetDefault = function () {
    _visSelectAll();
    showToast("Đã đặt về mặc định — nhớ bấm Lưu để áp dụng", "blue");
};

/**
 * Đọc trạng thái checkbox → { section_id: true/false }.
 * Chỉ lấy các section có id (data-vis-id). Không đọc thứ tự.
 */
function _collectVisibilityMap() {
    const map = {};
    document.querySelectorAll("#visibilityPanel input[data-vis-id]").forEach(el => {
        map[el.dataset.visId] = !!el.checked;
    });
    return map;
}

/**
 * Áp dụng ngay lập tức lên DOM sau khi save (không reload trang).
 * Force toggle .hidden class theo mapping — respect user intent.
 */
function _applyVisibilityMapping(map) {
    if (!map) return;
    for (const [sid, visible] of Object.entries(map)) {
        const sec = document.getElementById(sid);
        if (!sec) continue;
        if (visible) {
            sec.classList.remove("hidden");
            delete sec.dataset.userHidden;
        } else {
            sec.classList.add("hidden");
            sec.dataset.userHidden = "1";
        }
    }
    if (typeof _renderHiddenSectionPills === "function") _renderHiddenSectionPills();
}


// ========================================================================
// T33 Task 2C — PUBLIC API TOKEN MANAGER (Settings tab "🌐 Public API")
// ========================================================================
// State cục bộ:
//   _pubTokState.scopes       — metadata multi-select scope từ BE
//   _pubTokState.tokens       — list token đã mask
//   _pubTokState.selected     — Set scope key user đang chọn (form create)
//   _pubTokState.lastNewToken — plaintext token vừa tạo (chỉ trong RAM,
//                               không lưu localStorage)
//   _pubTokState.snipTab      — "rest" | "iframe" | "png"
//   _pubTokState.snipChart    — chart_id đang preview cho iframe/PNG
const _pubTokState = {
    scopes: [],
    tokens: [],
    selected: new Set(),
    lastNewToken: "",
    snipTab: "rest",
    snipChart: "module-overview",
    // Tab riêng cho snippet-view modal (token cũ) — không share tab với new-token modal
    snipViewTab: "rest",
    snipViewChart: "module-overview",
    viewTokenPrefix: "",  // prefix hiển thị trong snippet-view modal (label)
    viewTokenName: "",
};

/** Load scope metadata + token list. Gọi khi mở settings modal. */
async function _pubTokRefresh() {
    if (!currentProjectSlug) return;
    try {
        // Fetch song song scope + tokens
        const [rScopes, rTokens] = await Promise.all([
            fetch(`/api/projects/${currentProjectSlug}/public-scopes`),
            fetch(`/api/projects/${currentProjectSlug}/public-tokens`),
        ]);
        if (!rScopes.ok || !rTokens.ok) throw new Error("Load public-api settings fail");
        const dScopes = await rScopes.json();
        const dTokens = await rTokens.json();
        _pubTokState.scopes = dScopes.scopes || [];
        _pubTokState.tokens = dTokens.tokens || [];
        _pubTokRenderList();
        _pubTokRenderScopes();
        _pubTokFillChartOptions();
    } catch (err) {
        console.error("[_pubTokRefresh]", err);
        showToast("Không tải được Public API: " + err.message, "red");
    }
}
window._pubTokRefresh = _pubTokRefresh;


// ==========================================================================
// T34 Task 2 — LAN info + access log UI trong Settings modal
// ==========================================================================
async function _lanRefresh() {
    // Fetch song song info + access log
    try {
        const [rInfo, rLog] = await Promise.all([
            fetch("/api/lan/info"),
            fetch("/api/lan/access-log?limit=100"),
        ]);
        if (rInfo.ok) _lanRenderInfo(await rInfo.json());
        // access-log có thể 403 nếu đang xem từ LAN — không phải lỗi
        if (rLog.ok) {
            _lanRenderAccessLog(await rLog.json());
        } else {
            const body = document.getElementById("lanAccessLogBody");
            if (body) {
                body.innerHTML = `<tr><td colspan="6" class="text-center text-orange-500 italic py-2">
                    🔒 Chỉ máy chủ (localhost) xem được access log.
                </td></tr>`;
            }
        }
    } catch (err) {
        console.error("[_lanRefresh]", err);
    }
}
window._lanRefresh = _lanRefresh;

function _lanRenderInfo(d) {
    // URL list
    const urlList = document.getElementById("lanUrlList");
    if (urlList) {
        urlList.innerHTML = (d.urls || []).map(u => {
            const isLocal = u.ip === "127.0.0.1";
            const badgeColor = isLocal ? "bg-slate-100 text-slate-700 dark:bg-slate-600 dark:text-slate-100"
                                        : "bg-blue-100 text-blue-800 dark:bg-blue-900 dark:text-blue-100";
            return `
                <div class="flex items-center gap-2 flex-wrap">
                    <span class="px-2 py-0.5 rounded text-[10px] ${badgeColor}">${escapeHtml(u.label || "")}</span>
                    <a href="${escapeAttr(u.url)}" target="_blank" class="font-mono text-blue-600 hover:underline">${escapeHtml(u.url)}</a>
                    <button type="button" onclick="_lanCopyUrl('${escapeAttr(u.url)}')"
                            class="text-[10px] px-1.5 py-0.5 border rounded hover:bg-white dark:hover:bg-slate-600 dark:border-slate-500"
                            title="Copy URL">📋</button>
                </div>
            `;
        }).join("");
    }
    // Badges
    const guardEl = document.getElementById("lanAdminGuardBadge");
    if (guardEl) {
        const on = d.admin_guard;
        guardEl.innerHTML = `Admin Guard: <span class="font-mono ${on ? 'text-green-600' : 'text-red-600'}">${on ? 'ON 🔒' : 'OFF ⚠'}</span>`;
    }
    const logEl = document.getElementById("lanAccessLogBadge");
    if (logEl) {
        const on = d.access_log;
        logEl.innerHTML = `Access Log: <span class="font-mono ${on ? 'text-green-600' : 'text-gray-500'}">${on ? 'ON' : 'OFF'}</span>`;
    }
    const clientEl = document.getElementById("lanCurrentClientBadge");
    if (clientEl) {
        const isLocal = d.is_localhost_request;
        clientEl.innerHTML = `Bạn đang: <span class="font-mono ${isLocal ? 'text-green-600' : 'text-orange-500'}">${isLocal ? 'LOCALHOST (admin OK)' : 'LAN (view only)'}</span>`;
    }
}

function _lanRenderAccessLog(d) {
    const body = document.getElementById("lanAccessLogBody");
    if (!body) return;
    const entries = d.entries || [];
    if (!entries.length) {
        body.innerHTML = `<tr><td colspan="6" class="text-center text-gray-400 italic py-2">Log rỗng</td></tr>`;
        return;
    }
    body.innerHTML = entries.map(e => {
        const t = (e.ts || "").split("T")[1] || e.ts;
        const status = Number(e.status || 0);
        const statusColor = status >= 500 ? "text-red-600"
                          : status >= 400 ? "text-orange-500"
                          : status >= 300 ? "text-blue-500"
                          : "text-green-600";
        const ipBadge = e.is_localhost
            ? "text-slate-700 dark:text-slate-200"
            : "text-orange-600 font-semibold";
        return `
            <tr class="border-t dark:border-slate-600">
                <td class="px-2 py-1 font-mono">${escapeHtml(t || "")}</td>
                <td class="px-2 py-1 font-mono ${ipBadge}">${escapeHtml(e.ip || "?")}</td>
                <td class="px-2 py-1 font-mono">${escapeHtml(e.method || "")}</td>
                <td class="px-2 py-1 font-mono truncate max-w-xs" title="${escapeAttr(e.path || "")}">${escapeHtml(e.path || "")}</td>
                <td class="px-2 py-1 text-right font-mono ${statusColor}">${status}</td>
                <td class="px-2 py-1 text-right font-mono text-gray-500">${e.duration_ms ?? 0}</td>
            </tr>
        `;
    }).join("");
}

async function _lanCopyUrl(url) {
    try {
        await navigator.clipboard.writeText(url);
        showToast(`✓ Đã copy: ${url}`);
    } catch {
        // Fallback textarea
        const ta = document.createElement("textarea");
        ta.value = url;
        document.body.appendChild(ta);
        ta.select();
        document.execCommand("copy");
        document.body.removeChild(ta);
        showToast(`✓ Đã copy: ${url}`);
    }
}
window._lanCopyUrl = _lanCopyUrl;


/** Render bảng token — mỗi row có nút Revoke + Xem snippet. */
function _pubTokRenderList() {
    const tbody = document.getElementById("pubTokListBody");
    const emptyMsg = document.getElementById("pubTokListEmpty");
    const table = document.getElementById("pubTokListTable");
    if (!tbody) return;
    const toks = _pubTokState.tokens || [];
    if (toks.length === 0) {
        tbody.innerHTML = "";
        if (emptyMsg) emptyMsg.classList.remove("hidden");
        if (table) table.classList.add("hidden");
        return;
    }
    if (emptyMsg) emptyMsg.classList.add("hidden");
    if (table) table.classList.remove("hidden");
    tbody.innerHTML = toks.map(t => {
        const scopeTxt = (t.scope || []).length > 3
            ? `${t.scope.slice(0, 3).join(", ")} + ${t.scope.length - 3}…`
            : (t.scope || []).join(", ");
        const revokedBadge = t.revoked
            ? `<span class="text-[10px] px-1.5 py-0.5 bg-red-100 text-red-700 rounded">Revoked</span>`
            : `<span class="text-[10px] px-1.5 py-0.5 bg-emerald-100 text-emerald-700 rounded">Active</span>`;
        const created = t.created_at ? t.created_at.slice(0, 10) : "-";
        const lastUsed = t.last_used_at ? t.last_used_at.slice(0, 10) : "chưa dùng";
        const actions = t.revoked
            ? `<button type="button" onclick="_pubTokViewSnippets('${escapeAttr(t.token_prefix)}','${escapeAttr(t.name)}')" class="text-[11px] px-2 py-0.5 border rounded hover:bg-white dark:hover:bg-slate-600 dark:border-slate-500" title="Xem lại snippet">🔗</button>`
            : `
                <button type="button" onclick="_pubTokViewSnippets('${escapeAttr(t.token_prefix)}','${escapeAttr(t.name)}')" class="text-[11px] px-2 py-0.5 border rounded hover:bg-white dark:hover:bg-slate-600 dark:border-slate-500 mr-1" title="Xem snippet copy-ready">🔗</button>
                <button type="button" onclick="_pubTokRevoke('${t.id}','${escapeAttr(t.name)}')" class="text-[11px] px-2 py-0.5 border border-red-300 text-red-600 rounded hover:bg-red-50 dark:hover:bg-red-900/30" title="Revoke token này">🚫</button>
            `;
        return `<tr class="${t.revoked ? 'opacity-60' : ''} border-t dark:border-slate-600">
            <td class="px-2 py-1">${escapeHtml(t.name)} ${revokedBadge}</td>
            <td class="px-2 py-1 font-mono text-[10px]">${escapeHtml(t.token_prefix || '')}…</td>
            <td class="px-2 py-1 text-[10px] text-gray-600 dark:text-gray-400" title="${escapeAttr((t.scope || []).join(', '))}">${escapeHtml(scopeTxt)}</td>
            <td class="px-2 py-1 text-[11px]">${created}</td>
            <td class="px-2 py-1 text-[11px]">${lastUsed}</td>
            <td class="px-2 py-1 text-right whitespace-nowrap">${actions}</td>
        </tr>`;
    }).join("");
}

/** Render grid checkbox scope cho form create. */
function _pubTokRenderScopes() {
    const grid = document.getElementById("pubTokScopeGrid");
    if (!grid) return;
    const scopes = _pubTokState.scopes || [];
    grid.innerHTML = scopes.map(s => {
        const checked = _pubTokState.selected.has(s.key) ? "checked" : "";
        const special = s.key === "*" ? "font-semibold text-blue-700 dark:text-blue-400" : "";
        return `<label class="flex items-center gap-1.5 text-xs ${special} cursor-pointer">
            <input type="checkbox" data-scope-key="${escapeAttr(s.key)}" ${checked}
                   onchange="_pubTokOnScopeToggle(this)" class="scale-90">
            <span title="${escapeAttr(s.key)}">${escapeHtml(s.label || s.key)}</span>
        </label>`;
    }).join("");
}

/** Populate select chart_id trong 2 modal snippet (dùng chung metadata). */
function _pubTokFillChartOptions() {
    const CHART_KEYS = (_pubTokState.scopes || [])
        .map(s => s.key)
        .filter(k => k !== "*" && k !== "summary" && k !== "functions");
    const html = CHART_KEYS.map(k => `<option value="${escapeAttr(k)}">${escapeHtml(k)}</option>`).join("");
    ["pubTokSnipChart", "pubTokSnipViewChart"].forEach(id => {
        const sel = document.getElementById(id);
        if (sel && !sel.dataset.filled) {
            sel.innerHTML = html;
            sel.dataset.filled = "1";
            // Set default
            if (CHART_KEYS.includes(_pubTokState.snipChart)) sel.value = _pubTokState.snipChart;
        }
    });
}

window._pubTokOnScopeToggle = function (checkbox) {
    const key = checkbox.dataset.scopeKey;
    if (checkbox.checked) _pubTokState.selected.add(key);
    else _pubTokState.selected.delete(key);
};

window._pubTokScopeAll = function () {
    _pubTokState.selected = new Set(
        (_pubTokState.scopes || []).map(s => s.key).filter(k => k !== "*")
    );
    _pubTokRenderScopes();
};

window._pubTokScopeNone = function () {
    _pubTokState.selected.clear();
    _pubTokRenderScopes();
};

window._pubTokScopeWildcard = function () {
    _pubTokState.selected = new Set(["*"]);
    _pubTokRenderScopes();
};

window._pubTokToggleCreate = function (show) {
    const form = document.getElementById("pubTokCreateForm");
    const openBtn = document.getElementById("pubTokCreateOpenBtn");
    if (!form || !openBtn) return;
    if (show) {
        form.classList.remove("hidden");
        openBtn.classList.add("hidden");
        // Reset form
        document.getElementById("pubTokName").value = "";
        _pubTokState.selected.clear();
        _pubTokRenderScopes();
    } else {
        form.classList.add("hidden");
        openBtn.classList.remove("hidden");
    }
};

window._pubTokSubmitCreate = async function () {
    const name = (document.getElementById("pubTokName")?.value || "").trim();
    if (!name) {
        showToast("Nhập tên token", "red");
        return;
    }
    const scope = Array.from(_pubTokState.selected);
    if (scope.length === 0) {
        showToast("Chọn ít nhất 1 scope (hoặc '🌟 Wildcard *')", "red");
        return;
    }
    try {
        const r = await fetch(`/api/projects/${currentProjectSlug}/public-tokens`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ name, scope }),
        });
        const d = await r.json();
        if (!r.ok) throw new Error(d.error || `HTTP ${r.status}`);
        // Đóng form + show modal token
        _pubTokToggleCreate(false);
        _pubTokState.lastNewToken = d.token || "";
        _pubTokState.viewTokenPrefix = (d.entry && d.entry.token_prefix) || "";
        _pubTokState.viewTokenName = (d.entry && d.entry.name) || name;
        // Refresh list
        await _pubTokRefresh();
        _pubTokOpenNewModal();
    } catch (err) {
        console.error("[_pubTokSubmitCreate]", err);
        showToast("Tạo token lỗi: " + err.message, "red");
    }
};

window._pubTokRevoke = async function (tokenId, name) {
    if (!confirm(`Revoke token "${name}"?\nToken này sẽ không dùng được nữa.`)) return;
    try {
        const r = await fetch(
            `/api/projects/${currentProjectSlug}/public-tokens/${encodeURIComponent(tokenId)}`,
            { method: "DELETE" },
        );
        if (!r.ok) throw new Error((await r.json()).error || `HTTP ${r.status}`);
        showToast(`Đã revoke token "${name}"`);
        await _pubTokRefresh();
    } catch (err) {
        showToast("Revoke lỗi: " + err.message, "red");
    }
};

// --- New-token modal (hiển 1 lần plaintext + snippet) ---

function _pubTokOpenNewModal() {
    const modal = document.getElementById("pubTokNewModal");
    if (!modal) return;
    document.getElementById("pubTokNewValue").value = _pubTokState.lastNewToken;
    _pubTokState.snipTab = "rest";
    _pubTokSetTabActive("rest", false);
    _pubTokSnipUpdate(false);
    modal.classList.remove("hidden");
    modal.classList.add("flex");
}

window._pubTokCloseNewModal = function () {
    const modal = document.getElementById("pubTokNewModal");
    if (!modal) return;
    modal.classList.add("hidden");
    modal.classList.remove("flex");
    // Xoá plaintext khỏi RAM state — không lưu, không log
    _pubTokState.lastNewToken = "";
    const input = document.getElementById("pubTokNewValue");
    if (input) input.value = "";
};

window._pubTokCopyValue = async function () {
    const input = document.getElementById("pubTokNewValue");
    if (!input) return;
    try {
        await navigator.clipboard.writeText(input.value);
        showToast("Đã copy token — nhớ dán vào password manager");
    } catch (e) {
        input.select();
        document.execCommand("copy");
        showToast("Đã copy (fallback)");
    }
};

// --- Snippet view modal (cho token cũ, không có plaintext) ---

window._pubTokViewSnippets = function (tokenPrefix, name) {
    _pubTokState.viewTokenPrefix = tokenPrefix || "";
    _pubTokState.viewTokenName = name || "";
    const modal = document.getElementById("pubTokSnipModal");
    if (!modal) return;
    const nameEl = document.getElementById("pubTokSnipTokenName");
    if (nameEl) nameEl.textContent = name || "";
    _pubTokState.snipViewTab = "rest";
    _pubTokSetTabActive("rest", true);
    _pubTokSnipUpdate(true);
    modal.classList.remove("hidden");
    modal.classList.add("flex");
};

window._pubTokCloseSnipModal = function () {
    const modal = document.getElementById("pubTokSnipModal");
    if (!modal) return;
    modal.classList.add("hidden");
    modal.classList.remove("flex");
};

// --- Snippet tabs + generate ---

window._pubTokSnipTab = function (tab, isView) {
    if (isView) {
        _pubTokState.snipViewTab = tab;
    } else {
        _pubTokState.snipTab = tab;
    }
    _pubTokSetTabActive(tab, isView);
    _pubTokSnipUpdate(isView);
};

function _pubTokSetTabActive(tab, isView) {
    const sel = isView ? "[data-snip-view-tab]" : "[data-snip-tab]";
    document.querySelectorAll(sel).forEach(btn => {
        const active = btn.dataset[isView ? "snipViewTab" : "snipTab"] === tab;
        btn.classList.toggle("border-blue-600", active);
        btn.classList.toggle("text-blue-600", active);
        btn.classList.toggle("font-semibold", active);
        btn.classList.toggle("border-transparent", !active);
        btn.classList.toggle("text-gray-500", !active);
    });
    // Chart selector chỉ hiện với iframe / png
    const showChart = tab === "iframe" || tab === "png";
    const label = document.getElementById(isView ? "pubTokSnipViewChartLabel" : "pubTokSnipChartLabel");
    if (label) label.style.display = showChart ? "" : "none";
}

/** Build snippet dựa vào tab + chart_id + host. */
function _pubTokBuildSnippet(tab, chartId, tokenValue) {
    const host = window.location.origin;   // VD http://localhost:5000
    const slug = currentProjectSlug || "<slug>";
    const tok = tokenValue || "pub_YOUR_TOKEN";
    if (tab === "rest") {
        return [
            `# Bash / curl`,
            `curl -H "X-API-Key: ${tok}" \\`,
            `  "${host}/public/api/v1/projects/${slug}/summary"`,
            ``,
            `# PowerShell`,
            `$headers = @{"X-API-Key" = "${tok}"}`,
            `Invoke-RestMethod -Uri "${host}/public/api/v1/projects/${slug}/summary" -Headers $headers`,
            ``,
            `# Chart cụ thể (thay <chart_id>)`,
            `curl -H "X-API-Key: ${tok}" \\`,
            `  "${host}/public/api/v1/projects/${slug}/charts/${chartId || 'module-overview'}"`,
            ``,
            `# Danh sách function (pagination)`,
            `curl -H "X-API-Key: ${tok}" \\`,
            `  "${host}/public/api/v1/projects/${slug}/functions?page=1&size=50"`,
        ].join("\n");
    }
    if (tab === "iframe") {
        return `<iframe
  src="${host}/embed/${slug}/${chartId || 'module-overview'}?token=${tok}"
  width="800" height="400"
  frameborder="0"
  title="iHRP Chart"></iframe>

<!-- Tùy chọn: nền trong suốt -->
<iframe
  src="${host}/embed/${slug}/${chartId || 'module-overview'}?token=${tok}&bg=transparent"
  width="800" height="400"
  frameborder="0"
  style="background: transparent"></iframe>`;
    }
    if (tab === "png") {
        return `<!-- Ảnh PNG snapshot (Playwright cần cài trên server) -->
<img src="${host}/public/api/v1/projects/${slug}/charts/${chartId || 'module-overview'}/image?w=800&h=400&token=${tok}"
     alt="${chartId || 'module-overview'}"
     width="800" height="400" />

<!-- Word/email: tải xuống trực tiếp -->
<a href="${host}/public/api/v1/projects/${slug}/charts/${chartId || 'module-overview'}/image?w=1200&h=600&token=${tok}"
   download="${chartId || 'module-overview'}.png">Tải PNG (1200×600)</a>`;
    }
    return "";
}

window._pubTokSnipUpdate = function (isView) {
    const tab = isView ? _pubTokState.snipViewTab : _pubTokState.snipTab;
    const chartSel = document.getElementById(isView ? "pubTokSnipViewChart" : "pubTokSnipChart");
    const chartId = chartSel?.value || "module-overview";
    if (isView) _pubTokState.snipViewChart = chartId;
    else _pubTokState.snipChart = chartId;
    const tokenValue = isView ? "" : _pubTokState.lastNewToken;
    const body = _pubTokBuildSnippet(tab, chartId, tokenValue);
    const el = document.getElementById(isView ? "pubTokSnipViewBody" : "pubTokSnipBody");
    if (el) el.textContent = body;
};

window._pubTokCopySnippet = async function (isView) {
    const el = document.getElementById(isView ? "pubTokSnipViewBody" : "pubTokSnipBody");
    if (!el) return;
    try {
        await navigator.clipboard.writeText(el.textContent);
        showToast("Đã copy snippet");
    } catch (e) {
        const range = document.createRange();
        range.selectNode(el);
        window.getSelection().removeAllRanges();
        window.getSelection().addRange(range);
        document.execCommand("copy");
        showToast("Đã copy (fallback)");
    }
};

// --- Helper escape (nếu chưa có escapeAttr trong global) ---
if (typeof window.escapeAttr !== "function") {
    window.escapeAttr = function (s) {
        return String(s == null ? "" : s)
            .replace(/&/g, "&amp;")
            .replace(/"/g, "&quot;")
            .replace(/'/g, "&#39;")
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;");
    };
}


// ========================================================================
// T26 — WEEKLY DIGEST ARCHIVE
// ========================================================================
const _DIGEST_DAY_NAMES = ["Thứ 2", "Thứ 3", "Thứ 4", "Thứ 5", "Thứ 6", "Thứ 7", "Chủ nhật"];

async function loadDigests() {
    if (!currentProjectSlug) return;
    const section = document.getElementById("section-my-digests");
    if (!section) return;
    try {
        // Fetch song song: list digest + settings (để hiện badge lịch)
        const [rList, rSet] = await Promise.all([
            fetch(`/api/projects/${currentProjectSlug}/digests`),
            fetch(`/api/projects/${currentProjectSlug}/settings`),
        ]);
        const list = rList.ok ? await rList.json() : { items: [] };
        const settings = rSet.ok ? await rSet.json() : {};
        _renderDigestList(list.items || [], settings);
    } catch (err) {
        console.error("[loadDigests]", err);
    }
}

function _renderDigestList(items, settings) {
    const section = document.getElementById("section-my-digests");
    const listEl = document.getElementById("digestList");
    const badgeText = document.getElementById("digestScheduleText");
    if (!section || !listEl) return;

    // Badge lịch
    if (badgeText) {
        const dig = (settings && settings.digest) || {};
        if (dig.enabled) {
            const dayLbl = _DIGEST_DAY_NAMES[dig.day_of_week] || `Thứ ${dig.day_of_week + 2}`;
            const hr = String(dig.hour ?? 9).padStart(2, "0");
            badgeText.textContent = `${dayLbl} lúc ${hr}:00`;
        } else {
            badgeText.textContent = "Tắt";
        }
    }

    // Nếu chưa có file digest và schedule off → ẩn section cho gọn dashboard
    if (!items.length && !(settings && settings.digest && settings.digest.enabled)) {
        section.classList.add("hidden");
        return;
    }
    section.classList.remove("hidden");

    if (!items.length) {
        listEl.innerHTML = `<div class="text-gray-500 text-sm italic py-3">Chưa có digest nào — bấm "Sinh digest ngay" hoặc chờ scheduler tự sinh.</div>`;
        return;
    }
    // Render bảng: filename | created_at | size | actions
    listEl.innerHTML = `
        <div class="overflow-x-auto">
            <table class="w-full text-sm">
                <thead class="bg-gray-100 text-gray-700">
                    <tr>
                        <th class="px-3 py-2 text-left">File digest</th>
                        <th class="px-3 py-2 text-left">Sinh lúc</th>
                        <th class="px-3 py-2 text-right">Kích thước</th>
                        <th class="px-3 py-2 text-center">Thao tác</th>
                    </tr>
                </thead>
                <tbody>
                    ${items.map(it => {
                        const sizeKb = (it.size_bytes / 1024).toFixed(1);
                        const ts = _fmtDigestTime(it.created_at);
                        const url = `/api/projects/${currentProjectSlug}/digests/${encodeURIComponent(it.filename)}`;
                        return `<tr class="border-b hover:bg-slate-50">
                            <td class="px-3 py-2 font-mono text-xs">${escapeHtml(it.filename)}</td>
                            <td class="px-3 py-2 text-xs text-gray-600">${escapeHtml(ts)}</td>
                            <td class="px-3 py-2 text-right text-xs text-gray-600">${sizeKb} KB</td>
                            <td class="px-3 py-2 text-center">
                                <a href="${url}" class="text-blue-600 hover:underline text-xs mr-3" download>⬇ Tải</a>
                                <button onclick="_deleteDigest('${escapeAttr(it.filename)}')"
                                        class="text-red-500 hover:text-red-700 text-xs">🗑 Xoá</button>
                            </td>
                        </tr>`;
                    }).join("")}
                </tbody>
            </table>
        </div>`;
}

function _fmtDigestTime(iso) {
    if (!iso) return "—";
    try {
        const d = new Date(iso);
        if (isNaN(d.getTime())) return iso;
        const pad = n => String(n).padStart(2, "0");
        return `${pad(d.getDate())}/${pad(d.getMonth() + 1)}/${d.getFullYear()} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
    } catch (e) { return iso; }
}

window.generateDigestNow = async function () {
    if (!currentProjectSlug) return;
    try {
        showToast("Đang sinh digest...");
        const r = await fetch(`/api/projects/${currentProjectSlug}/digests`, { method: "POST" });
        if (!r.ok) {
            const err = await r.json().catch(() => ({}));
            showToast(err.error || "Sinh digest thất bại", "red");
            return;
        }
        const d = await r.json();
        showToast(`✅ Đã sinh ${d.filename}`, "green");
        // Reload settings + list
        loadDigests();
    } catch (err) {
        showToast("Lỗi mạng: " + err.message, "red");
    }
};

window._deleteDigest = async function (filename) {
    if (!currentProjectSlug || !filename) return;
    if (!confirm(`Xoá digest "${filename}"?`)) return;
    try {
        const r = await fetch(`/api/projects/${currentProjectSlug}/digests/${encodeURIComponent(filename)}`, { method: "DELETE" });
        if (!r.ok) {
            showToast("Xoá thất bại", "red");
            return;
        }
        showToast("Đã xoá");
        loadDigests();
    } catch (err) {
        showToast("Lỗi: " + err.message, "red");
    }
};


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
        <div class="border rounded-lg p-3 bg-yellow-50 transition">
            <div class="flex items-start justify-between gap-2">
                <div class="flex-1 min-w-0">
                    <div class="text-xs font-mono text-gray-500">${escapeHtml(it.ma_cn)}</div>
                    <div class="text-sm font-semibold text-gray-800 truncate">${escapeHtml(it.ten_cn || "")}</div>
                    <div class="text-xs text-blue-700 mt-0.5">${escapeHtml(it.module || "")} · ${escapeHtml(it.quy_trinh || "")}</div>
                    ${it.note ? `<div class="text-xs text-gray-700 mt-2 line-clamp-2 border-l-2 border-yellow-400 pl-2 italic">📝 ${escapeHtml(it.note)}</div>` : ""}
                </div>
                <div class="flex flex-col items-center gap-1 shrink-0">
                    <button type="button" class="view-icon-btn"
                            onclick="openFunctionDetailByMaCn('${escapeAttr(it.ma_cn)}')"
                            title="Xem chi tiết function">👁</button>
                    <button type="button"
                            onclick="toggleBookmarkByMaCn('${escapeAttr(it.ma_cn)}')"
                            class="text-yellow-600 hover:text-red-500 text-lg" title="Bỏ bookmark">⭐</button>
                </div>
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

// ============================================================================
// T30 — REGISTRY API + ĐỒNG BỘ DỮ LIỆU
// ----------------------------------------------------------------------------
// State: cache list integrations + capabilities (dropdown enum) từ backend.
// Cấu trúc UI: 1 modal 2 tab (Danh sách / Editor) + 1 dropdown Sync nhanh
// bên cạnh header.
// ============================================================================

let _integState = {
    integrations: [],
    capabilities: null,
    editing: null,   // integration đang edit; null = tạo mới
};

/** Mở modal → luôn refresh list từ backend. */
async function openIntegrationsModal() {
    const modal = document.getElementById("integrationsModal");
    if (!modal) return;
    modal.classList.remove("hidden");
    modal.classList.add("flex");
    _integSetTab("list");
    await _integReloadList();
}

function closeIntegrationsModal() {
    const modal = document.getElementById("integrationsModal");
    if (!modal) return;
    modal.classList.add("hidden");
    modal.classList.remove("flex");
}

/** Chuyển tab list ↔ editor. */
function _integSetTab(name) {
    for (const t of ["list", "edit"]) {
        const tab = document.getElementById(`integTab-${t}`);
        const pane = document.getElementById(`integPane-${t}`);
        if (!tab || !pane) continue;
        if (t === name) {
            tab.classList.add("border-cyan-500", "text-cyan-600", "font-semibold");
            tab.classList.remove("border-transparent", "text-gray-500");
            pane.classList.remove("hidden");
        } else {
            tab.classList.remove("border-cyan-500", "text-cyan-600", "font-semibold");
            tab.classList.add("border-transparent", "text-gray-500");
            pane.classList.add("hidden");
        }
    }
}

async function _integReloadList() {
    try {
        const r = await fetch(`/api/projects/${currentProjectSlug}/integrations`);
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        const data = await r.json();
        _integState.integrations = data.integrations || [];
        _integState.capabilities = data.capabilities || null;
        _integRenderList();
        _integRefreshSyncQuickMenu();   // đồng bộ dropdown header
    } catch (err) {
        showToast("Không load được danh sách integration: " + err.message, "red");
    }
}

function _integRenderList() {
    const tbody = document.getElementById("integListTbody");
    const empty = document.getElementById("integListEmpty");
    if (!tbody) return;
    tbody.innerHTML = "";
    const items = _integState.integrations || [];
    if (!items.length) {
        empty?.classList.remove("hidden");
        return;
    }
    empty?.classList.add("hidden");
    for (const it of items) {
        const tr = document.createElement("tr");
        tr.className = "border-b dark:border-slate-700";
        const statusBadge = _integStatusBadge(it.last_sync_status, it.last_sync_message);
        const lastAt = it.last_synced_at
            ? new Date(it.last_synced_at).toLocaleString("vi-VN")
            : "<span class='text-gray-400 italic'>chưa sync</span>";
        const endpointsOpts = (it.endpoints || [])
            .map(ep => `<option value="${_escapeHtml(ep.id)}">${_escapeHtml(ep.name)}</option>`)
            .join("");
        tr.innerHTML = `
            <td class="px-2 py-2 font-medium">${_escapeHtml(it.name)}</td>
            <td class="px-2 py-2 text-xs text-gray-500 break-all">${_escapeHtml(it.base_url)}</td>
            <td class="px-2 py-2 text-center">${(it.endpoints || []).length}</td>
            <td class="px-2 py-2 text-xs">${lastAt}</td>
            <td class="px-2 py-2">${statusBadge}</td>
            <td class="px-2 py-2 text-center">
                <div class="flex flex-wrap gap-1 justify-center items-center">
                    <button onclick="_integTestFromList('${_escapeAttr(it.id)}')"
                            class="bg-amber-500 hover:bg-amber-600 text-white px-2 py-1 rounded text-xs" title="Test login">🔍</button>
                    ${endpointsOpts
                        ? `<select id="syncEp-${_escapeAttr(it.id)}" class="border rounded px-1 py-1 text-xs dark:bg-slate-700 dark:border-slate-600">${endpointsOpts}</select>
                           <button onclick="_integSyncFromList('${_escapeAttr(it.id)}')"
                                   class="bg-cyan-600 hover:bg-cyan-700 text-white px-2 py-1 rounded text-xs" title="Sync endpoint đã chọn">🔄</button>`
                        : `<span class="text-xs text-gray-400 italic">chưa có endpoint</span>`}
                    <button onclick="_integOpenEditor('${_escapeAttr(it.id)}')"
                            class="bg-slate-500 hover:bg-slate-600 text-white px-2 py-1 rounded text-xs" title="Chỉnh sửa">✏️</button>
                    <button onclick="_integDeleteConfirm('${_escapeAttr(it.id)}')"
                            class="bg-red-500 hover:bg-red-600 text-white px-2 py-1 rounded text-xs" title="Xoá">🗑</button>
                </div>
            </td>
        `;
        tbody.appendChild(tr);
    }
}

function _integStatusBadge(status, message) {
    if (!status) return `<span class="text-xs text-gray-400">—</span>`;
    const msg = _escapeAttr((message || "").slice(0, 200));
    if (status === "ok") {
        return `<span title="${msg}" class="inline-block bg-green-100 text-green-800 text-xs px-2 py-0.5 rounded">✔ ok</span>`;
    }
    return `<span title="${msg}" class="inline-block bg-red-100 text-red-800 text-xs px-2 py-0.5 rounded">✕ lỗi</span>`;
}

/** Escape HTML để chống XSS khi in name/base_url do user nhập. */
function _escapeHtml(s) {
    return String(s ?? "").replace(/[&<>"']/g, c => ({
        "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
    }[c]));
}
function _escapeAttr(s) {
    // Cho id chỉ chứa ký tự safe — vẫn escape để chống inject
    return String(s ?? "").replace(/['"\\<>]/g, "");
}

// ---------------------------------------------------------------------------
// Editor: mở form thêm mới hoặc chỉnh sửa
// ---------------------------------------------------------------------------

// Label tiếng Việt cho từng auth method (dropdown option text)
const _INTEG_AUTH_LABELS = {
    "form_login": "Form login (POST username/password)",
    "basic_auth": "HTTP Basic Auth",
    "bearer_token": "Bearer token",
    "api_key": "API Key (header/query)",
    "database": "Database (SQL view)",
};

function _integOpenEditor(integrationId) {
    _integState.editing = integrationId
        ? (_integState.integrations.find(i => i.id === integrationId) || null)
        : null;

    // Populate auth method dropdown từ capabilities (all first-class)
    _integPopulateAuthMethods();

    const it = _integState.editing;
    document.getElementById("integName").value = it?.name || "";
    document.getElementById("integBaseUrl").value = it?.base_url || "";
    const auth = it?.auth || {};

    // Auth method: set dropdown value + trigger show/hide field group
    document.getElementById("integAuthMethod").value = auth.method || "form_login";

    // form_login fields
    document.getElementById("integLoginPath").value = auth.login_path || "/login";
    document.getElementById("integUsernameField").value = auth.username_field || "username";
    document.getElementById("integPasswordField").value = auth.password_field || "password";
    document.getElementById("integCredEnv").value = auth.credential_env || "";

    // basic_auth field — dùng chung credential_env nhưng có input riêng để user
    // switch qua lại không mất giá trị
    document.getElementById("integCredEnvBasic").value = auth.credential_env || "";

    // bearer_token field
    document.getElementById("integBearerEnv").value = auth.bearer_env || "";

    // api_key fields
    document.getElementById("integApiKeyEnv").value = auth.apikey_env || "";
    document.getElementById("integApiKeyHeader").value = auth.apikey_header || "X-API-Key";
    document.getElementById("integApiKeyLocation").value = auth.apikey_location || "header";

    // T31 — database fields
    const dbDriver = document.getElementById("integDbDriver");
    const dbHost = document.getElementById("integDbHost");
    const dbPort = document.getElementById("integDbPort");
    const dbDatabase = document.getElementById("integDbDatabase");
    const dbCredEnv = document.getElementById("integDbCredEnv");
    if (dbDriver) dbDriver.value = auth.db_driver || "";
    if (dbHost) dbHost.value = auth.db_host || "";
    if (dbPort) dbPort.value = auth.db_port || "";
    if (dbDatabase) dbDatabase.value = auth.db_database || "";
    // credential_env dùng chung với form_login/basic_auth ở backend; input riêng
    // trong UI để không mất giá trị khi switch method qua lại.
    if (dbCredEnv) dbCredEnv.value = auth.credential_env || "";

    // T35 Task 1 — verify_ssl (default true). Chỉ áp dụng cho HTTP method.
    const verifySslEl = document.getElementById("integVerifySsl");
    if (verifySslEl) {
        // Nếu auth chưa có field (backward compat) → default true (BẬT)
        verifySslEl.checked = auth.verify_ssl !== false;
    }

    _integOnAuthMethodChange();  // show đúng block field
    _integOnVerifySslChange();    // update warning banner
    _integOnDbDriverChange();     // hint driver (nếu database)
    _integRenderEndpoints(it?.endpoints || []);
    _integShowEditorMsg("", "");
    _integSetTab("edit");
}

function _integPopulateAuthMethods() {
    const sel = document.getElementById("integAuthMethod");
    if (!sel) return;
    sel.innerHTML = "";
    const methods = _integState.capabilities?.auth_methods || [{ value: "form_login", supported: true }];
    for (const m of methods) {
        const opt = document.createElement("option");
        opt.value = m.value;
        const label = _INTEG_AUTH_LABELS[m.value] || m.value;
        opt.textContent = label + (m.supported ? "" : " (đang phát triển)");
        opt.disabled = !m.supported;
        sel.appendChild(opt);
    }
}

/**
 * Show/hide field groups theo auth.method đang chọn + update description hint.
 * Được gọi mỗi lần user đổi dropdown hoặc khi mở editor.
 */
function _integOnAuthMethodChange() {
    const method = document.getElementById("integAuthMethod")?.value || "form_login";
    const groups = document.querySelectorAll("[data-auth-fields]");
    for (const g of groups) {
        if (g.id === `integAuth-${method}`) {
            g.classList.remove("hidden");
        } else {
            g.classList.add("hidden");
        }
    }
    const descEl = document.getElementById("integAuthDesc");
    if (descEl) {
        const meta = _integState.capabilities?.auth_method_fields?.[method];
        descEl.textContent = meta?.description || "";
    }
    // Đồng bộ credential_env giữa 3 method dùng chung field (form_login,
    // basic_auth, database) — 3 input khác nhau để không mất giá trị khi
    // switch, nhưng backend chỉ nhận 1 field `credential_env`.
    const credInputs = [
        document.getElementById("integCredEnv"),      // form_login
        document.getElementById("integCredEnvBasic"), // basic_auth
        document.getElementById("integDbCredEnv"),    // database
    ].filter(Boolean);
    const firstFilled = credInputs.find(el => el.value?.trim());
    if (firstFilled) {
        credInputs.forEach(el => { if (!el.value?.trim()) el.value = firstFilled.value; });
    }
    // T35 Task 1 — SSL verify checkbox chỉ áp dụng cho HTTP method (form_login,
    // basic_auth, bearer_token, api_key). Với database → ẩn (SSL cho DB config
    // ở connection string / driver, không qua requests.Session).
    const sslWrap = document.getElementById("integSslVerifyWrap");
    if (sslWrap) {
        if (method === "database") {
            sslWrap.classList.add("hidden");
        } else {
            sslWrap.classList.remove("hidden");
        }
    }
}

/**
 * T35 Task 1 — Hiện/ẩn warning banner khi user bỏ tick verify SSL.
 * Chỉ là hint UX — không auto-block, user phải chủ động chấp nhận.
 */
function _integOnVerifySslChange() {
    const checkbox = document.getElementById("integVerifySsl");
    const warn = document.getElementById("integSslWarning");
    if (!checkbox || !warn) return;
    // checked = TRUE (verify) → an toàn → ẩn warning
    // checked = FALSE (bypass) → hiển warning đỏ
    if (checkbox.checked) {
        warn.classList.add("hidden");
    } else {
        warn.classList.remove("hidden");
    }
}
window._integOnVerifySslChange = _integOnVerifySslChange;

/**
 * Hint driver hiện tại (VD SQL Server → cảnh báo cần ODBC Driver 17/18).
 * Cũng auto-fill default port nếu port đang trống.
 */
function _integOnDbDriverChange() {
    const driver = document.getElementById("integDbDriver")?.value || "";
    const hintEl = document.getElementById("integDbDriverHint");
    const portEl = document.getElementById("integDbPort");
    const meta = (_integState.capabilities?.db_drivers || [])
        .find(d => d.value === driver);
    if (hintEl) {
        if (meta?.hint) {
            hintEl.textContent = "ℹ️ " + meta.hint;
            hintEl.classList.remove("hidden");
        } else {
            hintEl.textContent = "";
            hintEl.classList.add("hidden");
        }
    }
    if (portEl && meta?.default_port && !portEl.value) {
        portEl.value = String(meta.default_port);
    }
}

/**
 * Test kết nối DB — gọi endpoint mới `/test-db`. Verify:
 * - Driver đã cài trên server (backend lazy-import).
 * - Host/port/database + credential_env resolve được từ .env.
 * - Ping SELECT 1 thành công.
 * KHÔNG chạy query của bất kỳ endpoint nào (dùng /sync cho việc đó).
 */
async function _integTestDb() {
    const integrationId = _integState.editing?.id;
    if (!integrationId) {
        _integShowEditorMsg("Bấm 💾 Lưu trước để tạo integration, rồi mới test được", "warn");
        return;
    }
    _integShowEditorMsg("Đang test kết nối DB…", "warn");
    try {
        const r = await fetch(
            `/api/projects/${currentProjectSlug}/integrations/${encodeURIComponent(integrationId)}/test-db`,
            { method: "POST" }
        );
        const data = await r.json();
        if (data.status === "ok") {
            _integShowEditorMsg("✅ " + (data.message || "Connect OK"), "ok");
        } else {
            _integShowEditorMsg("❌ " + (data.message || "Connect fail"), "err");
        }
    } catch (err) {
        _integShowEditorMsg("Lỗi mạng: " + err.message, "err");
    }
}

function _integRenderEndpoints(endpoints) {
    const wrap = document.getElementById("integEndpointsWrap");
    if (!wrap) return;
    wrap.innerHTML = "";
    if (!endpoints.length) {
        _integAddEndpoint();
        return;
    }
    for (const ep of endpoints) _integAddEndpoint(ep);
}

function _integAddEndpoint(ep) {
    const wrap = document.getElementById("integEndpointsWrap");
    const tpl = document.getElementById("integEndpointTemplate");
    if (!wrap || !tpl) return;
    const node = tpl.content.firstElementChild.cloneNode(true);

    // Populate select response_type + target_action từ capabilities (nếu có)
    const caps = _integState.capabilities || {};
    const respSel = node.querySelector('[data-field="response_type"]');
    const targetSel = node.querySelector('[data-field="target_action"]');
    // Label tiếng Việt cho response type
    const respLabels = { "excel": "Excel (.xlsx/.xls)", "json": "JSON API", "database": "Database (SQL view)", "csv": "CSV" };
    if (respSel) {
        respSel.innerHTML = "";
        for (const r of (caps.response_types || [{ value: "excel", supported: true }])) {
            const opt = document.createElement("option");
            opt.value = r.value;
            opt.textContent = (respLabels[r.value] || r.value) + (r.supported ? "" : " (đang phát triển)");
            opt.disabled = !r.supported;
            respSel.appendChild(opt);
        }
    }
    if (targetSel) {
        targetSel.innerHTML = "";
        for (const t of (caps.target_actions || ["snapshot", "append", "replace"])) {
            const opt = document.createElement("option");
            opt.value = t;
            opt.textContent = t;
            targetSel.appendChild(opt);
        }
    }

    // Set values (nếu ep có sẵn) — hoặc default
    if (ep) {
        node.querySelector('[data-field="name"]').value = ep.name || "";
        node.querySelector('[data-field="path"]').value = ep.path || "";
        node.querySelector('[data-field="http_method"]').value = ep.http_method || "GET";
        if (respSel) respSel.value = ep.response_type || "excel";
        if (targetSel) targetSel.value = ep.target_action || "snapshot";
        node.querySelector('[data-field="params"]').value =
            ep.params && Object.keys(ep.params).length ? JSON.stringify(ep.params, null, 2) : "";
        // JSON mapping fields
        const dpEl = node.querySelector('[data-field="data_path"]');
        const fmEl = node.querySelector('[data-field="field_mapping"]');
        if (dpEl) dpEl.value = ep.data_path || "";
        if (fmEl && ep.field_mapping && Object.keys(ep.field_mapping).length) {
            fmEl.value = JSON.stringify(ep.field_mapping, null, 2);
        }
        // T31 — Database fields: query + query_params + field_mapping (dùng textarea
        // riêng data-field="field_mapping_db" trong panel DB để không ghi đè JSON panel).
        const qEl = node.querySelector('[data-field="query"]');
        const qpEl = node.querySelector('[data-field="query_params"]');
        const fmDbEl = node.querySelector('[data-field="field_mapping_db"]');
        if (qEl) qEl.value = ep.query || "";
        if (qpEl && ep.query_params && Object.keys(ep.query_params).length) {
            qpEl.value = JSON.stringify(ep.query_params, null, 2);
        }
        if (fmDbEl && ep.field_mapping && Object.keys(ep.field_mapping).length
                   && ep.response_type === "database") {
            fmDbEl.value = JSON.stringify(ep.field_mapping, null, 2);
        }
        node.dataset.endpointId = ep.id || "";
    }

    // Show/hide JSON panel theo response_type ban đầu
    _integOnResponseTypeChange(respSel, node);

    node.querySelector("[data-remove]").addEventListener("click", () => {
        node.remove();
    });
    // Auto-suggest button — bind sau khi node vào DOM
    const suggestBtn = node.querySelector("[data-json-suggest]");
    if (suggestBtn) {
        suggestBtn.addEventListener("click", () => _integAutoSuggestMapping(node));
    }
    wrap.appendChild(node);
}

/**
 * Show/hide panel mapping dựa vào giá trị response_type:
 *   - "json"     → panel Field Mapping (JSON path).
 *   - "database" → panel SQL (query + query_params + field_mapping cột SQL).
 *   - khác       → ẩn cả 2.
 * Có thể được gọi từ inline onchange (chỉ nhận element select) hoặc từ
 * _integAddEndpoint (nhận cả node cha để không phải traverse ngược).
 */
function _integOnResponseTypeChange(sel, nodeCtx) {
    const rowNode = nodeCtx || sel?.closest("[data-endpoint-row]");
    if (!rowNode) return;
    const jsonPanel = rowNode.querySelector("[data-json-panel]");
    const dbPanel = rowNode.querySelector("[data-db-panel]");
    const value = sel?.value || rowNode.querySelector('[data-field="response_type"]')?.value;
    if (jsonPanel) jsonPanel.classList.toggle("hidden", value !== "json");
    if (dbPanel) dbPanel.classList.toggle("hidden", value !== "database");
}

/**
 * Auto-suggest field_mapping: gọi POST /preview-json → nhận flat_keys →
 * suggest mapping theo heuristic tên field (code → Mã CN, phases.analysis.status
 * → Analysis - Status…). User có thể sửa lại textarea trước khi Lưu.
 */
async function _integAutoSuggestMapping(rowNode) {
    const editing = _integState.editing;
    if (!editing) {
        showToast("Bấm 💾 Lưu integration trước để có endpoint id, rồi mới suggest được", "red");
        return;
    }
    const endpointId = rowNode.dataset.endpointId;
    if (!endpointId) {
        showToast("Endpoint này chưa được lưu — bấm 💾 Lưu trước", "red");
        return;
    }
    const out = rowNode.querySelector("[data-json-suggest-out]");
    if (out) {
        out.classList.remove("hidden");
        out.textContent = "Đang gọi endpoint để lấy sample record…";
    }
    try {
        const r = await fetch(
            `/api/projects/${currentProjectSlug}/integrations/${encodeURIComponent(editing.id)}/preview-json`,
            {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ endpoint_id: endpointId }),
            }
        );
        const data = await r.json();
        if (data.status !== "ok") {
            if (out) out.textContent = "❌ " + (data.message || "Preview failed");
            return;
        }
        const flatKeys = data.flat_keys || {};
        // Heuristic map key → cột iHRP (name-based)
        const suggested = _integSuggestMapping(flatKeys);
        // Merge vào textarea hiện tại nếu user đã có mapping từ trước
        const fmEl = rowNode.querySelector('[data-field="field_mapping"]');
        let current = {};
        if (fmEl?.value?.trim()) {
            try { current = JSON.parse(fmEl.value); } catch (e) { current = {}; }
        }
        const merged = { ...suggested, ...current };  // giữ user's manual edits
        if (fmEl) fmEl.value = JSON.stringify(merged, null, 2);
        if (out) {
            const lines = Object.entries(flatKeys).slice(0, 30).map(
                ([k, v]) => `  • ${k} = ${JSON.stringify(v).slice(0, 60)}`
            );
            out.innerHTML =
                `<div class="font-semibold text-emerald-700 dark:text-emerald-300">✅ ${data.message}</div>` +
                `<div class="mt-1 text-gray-600 dark:text-gray-300">Đã suggest <b>${Object.keys(suggested).length}</b> cột. Xem sample keys:</div>` +
                `<pre class="mt-1 whitespace-pre-wrap">${_escapeHtml(lines.join("\n"))}</pre>`;
        }
    } catch (err) {
        if (out) out.textContent = "Lỗi mạng: " + err.message;
    }
}

/**
 * Heuristic suggest mapping từ flat keys.
 * VD:
 *   "code" → "Mã CN"
 *   "phases.analysis.status" → "Analysis - Status"
 *   "phases.dev.pic" → "Dev - PIC"
 */
function _integSuggestMapping(flatKeys) {
    // Từ điển field → cột iHRP (lowercase key)
    const nameMap = {
        "code": "Mã CN",
        "ma_cn": "Mã CN",
        "function_code": "Mã CN",
        "name": "Tên chức năng",
        "function_name": "Tên chức năng",
        "ten_chuc_nang": "Tên chức năng",
        "module": "Module",
        "module_code": "Module",
        "phan_he": "Module",
        "process": "Quy trình",
        "quy_trinh": "Quy trình",
        "priority": "Priority",
        "complexity": "Complexity",
        "fit_gap": "FIT/GAP",
        "fit/gap": "FIT/GAP",
        "phase": "Giai đoạn",
        "giai_doan": "Giai đoạn",
    };
    // Phase attribute mapping (Vietnamese)
    const attrMap = {
        "start": "Start",
        "end": "End",
        "from": "From",
        "to": "To",
        "status": "Status",
        "pic": "PIC",
    };
    // Phase name → Vietnamese label (giữ nguyên uppercase first letter)
    const phaseNameMap = {
        "analysis": "Analysis",
        "phan_tich": "Analysis",
        "design": "Design",
        "dev": "Dev",
        "development": "Dev",
        "lap_trinh": "Dev",
        "config": "Config",
        "test": "Test",
        "uat": "UAT",
        "golive": "Golive",
        "training": "Training",
    };
    const out = {};
    for (const path of Object.keys(flatKeys)) {
        const lower = path.toLowerCase();
        // Case 1: flat key trực tiếp trong nameMap
        const leaf = lower.split(".").pop();
        if (nameMap[leaf]) {
            out[nameMap[leaf]] = path;
            continue;
        }
        // Case 2: phase-nested VD phases.analysis.status hoặc analysis.status
        const parts = lower.split(".");
        if (parts.length >= 2) {
            const attr = parts[parts.length - 1];
            const phase = parts[parts.length - 2];
            if (attrMap[attr] && phaseNameMap[phase]) {
                out[`${phaseNameMap[phase]} - ${attrMap[attr]}`] = path;
                continue;
            }
        }
    }
    return out;
}

/** Đọc data từ editor DOM → payload để POST/PUT. */
function _integReadEditorPayload() {
    const authMethod = document.getElementById("integAuthMethod").value;
    const rows = document.querySelectorAll("#integEndpointsWrap [data-endpoint-row]");
    const endpoints = [];
    for (const row of rows) {
        const name = row.querySelector('[data-field="name"]').value.trim();
        const path = row.querySelector('[data-field="path"]').value.trim();
        const responseType = row.querySelector('[data-field="response_type"]').value;
        // Với response_type=database: path optional (query mới quan trọng).
        // Với các response_type khác: name + path bắt buộc.
        if (!name) continue;
        if (responseType !== "database" && !path) continue;

        let params = {};
        const paramsRaw = row.querySelector('[data-field="params"]').value.trim();
        if (paramsRaw) {
            try {
                const parsed = JSON.parse(paramsRaw);
                if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) {
                    params = parsed;
                } else {
                    throw new Error("params phải là JSON object");
                }
            } catch (err) {
                throw new Error(`Endpoint "${name}": params không phải JSON object hợp lệ — ${err.message}`);
            }
        }
        const dataPath = (row.querySelector('[data-field="data_path"]')?.value || "").trim();
        let fieldMapping = {};
        // JSON response type — parse field_mapping textarea (data-field="field_mapping").
        if (responseType === "json") {
            const fmRaw = (row.querySelector('[data-field="field_mapping"]')?.value || "").trim();
            if (fmRaw) {
                try {
                    const parsed = JSON.parse(fmRaw);
                    if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) {
                        fieldMapping = parsed;
                    } else {
                        throw new Error("field_mapping phải là JSON object {col: path}");
                    }
                } catch (err) {
                    throw new Error(`Endpoint "${name}": field_mapping không hợp lệ — ${err.message}`);
                }
            }
        }
        // T31 — Database response type: parse query + query_params + field_mapping_db.
        let query = "";
        let queryParams = {};
        if (responseType === "database") {
            query = (row.querySelector('[data-field="query"]')?.value || "").trim();
            if (!query) {
                throw new Error(`Endpoint "${name}": chưa nhập SQL 'query'`);
            }
            const qpRaw = (row.querySelector('[data-field="query_params"]')?.value || "").trim();
            if (qpRaw) {
                try {
                    const parsed = JSON.parse(qpRaw);
                    if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) {
                        queryParams = parsed;
                    } else {
                        throw new Error("query_params phải là JSON object");
                    }
                } catch (err) {
                    throw new Error(`Endpoint "${name}": query_params không hợp lệ — ${err.message}`);
                }
            }
            const fmDbRaw = (row.querySelector('[data-field="field_mapping_db"]')?.value || "").trim();
            if (fmDbRaw) {
                try {
                    const parsed = JSON.parse(fmDbRaw);
                    if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) {
                        fieldMapping = parsed;
                    } else {
                        throw new Error("field_mapping (DB) phải là JSON object {col_iHRP: col_sql}");
                    }
                } catch (err) {
                    throw new Error(`Endpoint "${name}": field_mapping (DB) không hợp lệ — ${err.message}`);
                }
            }
        }
        endpoints.push({
            id: row.dataset.endpointId || undefined,
            name,
            path,
            http_method: row.querySelector('[data-field="http_method"]').value,
            response_type: responseType,
            target_action: row.querySelector('[data-field="target_action"]').value,
            params,
            data_path: dataPath,
            field_mapping: fieldMapping,
            // Database-only
            query,
            query_params: queryParams,
        });
    }
    // credential_env: 3 input riêng — chọn input theo method đang active.
    // (form_login → integCredEnv, basic_auth → integCredEnvBasic, database → integDbCredEnv.)
    let credEnv = "";
    if (authMethod === "basic_auth") {
        credEnv = document.getElementById("integCredEnvBasic").value.trim().toUpperCase();
    } else if (authMethod === "database") {
        credEnv = document.getElementById("integDbCredEnv")?.value.trim().toUpperCase() || "";
    } else {
        credEnv = document.getElementById("integCredEnv").value.trim().toUpperCase();
    }
    return {
        name: document.getElementById("integName").value.trim(),
        base_url: document.getElementById("integBaseUrl").value.trim(),
        auth: {
            method: authMethod,
            // form_login fields (backend chỉ dùng khi method=form_login)
            login_path: document.getElementById("integLoginPath").value.trim() || "/login",
            username_field: document.getElementById("integUsernameField").value.trim() || "username",
            password_field: document.getElementById("integPasswordField").value.trim() || "password",
            credential_env: credEnv,
            // bearer_token
            bearer_env: document.getElementById("integBearerEnv").value.trim().toUpperCase(),
            // api_key
            apikey_env: document.getElementById("integApiKeyEnv").value.trim().toUpperCase(),
            apikey_header: document.getElementById("integApiKeyHeader").value.trim() || "X-API-Key",
            apikey_location: document.getElementById("integApiKeyLocation").value,
            // T31 — database
            db_driver: document.getElementById("integDbDriver")?.value || "",
            db_host: document.getElementById("integDbHost")?.value.trim() || "",
            db_port: parseInt(document.getElementById("integDbPort")?.value || "0", 10) || 0,
            db_database: document.getElementById("integDbDatabase")?.value.trim() || "",
            // T35 Task 1 — SSL verify (default true nếu checkbox không tồn tại).
            // Sanitize backend cũng default true — nên field này chỉ cần set khi user
            // tắt tick.
            verify_ssl: document.getElementById("integVerifySsl")
                ? !!document.getElementById("integVerifySsl").checked
                : true,
        },
        endpoints,
    };
}

function _integShowEditorMsg(text, kind) {
    const el = document.getElementById("integEditorMsg");
    if (!el) return;
    if (!text) {
        el.classList.add("hidden");
        el.textContent = "";
        return;
    }
    el.classList.remove("hidden");
    el.textContent = text;
    el.className = "text-xs px-3 py-2 rounded " + (kind === "ok"
        ? "bg-green-100 text-green-800"
        : kind === "warn"
            ? "bg-amber-100 text-amber-800"
            : "bg-red-100 text-red-800");
}

async function _integSaveEditor() {
    let payload;
    try {
        payload = _integReadEditorPayload();
    } catch (err) {
        _integShowEditorMsg(err.message, "err");
        return;
    }
    const authMethod = payload.auth.method;
    if (!payload.name) {
        _integShowEditorMsg("Thiếu 'Tên'", "err");
        return;
    }
    // T31 — Database method KHÔNG cần base_url (backend cho phép rỗng).
    if (authMethod !== "database" && !payload.base_url) {
        _integShowEditorMsg("Thiếu 'Base URL'", "err");
        return;
    }

    // Validate credential prefix theo method — mỗi method cần prefix env khác nhau
    let missingHint = "";
    if ((authMethod === "form_login" || authMethod === "basic_auth") && !payload.auth.credential_env) {
        missingHint = "Thiếu 'Prefix env' (credential_env) — sẽ không đọc được USERNAME/PASSWORD từ .env";
    } else if (authMethod === "bearer_token" && !payload.auth.bearer_env) {
        missingHint = "Thiếu 'Prefix env' (bearer_env) — sẽ không đọc được TOKEN từ .env";
    } else if (authMethod === "api_key" && !payload.auth.apikey_env) {
        missingHint = "Thiếu 'Prefix env' (apikey_env) — sẽ không đọc được KEY từ .env";
    } else if (authMethod === "database") {
        const dbAuth = payload.auth;
        if (!dbAuth.db_driver) missingHint = "Thiếu 'Driver' (SQL Server / Postgres / MySQL)";
        else if (!dbAuth.db_host) missingHint = "Thiếu 'Host / IP'";
        else if (!dbAuth.db_database) missingHint = "Thiếu 'Database name'";
        else if (!dbAuth.credential_env) missingHint = "Thiếu 'Prefix env' — không đọc được USERNAME/PASSWORD từ .env";
    }
    if (missingHint) _integShowEditorMsg(missingHint, "warn");

    const editing = _integState.editing;
    const url = editing
        ? `/api/projects/${currentProjectSlug}/integrations/${encodeURIComponent(editing.id)}`
        : `/api/projects/${currentProjectSlug}/integrations`;
    // Fix bug T31: đổi tên biến để không đè `method` = auth.method ở trên.
    const httpVerb = editing ? "PUT" : "POST";
    try {
        const r = await fetch(url, {
            method: httpVerb,
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload),
        });
        const data = await r.json();
        if (!r.ok) {
            _integShowEditorMsg(data.error || `HTTP ${r.status}`, "err");
            return;
        }
        showToast(editing ? "Đã cập nhật integration" : "Đã tạo integration");
        await _integReloadList();
        _integSetTab("list");
    } catch (err) {
        _integShowEditorMsg("Lỗi mạng: " + err.message, "err");
    }
}

async function _integDeleteConfirm(integrationId) {
    const it = _integState.integrations.find(i => i.id === integrationId);
    if (!it) return;
    if (!confirm(`Xoá integration "${it.name}"?`)) return;
    try {
        const r = await fetch(`/api/projects/${currentProjectSlug}/integrations/${encodeURIComponent(integrationId)}`, {
            method: "DELETE",
        });
        if (!r.ok) {
            const data = await r.json().catch(() => ({}));
            throw new Error(data.error || `HTTP ${r.status}`);
        }
        showToast("Đã xoá integration");
        await _integReloadList();
    } catch (err) {
        showToast("Xoá lỗi: " + err.message, "red");
    }
}

// ---------------------------------------------------------------------------
// Test login / Sync — từ list hoặc từ editor
// ---------------------------------------------------------------------------

async function _integTestLogin() {
    // Nếu đang tạo mới → phải lưu trước để có id
    let integrationId = _integState.editing?.id;
    if (!integrationId) {
        _integShowEditorMsg("Bấm 💾 Lưu trước để tạo integration, rồi mới test được", "warn");
        return;
    }
    _integShowEditorMsg("Đang test login…", "warn");
    try {
        const r = await fetch(`/api/projects/${currentProjectSlug}/integrations/${encodeURIComponent(integrationId)}/test`, {
            method: "POST",
        });
        const data = await r.json();
        if (data.status === "ok") {
            _integShowEditorMsg("✅ " + (data.message || "Login OK"), "ok");
            showToast("Test login thành công");
        } else {
            _integShowEditorMsg("❌ " + (data.message || "Login fail"), "err");
        }
        // Refresh cache để status badge cập nhật
        await _integReloadList();
    } catch (err) {
        _integShowEditorMsg("Lỗi mạng: " + err.message, "err");
    }
}

async function _integTestFromList(integrationId) {
    showToast("Đang test login…");
    try {
        const r = await fetch(`/api/projects/${currentProjectSlug}/integrations/${encodeURIComponent(integrationId)}/test`, {
            method: "POST",
        });
        const data = await r.json();
        showToast((data.status === "ok" ? "✔ " : "✕ ") + (data.message || "").slice(0, 200),
                  data.status === "ok" ? "green" : "red");
        await _integReloadList();
    } catch (err) {
        showToast("Test lỗi: " + err.message, "red");
    }
}

async function _integSyncFromList(integrationId) {
    const sel = document.getElementById(`syncEp-${integrationId}`);
    const endpointId = sel?.value;
    if (!endpointId) {
        showToast("Chưa chọn endpoint để sync", "red");
        return;
    }
    await _integSyncEndpoint(integrationId, endpointId);
}

// ---------------------------------------------------------------------------
// SYNC PROGRESS MODAL — visual feedback khi user bấm Đồng bộ
// ---------------------------------------------------------------------------

let _syncModalCanClose = false;
let _syncStepTimer = null;
window._syncModalCanClose = false; // expose để inline onclick check

/** Reset modal về state chưa chạy. */
function _syncResetProgress() {
    const bar = document.getElementById("syncProgressBar");
    if (bar) bar.style.width = "0%";
    const steps = document.querySelectorAll("#syncProgressSteps li");
    steps.forEach(li => {
        li.classList.remove("text-emerald-600", "font-semibold", "text-gray-800", "dark:text-gray-100");
        li.classList.add("text-gray-400");
        const dot = li.querySelector("span:first-child");
        if (dot) dot.textContent = "○";
    });
    const result = document.getElementById("syncProgressResult");
    if (result) { result.classList.add("hidden"); result.innerHTML = ""; }
    const footer = document.getElementById("syncProgressFooter");
    if (footer) footer.classList.add("hidden");
    const icon = document.getElementById("syncProgressIcon");
    if (icon) { icon.textContent = "🔄"; icon.classList.add("animate-pulse"); }
    const title = document.getElementById("syncProgressTitle");
    if (title) title.textContent = "Đang đồng bộ dữ liệu…";
    const sub = document.getElementById("syncProgressSubtitle");
    if (sub) sub.textContent = "Vui lòng đợi trong giây lát";
    const header = document.getElementById("syncProgressHeader");
    if (header) {
        header.classList.remove("from-emerald-500", "to-green-600", "from-red-500", "to-rose-600");
        header.classList.add("from-cyan-500", "to-blue-600");
    }
}

/** Mark 1 step done (green check) và cập nhật % progress bar. */
function _syncMarkStep(stepName, percent) {
    const li = document.querySelector(`#syncProgressSteps li[data-step="${stepName}"]`);
    if (li) {
        li.classList.remove("text-gray-400");
        li.classList.add("text-emerald-600", "font-semibold");
        const dot = li.querySelector("span:first-child");
        if (dot) dot.textContent = "✓";
    }
    const bar = document.getElementById("syncProgressBar");
    if (bar) bar.style.width = `${Math.min(100, Math.max(0, percent))}%`;
}

/** Highlight step đang chạy (spinner). */
function _syncActiveStep(stepName) {
    const steps = document.querySelectorAll("#syncProgressSteps li");
    steps.forEach(li => {
        if (li.dataset.step === stepName && !li.classList.contains("text-emerald-600")) {
            li.classList.remove("text-gray-400");
            li.classList.add("text-gray-800", "dark:text-gray-100", "font-semibold");
            const dot = li.querySelector("span:first-child");
            if (dot) dot.textContent = "●";
        }
    });
}

/** Đóng modal (chỉ được phép sau khi sync xong). */
function closeSyncProgressModal() {
    if (!_syncModalCanClose) return;
    const modal = document.getElementById("syncProgressModal");
    if (!modal) return;
    modal.classList.add("hidden");
    modal.classList.remove("flex");
    _syncModalCanClose = false;
    window._syncModalCanClose = false;
    if (_syncStepTimer) { clearTimeout(_syncStepTimer); _syncStepTimer = null; }
}
window.closeSyncProgressModal = closeSyncProgressModal;

/** Hiển thị modal + animation stepping từ connect → auth → fetch. */
function _syncOpenModal(endpointName) {
    _syncResetProgress();
    const modal = document.getElementById("syncProgressModal");
    if (!modal) return;
    const sub = document.getElementById("syncProgressSubtitle");
    if (sub && endpointName) sub.textContent = `Endpoint: ${endpointName}`;
    modal.classList.remove("hidden");
    modal.classList.add("flex");
    _syncModalCanClose = false;
    window._syncModalCanClose = false;
    // Animate 3 step đầu (giả lập vì network fetch nằm trong 1 request đồng bộ).
    // Timing lấy được từ đo thực tế: connect~400ms, auth~200ms, fetch~1-3s.
    _syncActiveStep("connect");
    _syncStepTimer = setTimeout(() => {
        _syncMarkStep("connect", 20);
        _syncActiveStep("auth");
        _syncStepTimer = setTimeout(() => {
            _syncMarkStep("auth", 35);
            _syncActiveStep("fetch");
        }, 400);
    }, 400);
}

/** Hiển thị kết quả cuối (success/error) và cho phép đóng modal. */
function _syncShowResult(success, data, endpointName) {
    if (_syncStepTimer) { clearTimeout(_syncStepTimer); _syncStepTimer = null; }
    const bar = document.getElementById("syncProgressBar");
    const icon = document.getElementById("syncProgressIcon");
    const title = document.getElementById("syncProgressTitle");
    const sub = document.getElementById("syncProgressSubtitle");
    const result = document.getElementById("syncProgressResult");
    const footer = document.getElementById("syncProgressFooter");
    const header = document.getElementById("syncProgressHeader");

    if (success) {
        _syncMarkStep("connect", 100);
        _syncMarkStep("auth", 100);
        _syncMarkStep("fetch", 100);
        _syncMarkStep("parse", 100);
        _syncMarkStep("snapshot", 100);
        if (bar) bar.style.width = "100%";
        if (icon) { icon.textContent = "✅"; icon.classList.remove("animate-pulse"); }
        if (title) title.textContent = "Đồng bộ thành công!";
        if (sub) sub.textContent = endpointName || "";
        if (header) {
            header.classList.remove("from-cyan-500", "to-blue-600");
            header.classList.add("from-emerald-500", "to-green-600");
        }
        const rowsImported = data.rows_imported || data.rows_count || 0;
        const snapId = data.snapshot_id || data.snapshot_entry?.date || "?";
        const stats = data.snapshot_entry || {};
        if (result) {
            result.classList.remove("hidden", "bg-red-50", "text-red-700", "border-red-200");
            result.classList.add("bg-emerald-50", "dark:bg-emerald-900/20", "text-emerald-800", "dark:text-emerald-200", "border", "border-emerald-200");
            result.innerHTML = `
                <div class="font-bold text-base mb-1">📥 ${rowsImported} chức năng đã kéo về</div>
                <div class="text-xs space-y-0.5">
                    <div>• Snapshot: <code class="font-mono">${escapeHtml(String(snapId))}</code></div>
                    ${stats.overall_pct != null ? `<div>• Tiến độ tổng: <strong>${stats.overall_pct}%</strong></div>` : ""}
                    ${stats.overdue_count != null ? `<div>• Task trễ deadline: <strong>${stats.overdue_count}</strong></div>` : ""}
                    ${stats.unassigned_count != null ? `<div>• Task chưa có PIC: <strong>${stats.unassigned_count}</strong></div>` : ""}
                    ${stats.high_risk_count != null ? `<div>• Task rủi ro cao: <strong>${stats.high_risk_count}</strong></div>` : ""}
                    <div class="pt-1 text-emerald-600">Dashboard sẽ tự động refresh với dữ liệu mới.</div>
                </div>
            `;
        }
    } else {
        if (icon) { icon.textContent = "❌"; icon.classList.remove("animate-pulse"); }
        if (title) title.textContent = "Đồng bộ thất bại";
        if (sub) sub.textContent = endpointName || "";
        if (header) {
            header.classList.remove("from-cyan-500", "to-blue-600");
            header.classList.add("from-red-500", "to-rose-600");
        }
        if (result) {
            result.classList.remove("hidden", "bg-emerald-50", "text-emerald-800", "border-emerald-200");
            result.classList.add("bg-red-50", "dark:bg-red-900/20", "text-red-800", "dark:text-red-200", "border", "border-red-200");
            const msg = (data && (data.message || data.error)) || "Lỗi không xác định";
            result.innerHTML = `
                <div class="font-bold mb-1">Lỗi</div>
                <div class="text-xs whitespace-pre-wrap break-words">${escapeHtml(String(msg))}</div>
                <div class="mt-2 text-[10px] text-red-500">Gợi ý: (1) Kiểm tra kết nối mạng · (2) API key trong .env còn hạn không · (3) Endpoint URL đúng chưa</div>
            `;
        }
    }
    if (footer) footer.classList.remove("hidden");
    _syncModalCanClose = true;
    window._syncModalCanClose = true;
    // Auto-close sau 8s nếu thành công
    if (success) {
        setTimeout(() => { if (_syncModalCanClose) closeSyncProgressModal(); }, 8000);
    }
}

/** Sync 1 endpoint — dùng chung cho list & quick menu. */
async function _integSyncEndpoint(integrationId, endpointId) {
    const it = _integState.integrations.find(i => i.id === integrationId);
    const ep = it?.endpoints?.find(e => e.id === endpointId);
    const epName = ep?.name || "endpoint";
    _syncOpenModal(epName);
    try {
        const r = await fetch(`/api/projects/${currentProjectSlug}/integrations/${encodeURIComponent(integrationId)}/sync`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ endpoint_id: endpointId }),
        });
        // Đánh dấu fetch done → step parse
        _syncMarkStep("connect", 50);
        _syncMarkStep("auth", 65);
        _syncMarkStep("fetch", 80);
        _syncActiveStep("parse");
        const data = await r.json();
        _syncMarkStep("parse", 90);
        _syncActiveStep("snapshot");
        if (data.status === "ok") {
            _syncShowResult(true, data, epName);
            // Refresh dashboard để user thấy dữ liệu mới ngay
            await tryLoadDashboardForCurrent(true);
        } else {
            _syncShowResult(false, data, epName);
        }
        await _integReloadList();
    } catch (err) {
        _syncShowResult(false, { message: `Lỗi kết nối: ${err.message}` }, epName);
    }
}

// ---------------------------------------------------------------------------
// Quick sync dropdown (nút "🔄 Đồng bộ" ở header)
// ---------------------------------------------------------------------------

function toggleSyncQuickMenu(event) {
    event?.stopPropagation();
    const menu = document.getElementById("syncQuickMenu");
    if (!menu) return;
    const hidden = menu.classList.contains("hidden");
    // Đóng menu khác bất kỳ đang mở (drill status, project selector…) — để đơn giản chỉ toggle menu này
    if (hidden) {
        _integRefreshSyncQuickMenu();
        menu.classList.remove("hidden");
        // Click ngoài → đóng
        setTimeout(() => {
            document.addEventListener("click", _integCloseSyncMenuOnce, { once: true });
        }, 0);
    } else {
        menu.classList.add("hidden");
    }
}
function _integCloseSyncMenuOnce(e) {
    const menu = document.getElementById("syncQuickMenu");
    const btn = document.getElementById("btnSyncQuick");
    if (!menu) return;
    if (menu.contains(e.target) || btn?.contains(e.target)) {
        // Không đóng nếu click bên trong menu / trên nút
        document.addEventListener("click", _integCloseSyncMenuOnce, { once: true });
        return;
    }
    menu.classList.add("hidden");
}

async function _integRefreshSyncQuickMenu() {
    const menu = document.getElementById("syncQuickMenu");
    if (!menu) return;
    if (!_integState.integrations.length && !_integState.capabilities) {
        // Chưa fetch → fetch nền
        try {
            const r = await fetch(`/api/projects/${currentProjectSlug}/integrations`);
            if (r.ok) {
                const data = await r.json();
                _integState.integrations = data.integrations || [];
                _integState.capabilities = data.capabilities || null;
            }
        } catch {}
    }
    _integRenderSyncQuickMenu();
}

function _integRenderSyncQuickMenu() {
    const menu = document.getElementById("syncQuickMenu");
    if (!menu) return;
    menu.innerHTML = "";
    const items = _integState.integrations || [];
    if (!items.length) {
        menu.innerHTML = `
            <div class="p-4 text-xs text-gray-500">
                Chưa có integration nào.
                <button onclick="openIntegrationsModal(); toggleSyncQuickMenu(event)"
                        class="mt-2 block w-full bg-cyan-600 hover:bg-cyan-700 text-white px-3 py-1.5 rounded">
                    ➕ Tạo integration đầu tiên
                </button>
            </div>`;
        return;
    }
    const parts = [];
    for (const it of items) {
        if (!(it.endpoints || []).length) continue;
        parts.push(`<div class="px-3 py-2 border-b dark:border-slate-700">
            <div class="text-xs font-semibold text-gray-700 dark:text-gray-200">${_escapeHtml(it.name)}</div>
            <div class="text-[10px] text-gray-500 mb-1 truncate">${_escapeHtml(it.base_url)}</div>
            ${(it.endpoints || []).map(ep => `
                <button onclick="_integSyncEndpoint('${_escapeAttr(it.id)}','${_escapeAttr(ep.id)}'); toggleSyncQuickMenu(event)"
                        class="w-full text-left px-2 py-1 rounded hover:bg-cyan-50 dark:hover:bg-slate-700 text-xs">
                    🔄 ${_escapeHtml(ep.name)}
                </button>
            `).join("")}
        </div>`);
    }
    parts.push(`<div class="px-3 py-2">
        <button onclick="openIntegrationsModal(); toggleSyncQuickMenu(event)"
                class="w-full text-xs text-cyan-700 hover:underline">⚙️ Quản lý integrations…</button>
    </div>`);
    menu.innerHTML = parts.join("");
}

// Auto-fetch integrations sau khi loadProjectList (không block init) — cho dropdown Sync hiển thị ngay
document.addEventListener("DOMContentLoaded", () => {
    setTimeout(() => {
        if (typeof currentProjectSlug === "string" && currentProjectSlug) {
            _integRefreshSyncQuickMenu();
        }
    }, 1200);
});


// ==========================================================================
// GANTT CALENDAR — Excel-style timeline (3-tier header + Today marker)
// Bar tô màu theo phase category, text % completion trong cell giữa bar,
// dùng chung state global filter. Rebuild bằng /api/.../gantt-calendar.
// ==========================================================================
const _ganttCalState = {
    group_by: "module",
    granularity: "week",
};

function _gcKey() { return `ganttCal:${currentProjectSlug || "default"}`; }
function _loadGanttCalState() {
    try {
        const raw = localStorage.getItem(_gcKey());
        if (raw) {
            const j = JSON.parse(raw);
            if (j.group_by) _ganttCalState.group_by = j.group_by;
            if (j.granularity) _ganttCalState.granularity = j.granularity;
        }
    } catch (e) { /* ignore */ }
}
function _saveGanttCalState() {
    try { localStorage.setItem(_gcKey(), JSON.stringify(_ganttCalState)); } catch (e) {}
}
function _syncGanttCalButtons() {
    document.querySelectorAll(".gantt-cal-groupby-btn").forEach(b => {
        const active = b.dataset.gcb === _ganttCalState.group_by;
        b.classList.toggle("bg-blue-600", active);
        b.classList.toggle("text-white", active);
        b.classList.toggle("hover:bg-blue-50", !active);
    });
    document.querySelectorAll(".gantt-cal-gran-btn").forEach(b => {
        const active = b.dataset.gcg === _ganttCalState.granularity;
        b.classList.toggle("bg-blue-600", active);
        b.classList.toggle("text-white", active);
        b.classList.toggle("hover:bg-blue-50", !active);
    });
}
window.setGanttCalGroupBy = function (mode) {
    if (!["module", "process", "function"].includes(mode)) return;
    _ganttCalState.group_by = mode;
    _saveGanttCalState();
    _syncGanttCalButtons();
    loadGanttCalendar();
};
window.setGanttCalGranularity = function (gr) {
    if (!["day", "week", "month"].includes(gr)) return;
    _ganttCalState.granularity = gr;
    _saveGanttCalState();
    _syncGanttCalButtons();
    loadGanttCalendar();
};

async function loadGanttCalendar() {
    if (!currentProjectSlug) return;
    const sec = document.getElementById("section-gantt-calendar");
    if (!sec) return;
    _loadGanttCalState();
    _syncGanttCalButtons();
    const container = document.getElementById("ganttCalendarContainer");
    if (!container) return;
    container.innerHTML = `<div class="text-gray-400 text-center py-10 text-sm">⏳ Đang tải…</div>`;

    const qsFilter = (typeof _buildFilterQuery === "function") ? _buildFilterQuery() : "";
    const qs = new URLSearchParams();
    qs.set("group_by", _ganttCalState.group_by);
    qs.set("granularity", _ganttCalState.granularity);
    const url = `/api/projects/${currentProjectSlug}/gantt-calendar?${qs.toString()}${qsFilter ? "&" + qsFilter : ""}`;
    try {
        const r = await fetch(url);
        if (!r.ok) throw new Error(await r.text());
        const data = await r.json();
        _renderGanttCalendar(data);
    } catch (err) {
        container.innerHTML = `<div class="text-red-600 text-center py-10 text-sm">Lỗi tải Gantt Calendar: ${escapeHtml(err.message)}</div>`;
    }
}

function _renderGanttCalendar(data) {
    const container = document.getElementById("ganttCalendarContainer");
    const legend = document.getElementById("ganttCalendarLegend");
    const info = document.getElementById("ganttCalendarInfo");
    if (!container) return;

    // T35 Task 2 — Render banner cảnh báo outlier dates (nếu có).
    // Lưu skipped_dates vào window scope để modal chi tiết đọc lại.
    _renderGanttCalOutlierBanner(data.skipped_dates || [], data.skipped_count || 0);

    if (data.empty || !(data.rows || []).length || !(data.columns || []).length) {
        container.innerHTML = `<div class="text-gray-400 text-center py-10 text-sm">
            Không có dữ liệu để vẽ Gantt Calendar.<br>
            <span class="text-xs">Function cần có Start/End date ở ít nhất 1 phase.</span>
        </div>`;
        if (legend) legend.innerHTML = "";
        if (info) info.textContent = "";
        return;
    }

    if (info) {
        info.textContent =
            `Range: ${data.min_date} → ${data.max_date} · ${data.columns.length} cột (${data.granularity})`
            + ` · ${data.rows.length} row (${data.group_by})`
            + (data.today_col !== null ? ` · Today ở cột #${data.today_col + 1}` : "");
    }

    const cats = data.legend || {};
    const catColor = (k) => (cats[k] && cats[k].color) || "#94a3b8";

    // ==== Build header ====
    // Số tầng header: day=3, week=2, month=1
    const gr = data.granularity;
    const monthSpans = data.month_spans || [];
    const weekSpans = data.week_spans || [];
    let theadHtml = "";

    // Row 1: Month
    theadHtml += `<tr><th class="gantt-cal-label-th" rowspan="${gr === "day" ? 3 : gr === "week" ? 2 : 1}">Module / Quy trình / Function</th>`;
    monthSpans.forEach(sp => {
        theadHtml += `<th colspan="${sp.colspan}">${escapeHtml(sp.label)}</th>`;
    });
    theadHtml += `</tr>`;

    // Row 2: Week
    if (gr === "day") {
        theadHtml += `<tr>`;
        weekSpans.forEach(sp => {
            theadHtml += `<th colspan="${sp.colspan}">${escapeHtml(sp.label)}</th>`;
        });
        theadHtml += `</tr>`;
    } else if (gr === "week") {
        theadHtml += `<tr>`;
        data.columns.forEach(c => {
            const extra = c.week_date_label ? `<br><span class="text-[9px] text-gray-500">${escapeHtml(c.week_date_label)}</span>` : "";
            theadHtml += `<th>${escapeHtml(c.label)}${extra}</th>`;
        });
        theadHtml += `</tr>`;
    }

    // Row 3: Day (chỉ granularity=day)
    if (gr === "day") {
        theadHtml += `<tr>`;
        data.columns.forEach(c => {
            theadHtml += `<th>${escapeHtml(c.label)}</th>`;
        });
        theadHtml += `</tr>`;
    }

    // ==== Build body ====
    const todayCol = data.today_col;
    let tbodyHtml = "";
    data.rows.forEach(row => {
        const catHex = catColor(row.category || "summary");
        // Bar nhạt (dùng cho fill) + text đậm cho pct
        const barLight = _hexLighten(catHex, 0.4);
        const barText = catHex;
        const isSummary = row.category === "summary";
        const rowCls = isSummary ? "summary-row" : "";
        const labelExtras = [];
        if (row.func_count) labelExtras.push(`${row.func_count} func`);
        if (row.overdue_count) labelExtras.push(`<span class="text-red-600">⚠ ${row.overdue_count} trễ</span>`);
        const labelSuffix = labelExtras.length ? `<span class="text-[10px] text-gray-500 ml-1">(${labelExtras.join(" · ")})</span>` : "";
        const activePhaseTag = row.active_phase ? `<span class="text-[9px] text-gray-500 ml-1">[${escapeHtml(row.active_phase)}]</span>` : "";
        tbodyHtml += `<tr class="${rowCls}">
            <td class="gantt-cal-label" title="Start: ${row.start || "-"} · End: ${row.end || "-"} · ${row.pct}%">
                ${escapeHtml(row.name)}${activePhaseTag}${labelSuffix}
            </td>`;
        const cells = row.cells || [];
        const midIdx = (row.span_start_col !== null && row.span_end_col !== null)
            ? Math.floor((row.span_start_col + row.span_end_col) / 2) : null;
        cells.forEach((active, i) => {
            const isToday = (todayCol !== null && i === todayCol);
            const classes = ["gantt-cal-cell"];
            if (active) classes.push("active");
            if (isToday) classes.push("today-col");
            let style = "";
            let inner = "";
            if (active) {
                style = `background:${barLight};`;
                if (midIdx === i) {
                    inner = `<span class="gantt-cal-pct" style="color:${barText}">${row.pct}%</span>`;
                }
            }
            tbodyHtml += `<td class="${classes.join(" ")}" style="${style}">${inner}</td>`;
        });
        tbodyHtml += `</tr>`;
    });

    container.innerHTML = `<table class="gantt-cal-table">
        <thead>${theadHtml}</thead>
        <tbody>${tbodyHtml}</tbody>
    </table>`;

    // ==== Legend ====
    if (legend) {
        const items = Object.entries(cats).map(([k, m]) => `
            <span class="gantt-cal-legend-chip">
                <span class="swatch" style="background:${m.color}"></span>
                <span>${escapeHtml(m.label)}</span>
            </span>
        `).join("");
        legend.innerHTML = items + (todayCol !== null
            ? `<span class="gantt-cal-legend-chip ml-auto"><span class="swatch" style="background:#ec4899"></span><span>Today</span></span>`
            : "");
    }

    // T35 Task 2 — Auto-scroll to today cột khi load lần đầu (chỉ scroll
    // ngang trong container, không scroll vertical page). Delay 100ms để
    // DOM table đã layout xong.
    if (todayCol !== null && todayCol !== undefined) {
        setTimeout(() => _scrollGanttCalToTodayCol(todayCol), 100);
    }
}

/**
 * T35 Task 2 — Render banner cảnh báo outlier + lưu state cho modal chi tiết.
 * Ẩn banner nếu không có outlier.
 */
function _renderGanttCalOutlierBanner(skippedDates, count) {
    const banner = document.getElementById("ganttCalOutlierBanner");
    const msg = document.getElementById("ganttCalOutlierMsg");
    if (!banner) return;
    // Lưu vào window scope để modal đọc lại
    window._ganttCalSkippedDates = skippedDates || [];
    if (!count || count === 0) {
        banner.classList.add("hidden");
        return;
    }
    if (msg) {
        // Đếm distinct function bị ảnh hưởng (theo Mã CN)
        const distinctMaCn = new Set((skippedDates || []).map(d => d.ma_cn || d.row_num));
        msg.textContent = `${count} phase-record có date < 2000 hoặc > ${new Date().getFullYear() + 10} (${distinctMaCn.size} function bị ảnh hưởng) — đã loại khỏi timeline.`;
    }
    banner.classList.remove("hidden");
}

function openGanttCalOutlierModal() {
    const modal = document.getElementById("ganttCalOutlierModal");
    const tbody = document.getElementById("ganttCalOutlierTableBody");
    if (!modal || !tbody) return;
    const rows = window._ganttCalSkippedDates || [];
    if (!rows.length) {
        tbody.innerHTML = `<tr><td colspan="6" class="text-center py-4 text-gray-400">Không có outlier</td></tr>`;
    } else {
        tbody.innerHTML = rows.map(r => `
            <tr class="border-b dark:border-slate-700 hover:bg-amber-50 dark:hover:bg-amber-900/10">
                <td class="px-2 py-1 font-mono text-xs">${escapeHtml(r.ma_cn || "?")}</td>
                <td class="px-2 py-1">${escapeHtml(r.ten_cn || "")}</td>
                <td class="px-2 py-1">${escapeHtml(r.module || "")}</td>
                <td class="px-2 py-1">${escapeHtml(r.phase || "")}</td>
                <td class="px-2 py-1 text-xs text-gray-600">${escapeHtml(r.attr || "")}</td>
                <td class="px-2 py-1 font-mono text-red-600 font-semibold">${escapeHtml(r.value || "")}</td>
            </tr>
        `).join("");
    }
    modal.classList.remove("hidden");
    modal.classList.add("flex");
}
window.openGanttCalOutlierModal = openGanttCalOutlierModal;

function closeGanttCalOutlierModal() {
    const modal = document.getElementById("ganttCalOutlierModal");
    if (!modal) return;
    modal.classList.add("hidden");
    modal.classList.remove("flex");
}
window.closeGanttCalOutlierModal = closeGanttCalOutlierModal;

/**
 * T35 Task 2 — Scroll ngang container Gantt Calendar tới cột Today.
 * Auto-called sau khi render + có nút "🎯 Today" ở toolbar.
 */
function _scrollGanttCalToTodayCol(todayCol) {
    const container = document.getElementById("ganttCalendarContainer");
    if (!container) return;
    // Tìm td.today-col trong tbody — reliable hơn tính offset theo colspan
    const todayCell = container.querySelector("td.today-col");
    if (!todayCell) return;
    // Chỉ scroll ngang container, KHÔNG scroll page (giữ user ở vị trí đọc).
    const containerRect = container.getBoundingClientRect();
    const cellRect = todayCell.getBoundingClientRect();
    // Vị trí cell tương đối với container + container.scrollLeft hiện tại
    const cellLeftInScroll = cellRect.left - containerRect.left + container.scrollLeft;
    // Center cell trong viewport container
    const targetScroll = cellLeftInScroll - containerRect.width / 2 + cellRect.width / 2;
    container.scrollTo({ left: Math.max(0, targetScroll), behavior: "smooth" });
}

function scrollGanttCalToToday() {
    const container = document.getElementById("ganttCalendarContainer");
    if (!container) return;
    const todayCell = container.querySelector("td.today-col");
    if (!todayCell) {
        showToast("Không có cột Today trong timeline hiện tại");
        return;
    }
    _scrollGanttCalToTodayCol();
    showToast("🎯 Đã cuộn đến cột Today");
}
window.scrollGanttCalToToday = scrollGanttCalToToday;

/** Lighten hex color bằng cách trộn với trắng theo factor (0..1). */
function _hexLighten(hex, factor = 0.4) {
    if (!hex || hex[0] !== "#") return hex;
    let h = hex.slice(1);
    if (h.length === 3) h = h.split("").map(c => c + c).join("");
    if (h.length !== 6) return hex;
    const r = parseInt(h.slice(0, 2), 16);
    const g = parseInt(h.slice(2, 4), 16);
    const b = parseInt(h.slice(4, 6), 16);
    const nr = Math.round(r + (255 - r) * factor);
    const ng = Math.round(g + (255 - g) * factor);
    const nb = Math.round(b + (255 - b) * factor);
    return `#${nr.toString(16).padStart(2, "0")}${ng.toString(16).padStart(2, "0")}${nb.toString(16).padStart(2, "0")}`;
}

/** Trigger download Excel export cho Gantt Calendar hiện tại. */
window.exportGanttCalendar = function () {
    if (!currentProjectSlug) return;
    const qsFilter = (typeof _buildFilterQuery === "function") ? _buildFilterQuery() : "";
    const qs = new URLSearchParams();
    qs.set("group_by", _ganttCalState.group_by);
    qs.set("granularity", _ganttCalState.granularity);
    const url = `/api/projects/${currentProjectSlug}/export-gantt-calendar?${qs.toString()}${qsFilter ? "&" + qsFilter : ""}`;
    window.location.href = url;
};

// ========================================================================
// T34 Task 4 — UNIFIED HELP SYSTEM
//   1. Section-level help button (?) → modal có structure {purpose, steps,
//      example, tips, learn_more}. Coexist với chart-help popover cũ.
//   2. Global Help menu (Ctrl+/) — search + list toàn bộ topic.
//   3. Onboarding tour cho project mới.
//   4. Command Palette entries "❓ Trợ giúp: <topic>".
// Content định nghĩa ở static/js/help_content.js (window.HELP_CONTENT).
// ========================================================================

/**
 * Attach nút "?" section-help vào mọi tiêu đề có data-help hoặc data-help-id.
 * Idempotent (chạy nhiều lần vẫn OK — bỏ qua nếu đã inject).
 * Map key: `section-X` (data-help) → `X` (HELP_CONTENT key), hoặc `X` trực tiếp
 * qua data-help-id.
 */
function attachUnifiedSectionHelp() {
    if (!window.HELP_CONTENT) return;
    const selector = "[data-help-id], [data-help]";
    document.querySelectorAll(selector).forEach(el => {
        // Ưu tiên data-help-id, fallback data-help (strip "section-" prefix)
        let key = el.getAttribute("data-help-id");
        if (!key) {
            const rawHelp = el.getAttribute("data-help") || "";
            key = rawHelp.startsWith("section-") ? rawHelp.slice("section-".length) : rawHelp;
        }
        if (!key || !window.HELP_CONTENT[key]) return;
        // Đã có unified-help-btn rồi thì skip
        if (el.querySelector(".unified-help-btn")) return;

        const btn = document.createElement("button");
        btn.type = "button";
        btn.className = "unified-help-btn";
        btn.textContent = "?";
        btn.title = "Xem hướng dẫn chi tiết";
        btn.setAttribute("aria-label", "Xem hướng dẫn");
        btn.setAttribute("data-help-key", key);
        btn.addEventListener("click", (e) => {
            e.stopPropagation();
            e.preventDefault();
            openSectionHelpModal(key);
        });
        el.appendChild(btn);
    });
}

/** Mở modal help cho 1 topic — populate từ HELP_CONTENT. */
function openSectionHelpModal(key) {
    const content = window.HELP_CONTENT && window.HELP_CONTENT[key];
    if (!content) {
        console.warn("[section-help] key không có nội dung:", key);
        return;
    }
    const modal = document.getElementById("sectionHelpModal");
    if (!modal) return;

    document.getElementById("secHelpCategory").textContent = content.category || "";
    document.getElementById("secHelpTitle").textContent = content.title || key;

    const body = document.getElementById("secHelpBody");
    const blocks = [];

    if (content.purpose) {
        blocks.push(`
            <div class="help-block-modal">
                <div class="help-block-label">📖 Mục đích</div>
                <div class="help-block-content">${escapeHtml(content.purpose)}</div>
            </div>`);
    }

    if (content.steps && content.steps.length) {
        const items = content.steps.map(s => `<li>${escapeHtml(s)}</li>`).join("");
        blocks.push(`
            <div class="help-block-modal">
                <div class="help-block-label">🎯 Cách dùng</div>
                <ol class="help-block-content list-decimal ml-5 space-y-1">${items}</ol>
            </div>`);
    }

    if (content.example) {
        blocks.push(`
            <div class="help-block-modal help-example">
                <div class="help-block-label">💡 Ví dụ</div>
                <div class="help-block-content italic">${escapeHtml(content.example)}</div>
            </div>`);
    }

    if (content.tips && content.tips.length) {
        const items = content.tips.map(t => `<li>${escapeHtml(t)}</li>`).join("");
        blocks.push(`
            <div class="help-block-modal">
                <div class="help-block-label">⚡ Tips &amp; lưu ý</div>
                <ul class="help-block-content list-disc ml-5 space-y-1">${items}</ul>
            </div>`);
    }

    body.innerHTML = blocks.join("");

    const learnMore = document.getElementById("secHelpLearnMore");
    if (content.learn_more) {
        learnMore.href = content.learn_more.startsWith("http") ? content.learn_more : "/" + content.learn_more.replace(/^\/+/, "");
        learnMore.classList.remove("hidden");
    } else {
        learnMore.classList.add("hidden");
    }

    modal.classList.remove("hidden");
    modal.classList.add("flex");
}
window.openSectionHelpModal = openSectionHelpModal;

function closeSectionHelpModal() {
    const modal = document.getElementById("sectionHelpModal");
    if (!modal) return;
    modal.classList.add("hidden");
    modal.classList.remove("flex");
}
window.closeSectionHelpModal = closeSectionHelpModal;

// -------------------- Global Help menu (Ctrl+/) --------------------

let _helpGlobalQuery = "";

function openGlobalHelpModal() {
    const modal = document.getElementById("globalHelpModal");
    if (!modal) return;
    modal.classList.remove("hidden");
    modal.classList.add("flex");
    // Focus vào input
    const input = document.getElementById("globalHelpSearch");
    if (input) {
        input.value = "";
        _helpGlobalQuery = "";
        setTimeout(() => input.focus(), 50);
    }
    _helpGlobalRender();
}
window.openGlobalHelpModal = openGlobalHelpModal;

function closeGlobalHelpModal() {
    const modal = document.getElementById("globalHelpModal");
    if (!modal) return;
    modal.classList.add("hidden");
    modal.classList.remove("flex");
}
window.closeGlobalHelpModal = closeGlobalHelpModal;

function _helpGlobalOnSearch(v) {
    _helpGlobalQuery = (v || "").trim().toLowerCase();
    _helpGlobalRender();
}
window._helpGlobalOnSearch = _helpGlobalOnSearch;

/** Fuzzy: mọi ký tự query xuất hiện theo thứ tự trong text (case-insensitive). */
function _helpFuzzyMatch(text, q) {
    if (!q) return true;
    text = (text || "").toLowerCase();
    if (text.includes(q)) return true;   // Exact substring — ưu tiên
    let ti = 0, qi = 0;
    while (ti < text.length && qi < q.length) {
        if (text[ti] === q[qi]) qi++;
        ti++;
    }
    return qi === q.length;
}

function _helpGlobalRender() {
    const list = document.getElementById("globalHelpList");
    if (!list || !window.HELP_CONTENT) return;

    const q = _helpGlobalQuery;
    // Group entries theo category
    const byCategory = {};
    Object.entries(window.HELP_CONTENT).forEach(([key, c]) => {
        const searchable = `${c.title || ""} ${c.purpose || ""} ${c.category || ""}`;
        if (q && !_helpFuzzyMatch(searchable, q)) return;
        const cat = c.category || "Khác";
        if (!byCategory[cat]) byCategory[cat] = [];
        byCategory[cat].push({ key, c });
    });

    const cats = window.HELP_CATEGORIES || Object.keys(byCategory);
    // Sort category theo thứ tự HELP_CATEGORIES định nghĩa; category không trong list → cuối
    const sortedCats = [
        ...cats.filter(c => byCategory[c]),
        ...Object.keys(byCategory).filter(c => !cats.includes(c)),
    ];

    if (!sortedCats.length) {
        list.innerHTML = `<div class="text-center py-8 text-gray-400">Không tìm thấy topic khớp "${escapeHtml(q)}"</div>`;
        return;
    }

    list.innerHTML = sortedCats.map(cat => {
        const entries = byCategory[cat] || [];
        const items = entries.map(({ key, c }) => `
            <button type="button"
                    onclick="_helpGlobalOpenTopic('${escapeAttr(key)}')"
                    class="w-full text-left p-3 rounded hover:bg-blue-50 dark:hover:bg-slate-700 border border-transparent hover:border-blue-200 transition-colors">
                <div class="text-sm font-semibold text-gray-800 dark:text-gray-100">${escapeHtml(c.title || key)}</div>
                <div class="text-xs text-gray-500 dark:text-gray-400 mt-0.5 line-clamp-2">${escapeHtml(c.purpose || "")}</div>
            </button>
        `).join("");
        return `
            <div>
                <div class="text-xs uppercase tracking-wider text-blue-600 dark:text-blue-400 font-semibold mb-2 mt-3">${escapeHtml(cat)}</div>
                <div class="grid grid-cols-1 md:grid-cols-2 gap-2">${items}</div>
            </div>
        `;
    }).join("");
}

function _helpGlobalOpenTopic(key) {
    closeGlobalHelpModal();
    openSectionHelpModal(key);
}
window._helpGlobalOpenTopic = _helpGlobalOpenTopic;

// Phím tắt Ctrl+/ mở global help + Esc đóng
document.addEventListener("keydown", (e) => {
    // Ctrl+/ (hoặc Cmd+/) mở global help
    if ((e.ctrlKey || e.metaKey) && e.key === "/") {
        e.preventDefault();
        // Toggle nếu đang mở
        const modal = document.getElementById("globalHelpModal");
        if (modal && !modal.classList.contains("hidden")) {
            closeGlobalHelpModal();
        } else {
            openGlobalHelpModal();
        }
    }
    // Esc đóng
    if (e.key === "Escape") {
        const secModal = document.getElementById("sectionHelpModal");
        const glbModal = document.getElementById("globalHelpModal");
        if (secModal && !secModal.classList.contains("hidden")) {
            closeSectionHelpModal();
        }
        if (glbModal && !glbModal.classList.contains("hidden")) {
            closeGlobalHelpModal();
        }
    }
});

// -------------------- Onboarding Tour --------------------

const _TOUR_STEPS = [
    {
        selector: "#uploadZone, #stickyUploadBtn",
        title: "Bước 1: Upload file Excel",
        desc: "Đây là nơi bắt đầu — kéo thả file Function List (.xlsx) vào đây. Nếu file có header không chuẩn iHRP, Column Mapping Wizard sẽ mở cho bạn map thủ công.",
    },
    {
        selector: "#section-summary, #section-summary-header",
        title: "Bước 2: 6 chỉ số cốt lõi",
        desc: "Sau khi upload, đây là 6 con số quan trọng nhất: Tổng chức năng, % tiến độ, function trễ, chưa PIC, high-risk, số module. Xem trong 3 giây để biết sức khoẻ dự án.",
    },
    {
        selector: "#section-globalfilter",
        title: "Bước 3: Filter global",
        desc: "Lọc theo Module × Quy trình × PIC — mọi biểu đồ + số ở mọi section sẽ tự cập nhật. Có thể lưu filter thành 'Saved View' để dùng lại.",
    },
    {
        selector: "#section-module",
        title: "Bước 4: Tổng quan theo Module",
        desc: "Bảng % progress từng module. Nếu module nào <30% (đỏ) → cảnh báo. Click cell 'Trễ' → drill xem function cụ thể.",
    },
    {
        selector: "#section-gantt-calendar",
        title: "Bước 5: Gantt Calendar",
        desc: "Timeline Excel-style — mỗi row 1 module, cell bar % completion. Marker đỏ chỉ 'Today'. Xuất Excel để share leadership.",
    },
    {
        selector: "#section-overdue",
        title: "Bước 6: Danh sách trễ",
        desc: "Function cần xử lý ngay. Filter theo module/PIC, xuất Excel để gửi team.",
    },
    {
        selector: "#btnExportPdf, #btnExportAllIssues",
        title: "Bước 7: Xuất báo cáo",
        desc: "📄 Xuất PDF cho leadership; 📊 Xuất vấn đề = 1 file Excel multi-sheet có mọi loại issue.",
    },
    {
        selector: "#btnGlobalHelp, #btnSettings",
        title: "Bước 8: Trợ giúp + Cài đặt",
        desc: "❓ Trợ giúp — mở menu này bằng Ctrl+/. Xem help từng section bằng nút ? cạnh title. ⚙️ Cài đặt để chỉnh threshold, ẩn/hiện section, Public API, LAN.",
    },
];

let _tourStep = 0;

/** Onboarding tour flag key theo project slug. */
function _tourStorageKey() {
    return "ihrp_onboarded_" + (currentProjectSlug || "default");
}

/** Kiểm tra + tự start tour nếu chưa onboarded (gọi sau khi upload data thành công). */
function maybeStartOnboardingTour() {
    try {
        const key = _tourStorageKey();
        if (localStorage.getItem(key)) return; // đã onboarded
        if (!currentProjectSlug) return; // chưa có project — chưa gợi tour
        setTimeout(() => startOnboardingTour(), 800);
    } catch (err) {
        console.warn("[tour maybeStart]", err);
    }
}
window.maybeStartOnboardingTour = maybeStartOnboardingTour;

function startOnboardingTour() {
    _tourStep = 0;
    const overlay = document.getElementById("onboardingTourOverlay");
    if (!overlay) return;
    overlay.classList.remove("hidden");
    _tourRender();
    window.addEventListener("resize", _tourRender);
    window.addEventListener("scroll", _tourRender, true);
}
window.startOnboardingTour = startOnboardingTour;

function _tourNext() {
    if (_tourStep < _TOUR_STEPS.length - 1) {
        _tourStep++;
        _tourRender();
    } else {
        _tourFinish(true);
    }
}
window._tourNext = _tourNext;

function _tourBack() {
    if (_tourStep > 0) {
        _tourStep--;
        _tourRender();
    }
}
window._tourBack = _tourBack;

function _tourSkip() {
    _tourFinish(false);
}
window._tourSkip = _tourSkip;

/** Đóng tour + đánh dấu onboarded (dù skip hay finish). */
function _tourFinish(completed) {
    const overlay = document.getElementById("onboardingTourOverlay");
    if (overlay) overlay.classList.add("hidden");
    try {
        localStorage.setItem(_tourStorageKey(), completed ? "1" : "skipped");
    } catch (err) {}
    window.removeEventListener("resize", _tourRender);
    window.removeEventListener("scroll", _tourRender, true);
    if (completed && typeof showToast === "function") {
        showToast("🎉 Hoàn tất tour! Bấm ? cạnh mỗi section để xem hướng dẫn cụ thể.");
    }
}

/** Render step hiện tại: đặt spotlight quanh selector + đặt tooltip cạnh. */
function _tourRender() {
    const step = _TOUR_STEPS[_tourStep];
    if (!step) return;

    // Update text
    document.getElementById("tourStepBadge").textContent = `Bước ${_tourStep + 1}/${_TOUR_STEPS.length}`;
    document.getElementById("tourStepTitle").textContent = step.title;
    document.getElementById("tourStepDesc").textContent = step.desc;

    // Dot indicator
    const dots = _TOUR_STEPS.map((_, i) =>
        `<span class="w-2 h-2 rounded-full ${i === _tourStep ? "bg-blue-600" : "bg-gray-300"}"></span>`
    ).join("");
    document.getElementById("tourDotIndicator").innerHTML = dots;

    // Back / Next button state
    document.getElementById("tourBackBtn").disabled = (_tourStep === 0);
    document.getElementById("tourBackBtn").style.opacity = (_tourStep === 0) ? "0.4" : "1";
    document.getElementById("tourNextBtn").textContent =
        (_tourStep === _TOUR_STEPS.length - 1) ? "🎉 Hoàn tất" : "Tiếp →";

    // Tìm target element (thử từng selector — lấy element đầu tiên visible)
    const selectors = step.selector.split(",").map(s => s.trim());
    let target = null;
    for (const sel of selectors) {
        const els = document.querySelectorAll(sel);
        for (const el of els) {
            const r = el.getBoundingClientRect();
            if (r.width > 0 && r.height > 0) { target = el; break; }
        }
        if (target) break;
    }

    if (!target) {
        // Không tìm thấy target → hiện tooltip giữa màn hình, ẩn spotlight
        _tourPositionTooltip(null);
        _tourPositionSpotlight(null);
        return;
    }

    // Scroll target vào view (smooth)
    target.scrollIntoView({ behavior: "smooth", block: "center" });
    // Chờ scroll xong (loose — 300ms) rồi position
    setTimeout(() => {
        const r = target.getBoundingClientRect();
        _tourPositionSpotlight(r);
        _tourPositionTooltip(r);
    }, 350);
}

function _tourPositionSpotlight(rect) {
    const spot = document.getElementById("tourSpotlight");
    const top = document.querySelector(".tour-backdrop-top");
    const bot = document.querySelector(".tour-backdrop-bottom");
    const lft = document.querySelector(".tour-backdrop-left");
    const rgt = document.querySelector(".tour-backdrop-right");
    if (!spot) return;

    if (!rect) {
        // Không có target — spotlight ẩn, backdrop full
        spot.style.display = "none";
        [top, bot, lft, rgt].forEach(el => { if (el) el.style.display = "none"; });
        // 1 backdrop full
        if (top) {
            top.style.display = "block";
            top.style.top = "0"; top.style.left = "0";
            top.style.width = "100vw"; top.style.height = "100vh";
        }
        return;
    }

    spot.style.display = "block";
    const pad = 6;
    const x = Math.max(0, rect.left - pad);
    const y = Math.max(0, rect.top - pad);
    const w = rect.width + pad * 2;
    const h = rect.height + pad * 2;
    spot.style.left = `${x}px`;
    spot.style.top = `${y}px`;
    spot.style.width = `${w}px`;
    spot.style.height = `${h}px`;

    // Chia 4 backdrop mảnh vá quanh spotlight
    if (top) {
        top.style.display = "block";
        top.style.top = "0"; top.style.left = "0";
        top.style.width = "100vw"; top.style.height = `${y}px`;
    }
    if (bot) {
        bot.style.display = "block";
        bot.style.top = `${y + h}px`; bot.style.left = "0";
        bot.style.width = "100vw"; bot.style.height = `calc(100vh - ${y + h}px)`;
    }
    if (lft) {
        lft.style.display = "block";
        lft.style.top = `${y}px`; lft.style.left = "0";
        lft.style.width = `${x}px`; lft.style.height = `${h}px`;
    }
    if (rgt) {
        rgt.style.display = "block";
        rgt.style.top = `${y}px`; rgt.style.left = `${x + w}px`;
        rgt.style.width = `calc(100vw - ${x + w}px)`; rgt.style.height = `${h}px`;
    }
}

function _tourPositionTooltip(rect) {
    const tip = document.getElementById("tourTooltip");
    if (!tip) return;
    const tipW = 400;
    const tipH = tip.offsetHeight || 200;

    if (!rect) {
        // Center giữa màn hình
        tip.style.left = `calc(50vw - ${tipW / 2}px)`;
        tip.style.top = `calc(50vh - ${tipH / 2}px)`;
        return;
    }

    // Ưu tiên đặt dưới target; nếu không đủ chỗ → đặt trên
    let top = rect.bottom + 12;
    if (top + tipH > window.innerHeight - 20) {
        top = Math.max(20, rect.top - tipH - 12);
    }
    let left = rect.left + rect.width / 2 - tipW / 2;
    left = Math.max(12, Math.min(left, window.innerWidth - tipW - 12));
    tip.style.left = `${left}px`;
    tip.style.top = `${top}px`;
}

// -------------------- Command Palette entries --------------------

/** Trả list Command Palette entry cho các help topic — được _cmdCollectSections/_CMD_ACTIONS merge vào. */
function _helpCollectCmdEntries() {
    if (!window.HELP_CONTENT) return [];
    return Object.entries(window.HELP_CONTENT).map(([key, c]) => ({
        id: "help." + key,
        label: `❓ Trợ giúp: ${c.title || key}`,
        kind: "help",
        sub: c.category || "",
        run: () => openSectionHelpModal(key),
    }));
}
window._helpCollectCmdEntries = _helpCollectCmdEntries;

// Inject cmd entry vào _CMD_ACTIONS sau khi help_content.js đã load
if (typeof _CMD_ACTIONS !== "undefined" && Array.isArray(_CMD_ACTIONS)) {
    // Chỉ inject 1 lần
    if (!_CMD_ACTIONS.__helpInjected) {
        _CMD_ACTIONS.__helpInjected = true;
        // Lazy inject — dùng getter proxy: khi _cmdBuildItems() gọi
        // [..._CMD_ACTIONS] thì spread ra tận tay. Nên inject trực tiếp:
        try {
            _helpCollectCmdEntries().forEach(e => _CMD_ACTIONS.push(e));
        } catch (err) {
            console.warn("[help cmd inject]", err);
        }
    }
}

// escapeAttr fallback (nếu chưa định nghĩa ở nơi khác)
if (typeof escapeAttr !== "function") {
    window.escapeAttr = function (s) {
        return String(s == null ? "" : s)
            .replace(/&/g, "&amp;")
            .replace(/"/g, "&quot;")
            .replace(/'/g, "&#39;")
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;");
    };
}

// -------------------- Wire up --------------------

/** Init unified help — gọi sau DOM ready + mỗi khi có section mới hiện lên. */
function initUnifiedHelp() {
    attachUnifiedSectionHelp();
}

if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initUnifiedHelp);
} else {
    initUnifiedHelp();
}

// Re-attach nếu applyDashboardResponse render lại section (hook vào window để
// dashboard code chính có thể gọi window.attachUnifiedSectionHelp() sau).
window.attachUnifiedSectionHelp = attachUnifiedSectionHelp;

