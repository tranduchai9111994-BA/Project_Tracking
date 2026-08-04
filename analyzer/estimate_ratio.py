"""
Ước lượng theo hệ số (ratio / parametric) — bổ sung cho Forecast Manpower.

Không thay Forecast Manpower (unit/duration trên Estimate MH). Module này:
  1. Seed BA_MD / Dev_MD mỗi function theo thứ tự:
       Estimate MH trên phase map BA/Dev → lookup Complexity×FIT/GAP → defaults
  2. Áp hệ số chỉnh được: Des=BA×r, Test=Dev×r, Doc=Dev×r, …
  3. Config/Migration: ưu tiên Estimate MH trên FL nếu có; không thì ratio của Dev
  4. Overhead dự án (tuỳ chọn): UAT ≈ % tổng gồm UAT, Golive=%UAT, PM%, bảo hành, pentest cố định

Tham số lưu tại:
  - per-project: ``uploads/projects/<slug>/estimation_params.json``
  - global: ``uploads/estimation_params.json`` (cạnh thư mục projects)
  - fallback: DEFAULT_PARAMS trong code (gợi ý PMO, không khóa SOVI)

Quy đổi: MH ↔ MD qua ``mh_per_day`` (mặc định 8); MD ↔ MM qua ``md_per_mm`` (mặc định 22).
"""
from __future__ import annotations

import copy
import json
import os
import re
from collections import defaultdict
from typing import Any, Optional

from parser.excel_parser import FunctionRow, ParsedData, PhaseData

PARAMS_FILENAME = "estimation_params.json"

# Bucket chuẩn cho bảng tổng hợp
BUCKET_ORDER = (
    "ba",
    "des",
    "dev",
    "test",
    "config",
    "migration",
    "doc",
    "uat",
    "golive",
    "pm",
    "warranty",
    "pentest",
    "other",
)

BUCKET_LABELS_VI = {
    "ba": "Phân tích (BA)",
    "des": "Thiết kế (DES)",
    "dev": "Lập trình (DEV)",
    "test": "Kiểm thử (Test)",
    "config": "Cấu hình",
    "migration": "Migration",
    "doc": "Tài liệu (Doc)",
    "uat": "UAT",
    "golive": "Golive & Support",
    "pm": "PM overhead",
    "warranty": "Bảo hành",
    "pentest": "Pentest / Performance",
    "other": "Khác (FL)",
}

# Preset quy mô dự án HRIS (nhỏ / trung bình / lớn) — seed + MH mặc định Forecast
SIZE_PRESETS: dict[str, dict[str, Any]] = {
    "small": {
        "id": "small",
        "label": "Nhỏ",
        "hint": "Config đơn giản · ~1–2 người triển khai",
        "seed_defaults": {"ba_md": 0.25, "dev_md": 0.75},
        "default_mh": 2.0,
    },
    "medium": {
        "id": "medium",
        "label": "Trung bình",
        "hint": "HRIS nhỏ–vừa · ~2–3 người · ~300–400 CN",
        "seed_defaults": {"ba_md": 0.35, "dev_md": 1.25},
        "default_mh": 4.0,
    },
    "large": {
        "id": "large",
        "label": "Lớn",
        "hint": "GAP / custom nhiều · MH cao hơn",
        "seed_defaults": {"ba_md": 0.5, "dev_md": 2.0},
        "default_mh": 8.0,
    },
}

