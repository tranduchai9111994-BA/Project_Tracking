"""
Resolver mốc so sánh cho các bảng có cột tăng/giảm.

Tồn tại vì trong hệ thống, "bản trước" và "tuần trước" KHÔNG giống nhau:
snapshot chỉ có 1 bản/ngày và chỉ sinh ra khi upload/sync, nên `snapshots[1]`
có thể là hôm qua mà cũng có thể là 3 tuần trước. Module này buộc mọi chỗ phải
nói rõ đang so với mốc nào, kèm nhãn tiếng Việt có ngày thật để PM không đọc
nhầm con số.

4 mode:
  baseline — baseline gần nhất đã chốt (mặc định nếu project đã có baseline)
  week     — bản gần nhất có ngày <= today - 7 (đúng nghĩa "tuần trước")
  previous — snapshots[1], quy ước cũ của function-diff / insight strip
  date     — 1 snapshot cụ thể do user chọn
`off` → tắt so sánh, không tính delta.
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Optional

from analyzer.baseline_manager import latest_baseline

WEEK_LOOKBACK_DAYS = 7
VALID_MODES = ("baseline", "week", "previous", "date", "off")
DEFAULT_MODE = "baseline"


def _fmt_vi(value: Any) -> str:
    """'2026-06-01' → '01/06/2026'; giá trị lạ trả nguyên văn."""
    s = str(value or "").strip()
    try:
        return date.fromisoformat(s[:10]).strftime("%d/%m/%Y")
    except ValueError:
        return s


def normalize_mode(raw: Any, *, has_baseline: bool = False) -> str:
    """Chuẩn hoá mode; giá trị lạ → baseline nếu có baseline, else previous."""
    m = str(raw or "").strip().lower()
    if m in VALID_MODES:
        return m
    return DEFAULT_MODE if has_baseline else "previous"


def _empty(mode: str, error: str) -> dict[str, Any]:
    return {
        "mode": mode,
        "source": "",
        "id": "",
        "snapshot_date": "",
        "label": "",
        "meta": None,
        "error": error,
    }


def resolve_compare_base(
    snapshots: list[dict],
    baselines: list[dict],
    *,
    mode: str = DEFAULT_MODE,
    explicit_date: str = "",
    today: Optional[date] = None,
) -> dict[str, Any]:
    """
    Chọn mốc so sánh.

    Args:
        snapshots: `SnapshotManager.list_snapshots()` (đã sort giảm dần theo ngày).
        baselines: `BaselineManager.list_baselines()`.
        mode: baseline | week | previous | date | off.
        explicit_date: 'YYYY-MM-DD', chỉ dùng khi mode='date'.
        today: mốc hôm nay (inject để test).

    Returns:
        {mode, source, id, snapshot_date, label, meta, error}
        - `source`: "baseline" (đọc từ baselines/) hoặc "snapshot" (đọc từ snapshots/).
        - `id`: baseline_id khi source=baseline, ngày snapshot khi source=snapshot.
        - `error`: message tiếng Việt nếu không tìm được mốc; không raise.
    """
    today = today or date.today()
    snaps = list(snapshots or [])
    mode = str(mode or DEFAULT_MODE).strip().lower()
    if mode not in VALID_MODES:
        mode = DEFAULT_MODE

    if mode == "off":
        return _empty("off", "")

    if mode == "baseline":
        entry = latest_baseline(baselines or [], today)
        if not entry:
            return _empty(
                "baseline",
                "Chưa chốt baseline nào. Bấm «Chốt baseline» để lấy bản hiện tại "
                "làm kế hoạch gốc.",
            )
        ver = entry.get("version")
        snap_date = str(entry.get("snapshot_date") or "")
        label_parts = [f"Baseline v{ver}" if ver else "Baseline"]
        if entry.get("label"):
            label_parts.append(str(entry["label"]))
        return {
            "mode": "baseline",
            "source": "baseline",
            "id": str(entry.get("id") or ""),
            "snapshot_date": snap_date,
            "label": f"{' — '.join(label_parts)} · {_fmt_vi(snap_date)}",
            "meta": entry,
            "error": "",
        }

    if mode == "week":
        cutoff = today - timedelta(days=WEEK_LOOKBACK_DAYS)
        picked = None
        for s in sorted(snaps, key=lambda x: str(x.get("date") or ""), reverse=True):
            try:
                d = date.fromisoformat(str(s.get("date") or "")[:10])
            except ValueError:
                continue
            if d <= cutoff:
                picked = s
                break
        if not picked:
            return _empty(
                "week",
                f"Chưa có bản nào từ {WEEK_LOOKBACK_DAYS} ngày trước "
                f"({_fmt_vi(cutoff.isoformat())}) trở về trước để so sánh.",
            )
        snap_date = str(picked.get("date") or "")
        return {
            "mode": "week",
            "source": "snapshot",
            "id": snap_date,
            "snapshot_date": snap_date,
            "label": f"Tuần trước · {_fmt_vi(snap_date)}",
            "meta": picked,
            "error": "",
        }

    if mode == "previous":
        if len(snaps) < 2:
            return _empty(
                "previous",
                "Chỉ có 1 bản trong lịch sử — chưa có bản trước để so sánh.",
            )
        picked = snaps[1]
        snap_date = str(picked.get("date") or "")
        return {
            "mode": "previous",
            "source": "snapshot",
            "id": snap_date,
            "snapshot_date": snap_date,
            "label": f"Bản trước · {_fmt_vi(snap_date)}",
            "meta": picked,
            "error": "",
        }

    # mode == "date"
    want = str(explicit_date or "").strip()[:10]
    if not want:
        return _empty("date", "Chưa chọn bản để so sánh.")
    picked = next((s for s in snaps if str(s.get("date") or "") == want), None)
    if not picked:
        return _empty("date", f"Không tìm thấy bản ngày {_fmt_vi(want)}.")
    return {
        "mode": "date",
        "source": "snapshot",
        "id": want,
        "snapshot_date": want,
        "label": f"Bản {_fmt_vi(want)}",
        "meta": picked,
        "error": "",
    }
