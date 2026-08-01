"""
Xuất Excel các phân tích PMO/BA bổ sung — Tong_hop + Chi_tiet khi phù hợp.

Bao gồm: Baseline SV, EVM, Scope Creep, UAT Quality, Completion Forecast,
PIC upcoming, Estimate Ratio.
"""
from __future__ import annotations

import os
from datetime import date
from typing import Any

from exporter.excel_exporter import (
    GREEN_FILL,
    ORANGE_FILL,
    RED_FILL,
    _SheetBook,
    _normalize_export_mode,
    _want_detail,
    _want_summary,
    _write_sheet,
)
from exporter.reason_formatters import (
    process_code,
    reason_scope_creep,
    reason_uat_warning,
)


def _subtitle(extra: str = "") -> str:
    base = f"Ngày xuất: {date.today().strftime('%d/%m/%Y')}"
    return f"{base}  |  {extra}" if extra else base


def _save(wb, output_dir: str, prefix: str) -> str:
    os.makedirs(output_dir, exist_ok=True)
    from datetime import datetime
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = os.path.join(output_dir, f"{prefix}_{stamp}.xlsx")
    wb.save(path)
    return path


def export_baseline_sv_report(
    payload: dict[str, Any],
    output_dir: str = "uploads",
    *,
    mode: str = "both",
) -> str:
    """Xuất Schedule Variance vs snapshot baseline."""
    mode = _normalize_export_mode(mode)
    book = _SheetBook()
    sm = payload.get("summary") or {}
    snap = payload.get("baseline_snapshot_id") or ""
    sub = _subtitle(
        f"Baseline: {snap}  |  So sánh: {sm.get('compared', 0)}  |  "
        f"Trễ: {sm.get('late_count', 0)}  |  Sớm: {sm.get('early_count', 0)}  |  "
        f"Avg SV: {sm.get('avg_sv_days', 0)}d"
    )

    if _want_summary(mode):
        # Milestone
        ms_rows = []
        for m in (payload.get("milestones") or {}).values():
            sv = m.get("sv_days")
            ms_rows.append([
                m.get("label") or m.get("id") or "",
                (m.get("baseline") or {}).get("month") or "",
                (m.get("baseline") or {}).get("date") or "",
                (m.get("current") or {}).get("month") or "",
                (m.get("current") or {}).get("date") or "",
                sv if sv is not None else "",
                "Trễ" if m.get("late") else ("Sớm" if m.get("early") else "OK"),
            ])
        _write_sheet(
            book.sheet("Milestone"),
            "Baseline SV — Milestone",
            [
                ("Milestone", 22),
                ("Baseline tháng", 14),
                ("Baseline ngày", 14),
                ("Hiện tại tháng", 14),
                ("Hiện tại ngày", 14),
                ("SV (ngày)", 12),
                ("Đánh giá", 10),
            ],
            ms_rows,
            subtitle=sub,
            row_fill_fn=lambda _r, i: (
                RED_FILL if (ms_rows[i][5] not in ("", None) and ms_rows[i][5] > 0)
                else GREEN_FILL if (ms_rows[i][5] not in ("", None) and ms_rows[i][5] < 0)
                else None
            ),
        )
        # Module
        mod_rows = [
            [
                m.get("module"),
                m.get("compared"),
                m.get("late_count"),
                m.get("early_count"),
                m.get("avg_sv_days"),
            ]
            for m in (payload.get("modules") or [])
        ]
        _write_sheet(
            book.sheet("Theo_module"),
            "Baseline SV — Theo module",
            [
                ("Module", 28),
                ("So sánh", 12),
                ("Trễ", 10),
                ("Sớm", 10),
                ("Avg SV (ngày)", 14),
            ],
            mod_rows,
            subtitle=sub,
            row_fill_fn=lambda _r, i: (
                RED_FILL if (mod_rows[i][4] or 0) > 0
                else GREEN_FILL if (mod_rows[i][4] or 0) < 0
                else None
            ),
        )

    if _want_detail(mode):
        fn_rows = []
        for it in payload.get("functions") or []:
            fn_rows.append([
                it.get("ma_cn"),
                it.get("ten_cn"),
                it.get("module"),
                process_code(it),
                it.get("phase"),
                it.get("baseline_end"),
                it.get("current_end"),
                it.get("sv_days"),
                "Trễ" if it.get("late") else ("Sớm" if it.get("early") else "OK"),
                it.get("status") or "",
            ])
        _write_sheet(
            book.sheet("Chi_tiet"),
            "Baseline SV — Function × Phase",
            [
                ("Mã CN", 16),
                ("Tên chức năng", 36),
                ("Module", 18),
                ("Quy trình", 22),
                ("Phase", 18),
                ("End baseline", 14),
                ("End hiện tại", 14),
                ("SV (ngày)", 12),
                ("Đánh giá", 10),
                ("Status", 14),
            ],
            fn_rows,
            subtitle=sub + f"  |  Tổng dòng: {payload.get('functions_total', len(fn_rows))}",
            row_fill_fn=lambda _r, i: (
                RED_FILL if fn_rows[i][8] == "Trễ"
                else GREEN_FILL if fn_rows[i][8] == "Sớm"
                else None
            ),
        )

    return _save(book.wb, output_dir, "Baseline_SV")


