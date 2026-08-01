"""
Dọn đĩa local — snapshot cũ / export tạm / synced tạm / PM PPTX trùng —
gọi khi start app (và sau sync nếu cần).
"""
from __future__ import annotations

import os
import time
from typing import Optional

# Giữ N file synced_*.xlsx mới nhất mỗi project (file tạm sau API sync).
MAX_SYNCED_XLSX = 5


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


def purge_excess_synced_xlsx(project_dir: str, keep: int = MAX_SYNCED_XLSX) -> int:
    """
    Giữ tối đa `keep` file synced_*.xlsx mới nhất ở root project
    (không đụng current.xlsx / snapshots/).
    """
    if not os.path.isdir(project_dir):
        return 0
    keep = max(1, int(keep))
    files = [
        os.path.join(project_dir, f)
        for f in os.listdir(project_dir)
        if f.startswith("synced_")
        and f.lower().endswith(".xlsx")
        and os.path.isfile(os.path.join(project_dir, f))
    ]
    files.sort(key=lambda p: os.path.getmtime(p), reverse=True)
    deleted = 0
    for path in files[keep:]:
        try:
            os.remove(path)
            deleted += 1
        except OSError:
            continue
    return deleted


def purge_excess_synced_all(
    base_projects_dir: str, keep: int = MAX_SYNCED_XLSX
) -> int:
    """Chạy purge_excess_synced_xlsx cho mọi project dưới base_projects_dir."""
    if not os.path.isdir(base_projects_dir):
        return 0
    deleted = 0
    for slug in os.listdir(base_projects_dir):
        project_dir = os.path.join(base_projects_dir, slug)
        if os.path.isdir(project_dir):
            deleted += purge_excess_synced_xlsx(project_dir, keep=keep)
    return deleted


def purge_duplicate_pm_weekly(project_dir: str) -> int:
    """
    Khi đã có weekly.pptx canonical — xóa bản PPTX tên dài (*weekly*.pptx khác)
    trong pm/. Tên gốc vẫn lưu trong weekly.json (source_filename).
    """
    pm = os.path.join(project_dir, "pm")
    if not os.path.isdir(pm):
        return 0
    canonical = os.path.join(pm, "weekly.pptx")
    if not os.path.isfile(canonical):
        return 0
    deleted = 0
    try:
        names = os.listdir(pm)
    except OSError:
        return 0
    for name in names:
        low = name.lower()
        if not low.endswith(".pptx"):
            continue
        if low == "weekly.pptx":
            continue
        if "weekly" not in low:
            continue
        path = os.path.join(pm, name)
        if not os.path.isfile(path):
            continue
        try:
            os.remove(path)
            deleted += 1
        except OSError:
            continue
    return deleted


def purge_duplicate_pm_weekly_all(base_projects_dir: str) -> int:
    """Chạy purge_duplicate_pm_weekly cho mọi project."""
    if not os.path.isdir(base_projects_dir):
        return 0
    deleted = 0
    for slug in os.listdir(base_projects_dir):
        project_dir = os.path.join(base_projects_dir, slug)
        if os.path.isdir(project_dir):
            deleted += purge_duplicate_pm_weekly(project_dir)
    return deleted