# Defaults gợi ý PMO — căn «trung bình» HRIS (không khóa SOVI). Dev 2.0 MD/function quá cao cho config đơn giản.
DEFAULT_PARAMS: dict[str, Any] = {
    "version": 1,
    "label": "Ước lượng theo hệ số (mặc định PMO — chỉnh được)",
    "project_size": "medium",
    "mh_per_day": 8.0,
    "md_per_mm": 22.0,
    # Tổng effort hợp đồng (MD hoặc MM) — scale seed để khớp (calibrate)
    "contract_md": None,
    "contract_mm": None,
    "seed_defaults": {
        "ba_md": 0.35,
        "dev_md": 1.25,
    },
    "ratios": {
        "des_of_ba": 0.25,
        "test_of_dev": 0.30,
        "doc_of_dev": 0.15,
        "config_of_dev": 0.25,
        "migration_of_dev": 0.0,
        "uat_of_total_incl_uat": 0.15,
        "golive_of_uat": 0.15,
        "pm_of_subtotal": 0.05,
        "warranty_of_build": 0.08,
    },
    "overhead": {
        "include_uat": True,
        "include_golive": True,
        "include_pm": True,
        "include_warranty": False,
        "include_pentest": False,
        "pentest_md": 22.0,
    },
    # Optional: [{"complexity": "High", "fit_gap": "GAP", "ba_md": 2.0, "dev_md": 8.0}, ...]
    "lookup": [],
    # Keyword (regex, case-insensitive) → bucket. Khớp phase name hoặc task_type.
    "phase_keywords": {
        "ba": [r"analy", r"ph[aă]n\s*t[ií]ch", r"\bba\b"],
        "des": [r"\bdes\b", r"design", r"thi[eế]t\s*k[eế]"],
        "dev": [r"\bdev\b", r"l[aậ]p\s*tr[iì]nh", r"\bcode\b", r"coding"],
        "test": [r"test", r"local", r"ki[eể]m\s*th[uử]"],
        "config": [r"config", r"c[aấ]u\s*h[iì]nh"],
        "migration": [r"migrat", r"migrate"],
        "doc": [r"\bdoc\b", r"t[aà]i\s*li[eệ]u"],
        "uat": [r"^uat$", r"\buat\b"],
        "golive": [r"golive", r"go.?live", r"\bprod\b", r"support"],
    },
}


def default_params() -> dict[str, Any]:
    return copy.deepcopy(DEFAULT_PARAMS)


