/**
 * Task 19: Color System centralized — song song với analyzer/palette.py.
 *
 * Áp dụng nguyên tắc data-viz:
 * - Semantic tiered (progress %)
 * - Semantic status (Closed/In-progress/...)
 * - Categorical (Tableau 10) cho dimension
 * - Diverging (variance)
 * - Dark mode parallel
 *
 * Detect dark mode: check `document.documentElement.classList.contains('dark')`
 * hoặc `prefers-color-scheme: dark`.
 */
(function (global) {

  const PROGRESS_TIERED = {
    low:  "#dc2626",   // <30% đỏ
    mid:  "#f59e0b",   // 30-70% vàng
    high: "#16a34a",   // >=70% xanh
  };
  let PROGRESS_THRESHOLDS = [30, 70];   // mutable — có thể override từ settings

  const STATUS = {
    "Closed":       "#16a34a",
    "In-progress":  "#2563eb",
    "Assigned":     "#0891b2",
    "Resolved":     "#84cc16",
    "Pending":      "#f59e0b",
    "Open":         "#64748b",
    "Cancelled":    "#94a3b8",
    "Overdue":      "#dc2626",
    "Blank":        "#e2e8f0",
    "(Blank)":      "#e2e8f0",
  };

  const CATEGORICAL = [
    "#4e79a7", "#f28e2b", "#e15759", "#76b7b2",
    "#59a14f", "#edc948", "#b07aa1", "#ff9da7",
    "#9c755f", "#bab0ac",
  ];

  const DIVERGING = {
    neg_strong: "#b91c1c",
    neg_mid:    "#f87171",
    zero:       "#e5e7eb",
    pos_mid:    "#86efac",
    pos_strong: "#15803d",
  };

  const DARK_MODE_MAP = {
    "#dc2626": "#ef4444",
    "#f59e0b": "#fbbf24",
    "#16a34a": "#22c55e",
    "#2563eb": "#3b82f6",
    "#0891b2": "#22d3ee",
    "#84cc16": "#a3e635",
    "#64748b": "#94a3b8",
    "#94a3b8": "#cbd5e1",
    "#e2e8f0": "#334155",
    "#b91c1c": "#dc2626",
    "#f87171": "#fca5a5",
    "#e5e7eb": "#475569",
    "#86efac": "#4ade80",
    "#15803d": "#22c55e",
  };

  function isDark() {
    // Ưu tiên class 'dark' trên html; fallback prefers-color-scheme
    if (typeof document === "undefined") return false;
    if (document.documentElement?.classList?.contains("dark")) return true;
    if (window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches) {
      // Chỉ dùng prefers khi user chưa force light mode
      return !document.documentElement?.classList?.contains("light");
    }
    return false;
  }

  function _dark(color, dark) {
    if (dark === undefined) dark = isDark();
    return dark ? (DARK_MODE_MAP[color] || color) : color;
  }

  function progressColor(pct, dark, thresholds) {
    const [lowMax, midMax] = thresholds || PROGRESS_THRESHOLDS;
    let c;
    if (pct < lowMax)      c = PROGRESS_TIERED.low;
    else if (pct < midMax) c = PROGRESS_TIERED.mid;
    else                    c = PROGRESS_TIERED.high;
    return _dark(c, dark);
  }

  function statusColor(status, dark) {
    const s = (status || "").trim();
    const c = STATUS[s] || STATUS.Open;
    return _dark(c, dark);
  }

  function categoricalColors(n, dark) {
    const out = [];
    for (let i = 0; i < n; i++) {
      out.push(_dark(CATEGORICAL[i % CATEGORICAL.length], dark));
    }
    return out;
  }

  function divergingColor(value, minVal, maxVal, dark) {
    if (value === 0) return _dark(DIVERGING.zero, dark);
    let key;
    if (value < 0) {
      const thresh = minVal / 2;
      key = value <= thresh ? "neg_strong" : "neg_mid";
    } else {
      const thresh = maxVal / 2;
      key = value >= thresh ? "pos_strong" : "pos_mid";
    }
    return _dark(DIVERGING[key], dark);
  }

  function setProgressThresholds(low, mid) {
    if (Number.isFinite(low) && Number.isFinite(mid) && low < mid) {
      PROGRESS_THRESHOLDS = [low, mid];
    }
  }

  // Public API
  global.Palette = {
    PROGRESS_TIERED,
    STATUS,
    CATEGORICAL,
    DIVERGING,
    isDark,
    progressColor,
    statusColor,
    categoricalColors,
    divergingColor,
    setProgressThresholds,
    getProgressThresholds: () => [...PROGRESS_THRESHOLDS],
  };
})(typeof window !== "undefined" ? window : globalThis);