def export_earned_value_report(
    payload: dict[str, Any],
    output_dir: str = "uploads",
    *,
    mode: str = "both",
) -> str:
    mode = _normalize_export_mode(mode)
    book = _SheetBook()
    sm = payload.get("summary") or {}
    sub = _subtitle(
        f"Baseline: {payload.get('baseline_snapshot_id') or 'N/A'}  |  "
        f"SPI: {sm.get('spi') if sm.get('spi') is not None else 'N/A'}  |  "
        f"CPI: {sm.get('cpi') if sm.get('cpi') is not None else 'N/A'}"
    )

    if _want_summary(mode):
        sum_rows = [
            ["BAC (MH)", sm.get("bac")],
            ["EV (MH)", sm.get("ev")],
            ["PV (MH)", sm.get("pv") if sm.get("pv") is not None else "N/A"],
            ["AC (MH proxy)", sm.get("ac")],
            ["SPI", sm.get("spi") if sm.get("spi") is not None else "N/A"],
            ["SPI label", sm.get("spi_label") or ""],
            ["CPI", sm.get("cpi") if sm.get("cpi") is not None else "N/A"],
            ["CPI label", sm.get("cpi_label") or ""],
            ["EV % BAC", sm.get("ev_pct_bac")],
            ["PV % BAC", sm.get("pv_pct_bac")],
            ["Phases counted", sm.get("phases_counted")],
            ["Phases default MH", sm.get("phases_default_mh")],
        ]
        _write_sheet(
            book.sheet("Tong_hop"),
            "Earned Value — Tổng hợp",
            [("Chỉ số", 28), ("Giá trị", 18)],
            sum_rows,
            subtitle=sub,
        )
        mod_rows = [
            [
                m.get("module"),
                m.get("bac"),
                m.get("ev"),
                m.get("pv") if m.get("pv") is not None else "N/A",
                m.get("ac"),
                m.get("spi") if m.get("spi") is not None else "N/A",
                m.get("cpi") if m.get("cpi") is not None else "N/A",
            ]
            for m in (payload.get("modules") or [])
        ]
        _write_sheet(
            book.sheet("Theo_module"),
            "Earned Value — Theo module",
            [
                ("Module", 28),
                ("BAC", 12),
                ("EV", 12),
                ("PV", 12),
                ("AC", 12),
                ("SPI", 10),
                ("CPI", 10),
            ],
            mod_rows,
            subtitle=sub,
            row_fill_fn=lambda _r, i: (
                RED_FILL if (
                    isinstance(mod_rows[i][5], (int, float)) and mod_rows[i][5] < 0.9
                ) or (
                    isinstance(mod_rows[i][6], (int, float)) and mod_rows[i][6] < 0.9
                )
                else ORANGE_FILL if (
                    isinstance(mod_rows[i][5], (int, float)) and mod_rows[i][5] < 1
                ) or (
                    isinstance(mod_rows[i][6], (int, float)) and mod_rows[i][6] < 1
                )
                else GREEN_FILL if (
                    isinstance(mod_rows[i][5], (int, float)) and mod_rows[i][5] >= 1
                ) and (
                    isinstance(mod_rows[i][6], (int, float)) and mod_rows[i][6] >= 1
                )
                else None
            ),
        )

    if _want_detail(mode):
        assum = [[a] for a in (payload.get("assumptions") or [])]
        msgs = [[m] for m in (payload.get("messages") or [])]
        detail_rows = assum + ([[""]] if assum and msgs else []) + msgs
        if not detail_rows:
            detail_rows = [["(không có ghi chú)"]]
        _write_sheet(
            book.sheet("Ghi_chu"),
            "Earned Value — Giả định & cảnh báo",
            [("Nội dung", 90)],
            detail_rows,
            subtitle=sub,
        )

    return _save(book.wb, output_dir, "Earned_Value")


