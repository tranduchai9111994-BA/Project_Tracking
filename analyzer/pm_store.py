# -*- coding: utf-8 -*-
"""
Lưu / đọc chiều PM per-project.

Layout:
  uploads/projects/<slug>/pm/
    plan.json
    plan.xlsx          (bản copy nguồn)
    weekly.json        (snapshot mới nhất)
    weekly.pptx
    mapping.json       (sheet mapping đã accept)
"""
from __future__ import annotations

import json
import os
import re
import shutil
from datetime import datetime
from typing import Any, Optional


def pm_dir(project_dir: str) -> str:
    d = os.path.join(project_dir, "pm")
    os.makedirs(d, exist_ok=True)
    return d


def _read_json(path: str, default: Any = None) -> Any:
    if not os.path.isfile(path):
        return default
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return default


def _write_json(path: str, data: Any) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def load_mapping(project_dir: str) -> dict[str, str]:
    return _read_json(os.path.join(pm_dir(project_dir), "mapping.json"), {}) or {}


def save_mapping(project_dir: str, mapping: dict[str, str]) -> dict[str, str]:
    path = os.path.join(pm_dir(project_dir), "mapping.json")
    _write_json(path, mapping)
    return mapping


def load_plan(project_dir: str) -> Optional[dict[str, Any]]:
    return _read_json(os.path.join(pm_dir(project_dir), "plan.json"))


def load_weekly(project_dir: str) -> Optional[dict[str, Any]]:
    return _read_json(os.path.join(pm_dir(project_dir), "weekly.json"))


def save_plan(
    project_dir: str,
    parsed: dict[str, Any],
    *,
    source_filename: str,
    source_path: Optional[str] = None,
) -> dict[str, Any]:
    """Lưu plan.json (+ copy file nguồn nếu có)."""
    d = pm_dir(project_dir)
    payload = {
        **parsed,
        "source_filename": source_filename,
        "imported_at": datetime.now().isoformat(timespec="seconds"),
    }
    _write_json(os.path.join(d, "plan.json"), payload)
    if parsed.get("sheet_mapping"):
        save_mapping(project_dir, parsed["sheet_mapping"])
    if source_path and os.path.isfile(source_path):
        ext = os.path.splitext(source_path)[1] or ".xlsx"
        dest = os.path.join(d, f"plan{ext}")
        try:
            if os.path.abspath(source_path) != os.path.abspath(dest):
                shutil.copy2(source_path, dest)
        except shutil.SameFileError:
            pass
    return payload


def save_weekly(
    project_dir: str,
    parsed: dict[str, Any],
    *,
    source_filename: str,
    source_path: Optional[str] = None,
) -> dict[str, Any]:
    d = pm_dir(project_dir)
    payload = {
        **parsed,
        "source_filename": source_filename,
        "imported_at": datetime.now().isoformat(timespec="seconds"),
    }
    _write_json(os.path.join(d, "weekly.json"), payload)
    if source_path and os.path.isfile(source_path):
        ext = os.path.splitext(source_path)[1] or ".pptx"
        dest = os.path.join(d, f"weekly{ext}")
        try:
            if os.path.abspath(source_path) != os.path.abspath(dest):
                shutil.copy2(source_path, dest)
        except shutil.SameFileError:
            pass
        # Chỉ giữ weekly.pptx — tên gốc nằm trong source_filename (weekly.json)
        try:
            from analyzer.disk_janitor import purge_duplicate_pm_weekly
            purge_duplicate_pm_weekly(project_dir)
        except Exception:
            pass
    return payload


def _find_pm_source(d: str, stem: str, exts: tuple[str, ...]) -> Optional[str]:
    """Tìm plan.xlsx / weekly.pptx (hoặc bản copy tên gốc) trong thư mục pm/."""
    for ext in exts:
        p = os.path.join(d, f"{stem}{ext}")
        if os.path.isfile(p):
            return p
    # Fallback: file nguồn MPHG_*KeHoachDuAn*.xlsx / *Weekly*.pptx
    try:
        for name in os.listdir(d):
            low = name.lower()
            if stem == "plan" and low.endswith((".xlsx", ".xls")) and (
                "kehoachduan" in low or "ke_hoach" in low or low.startswith("plan")
            ):
                return os.path.join(d, name)
            if stem == "weekly" and low.endswith(".pptx") and (
                "weekly" in low or low.startswith("weekly")
            ):
                return os.path.join(d, name)
    except OSError:
        pass
    return None


