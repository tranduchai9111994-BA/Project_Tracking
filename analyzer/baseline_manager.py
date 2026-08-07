"""
Baseline Manager — chuỗi re-baseline bất biến (v1, v2, v3...).

Khác `SnapshotManager`: snapshot là lịch sử tự động (1 bản/ngày, ghi đè cùng
ngày, bị prune khi vượt cap). Baseline là mốc kế hoạch do PM **chủ động chốt**
nên phải bất biến:

- Khi chốt, file .xlsx + pickle được COPY sang `baselines/` → nằm ngoài
  `snapshots/` nên `SnapshotManager._prune_overflow` không bao giờ xóa được.
- Ghi đè snapshot cùng ngày (upload lần 2 trong ngày) không đổi nội dung
  baseline; lệch nội dung được phát hiện qua `checksum` và ghi cờ
  `source_drifted` để UI cảnh báo.
- Nhiều baseline cùng tồn tại; `resolve_latest(as_of)` trả baseline gần nhất
  tính đến thời điểm as_of — đây là mốc dùng để so sánh.

Layout:
    uploads/projects/<slug>/baselines/
      baselines_index.json
      YYYY-MM-DD_v1_functionlist.xlsx
      YYYY-MM-DD_v1_functionlist.parsed.pkl
"""
from __future__ import annotations

import hashlib
import json
import os
import pickle
import shutil
from datetime import date, datetime
from typing import Any, Optional

INDEX_FILE = "baselines_index.json"
PICKLE_SUFFIX = ".parsed.pkl"


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _as_date(value: Any) -> Optional[date]:
    """Parse 'YYYY-MM-DD' → date; trả None nếu không hợp lệ."""
    if isinstance(value, date):
        return value
    s = str(value or "").strip()
    if not s:
        return None
    try:
        return date.fromisoformat(s[:10])
    except ValueError:
        return None


def latest_baseline(
    entries: list[dict], as_of: Optional[date] = None
) -> Optional[dict]:
    """
    Baseline gần nhất trong `entries` tính đến `as_of` (snapshot_date <= as_of).

    Tách khỏi class để `analyzer.compare_base` dùng lại cùng một luật, tránh
    hai chỗ định nghĩa "gần nhất" khác nhau.
    """
    candidates = []
    for e in entries or []:
        d = _as_date(e.get("snapshot_date"))
        if d is None:
            continue
        if as_of is not None and d > as_of:
            continue
        candidates.append((d, int(e.get("version") or 0), e))
    if not candidates:
        return None
    candidates.sort(key=lambda t: (t[0], t[1]))
    return candidates[-1][2]