def export_scope_creep_report(
    payload: dict[str, Any],
    output_dir: str = "uploads",
    *,
    mode: str = "both",
) -> str:
    mode = _normalize_export_mode(mode)
    book = _SheetBook()
    sm = payload.get("summary") or {}
    det = payload.get("detection") or {}
    sub = _subtitle(
        f"Nguồn: {det.get('mode') or '—'}  |  "
        f"CR: {sm.get('cr_count', 0)}/{sm.get('total_functions', 0)}  |  "
        f"Creep: {sm.get('creep_rate_pct')}%"
    )

    if _want_summary(mode):
        sum_rows = [
            ["Tổng function", sm.get("total_functions")],
            ["CR (phát sinh)", sm.get("cr_count")],
            ["Scope gốc", sm.get("original_count")],
            ["Scope creep %", sm.get("creep_rate_pct")],
            ["MH CR", sm.get("mh_cr")],
            ["MH gốc", sm.get("mh_original")],
            ["MH tổng", sm.get("mh_total")],
            ["MH CR %", sm.get("mh_cr_pct")],
            ["Cột CR", det.get("column_header") or ""],
        ]
        _write_sheet(
            book.sheet("Tong_hop"),
            "Scope Creep — Tổng hợp",
            [("Chỉ số", 28), ("Giá trị", 18)],
            sum_rows,
            subtitle=sub,
        )
        mod_rows = [
            [
                m.get("module"),
                m.get("total"),
                m.get("cr"),
                m.get("creep_rate_pct"),
                m.get("mh_cr"),
                m.get("mh_original"),
            ]
            for m in (payload.get("modules") or [])
        ]
        _write_sheet(
            book.sheet("Theo_module"),
            "Scope Creep — Theo module",
            [
                ("Module", 28),
                ("Tổng", 10),
                ("CR", 10),
                ("Creep %", 12),
                ("MH CR", 12),
                ("MH gốc", 12),
            ],
            mod_rows,
            subtitle=sub,
            row_fill_fn=lambda _r, i: (
                RED_FILL if (mod_rows[i][3] or 0) >= 15
                else ORANGE_FILL if (mod_rows[i][3] or 0) >= 8
                else None
            ),
        )

    if _want_detail(mode):
        cr_header = (payload.get("detection") or {}).get("column_header") or ""
        cr_rows = [
            [
                it.get("ma_cn"),
                it.get("ten_cn"),
                it.get("module"),
                process_code(it),
                it.get("mh"),
                it.get("cr_raised_date") or "",
                it.get("source") or "",
                "" if it.get("raw_cr") is None else str(it.get("raw_cr")),
                reason_scope_creep(it, column_header=cr_header),
            ]
            for it in (payload.get("cr_functions") or [])
        ]
        _write_sheet(
            book.sheet("Chi_tiet_CR"),
            "Scope Creep — Danh sách CR",
            [
                ("Mã CN", 16),
                ("Tên chức năng", 36),
                ("Module", 18),
                ("Quy trình", 22),
                ("MH", 10),
                ("Ngày phát sinh", 14),
                ("Nguồn", 16),
                ("Giá trị CR gốc", 16),
                ("Lý do phát hiện", 40),
            ],
            cr_rows,
            subtitle=sub,
        )

    return _save(book.wb, output_dir, "Scope_Creep")


