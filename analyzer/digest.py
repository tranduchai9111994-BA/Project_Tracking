"""
T26 — Weekly Digest scheduler (cron-lite).

Backend chỉ chạy check khi Flask app khởi động (không cần thread nền phức
tạp — user thường chạy local Windows, restart mỗi buổi sáng). Nếu:
  - digest.enabled == True
  - today.weekday() == digest.day_of_week
  - datetime.now().hour >= digest.hour
  - last_generated_date != today (chưa gen hôm nay)
→ sinh 1 file Excel digest → lưu vào <project_dir>/digests/YYYYMMDD.xlsx.

Digest tái sử dụng `exporter.excel_exporter.export_full_report` (đa sheet
Overdue / Unassigned / Long Duration / Stalled / High Risk / Summary) để
không duplicate logic. Frontend list history + download qua endpoint mới.
"""
from __future__ import annotations

import os
import sys
from datetime import date, datetime
from typing import Any, Optional

from analyzer import project_store as ps


DIGESTS_SUBDIR = "digests"


def digest_dir(project_dir: str) -> str:
    """Trả (và tạo nếu chưa có) folder digests/ trong project."""
    out = os.path.join(project_dir, DIGESTS_SUBDIR)
    os.makedirs(out, exist_ok=True)
    return out


def list_digests(project_dir: str) -> list[dict[str, Any]]:
    """Liệt kê các file digest hiện có (sorted desc theo mtime)."""
    folder = digest_dir(project_dir)
    items: list[dict[str, Any]] = []
    for name in os.listdir(folder):
        if not name.lower().endswith(".xlsx"):
            continue
        path = os.path.join(folder, name)
        try:
            stat = os.stat(path)
        except OSError:
            continue
        items.append({
            "filename": name,
            "size_bytes": stat.st_size,
            "created_at": datetime.fromtimestamp(stat.st_mtime).isoformat(timespec="seconds"),
        })
    items.sort(key=lambda x: x["created_at"], reverse=True)
    return items


def get_digest_path(project_dir: str, filename: str) -> Optional[str]:
    """Chống path traversal — chỉ trả path nếu filename hợp lệ và nằm trong digests/."""
    safe = os.path.basename(filename or "")
    if not safe or not safe.lower().endswith(".xlsx"):
        return None
    folder = digest_dir(project_dir)
    full = os.path.join(folder, safe)
    if not os.path.isfile(full):
        return None
    return full


def _should_generate_now(settings: dict[str, Any], now: datetime) -> bool:
    """Áp reg: enabled + đúng weekday + >= hour + chưa gen hôm nay."""
    dig = settings.get("digest") or {}
    if not dig.get("enabled"):
        return False
    if int(dig.get("day_of_week", 0)) != now.weekday():
        return False
    if now.hour < int(dig.get("hour", 9)):
        return False
    today_iso = now.date().isoformat()
    if str(dig.get("last_generated_date") or "") == today_iso:
        return False
    return True


def generate_digest_now(
    project_dir: str,
    metrics: dict[str, Any],
    today: Optional[date] = None,
) -> Optional[str]:
    """Sinh 1 file digest ngay lập tức từ metrics đã compute.

    Args:
        project_dir: folder của project
        metrics: dict metrics từ DashboardEngine.compute_all()
        today: ngày dùng để đặt tên file (default: hôm nay)

    Returns:
        Đường dẫn file đã sinh, hoặc None nếu lỗi.
    """
    from exporter.excel_exporter import export_full_report

    if not metrics:
        return None
    day = today or date.today()
    stamp = day.strftime("%Y%m%d")
    out_dir = digest_dir(project_dir)
    # export_full_report tự đặt tên `Full_Report_YYYYMMDD.xlsx` → sinh
    # tạm rồi rename để theo convention digest YYYYMMDD.xlsx.
    try:
        temp_path = export_full_report(metrics, output_dir=out_dir)
    except Exception as e:
        print(f"[digest] Lỗi generate: {e}", file=sys.stderr)
        return None
    final_path = os.path.join(out_dir, f"{stamp}.xlsx")
    if temp_path != final_path:
        try:
            if os.path.isfile(final_path):
                os.remove(final_path)
            os.rename(temp_path, final_path)
        except OSError:
            # Nếu rename fail (VD file lock), giữ temp_path
            return temp_path
    # Update last_generated_date
    settings = ps.load_project_settings(project_dir)
    settings["digest"]["last_generated_date"] = day.isoformat()
    ps.save_project_settings(project_dir, {"digest": settings["digest"]})
    return final_path


def run_scheduler(project_manager, state_loader, now: Optional[datetime] = None) -> list[dict]:
    """Chạy scheduler khi app khởi động.

    Args:
        project_manager: instance ProjectManager
        state_loader: callable(slug) -> Optional[dict] (dict có key 'metrics')
        now: datetime hiện tại (test-injectable)

    Returns:
        List các entry {slug, filename, status} — cho log/telemetry.
    """
    now = now or datetime.now()
    out: list[dict] = []
    try:
        projects = project_manager.list_projects(include_archived=False)
    except Exception as e:
        print(f"[digest scheduler] Lỗi list projects: {e}", file=sys.stderr)
        return out

    for proj in projects:
        try:
            pdir = project_manager.get_project_folder(proj.slug)
            settings = ps.load_project_settings(pdir)
            if not _should_generate_now(settings, now):
                continue
            state = state_loader(proj.slug)
            if not state or not state.get("metrics"):
                out.append({"slug": proj.slug, "status": "skip", "reason": "no data"})
                continue
            path = generate_digest_now(pdir, state["metrics"], today=now.date())
            if path:
                out.append({
                    "slug": proj.slug,
                    "filename": os.path.basename(path),
                    "status": "ok",
                })
            else:
                out.append({"slug": proj.slug, "status": "error", "reason": "export failed"})
        except Exception as e:
            out.append({"slug": proj.slug, "status": "error", "reason": str(e)})
            print(f"[digest scheduler] {proj.slug}: {e}", file=sys.stderr)
    return out