class BaselineManager:
    """Chốt, đọc, liệt kê, xóa các bản baseline bất biến của 1 project."""

    def __init__(self, baseline_dir: str):
        self.dir = baseline_dir
        os.makedirs(self.dir, exist_ok=True)
        self.index_path = os.path.join(self.dir, INDEX_FILE)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def pin_from_snapshot(
        self,
        snapshot_dir: str,
        snapshot_entry: dict,
        *,
        label: str = "",
        note: str = "",
        created_by: str = "",
    ) -> Optional[dict]:
        """
        Chốt 1 snapshot thành baseline mới (version tăng dần).

        Args:
            snapshot_dir: folder `snapshots/` chứa file gốc.
            snapshot_entry: entry từ `SnapshotManager.list_snapshots()`
                (cần `date`, `pickle`, tuỳ chọn `filename`, `archived`).
            label: nhãn ngắn do user đặt (VD "Kế hoạch approved 06/2026").
            note: ghi chú dài.
            created_by: username người chốt.

        Returns:
            Entry baseline vừa tạo, hoặc None nếu không đọc được pickle nguồn.
        """
        snap_date = str(snapshot_entry.get("date") or "").strip()
        if not snap_date:
            return None

        raw = self._read_snapshot_pickle_bytes(snapshot_dir, snapshot_entry)
        if raw is None:
            return None

        index = self._load_index()
        version = max((int(e.get("version") or 0) for e in index), default=0) + 1
        base_name = f"{snap_date}_v{version}_functionlist"
        pkl_name = f"{base_name}{PICKLE_SUFFIX}"
        xlsx_name = f"{base_name}.xlsx"

        with open(os.path.join(self.dir, pkl_name), "wb") as f:
            f.write(raw)

        # File .xlsx là tiện ích để tải lại bản gốc — thiếu cũng không chặn
        # (snapshot archived đã xóa hot xlsx).
        src_xlsx = os.path.join(snapshot_dir, str(snapshot_entry.get("filename") or ""))
        xlsx_saved = ""
        if snapshot_entry.get("filename") and os.path.isfile(src_xlsx):
            try:
                shutil.copy2(src_xlsx, os.path.join(self.dir, xlsx_name))
                xlsx_saved = xlsx_name
            except OSError:
                xlsx_saved = ""

        entry = {
            "id": f"{snap_date}_v{version}",
            "version": version,
            "snapshot_date": snap_date,
            "label": str(label or "").strip()[:120],
            "note": str(note or "").strip()[:500],
            "created_at": datetime.now().isoformat(timespec="seconds"),
            "created_by": str(created_by or "").strip()[:64],
            "checksum": _sha256(raw),
            "filename": xlsx_saved,
            "pickle": pkl_name,
            "total_functions": snapshot_entry.get("total_functions", 0),
            "overall_pct": snapshot_entry.get("overall_pct", 0),
            "source_drifted": False,
        }
        index.append(entry)
        self._save_index(self._sorted(index))
        return entry

    def list_baselines(self) -> list[dict]:
        """Danh sách baseline, sort giảm dần theo (snapshot_date, version)."""
        return self._sorted(self._load_index())

    def find(self, baseline_id: str) -> Optional[dict]:
        bid = str(baseline_id or "").strip()
        if not bid:
            return None
        for e in self._load_index():
            if str(e.get("id")) == bid:
                return e
        return None

    def load_baseline(self, baseline_id: str) -> Optional[dict]:
        """
        Load 1 baseline theo id.

        Returns: {"parsed": ParsedData, "meta": entry} hoặc None.
        Đọc từ bản copy trong `baselines/` nên không phụ thuộc snapshot gốc
        còn tồn tại hay đã bị prune.
        """
        entry = self.find(baseline_id)
        if not entry:
            return None
        pkl_path = os.path.join(self.dir, str(entry.get("pickle") or ""))
        if not os.path.isfile(pkl_path):
            return None
        try:
            with open(pkl_path, "rb") as f:
                parsed = pickle.load(f)
        except Exception:
            return None
        return {"parsed": parsed, "meta": entry}

    def resolve_latest(self, as_of: Optional[date] = None) -> Optional[dict]:
        """
        Baseline gần nhất tính đến `as_of` (snapshot_date <= as_of).

        `as_of=None` → baseline mới nhất. Đây là "baseline gần nhất" dùng làm
        mốc so sánh cho các bản kéo về sau.
        """
        return latest_baseline(self._load_index(), as_of)

    def delete(self, baseline_id: str) -> bool:
        """Xóa 1 baseline (entry + file)."""
        entry = self.find(baseline_id)
        if not entry:
            return False
        for key in ("filename", "pickle"):
            name = str(entry.get(key) or "")
            if not name:
                continue
            path = os.path.join(self.dir, name)
            if os.path.exists(path):
                try:
                    os.remove(path)
                except OSError:
                    pass
        index = [e for e in self._load_index() if str(e.get("id")) != str(entry.get("id"))]
        self._save_index(self._sorted(index))
        return True

    def mark_source_drift(self, snapshot_date: str, new_checksum: str) -> list[dict]:
        """
        Đánh dấu baseline có snapshot gốc bị ghi đè nội dung.

        Gọi sau khi `SnapshotManager.save_snapshot` ghi đè snapshot cùng ngày:
        nếu checksum mới khác checksum đã chốt → set `source_drifted=True`.
        Nội dung baseline KHÔNG bị thay, chỉ để UI cảnh báo là snapshot gốc
        không còn khớp bản đã chốt.
        """
        snap_date = str(snapshot_date or "").strip()
        if not snap_date or not new_checksum:
            return self.list_baselines()
        index = self._load_index()
        changed = False
        for e in index:
            if str(e.get("snapshot_date")) != snap_date:
                continue
            drifted = str(e.get("checksum") or "") != str(new_checksum)
            if bool(e.get("source_drifted")) != drifted:
                e["source_drifted"] = drifted
                changed = True
        if changed:
            self._save_index(self._sorted(index))
        return self._sorted(index)

    def refresh_source_drift(
        self, snapshot_dir: str, snapshot_entries: list[dict]
    ) -> list[dict]:
        """
        Rà lại cờ `source_drifted` cho mọi baseline còn snapshot gốc.

        Kiểm tra lười (gọi khi mở panel quản lý baseline) thay vì hook vào
        `save_snapshot` — nhờ đó không phải sửa mọi call site upload/sync, và
        kết quả luôn phản ánh trạng thái file hiện tại. Baseline mà snapshot
        gốc đã bị prune thì bỏ qua (không có gì để so).
        """
        by_date = {str(s.get("date") or ""): s for s in (snapshot_entries or [])}
        index = self._load_index()
        changed = False
        for e in index:
            snap = by_date.get(str(e.get("snapshot_date") or ""))
            if not snap:
                continue
            cur = snapshot_pickle_checksum(snapshot_dir, snap)
            if not cur:
                continue
            drifted = cur != str(e.get("checksum") or "")
            if bool(e.get("source_drifted")) != drifted:
                e["source_drifted"] = drifted
                changed = True
        if changed:
            self._save_index(self._sorted(index))
        return self._sorted(index)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _read_snapshot_pickle_bytes(
        snapshot_dir: str, snapshot_entry: dict
    ) -> Optional[bytes]:
        """Đọc bytes pickle của snapshot (hỗ trợ cả bản đã archive gzip)."""
        if snapshot_entry.get("archived"):
            try:
                from analyzer.archive_manager import load_archived_pickle_bytes
                return load_archived_pickle_bytes(snapshot_dir, snapshot_entry)
            except Exception:
                return None
        pkl_path = os.path.join(snapshot_dir, str(snapshot_entry.get("pickle") or ""))
        if not os.path.isfile(pkl_path):
            return None
        try:
            with open(pkl_path, "rb") as f:
                return f.read()
        except OSError:
            return None

    @staticmethod
    def _sorted(index: list[dict]) -> list[dict]:
        return sorted(
            index,
            key=lambda e: (str(e.get("snapshot_date") or ""), int(e.get("version") or 0)),
            reverse=True,
        )

    def _load_index(self) -> list[dict]:
        if not os.path.exists(self.index_path):
            return []
        try:
            with open(self.index_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                return data if isinstance(data, list) else []
        except (json.JSONDecodeError, OSError):
            return []

    def _save_index(self, index: list[dict]) -> None:
        with open(self.index_path, "w", encoding="utf-8") as f:
            json.dump(index, f, ensure_ascii=False, indent=2)


def snapshot_pickle_checksum(snapshot_dir: str, snapshot_entry: dict) -> str:
    """Checksum pickle của 1 snapshot (dùng để phát hiện drift). '' nếu lỗi."""
    raw = BaselineManager._read_snapshot_pickle_bytes(snapshot_dir, snapshot_entry)
    return _sha256(raw) if raw is not None else ""
