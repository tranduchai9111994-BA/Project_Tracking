"""Task 19: Color System centralized theo best practice data-viz.

- Semantic tiered (đỏ/vàng/xanh) cho progress %.
- Semantic status (Closed/In-progress/...) cố định.
- Categorical (Tableau 10) cho dimension (Module/PIC/Quy trình).
- Diverging (âm=đỏ, dương=xanh) cho variance.
- Dark mode parallel (đậm hơn để nổi trên bg tối).

Config `progress_thresholds` (low_max, mid_max) có thể override từ project
settings (Endpoint `/api/projects/<slug>/settings`).
"""
from __future__ import annotations

# ---------------------------------------------------------------------------
# Semantic tiered — progress %
# ---------------------------------------------------------------------------
PROGRESS_TIERED = {
    "low": "#dc2626",     # <30% → đỏ
    "mid": "#f59e0b",     # 30-70% → vàng amber
    "high": "#16a34a",    # >=70% → xanh
}
PROGRESS_THRESHOLDS = (30, 70)  # (low_max, mid_max) — default

# ---------------------------------------------------------------------------
# Semantic status — cố định
# ---------------------------------------------------------------------------
STATUS = {
    "Closed": "#16a34a",       # xanh
    "In-progress": "#2563eb",  # xanh dương
    "Assigned": "#0891b2",     # cyan
    "Resolved": "#84cc16",     # lime
    "Pending": "#f59e0b",      # vàng amber
    "Open": "#64748b",         # slate
    "Cancelled": "#94a3b8",    # gray
    "Overdue": "#dc2626",      # đỏ
    "Blank": "#e2e8f0",        # light gray — status trống
}

# ---------------------------------------------------------------------------
# Categorical — Tableau 10 (safe cho colorblind)
# ---------------------------------------------------------------------------
CATEGORICAL = [
    "#4e79a7", "#f28e2b", "#e15759", "#76b7b2",
    "#59a14f", "#edc948", "#b07aa1", "#ff9da7",
    "#9c755f", "#bab0ac",
]

# ---------------------------------------------------------------------------
# Diverging — cho variance (âm=đỏ, dương=xanh)
# ---------------------------------------------------------------------------
DIVERGING = {
    "neg_strong": "#b91c1c",
    "neg_mid":    "#f87171",
    "zero":       "#e5e7eb",
    "pos_mid":    "#86efac",
    "pos_strong": "#15803d",
}

# ---------------------------------------------------------------------------
# Dark mode parallel — sáng hơn để đọc trên bg đen
# ---------------------------------------------------------------------------
DARK_MODE_MAP = {
    # Progress tiered
    "#dc2626": "#ef4444",
    "#f59e0b": "#fbbf24",
    "#16a34a": "#22c55e",
    # Status
    "#2563eb": "#3b82f6",
    "#0891b2": "#22d3ee",
    "#84cc16": "#a3e635",
    "#64748b": "#94a3b8",
    "#94a3b8": "#cbd5e1",
    "#e2e8f0": "#334155",
    # Diverging
    "#b91c1c": "#dc2626",
    "#f87171": "#fca5a5",
    "#e5e7eb": "#475569",
    "#86efac": "#4ade80",
    "#15803d": "#22c55e",
}


def _dark(color: str, dark: bool) -> str:
    """Trả biến thể dark nếu có, else giữ nguyên."""
    return DARK_MODE_MAP.get(color, color) if dark else color


def progress_color(pct: float, dark: bool = False,
                   thresholds: tuple[float, float] | None = None) -> str:
    """Trả màu theo % progress dùng semantic tiered.

    Args:
        pct: 0..100
        dark: dark mode
        thresholds: (low_max, mid_max) — override default (30, 70)
    """
    low_max, mid_max = thresholds or PROGRESS_THRESHOLDS
    if pct < low_max:
        c = PROGRESS_TIERED["low"]
    elif pct < mid_max:
        c = PROGRESS_TIERED["mid"]
    else:
        c = PROGRESS_TIERED["high"]
    return _dark(c, dark)


def status_color(status: str, dark: bool = False) -> str:
    """Trả màu theo status name. Không match → dùng Open."""
    s = (status or "").strip()
    c = STATUS.get(s) or STATUS["Open"]
    return _dark(c, dark)


def categorical_colors(n: int, dark: bool = False) -> list[str]:
    """Trả n màu categorical, cycle Tableau 10 nếu n > 10."""
    if n <= 0:
        return []
    out = []
    for i in range(n):
        c = CATEGORICAL[i % len(CATEGORICAL)]
        out.append(_dark(c, dark))
    return out


def diverging_color(value: float, min_val: float, max_val: float,
                    dark: bool = False) -> str:
    """Trả màu diverging theo giá trị.

    - value < 0: neg (đỏ), càng âm càng đậm
    - value == 0: zero
    - value > 0: pos (xanh), càng dương càng đậm
    """
    if value == 0:
        return _dark(DIVERGING["zero"], dark)
    if value < 0:
        # Ngưỡng: nửa min → mid, cả min → strong
        thresh = min_val / 2
        key = "neg_strong" if value <= thresh else "neg_mid"
    else:
        thresh = max_val / 2
        key = "pos_strong" if value >= thresh else "pos_mid"
    return _dark(DIVERGING[key], dark)