def export_uat_quality_report(
    payload: dict[str, Any],
    output_dir: str = "uploads",
    *,
    mode: str = "both",
) -> str:
    mode = _normalize_export_mode(mode)
    book = _SheetBook()
    sm = payload.get("summary") or {}
    det = payload.get("detection") or {}
    sub = _subtitle(
        f"Nguồn: {det.get('mode') or '—'}  |  "
        f"Defect: {sm.get('total_defects')}  |  "
        f"Reopen: {sm.get('reopen_rate_pct')}%"
    )

    if _want_summary(mode):
        sum_rows = [
            ["Tổng defect", sm.get("total_defects")],
            ["Tổng feedback", sm.get("total_feedback")],
            ["Fn có defect", sm.get("fns_with_defects")],
            ["Reopen rate %", sm.get("reopen_rate_pct")],
            ["Tổng reopen", sm.get("total_reopens")],
            ["TB vòng UAT", sm.get("avg_uat_cycles")],
            ["Fn ≥2 vòng", sm.get("multi_cycle_count")],
            ["Tag UAT issue", sm.get("tagged_uat_issue")],
            ["Cột defect", det.get("defect_header") or ""],
            ["Cột reopen", det.get("reopen_header") or ""],
            ["Cột cycle", det.get("uat_cycle_header") or ""],
        ]
        _write_sheet(
            book.sheet("Tong_hop"),
            "UAT Quality — Tổng hợp",
            [("Chỉ số", 28), ("Giá trị", 18)],
            sum_rows,
            subtitle=sub,
        )
        mod_rows = [
            [
                m.get("module"),
                m.get("defects"),
                m.get("feedback"),
                m.get("reopen_rate_pct"),
                m.get("avg_uat_cycles"),
                m.get("multi_cycle"),
            ]
            for m in (payload.get("modules") or [])
        ]
        _write_sheet(
            book.sheet("Theo_module"),
            "UAT Quality — Theo module",
            [
                ("Module", 28),
                ("Defect", 10),
                ("Feedback", 10),
                ("Reopen %", 12),
                ("TB cycle", 12),
                ("≥2 vòng", 10),
            ],
            mod_rows,
            subtitle=sub,
            row_fill_fn=lambda _r, i: (
                RED_FILL if (mod_rows[i][3] or 0) >= 20
                else ORANGE_FILL if (mod_rows[i][3] or 0) >= 10
                else None
            ),
        )

    if _want_detail(mode):
        fn_rows = [
            [
                it.get("ma_cn"),
                it.get("ten_cn"),
                it.get("module"),
                process_code(it),
                it.get("defect_count"),
                it.get("feedback_count"),
                it.get("reopen_count"),
                it.get("uat_cycle"),
                it.get("uat_status") or "",
                "Yes" if it.get("tagged_uat_issue") else "",
                reason_uat_warning(it),
            ]
            for it in (payload.get("functions") or [])
        ]
        _write_sheet(
            book.sheet("Chi_tiet"),
            "UAT Quality — Function",
            [
                ("Mã CN", 16),
                ("Tên chức năng", 36),
                ("Module", 18),
                ("Quy trình", 22),
                ("Defect", 10),
                ("Feedback", 10),
                ("Reopen", 10),
                ("Cycle", 10),
                ("UAT status", 14),
                ("Tag", 8),
                ("Cảnh báo", 36),
            ],
            fn_rows,
            subtitle=sub,
            row_fill_fn=lambda _r, i: (
                RED_FILL if (fn_rows[i][4] or 0) > 0 or (fn_rows[i][6] or 0) > 0
                else None
            ),
        )

    return _save(book.wb, output_dir, "UAT_Quality")