def hydrate_pm_from_sources(project_dir: str) -> dict[str, Any]:
    """
    Nếu thiếu plan.json/weekly.json nhưng còn file nguồn trong pm/ → parse + lưu.

    Dùng khi user copy file vào uploads/.../pm/ mà chưa qua UI import,
    hoặc sau khi restore project folder.
    """
    d = pm_dir(project_dir)
    plan = load_plan(project_dir)
    weekly = load_weekly(project_dir)

    def _pretty_name(src: str, stem: str) -> str:
        base = os.path.basename(src)
        # Nếu đang dùng plan.xlsx/weekly.pptx, ưu tiên tên file gốc cạnh đó (nếu có)
        if base.lower() in (f"{stem}.xlsx", f"{stem}.xls", f"{stem}.pptx"):
            try:
                for name in os.listdir(d):
                    low = name.lower()
                    if stem == "plan" and low.endswith((".xlsx", ".xls")) and "kehoachduan" in low:
                        return name
                    if stem == "weekly" and low.endswith(".pptx") and "weekly" in low and not low.startswith("weekly."):
                        return name
            except OSError:
                pass
        return base

    if plan is None:
        src = _find_pm_source(d, "plan", (".xlsx", ".xls"))
        if src:
            try:
                from parser.pm_plan_parser import parse_plan
                parsed = parse_plan(src)
                plan = save_plan(
                    project_dir,
                    parsed,
                    source_filename=_pretty_name(src, "plan"),
                    source_path=src,
                )
            except Exception:
                pass

    if weekly is None:
        src = _find_pm_source(d, "weekly", (".pptx",))
        if src:
            try:
                from parser.pm_weekly_parser import parse_weekly
                parsed = parse_weekly(src)
                weekly = save_weekly(
                    project_dir,
                    parsed,
                    source_filename=_pretty_name(src, "weekly"),
                    source_path=src,
                )
            except Exception:
                pass

    return {
        "plan": plan,
        "weekly": weekly,
        "has_plan": plan is not None,
        "has_weekly": weekly is not None,
    }


def load_pm_bundle(project_dir: str, *, hydrate: bool = True) -> dict[str, Any]:
    """Trả về {plan, weekly, has_plan, has_weekly}. hydrate=True → auto-parse nguồn nếu thiếu JSON."""
    if hydrate:
        return hydrate_pm_from_sources(project_dir)
    plan = load_plan(project_dir)
    weekly = load_weekly(project_dir)
    return {
        "plan": plan,
        "weekly": weekly,
        "has_plan": plan is not None,
        "has_weekly": weekly is not None,
    }


def link_with_function_list(
    plan: Optional[dict[str, Any]],
    weekly: Optional[dict[str, Any]],
    parsed_data: Any = None,
) -> dict[str, Any]:
    """
    Join mềm với Function List: module / phase / PIC trùng tên.

    Không hard-fail khi thiếu FL — trả links rỗng.
    """
    modules: set[str] = set()
    phases: set[str] = set()
    pics: set[str] = set()
    if parsed_data is not None:
        for fn in getattr(parsed_data, "functions", None) or []:
            mod = getattr(fn, "module", None) or (fn.get("module") if isinstance(fn, dict) else None)
            if mod:
                modules.add(str(mod).strip())
            for ph_name, ph in (getattr(fn, "phases", None) or (fn.get("phases") if isinstance(fn, dict) else {}) or {}).items():
                phases.add(str(ph_name).strip())
                pic_val = None
                if hasattr(ph, "pic"):
                    pic_val = ph.pic
                elif isinstance(ph, dict):
                    pic_val = ph.get("pic")
                if pic_val:
                    for p in re.split(r"[,;\n]+", str(pic_val)):
                        p = p.strip()
                        if p:
                            pics.add(p)

    schedule_links = []
    if plan:
        for i, item in enumerate(plan.get("schedule") or []):
            if item.get("is_phase_header"):
                continue
            name = item.get("name") or ""
            matched_modules = [m for m in modules if m and m.lower() in name.lower()]
            matched_phases = [p for p in phases if p and p.lower() in name.lower()]
            item_pics = set(item.get("pic_fpt") or []) | set(item.get("support_fpt") or [])
            matched_pics = sorted(item_pics & pics)
            if matched_modules or matched_phases or matched_pics:
                schedule_links.append({
                    "schedule_index": i,
                    "name": name,
                    "modules": matched_modules,
                    "phases": matched_phases,
                    "pics": matched_pics,
                })

    weekly_links = []
    if weekly:
        for kind, key in (("done", "task"), ("next", "task")):
            for i, item in enumerate(weekly.get(kind) or []):
                name = item.get(key) or ""
                matched_modules = [m for m in modules if m and m.lower() in name.lower()]
                if matched_modules:
                    weekly_links.append({
                        "kind": kind,
                        "index": i,
                        "task": name,
                        "modules": matched_modules,
                    })

    return {
        "fl_modules": sorted(modules),
        "fl_phases": sorted(phases),
        "schedule_links": schedule_links,
        "weekly_links": weekly_links,
        "link_count": len(schedule_links) + len(weekly_links),
    }
