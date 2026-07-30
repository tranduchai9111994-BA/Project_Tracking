"""
Thứ tự Module dùng chung toàn dashboard.

Schema file `uploads/projects/<slug>/module_order.json`:
  {"order": ["TMS", "HR", "PR", ...]}

Cũng chấp nhận (load):
  - list thuần: ["TMS", "HR", ...]
  - rank map: {"TMS": 1, "HR": 2, ...}

Default khi chưa config: alphabetical (giữ behavior cũ của parser).
Module mới (có trong data nhưng chưa trong config) → append cuối, alpha.
"""
from __future__ import annotations

from typing import Any, Iterable, Optional, Sequence


def normalize_order(raw: Any) -> list[str]:
    """Chuẩn hoá mọi shape lưu trữ → list tên module (unique, giữ thứ tự)."""
    if raw is None:
        return []
    if isinstance(raw, list):
        out: list[str] = []
        seen: set[str] = set()
        for x in raw:
            name = str(x).strip()
            if name and name not in seen:
                seen.add(name)
                out.append(name)
        return out
    if isinstance(raw, dict):
        # {"order": [...]}
        if "order" in raw and isinstance(raw["order"], list):
            return normalize_order(raw["order"])
        # {"TMS": 1, "HR": 2} — rank thấp hơn = ưu tiên hơn
        items: list[tuple[int, str]] = []
        for k, v in raw.items():
            name = str(k).strip()
            if not name:
                continue
            try:
                rank = int(v)
            except (TypeError, ValueError):
                rank = 10_000
            items.append((rank, name))
        items.sort(key=lambda t: (t[0], t[1]))
        return [n for _, n in items]
    return []


def module_sort_key(name: str, order: Optional[Sequence[str]] = None) -> tuple:
    """
    Key sort cho 1 module name.
    - Có trong order → (0, index)
    - Không có / order rỗng → (1, name)  # alphabetical fallback
    """
    n = str(name or "")
    if order:
        try:
            return (0, list(order).index(n))
        except ValueError:
            pass
    return (1, n)


def sort_modules(
    modules: Iterable[str],
    order: Optional[Sequence[str]] = None,
) -> list[str]:
    """
    Sắp xếp danh sách module theo `order` đã cấu hình.

    1. Các module có trong `order` — theo đúng thứ tự config
    2. Module còn lại — alphabetical
    3. Nếu `order` rỗng/None → alphabetical toàn bộ (default cũ)
    """
    present = []
    seen: set[str] = set()
    for m in modules:
        name = str(m or "").strip()
        if name and name not in seen:
            seen.add(name)
            present.append(name)

    if not order:
        return sorted(present)

    preferred = [m for m in order if m in seen]
    preferred_set = set(preferred)
    extras = sorted(m for m in present if m not in preferred_set)
    return preferred + extras


def apply_module_order(all_modules: list[str], order: Optional[Sequence[str]]) -> list[str]:
    """Alias rõ nghĩa cho call-site parse/filter."""
    return sort_modules(all_modules, order)


def process_module_rank(
    modules: Sequence[str],
    order: Optional[Sequence[str]] = None,
) -> tuple:
    """
    Rank của 1 quy trình theo module đại diện (module đầu theo order).
    Dùng để sort process tiles / process rows theo module rồi process name.
    """
    if not modules:
        return (1, "")
    best = min(modules, key=lambda m: module_sort_key(m, order))
    return module_sort_key(best, order)