def export_completion_forecast_report(
    payload: dict[str, Any],
    output_dir: str = "uploads",
    *,
    mode: str = "both",
) -> str:
    mode = _normalize_export_mode(mode)
    book = _SheetBook()
    band = payload.get("confidence_band") or {}
    sub = _subtitle(
        f"Status: {payload.get('status')}  |  "
        f"Velocity 4w: {payload.get('velocity_4w')}  |  "
        f"Remaining: {payload.get('remaining')}"
    )

    if _want_summary(mode):
        scen = payload.get("scenarios") or {}
        opt = scen.get("optimistic") or {}
        mid = scen.get("most_likely") or {}
        pes = scen.get("pessimistic") or {}
        sum_rows = [
            ["Ngày dự báo (most likely)", payload.get("forecast_date") or ""],
            ["Status", payload.get("status")],
            ["Message", payload.get("message") or ""],
            ["Remaining phases", payload.get("remaining")],
            ["Closed phases", payload.get("closed")],
            ["Total phases", payload.get("total")],
            ["Velocity 4 tuần (avg)", payload.get("velocity_4w")],
            ["Weeks needed", payload.get("weeks_needed")],
            ["Confidence", payload.get("confidence")],
            ["Optimistic date", band.get("optimistic") or opt.get("forecast_date") or ""],
            ["Optimistic velocity", opt.get("velocity") or ""],
            ["Most likely date", band.get("most_likely") or mid.get("forecast_date") or ""],
            ["Pessimistic date", band.get("pessimistic") or pes.get("forecast_date") or ""],
            ["Pessimistic velocity", pes.get("velocity") or ""],
            ["Band low (sớm)", band.get("low") or ""],
            ["Band high (muộn)", band.get("high") or ""],
            ["Phase scope", payload.get("scope_phase") or "(tất cả)"],
        ]
        _write_sheet(
            book.sheet("Tong_hop"),
            "Dự báo ngày xong — Tổng hợp",
            [("Chỉ số", 28), ("Giá trị", 50)],
            sum_rows,
            subtitle=sub,
        )

    if _want_detail(mode):
        bd = payload.get("burndown") or {}
        weeks = bd.get("weeks") or []
        closed = bd.get("closed_per_week") or []
        detail_rows = [
            [w, closed[i] if i < len(closed) else 0]
            for i, w in enumerate(weeks)
        ]
        _write_sheet(
            book.sheet("Velocity_tuan"),
            "Dự báo ngày xong — Closed theo tuần",
            [("Tuần", 18), ("Closed", 12)],
            detail_rows,
            subtitle=sub,
        )

    return _save(book.wb, output_dir, "Completion_Forecast")


def export_pic_upcoming_report(
    payload: dict[str, Any],
    output_dir: str = "uploads",
    *,
    mode: str = "both",
) -> str:
    mode = _normalize_export_mode(mode)
    book = _SheetBook()
    weeks = payload.get("weeks") or []
    pics = payload.get("pics") or []
    matrix = payload.get("matrix") or {}
    totals = (payload.get("totals") or {}).get("by_pic") or {}
    sub = _subtitle(f"Số tuần: {len(weeks)}  |  PIC: {len(pics)}")

    if _want_summary(mode):
        headers = [("PIC", 22)] + [
            (f"{w.get('label', '')} ({w.get('range_label', '')})", 14) for w in weeks
        ] + [("Tổng", 10)]
        rows = []
        for pic in pics:
            row_m = matrix.get(pic) or {}
            rows.append(
                [pic]
                + [row_m.get(w.get("key"), 0) or 0 for w in weeks]
                + [totals.get(pic, 0)]
            )
        _write_sheet(
            book.sheet("Tong_hop"),
            "PIC × tuần tới — Ma trận",
            headers,
            rows,
            subtitle=sub,
            row_fill_fn=lambda _r, i: (
                ORANGE_FILL if (rows[i][-1] or 0) >= 8
                else None
            ),
        )

    if _want_detail(mode):
        items = payload.get("items") or []
        detail_rows = [
            [
                it.get("pic"),
                it.get("week_key"),
                it.get("ma_cn"),
                it.get("ten_cn"),
                it.get("module"),
                it.get("phase"),
                it.get("start"),
                it.get("end"),
                it.get("status"),
            ]
            for it in items
        ]
        _write_sheet(
            book.sheet("Chi_tiet"),
            "PIC × tuần tới — Chi tiết task",
            [
                ("PIC", 18),
                ("Tuần (Mon)", 14),
                ("Mã CN", 16),
                ("Tên chức năng", 36),
                ("Module", 18),
                ("Phase", 18),
                ("Start", 12),
                ("End", 12),
                ("Status", 14),
            ],
            detail_rows,
            subtitle=sub + f"  |  {len(detail_rows)} task",
        )

    return _save(book.wb, output_dir, "PIC_Upcoming")


