"""
Dọn đĩa local — snapshot cũ / export tạm — gọi khi start app.
"""
from __future__ import annotations

import os
import time
from typing import Optional


def purge_old_exports(base_projects_dir: str, max_age_days: int = 7) -> int:
    """Xóa file trong exports/ cũ hơn max_age_days. Trả số file đã xóa."""
    deleted = 0
    if not os.path.isdir(base_projects_dir):
        return 0
    cutoff = time.time() - max_age_days * 86400
    for slug in os.listdir(base_projects_dir):
        export_dir = os.path.join(base_projects_dir, slug, "exports")
        if not os.path.isdir(export_dir):
            continue
        for name in os.listdir(export_dir):
            path = os.path.join(export_dir, name)
            if not os.path.isfile(path):
                continue
            try:
                if os.path.getmtime(path) < cutoff:
                    os.remove(path)
                    deleted += 1
            except OSError:
                continue
    return deleted


def purge_excess_snapshots(snapshot_dir: str, keep: int = 15) -> int:
    """
    Giữ tối đa `keep` snapshot xlsx mới nhất (theo mtime).
    Xóa kèm .pkl cùng stem nếu có.
    """
    if not os.path.isdir(snapshot_dir):
        return 0
    files = [
        os.path.join(snapshot_dir, f)
        for f in os.listdir(snapshot_dir)
        if f.endswith(".xlsx") and os.path.isfile(os.path.join(snapshot_dir, f))
    ]
    files.sort(key=lambda p: os.path.getmtime(p), reverse=True)
    deleted = 0
    for path in files[keep:]:
        try:
            os.remove(path)
            deleted += 1
            pkl = path.replace(".xlsx", ".parsed.pkl")
            if os.path.isfile(pkl):
                os.remove(pkl)
                deleted += 1
        except OSError:
            continue
    return deleted