def _deep_merge(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    out = copy.deepcopy(base)
    for k, v in (overlay or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = copy.deepcopy(v)
    return out


def _as_float(v: Any, fallback: float) -> float:
    try:
        if v is None or (isinstance(v, str) and not v.strip()):
            return float(fallback)
        return float(v)
    except (TypeError, ValueError):
        return float(fallback)


def apply_size_preset(
    params: dict[str, Any],
    size: str,
    *,
    overwrite_seeds: bool = True,
) -> dict[str, Any]:
    """Áp preset quy mô vào params (seed_defaults + project_size)."""
    out = copy.deepcopy(params)
    key = (size or "").strip().lower()
    if key not in SIZE_PRESETS:
        key = "medium"
    preset = SIZE_PRESETS[key]
    out["project_size"] = key
    if overwrite_seeds:
        out.setdefault("seed_defaults", {})
        out["seed_defaults"]["ba_md"] = float(preset["seed_defaults"]["ba_md"])
        out["seed_defaults"]["dev_md"] = float(preset["seed_defaults"]["dev_md"])
    out["default_mh"] = float(preset["default_mh"])
    return out


def resolve_contract_md(params: dict[str, Any]) -> Optional[float]:
    """Đọc tổng effort hợp đồng (MD). Ưu tiên contract_md; else contract_mm × md_per_mm."""
    md_per_mm = max(_as_float(params.get("md_per_mm"), 22.0), 0.1)
    raw_md = params.get("contract_md")
    if raw_md is not None and str(raw_md).strip() != "":
        v = _as_float(raw_md, 0.0)
        return v if v > 0 else None
    raw_mm = params.get("contract_mm")
    if raw_mm is not None and str(raw_mm).strip() != "":
        v = _as_float(raw_mm, 0.0)
        return (v * md_per_mm) if v > 0 else None
    return None


def scale_seeds_to_contract(
    params: dict[str, Any],
    estimated_total_md: float,
    contract_md: float,
) -> tuple[dict[str, Any], float]:
    """
    Scale seed_defaults + lookup theo factor = contract / estimate.

    Returns (params_đã_scale, factor). Không đụng ratios / overhead flags.
    """
    out = copy.deepcopy(params)
    if estimated_total_md <= 0 or contract_md <= 0:
        return out, 1.0
    factor = float(contract_md) / float(estimated_total_md)
    sd = out.setdefault("seed_defaults", {})
    sd["ba_md"] = max(_as_float(sd.get("ba_md"), 0.0) * factor, 0.0)
    sd["dev_md"] = max(_as_float(sd.get("dev_md"), 0.0) * factor, 0.0)
    lookup = out.get("lookup") or []
    if isinstance(lookup, list):
        for item in lookup:
            if not isinstance(item, dict):
                continue
            item["ba_md"] = max(_as_float(item.get("ba_md"), 0.0) * factor, 0.0)
            item["dev_md"] = max(_as_float(item.get("dev_md"), 0.0) * factor, 0.0)
    out["contract_md"] = float(contract_md)
    out["_calibration_factor"] = factor
    return out, factor


def normalize_params(raw: Optional[dict[str, Any]]) -> dict[str, Any]:
    """Merge user payload với DEFAULT_PARAMS + ép kiểu số an toàn."""
    # Tách project_size: nếu user gửi size mà chưa gửi seed → áp preset
    raw_in = raw if isinstance(raw, dict) else {}
    size_key = str(raw_in.get("project_size") or "").strip().lower()
    apply_preset = size_key in SIZE_PRESETS and (
        "seed_defaults" not in raw_in
        or raw_in.get("_apply_size_preset")
    )

    merged = _deep_merge(DEFAULT_PARAMS, raw_in)
    if apply_preset:
        merged = apply_size_preset(merged, size_key, overwrite_seeds=True)
    elif size_key in SIZE_PRESETS:
        merged["project_size"] = size_key
    else:
        ps = str(merged.get("project_size") or "medium").strip().lower()
        merged["project_size"] = ps if ps in SIZE_PRESETS else "medium"

    merged["mh_per_day"] = max(_as_float(merged.get("mh_per_day"), 8.0), 0.1)
    merged["md_per_mm"] = max(_as_float(merged.get("md_per_mm"), 22.0), 0.1)

    # Contract — giữ None nếu trống
    for ck in ("contract_md", "contract_mm"):
        v = merged.get(ck)
        if v is None or (isinstance(v, str) and not str(v).strip()):
            merged[ck] = None
        else:
            fv = _as_float(v, 0.0)
            merged[ck] = fv if fv > 0 else None

    sd = merged.setdefault("seed_defaults", {})
    med = SIZE_PRESETS["medium"]["seed_defaults"]
    sd["ba_md"] = max(_as_float(sd.get("ba_md"), med["ba_md"]), 0.0)
    sd["dev_md"] = max(_as_float(sd.get("dev_md"), med["dev_md"]), 0.0)

    ratios = merged.setdefault("ratios", {})
    for key, fb in DEFAULT_PARAMS["ratios"].items():
        ratios[key] = max(_as_float(ratios.get(key), fb), 0.0)
    # UAT ratio phải < 1
    if ratios["uat_of_total_incl_uat"] >= 1.0:
        ratios["uat_of_total_incl_uat"] = 0.15

    oh = merged.setdefault("overhead", {})
    for key in (
        "include_uat",
        "include_golive",
        "include_pm",
        "include_warranty",
        "include_pentest",
    ):
        oh[key] = bool(oh.get(key, DEFAULT_PARAMS["overhead"][key]))
    oh["pentest_md"] = max(_as_float(oh.get("pentest_md"), 22.0), 0.0)

    # default_mh gợi ý cho Forecast (không dùng trong tính ratio)
    preset_mh = SIZE_PRESETS.get(merged["project_size"], SIZE_PRESETS["medium"])["default_mh"]
    merged["default_mh"] = max(_as_float(merged.get("default_mh"), preset_mh), 0.1)

    lookup = merged.get("lookup") or []
    if not isinstance(lookup, list):
        lookup = []
    clean_lookup = []
    for item in lookup:
        if not isinstance(item, dict):
            continue
        clean_lookup.append({
            "complexity": str(item.get("complexity") or "").strip(),
            "fit_gap": str(item.get("fit_gap") or item.get("fit/gap") or "").strip(),
            "ba_md": max(_as_float(item.get("ba_md"), 0.0), 0.0),
            "dev_md": max(_as_float(item.get("dev_md"), 0.0), 0.0),
        })
    merged["lookup"] = clean_lookup

    pk = merged.get("phase_keywords") or {}
    if not isinstance(pk, dict) or not pk:
        merged["phase_keywords"] = copy.deepcopy(DEFAULT_PARAMS["phase_keywords"])
    else:
        # Đảm bảo mọi bucket có list pattern
        fixed = copy.deepcopy(DEFAULT_PARAMS["phase_keywords"])
        for bucket, patterns in pk.items():
            b = str(bucket).strip().lower()
            if b not in BUCKET_ORDER and b != "other":
                continue
            if isinstance(patterns, list) and patterns:
                fixed[b] = [str(p) for p in patterns if str(p).strip()]
        merged["phase_keywords"] = fixed

    if not str(merged.get("label") or "").strip():
        merged["label"] = DEFAULT_PARAMS["label"]
    merged["version"] = int(merged.get("version") or 1)
    return merged


def params_path_project(project_dir: str) -> str:
    return os.path.join(project_dir, PARAMS_FILENAME)


def params_path_global(projects_folder: str) -> str:
    """Global file nằm cạnh thư mục projects (parent của projects_folder)."""
    parent = os.path.dirname(os.path.abspath(projects_folder))
    return os.path.join(parent, PARAMS_FILENAME)


def load_estimation_params(
    project_dir: str,
    projects_folder: Optional[str] = None,
) -> dict[str, Any]:
    """
    Load params: project override → global → DEFAULT_PARAMS.
    Trả về dict đã normalize + metadata nguồn.
    """
    merged = copy.deepcopy(DEFAULT_PARAMS)
    source = "builtin"
    gpath = params_path_global(projects_folder) if projects_folder else None
    if gpath and os.path.isfile(gpath):
        try:
            with open(gpath, "r", encoding="utf-8") as f:
                raw = json.load(f)
            if isinstance(raw, dict):
                merged = _deep_merge(merged, raw)
                source = "global"
        except (OSError, ValueError, json.JSONDecodeError):
            pass
    ppath = params_path_project(project_dir) if project_dir else ""
    if ppath and os.path.isfile(ppath):
        try:
            with open(ppath, "r", encoding="utf-8") as f:
                raw = json.load(f)
            if isinstance(raw, dict):
                merged = _deep_merge(merged, raw)
                source = "project"
        except (OSError, ValueError, json.JSONDecodeError):
            pass
    params = normalize_params(merged)
    params["_source"] = source
    params["_paths"] = {
        "project": ppath or None,
        "global": gpath,
    }
    return params


def save_estimation_params(
    project_dir: str,
    payload: dict[str, Any],
    *,
    scope: str = "project",
    projects_folder: Optional[str] = None,
) -> dict[str, Any]:
    """
    Lưu params. scope=project|global.
    Ghi file đã normalize (bỏ key nội bộ _source/_paths).
    """
    current = load_estimation_params(project_dir, projects_folder)
    # Strip internals before merge
    for k in ("_source", "_paths"):
        current.pop(k, None)
        if isinstance(payload, dict):
            payload = {**payload}
            payload.pop(k, None)
    merged = normalize_params(_deep_merge(current, payload if isinstance(payload, dict) else {}))
    to_save = {k: v for k, v in merged.items() if not k.startswith("_")}

    if scope == "global":
        if not projects_folder:
            raise ValueError("projects_folder required for global scope")
        path = params_path_global(projects_folder)
    else:
        path = params_path_project(project_dir)
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(to_save, f, ensure_ascii=False, indent=2)
    saved = load_estimation_params(project_dir, projects_folder)
    return saved


def _compile_keywords(phase_keywords: dict[str, list[str]]) -> list[tuple[str, re.Pattern]]:
    """Danh sách (bucket, pattern) — thứ tự ưu tiên theo BUCKET_ORDER."""
    compiled: list[tuple[str, re.Pattern]] = []
    for bucket in BUCKET_ORDER:
        for pat in phase_keywords.get(bucket) or []:
            try:
                compiled.append((bucket, re.compile(pat, re.IGNORECASE)))
            except re.error:
                continue
    return compiled


def map_phase_bucket(
    phase_name: str,
    task_type: str,
    compiled: list[tuple[str, re.Pattern]],
) -> str:
    """Map tên phase / task_type → bucket bằng keyword."""
    texts = [phase_name or "", task_type or ""]
    for bucket, rx in compiled:
        for t in texts:
            if t and rx.search(t):
                return bucket
    return "other"


def _task_type(data: ParsedData, phase_name: str) -> str:
    for pg in data.phase_groups:
        if pg.name == phase_name:
            return pg.task_type or phase_name
    return phase_name


def _mh_to_md(mh: float, mh_per_day: float) -> float:
    return float(mh) / mh_per_day if mh_per_day else 0.0


def _md_to_mh(md: float, mh_per_day: float) -> float:
    return float(md) * mh_per_day


def _md_to_mm(md: float, md_per_mm: float) -> float:
    return float(md) / md_per_mm if md_per_mm else 0.0


def _norm_key(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip().lower())


def _lookup_seed(
    complexity: str,
    fit_gap: str,
    lookup: list[dict[str, Any]],
) -> Optional[tuple[float, float]]:
    """Khớp Complexity × FIT/GAP (không phân biệt hoa thường; trống = wildcard)."""
    c = _norm_key(complexity)
    f = _norm_key(fit_gap)
    for item in lookup:
        ic = _norm_key(str(item.get("complexity") or ""))
        iff = _norm_key(str(item.get("fit_gap") or ""))
        if ic and ic != c:
            continue
        if iff and iff != f:
            continue
        if not ic and not iff:
            continue
        return float(item["ba_md"]), float(item["dev_md"])
    return None


def _phase_estimate_md(pd: PhaseData, mh_per_day: float) -> Optional[float]:
    if pd.estimate_mh is not None and pd.estimate_mh > 0:
        return _mh_to_md(float(pd.estimate_mh), mh_per_day)
    return None


def _seed_ba_dev_for_row(
    row: FunctionRow,
    phase_buckets: dict[str, str],
    params: dict[str, Any],
) -> dict[str, Any]:
    """
    Seed BA/Dev MD cho 1 function.
    Returns dict với ba_md, dev_md, ba_source, dev_source, used_default_seed.
    """
    mh_per_day = float(params["mh_per_day"])
    ba_from_fl = 0.0
    dev_from_fl = 0.0
    ba_fl_hit = False
    dev_fl_hit = False

    for phase_name, pd in row.phases.items():
        bucket = phase_buckets.get(phase_name, "other")
        md = _phase_estimate_md(pd, mh_per_day)
        if md is None:
            continue
        if bucket == "ba":
            ba_from_fl += md
            ba_fl_hit = True
        elif bucket == "dev":
            dev_from_fl += md
            dev_fl_hit = True

    ba_source = "fl_estimate" if ba_fl_hit else ""
    dev_source = "fl_estimate" if dev_fl_hit else ""
    ba_md = ba_from_fl if ba_fl_hit else None
    dev_md = dev_from_fl if dev_fl_hit else None

    if ba_md is None or dev_md is None:
        hit = _lookup_seed(
            str(row.meta.get("complexity") or ""),
            str(row.meta.get("fit_gap") or ""),
            params.get("lookup") or [],
        )
        if hit:
            if ba_md is None:
                ba_md = hit[0]
                ba_source = "lookup"
            if dev_md is None:
                dev_md = hit[1]
                dev_source = "lookup"

    sd = params["seed_defaults"]
    used_default = False
    if ba_md is None:
        ba_md = float(sd["ba_md"])
        ba_source = "default"
        used_default = True
    if dev_md is None:
        dev_md = float(sd["dev_md"])
        dev_source = "default"
        used_default = True

    return {
        "ba_md": float(ba_md),
        "dev_md": float(dev_md),
        "ba_source": ba_source,
        "dev_source": dev_source,
        "used_default_seed": used_default,
    }


def _fl_bucket_md(
    row: FunctionRow,
    phase_buckets: dict[str, str],
    bucket: str,
    mh_per_day: float,
) -> Optional[float]:
    total = 0.0
    hit = False
    for phase_name, pd in row.phases.items():
        if phase_buckets.get(phase_name) != bucket:
            continue
        md = _phase_estimate_md(pd, mh_per_day)
        if md is not None:
            total += md
            hit = True
    return total if hit else None


def estimate_function_md(
    row: FunctionRow,
    phase_buckets: dict[str, str],
    params: dict[str, Any],
) -> dict[str, Any]:
    """Tính MD theo bucket cho 1 function (chưa gồm overhead dự án)."""
    ratios = params["ratios"]
    mh_per_day = float(params["mh_per_day"])
    seed = _seed_ba_dev_for_row(row, phase_buckets, params)
    ba_md = seed["ba_md"]
    dev_md = seed["dev_md"]

    buckets: dict[str, float] = {
        "ba": ba_md,
        "des": ba_md * float(ratios["des_of_ba"]),
        "dev": dev_md,
        "test": dev_md * float(ratios["test_of_dev"]),
        "doc": dev_md * float(ratios["doc_of_dev"]),
    }

    notes: list[str] = []
    cfg_fl = _fl_bucket_md(row, phase_buckets, "config", mh_per_day)
    if cfg_fl is not None:
        buckets["config"] = cfg_fl
        notes.append("config từ Estimate MH trên FL")
    else:
        buckets["config"] = dev_md * float(ratios["config_of_dev"])

    mig_fl = _fl_bucket_md(row, phase_buckets, "migration", mh_per_day)
    if mig_fl is not None:
        buckets["migration"] = mig_fl
        notes.append("migration từ Estimate MH trên FL")
    else:
        buckets["migration"] = dev_md * float(ratios["migration_of_dev"])

    # other FL estimates (không map) — cộng riêng để không mất effort
    other_md = 0.0
    for phase_name, pd in row.phases.items():
        if phase_buckets.get(phase_name) != "other":
            continue
        md = _phase_estimate_md(pd, mh_per_day)
        if md is not None:
            other_md += md
    if other_md > 0:
        buckets["other"] = other_md

    build_keys = ("ba", "des", "dev", "test", "config", "migration", "doc", "other")
    build_md = sum(buckets.get(k, 0.0) for k in build_keys)

    return {
        "ma_cn": row.meta.get("ma_cn") or "",
        "ten_cn": row.meta.get("ten_cn") or "",
        "module": row.meta.get("module") or "",
        "complexity": row.meta.get("complexity") or "",
        "fit_gap": row.meta.get("fit_gap") or "",
        "ba_source": seed["ba_source"],
        "dev_source": seed["dev_source"],
        "used_default_seed": seed["used_default_seed"],
        "buckets_md": {k: round(v, 4) for k, v in buckets.items() if v},
        "build_md": round(build_md, 4),
        "notes": notes,
    }


def _compute_estimate_ratio_core(
    data: ParsedData,
    params: dict[str, Any],
) -> dict[str, Any]:
    """Core tính toán (không calibrate contract) — dùng nội bộ."""
    compiled = _compile_keywords(params["phase_keywords"])
    phase_buckets: dict[str, str] = {}
    phase_mapping: list[dict[str, str]] = []
    for phase_name in data.all_phases or [pg.name for pg in data.phase_groups]:
        tt = _task_type(data, phase_name)
        bucket = map_phase_bucket(phase_name, tt, compiled)
        phase_buckets[phase_name] = bucket
        phase_mapping.append({
            "phase": phase_name,
            "task_type": tt,
            "bucket": bucket,
            "label": BUCKET_LABELS_VI.get(bucket, bucket),
        })

    details: list[dict[str, Any]] = []
    sum_buckets: dict[str, float] = defaultdict(float)
    n_default = 0
    n_funcs = 0

    for row in data.rows:
        n_funcs += 1
        est = estimate_function_md(row, phase_buckets, params)
        if est["used_default_seed"]:
            n_default += 1
        for k, v in est["buckets_md"].items():
            sum_buckets[k] += v
        details.append(est)

    ratios = params["ratios"]
    oh = params["overhead"]
    build_keys = ("ba", "des", "dev", "test", "config", "migration", "doc", "other")
    build_md = sum(sum_buckets.get(k, 0.0) for k in build_keys)

    # UAT = r/(1-r) * (build excl pentest) — theo công thức «% của tổng gồm UAT»
    if oh.get("include_uat") and build_md > 0:
        r = float(ratios["uat_of_total_incl_uat"])
        uat_md = (r / (1.0 - r)) * build_md if r < 1.0 else 0.0
        sum_buckets["uat"] = uat_md
    else:
        uat_md = 0.0

    if oh.get("include_golive") and uat_md > 0:
        sum_buckets["golive"] = uat_md * float(ratios["golive_of_uat"])

    pentest_md = float(oh.get("pentest_md") or 0.0) if oh.get("include_pentest") else 0.0
    if pentest_md > 0:
        sum_buckets["pentest"] = pentest_md

    build_plus_pentest = build_md + pentest_md
    if oh.get("include_warranty") and build_plus_pentest > 0:
        sum_buckets["warranty"] = build_plus_pentest * float(ratios["warranty_of_build"])

    subtotal_for_pm = (
        build_md
        + sum_buckets.get("uat", 0.0)
        + sum_buckets.get("golive", 0.0)
        + pentest_md
    )
    if oh.get("include_pm") and subtotal_for_pm > 0:
        sum_buckets["pm"] = subtotal_for_pm * float(ratios["pm_of_subtotal"])

    mh_per_day = float(params["mh_per_day"])
    md_per_mm = float(params["md_per_mm"])
    total_md = sum(sum_buckets.values())
    total_mh = _md_to_mh(total_md, mh_per_day)
    total_mm = _md_to_mm(total_md, md_per_mm)

    by_phase: list[dict[str, Any]] = []
    for bucket in BUCKET_ORDER:
        md = float(sum_buckets.get(bucket, 0.0))
        if md <= 0 and bucket == "other":
            continue
        if md <= 0 and bucket not in sum_buckets:
            continue
        by_phase.append({
            "bucket": bucket,
            "label": BUCKET_LABELS_VI.get(bucket, bucket),
            "md": round(md, 4),
            "mh": round(_md_to_mh(md, mh_per_day), 2),
            "mm": round(_md_to_mm(md, md_per_mm), 4),
            "is_overhead": bucket in ("uat", "golive", "pm", "warranty", "pentest"),
        })

    _bucket_to_task_type = {
        "ba": "Phân tích",
        "des": "Phân tích",
        "dev": "Lập trình",
        "test": "Kiểm thử",
        "config": "Cấu hình UAT",
        "doc": "Tài liệu",
        "uat": "UAT",
        "golive": "Cấu hình Golive",
        "migration": "Kiểm thử",
    }
    forecast_feed: dict[str, float] = defaultdict(float)
    for bucket, md in sum_buckets.items():
        if bucket in ("pm", "warranty", "pentest", "other"):
            continue
        if bucket == "des":
            forecast_feed["Thiết kế"] += _md_to_mh(md, mh_per_day)
            continue
        tt = _bucket_to_task_type.get(bucket)
        if tt:
            forecast_feed[tt] += _md_to_mh(md, mh_per_day)

    pct_default = round(100.0 * n_default / n_funcs, 1) if n_funcs else 0.0

    return {
        "phase_buckets": phase_buckets,
        "phase_mapping": phase_mapping,
        "details": details,
        "sum_buckets": dict(sum_buckets),
        "n_default": n_default,
        "n_funcs": n_funcs,
        "build_md": build_md,
        "total_md": total_md,
        "total_mh": total_mh,
        "total_mm": total_mm,
        "by_phase": by_phase,
        "forecast_feed": dict(forecast_feed),
        "pct_default": pct_default,
        "mh_per_day": mh_per_day,
        "md_per_mm": md_per_mm,
    }


def compute_estimate_ratio(
    data: ParsedData,
    params: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """
    Tính ước lượng theo hệ số cho toàn bộ ParsedData.

    Returns JSON-serializable dict: params, phase_mapping, by_phase (MM/MH/MD),
    totals, detail (per function), warnings, forecast_feed (MH theo task_type gợi ý).

    Nếu ``contract_md`` / ``contract_mm`` > 0: scale seed (+ lookup) rồi tính lại
    để tổng gần khớp hợp đồng (calibrate).
    """
    params = normalize_params(params)
    params = {k: v for k, v in params.items() if not k.startswith("_")}
    params = normalize_params(params)

    contract_md = resolve_contract_md(params)
    calibration: Optional[dict[str, Any]] = None

    # Tính với seed hiện tại (idempotent khi kèm contract)
    core = _compute_estimate_ratio_core(data, params)
    pre_contract_md = float(core["total_md"])

    if contract_md and pre_contract_md > 0:
        factor = float(contract_md) / pre_contract_md
        suggested_params, _ = scale_seeds_to_contract(params, pre_contract_md, contract_md)
        # Scale toàn bộ output để tổng = hợp đồng (ổn định khi tính lại)
        for k in list(core["sum_buckets"].keys()):
            core["sum_buckets"][k] *= factor
        core["build_md"] *= factor
        core["total_md"] = sum(core["sum_buckets"].values())
        core["total_mh"] = _md_to_mh(core["total_md"], core["mh_per_day"])
        core["total_mm"] = _md_to_mm(core["total_md"], core["md_per_mm"])
        core["by_phase"] = []
        for bucket in BUCKET_ORDER:
            md = float(core["sum_buckets"].get(bucket, 0.0))
            if md <= 0 and bucket == "other":
                continue
            if md <= 0 and bucket not in core["sum_buckets"]:
                continue
            core["by_phase"].append({
                "bucket": bucket,
                "label": BUCKET_LABELS_VI.get(bucket, bucket),
                "md": round(md, 4),
                "mh": round(_md_to_mh(md, core["mh_per_day"]), 2),
                "mm": round(_md_to_mm(md, core["md_per_mm"]), 4),
                "is_overhead": bucket in ("uat", "golive", "pm", "warranty", "pentest"),
            })
        feed2: dict[str, float] = defaultdict(float)
        _b2tt = {
            "ba": "Phân tích", "des": "Thiết kế", "dev": "Lập trình",
            "test": "Kiểm thử", "config": "Cấu hình UAT", "doc": "Tài liệu",
            "uat": "UAT", "golive": "Cấu hình Golive", "migration": "Kiểm thử",
        }
        for bucket, md in core["sum_buckets"].items():
            if bucket in ("pm", "warranty", "pentest", "other"):
                continue
            tt = _b2tt.get(bucket)
            if tt:
                feed2[tt] += _md_to_mh(md, core["mh_per_day"])
        core["forecast_feed"] = dict(feed2)
        for d in core["details"]:
            d["buckets_md"] = {
                k: round(v * factor, 4)
                for k, v in (d.get("buckets_md") or {}).items()
            }
            d["build_md"] = round(float(d.get("build_md") or 0) * factor, 4)

        sd_sug = suggested_params.get("seed_defaults") or {}
        calibration = {
            "contract_md": round(contract_md, 4),
            "pre_md": round(pre_contract_md, 4),
            "seed_factor": round(factor, 6),
            "global_factor": round(factor, 6),
            "post_md": round(float(core["total_md"]), 4),
            "matched": True,
            "suggested_seed_defaults": {
                "ba_md": round(float(sd_sug.get("ba_md") or 0), 6),
                "dev_md": round(float(sd_sug.get("dev_md") or 0), 6),
            },
        }

    phase_buckets = core["phase_buckets"]
    n_default = core["n_default"]
    n_funcs = core["n_funcs"]
    pct_default = core["pct_default"]
    mh_per_day = core["mh_per_day"]
    md_per_mm = core["md_per_mm"]
    build_md = core["build_md"]
    total_md = core["total_md"]
    total_mh = core["total_mh"]
    total_mm = core["total_mm"]

    seed_ref_only = pct_default > 50.0
    warnings: list[str] = []
    if seed_ref_only:
        warnings.append(
            f"Kết quả tham khảo — {pct_default}% function chưa có estimate thật "
            f"({n_default}/{n_funcs} dùng seed mặc định)."
        )
    elif n_default:
        warnings.append(
            f"{n_default}/{n_funcs} function ({pct_default}%) dùng seed BA/Dev mặc định "
            f"(không có Estimate MH phase BA/Dev và không khớp lookup)."
        )
    if calibration and calibration.get("seed_factor") and calibration["seed_factor"] != 1.0:
        warnings.append(
            f"Đã calibrate theo hợp đồng {calibration['contract_md']:g} MD "
            f"(hệ số seed ×{calibration['seed_factor']:g}"
            + (
                f", scale output ×{calibration['global_factor']:g}"
                if calibration.get("global_factor", 1.0) != 1.0
                else ""
            )
            + ")."
        )
    if not any(pb == "ba" for pb in phase_buckets.values()):
        warnings.append(
            "Không map được phase nào → BA. Kiểm tra tên phase hoặc phase_keywords trong params."
        )
    if not any(pb == "dev" for pb in phase_buckets.values()):
        warnings.append(
            "Không map được phase nào → Dev. Kiểm tra tên phase hoặc phase_keywords trong params."
        )

    size_info = SIZE_PRESETS.get(
        str(params.get("project_size") or "medium"), SIZE_PRESETS["medium"]
    )
    hints = [
        "Ước lượng theo hệ số — không ghi đè Estimate MH trên Function List.",
        "Không thay Forecast Manpower; có thể sao chép MH gợi ý để đối chiếu / nhập tay.",
        f"Quy mô: {size_info['label']} — {size_info['hint']}.",
        f"1 MD = {mh_per_day:g} MH · 1 MM = {md_per_mm:g} MD "
        f"(khác MM=160 MH của Forecast Manpower nếu md_per_mm≠20).",
        "Nhập tổng MD/MM hợp đồng để scale seed khớp effort ký kết.",
        "Defaults là gợi ý PMO (chỉnh trong estimation_params.json) — không khóa số liệu dự án mẫu.",
    ]

    # Strip internals trước khi trả
    params_out = {k: v for k, v in params.items() if not k.startswith("_")}

    return {
        "basis": "ratio",
        "basis_label": "Ước lượng theo hệ số",
        "params": params_out,
        "size_presets": {
            k: {
                "id": v["id"],
                "label": v["label"],
                "hint": v["hint"],
                "seed_defaults": v["seed_defaults"],
                "default_mh": v["default_mh"],
            }
            for k, v in SIZE_PRESETS.items()
        },
        "phase_mapping": core["phase_mapping"],
        "by_phase": core["by_phase"],
        "totals": {
            "functions": n_funcs,
            "functions_default_seed": n_default,
            "pct_default_seed": pct_default,
            "seed_reference_only": seed_ref_only,
            "build_md": round(build_md, 4),
            "md": round(total_md, 4),
            "mh": round(total_mh, 2),
            "mm": round(total_mm, 4),
            "mh_per_day": mh_per_day,
            "md_per_mm": md_per_mm,
            "contract_md": round(contract_md, 4) if contract_md else None,
        },
        "calibration": calibration,
        "detail": core["details"],
        "forecast_feed": {k: round(v, 2) for k, v in sorted(core["forecast_feed"].items())},
        "warnings": warnings,
        "hints": hints,
    }