def export_estimate_ratio_report(
    payload: dict[str, Any],
    output_dir: str = "uploads",
    *,
    mode: str = "both",
) -> str:
    mode = _normalize_export_mode(mode)
    book = _SheetBook()
    totals = payload.get("totals") or {}
    sub = _subtitle(
        f"Tổng: {totals.get('mm')} MM · {totals.get('mh')} MH · {totals.get('md')} MD  |  "
        f"Default seed: {totals.get('pct_default_seed')}%"
    )

    if _want_summary(mode):
        phase_rows = [
            [
                p.get("label") or p.get("bucket"),
                p.get("md"),
                p.get("mh"),
                p.get("mm"),
                "Yes" if p.get("is_overhead") else "",
            ]
            for p in (payload.get("by_phase") or [])
        ]
        _write_sheet(
            book.sheet("Tong_hop"),
            "Ước lượng hệ số — Theo công đoạn",
            [
                ("Công đoạn", 28),
                ("MD", 12),
                ("MH", 12),
                ("MM", 12),
                ("Overhead", 10),
            ],
            phase_rows,
            subtitle=sub,
        )
        feed_rows = [
            [k, v] for k, v in (payload.get("forecast_feed") or {}).items()
        ]
        if feed_rows:
            _write_sheet(
                book.sheet("Forecast_feed"),
                "MH gợi ý đối chiếu Forecast Manpower",
                [("Task type", 28), ("MH", 12)],
                feed_rows,
                subtitle=sub,
            )
        map_rows = [
            [
                m.get("phase"),
                m.get("task_type"),
                m.get("bucket"),
                m.get("label"),
            ]
            for m in (payload.get("phase_mapping") or [])
        ]
        if map_rows:
            _write_sheet(
                book.sheet("Phase_map"),
                "Map phase → bucket",
                [
                    ("Phase", 28),
                    ("Task type", 18),
                    ("Bucket", 14),
                    ("Nhãn", 22),
                ],
                map_rows,
                subtitle=sub,
            )

    if _want_detail(mode):
        detail_rows = []
        for it in payload.get("detail") or []:
            b = it.get("buckets_md") or {}
            detail_rows.append([
                it.get("ma_cn"),
                it.get("ten_cn"),
                it.get("module"),
                it.get("complexity"),
                it.get("fit_gap"),
                it.get("ba_source"),
                it.get("dev_source"),
                "Yes" if it.get("used_default_seed") else "",
                it.get("build_md"),
                b.get("ba"),
                b.get("des"),
                b.get("dev"),
                b.get("test"),
                b.get("config"),
                b.get("doc"),
                "; ".join(it.get("notes") or []),
            ])
        _write_sheet(
            book.sheet("Chi_tiet"),
            "Ước lượng hệ số — Chi tiết function",
            [
                ("Mã CN", 16),
                ("Tên", 32),
                ("Module", 16),
                ("Complexity", 12),
                ("FIT/GAP", 10),
                ("BA source", 12),
                ("Dev source", 12),
                ("Default seed", 12),
                ("Build MD", 12),
                ("BA MD", 10),
                ("DES MD", 10),
                ("Dev MD", 10),
                ("Test MD", 10),
                ("Config MD", 10),
                ("Doc MD", 10),
                ("Ghi chú", 30),
            ],
            detail_rows,
            subtitle=sub,
            row_fill_fn=lambda _r, i: (
                ORANGE_FILL if detail_rows[i][7] == "Yes" else None
            ),
        )

    return _save(book.wb, output_dir, "Estimate_Ratio")


def export_evm_scurve_report(
    payload: dict[str, Any],
    output_dir: str = "uploads",
    *,
    mode: str = "both",
) -> str:
    """Xuất S-curve EV/PV/AC theo tuần."""
    mode = _normalize_export_mode(mode)
    book = _SheetBook()
    pts = payload.get("points") or []
    sub = _subtitle(payload.get("message") or "")
    if _want_summary(mode) or _want_detail(mode):
        rows = [
            [
                p.get("date"),
                p.get("week"),
                p.get("bac"),
                p.get("ev"),
                p.get("pv") if p.get("pv") is not None else "N/A",
                p.get("ac"),
                p.get("spi") if p.get("spi") is not None else "N/A",
                p.get("cpi") if p.get("cpi") is not None else "N/A",
            ]
            for p in pts
        ]
        _write_sheet(
            book.sheet("S_curve"),
            "EVM S-curve — EV / PV / AC theo tuần",
            [
                ("Ngày", 14),
                ("Tuần", 14),
                ("BAC", 12),
                ("EV", 12),
                ("PV", 12),
                ("AC", 12),
                ("SPI", 10),
                ("CPI", 10),
            ],
            rows,
            subtitle=sub,
        )
    return _save(book.wb, output_dir, "EVM_SCurve")


def export_executive_dashboard_report(
    payload: dict[str, Any],
    output_dir: str = "uploads",
    *,
    mode: str = "both",
) -> str:
    """Xuất 1 trang Executive Dashboard cho PM."""
    mode = _normalize_export_mode(mode)
    book = _SheetBook()
    sm = payload.get("summary") or {}
    band = sm.get("forecast_band") or {}
    sub = _subtitle(payload.get("project_name") or "")

    if _want_summary(mode):
        sum_rows = [
            ["% hoàn thành", sm.get("pct_done")],
            ["Tổng function", sm.get("total_functions")],
            ["Overdue", sm.get("total_overdue")],
            ["Unassigned", sm.get("unassigned_count")],
            ["High risk", sm.get("high_risk_count")],
            ["SPI", sm.get("spi") if sm.get("spi") is not None else "N/A"],
            ["CPI", sm.get("cpi") if sm.get("cpi") is not None else "N/A"],
            ["BAC / EV / PV / AC",
             f"{sm.get('bac')} / {sm.get('ev')} / {sm.get('pv')} / {sm.get('ac')}"],
            ["Forecast (most likely)", sm.get("forecast_date") or ""],
            ["Forecast optimistic", band.get("optimistic") or ""],
            ["Forecast pessimistic", band.get("pessimistic") or ""],
            ["Scope creep %", sm.get("scope_creep_pct")],
            ["CR count", sm.get("cr_count")],
        ]
        _write_sheet(
            book.sheet("Tong_hop"),
            "PM Executive Dashboard",
            [("Chỉ số", 28), ("Giá trị", 40)],
            sum_rows,
            subtitle=sub,
        )
        ms_rows = [
            [m.get("label") or m.get("id"), m.get("month") or "", m.get("date") or "",
             m.get("status") or "", m.get("text") or ""]
            for m in (payload.get("milestones") or [])
        ]
        _write_sheet(
            book.sheet("Milestone"),
            "Milestone status",
            [("Milestone", 22), ("Tháng", 12), ("Ngày", 14), ("Status", 12), ("Ghi chú", 40)],
            ms_rows or [["(không có)", "", "", "", ""]],
            subtitle=sub,
        )

    if _want_detail(mode):
        risk_rows = [
            [
                r.get("ma_cn"), r.get("ten_cn"), r.get("module"), r.get("risk_score"),
                "; ".join(r.get("risk_factors") or []),
                (r.get("mitigation") or {}).get("owner") or "",
                (r.get("mitigation") or {}).get("target_date") or "",
                (r.get("mitigation") or {}).get("note") or "",
            ]
            for r in (payload.get("top_risks") or [])
        ]
        _write_sheet(
            book.sheet("Top_risks"),
            "Top 5 rủi ro",
            [
                ("Mã CN", 14), ("Tên", 32), ("Module", 16), ("Score", 10),
                ("Factors", 36), ("Owner", 14), ("Target", 12), ("Mitigation", 36),
            ],
            risk_rows or [["", "", "", "", "", "", "", "(không có)"]],
            subtitle=sub,
            row_fill_fn=lambda _r, i: (
                RED_FILL if risk_rows and (risk_rows[i][3] or 0) >= 70
                else ORANGE_FILL if risk_rows and (risk_rows[i][3] or 0) >= 50
                else None
            ),
        )

    return _save(book.wb, output_dir, "PM_Executive")
