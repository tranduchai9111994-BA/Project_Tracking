"""Tests cho rule Unassigned: predecessor Closed + Start đã đến."""
from datetime import date, timedelta

from analyzer.dashboard_engine import DashboardEngine
from analyzer.unassigned import (
    has_phase_start_arrived,
    is_predecessor_closed,
    is_unassigned_phase,
)
from parser.excel_parser import FunctionRow, PhaseData, PhaseGroup, ParsedData


TODAY = date(2026, 7, 31)
ORDER = ["Analysis", "Dev", "Config Local", "Config UAT", "Document", "Config Prod"]


def _pd(status=None, pics=None, *, start_off=None, end_off=None) -> PhaseData:
    return PhaseData(
        start_date=(TODAY + timedelta(days=start_off)) if start_off is not None else None,
        end_date=(TODAY + timedelta(days=end_off)) if end_off is not None else None,
        status=status,
        pics=list(pics or []),
    )


def _row(phases: dict[str, PhaseData], ma_cn: str = "X.01") -> FunctionRow:
    return FunctionRow(
        row_num=2,
        meta={"ma_cn": ma_cn, "ten_cn": ma_cn, "module": "M", "priority": "Must-have"},
        phases=phases,
    )


def _parsed(rows: list[FunctionRow], order: list[str] | None = None) -> ParsedData:
    order = order or ORDER
    return ParsedData(
        headers={},
        meta_columns={},
        phase_groups=[PhaseGroup(name=n, attributes={}) for n in order],
        rows=rows,
        all_modules=["M"],
        all_phases=order,
        all_pics=[],
        all_statuses=["Open", "In-progress", "Closed"],
    )


def _ua(row: FunctionRow, phase: str) -> bool:
    return is_unassigned_phase(row, phase, row.phases[phase], ORDER, TODAY)


def test_analysis_closed_dev_no_pic_flags():
    """Analysis Closed + Dev no PIC (status Open, không Start) → flag."""
    row = _row({
        "Analysis": _pd("Closed", ["A"], end_off=-10),
        "Dev": _pd("Open", []),
    })
    assert _ua(row, "Dev") is True


def test_analysis_not_closed_dev_no_pic_no_flag():
    """Analysis chưa Closed + Dev no PIC → không flag."""
    row = _row({
        "Analysis": _pd("In-progress", ["A"], end_off=5),
        "Dev": _pd("Open", []),
    })
    assert _ua(row, "Dev") is False

    row2 = _row({
        "Analysis": _pd("In-progress", ["A"]),
        "Dev": _pd(None, [], end_off=3),  # có End nhưng Analysis chưa xong
    })
    assert _ua(row2, "Dev") is False


def test_dev_closed_config_no_pic_flags():
    """Dev Closed + Config Local no PIC → flag."""
    row = _row({
        "Analysis": _pd("Closed", ["A"]),
        "Dev": _pd("Closed", ["B"]),
        "Config Local": _pd("Open", []),
    })
    assert _ua(row, "Config Local") is True


def test_dev_not_closed_config_no_pic_no_flag():
    """Dev chưa Closed + Config no PIC → không flag."""
    row = _row({
        "Analysis": _pd("Closed", ["A"]),
        "Dev": _pd("In-progress", ["B"]),
        "Config Local": _pd(None, [], end_off=10),
    })
    assert _ua(row, "Config Local") is False


def test_first_phase_in_scope_no_pic_flags():
    """Phase đầu (Analysis) in-scope thiếu PIC → flag."""
    row = _row({
        "Analysis": _pd("Open", []),
        "Dev": _pd(None, []),
    })
    assert _ua(row, "Analysis") is True


def test_first_phase_blank_no_flag():
    """Phase đầu hoàn toàn blank → không flag."""
    row = _row({
        "Analysis": _pd(None, []),
        "Dev": _pd(None, []),
    })
    assert _ua(row, "Analysis") is False


def test_predecessor_cancelled_does_not_unlock():
    """Cancelled ≠ Closed → không unlock phase sau."""
    row = _row({
        "Analysis": _pd("Cancelled", ["A"]),
        "Dev": _pd("Open", []),
    })
    assert is_predecessor_closed(row, "Dev", ORDER) is False
    assert _ua(row, "Dev") is False


def test_start_future_no_pic_no_flag():
    """Start tương lai + thiếu PIC + predecessor Closed → không flag."""
    row = _row({
        "Analysis": _pd("Closed", ["A"], end_off=-10),
        "Dev": _pd(None, [], start_off=5, end_off=20),
    })
    assert has_phase_start_arrived(row.phases["Dev"], TODAY) is False
    assert _ua(row, "Dev") is False

    # Status Open nhưng Start còn tương lai → vẫn không flag
    row2 = _row({
        "Analysis": _pd("Closed", ["A"], end_off=-10),
        "Dev": _pd("Open", [], start_off=3, end_off=15),
    })
    assert _ua(row2, "Dev") is False


def test_start_past_or_today_no_pic_flags():
    """Start past/today + thiếu PIC + predecessor Closed → flag."""
    row = _row({
        "Analysis": _pd("Closed", ["A"], end_off=-10),
        "Dev": _pd(None, [], start_off=-2, end_off=10),
    })
    assert has_phase_start_arrived(row.phases["Dev"], TODAY) is True
    assert _ua(row, "Dev") is True

    row_today = _row({
        "Analysis": _pd("Closed", ["A"], end_off=-10),
        "Dev": _pd(None, [], start_off=0, end_off=14),
    })
    assert _ua(row_today, "Dev") is True


def test_not_started_no_dates_no_flag():
    """Not Started (map Open) + không Start/End → không đếm thiếu PIC.

    Case PR.FR.49: Analysis Closed 03/08, Dev = Not Started, chưa có Dev Start.
    Trước đây map Open kích hoạt fallback «đang làm» → đếm sai.
    """
    dev = _pd("Open", [])
    dev.from_not_started = True
    row = _row({
        "Analysis": _pd("Closed", ["A"], end_off=-3),
        "Dev": dev,
    })
    assert has_phase_start_arrived(dev, TODAY) is False
    assert _ua(row, "Dev") is False


def test_not_started_future_start_not_stalled():
    """PRM.FR.53 — Analysis Closed, Dev Not Started Start 17/08 > today → không đình trễ."""
    from datetime import date as _date
    from analyzer.dashboard_engine import DashboardEngine
    today = _date(2026, 8, 6)
    analysis = PhaseData(
        status="Closed", start_date=_date(2026, 8, 2), end_date=_date(2026, 8, 2),
        pics=["NhiVN"],
    )
    dev = PhaseData(
        status="Open", start_date=_date(2026, 8, 17), end_date=_date(2026, 8, 19),
        pics=[], from_not_started=True,
    )
    row = FunctionRow(
        row_num=2,
        meta={"ma_cn": "PRM.FR.53", "ten_cn": "x", "module": "PR", "priority": "Must-have"},
        phases={"Analysis": analysis, "Dev": dev},
    )
    data = ParsedData(
        headers={}, meta_columns={},
        phase_groups=[PhaseGroup(name="Analysis"), PhaseGroup(name="Dev")],
        rows=[row],
        all_phases=["Analysis", "Dev"],
        all_modules=["PR"],
    )
    st = DashboardEngine(today=today)._stalled_tasks(data)
    assert not any(i["ma_cn"] == "PRM.FR.53" for i in st["items"])


def test_not_started_future_start_no_unassigned_flag():
    """Not Started + Start tương lai (PRM.FR.53 pattern) → không flag thiếu PIC."""
    from datetime import date as _date
    today = _date(2026, 8, 6)
    analysis = PhaseData(
        status="Closed", start_date=_date(2026, 8, 2), end_date=_date(2026, 8, 2),
        pics=["NhiVN"],
    )
    dev = PhaseData(
        status="Open", start_date=_date(2026, 8, 17), end_date=_date(2026, 8, 19),
        pics=[], from_not_started=True,
    )
    row = FunctionRow(
        row_num=2,
        meta={"ma_cn": "PRM.FR.53", "ten_cn": "x", "module": "PR", "priority": "Must-have"},
        phases={"Analysis": analysis, "Dev": dev},
    )
    assert has_phase_start_arrived(dev, today) is False
    assert is_unassigned_phase(row, "Dev", dev, ORDER, today) is False


def test_not_started_past_start_still_flags():
    """Not Started nhưng Start đã qua + thiếu PIC → vẫn flag (đã tới ngày)."""
    from datetime import date as _date
    today = _date(2026, 8, 20)
    analysis = PhaseData(
        status="Closed", end_date=_date(2026, 8, 2), pics=["A"],
    )
    dev = PhaseData(
        status="Open", start_date=_date(2026, 8, 17), end_date=_date(2026, 8, 19),
        pics=[], from_not_started=True,
    )
    row = FunctionRow(
        row_num=2,
        meta={"ma_cn": "X", "ten_cn": "x", "module": "M", "priority": "Must-have"},
        phases={"Analysis": analysis, "Dev": dev},
    )
    assert has_phase_start_arrived(dev, today) is True
    assert is_unassigned_phase(row, "Dev", dev, ORDER, today) is True


def test_real_open_no_start_still_flags():
    """Status Open thật (không phải Not Started) + không Start → vẫn flag.

    Giữ hành vi cũ: đang Open mà quên điền Start vẫn cần báo thiếu PIC.
    """
    row = _row({
        "Analysis": _pd("Closed", ["A"], end_off=-10),
        "Dev": _pd("Open", []),
    })
    assert row.phases["Dev"].from_not_started is False
    assert _ua(row, "Dev") is True


def test_parser_sets_from_not_started_flag():
    """Parse Excel: Not Started → status Open + from_not_started=True."""
    from parser.excel_parser import FunctionListParser
    p = FunctionListParser()
    assert p._is_not_started_token("Not Started") is True
    assert p._is_not_started_token("Open") is False
    assert p._normalize_status("Not Started", has_pic=False) == "Open"


def test_no_start_future_end_only_no_flag():
    """Không Start + chỉ có End tương lai (không status đang làm) → không flag."""
    row = _row({
        "Analysis": _pd("Closed", ["A"], end_off=-10),
        "Dev": _pd(None, [], end_off=14),
    })
    assert has_phase_start_arrived(row.phases["Dev"], TODAY) is False
    assert _ua(row, "Dev") is False


def test_no_start_past_end_flags():
    """Không Start + End đã đến + thiếu PIC → flag."""
    row = _row({
        "Analysis": _pd("Closed", ["A"], end_off=-10),
        "Dev": _pd(None, [], end_off=-1),
    })
    assert has_phase_start_arrived(row.phases["Dev"], TODAY) is True
    assert _ua(row, "Dev") is True


def test_engine_summary_and_list_match_gate():
    """DashboardEngine summary/list chỉ giữ case đã tới Start + pred Closed."""
    data = _parsed([
        _row({
            "Analysis": _pd("Closed", ["A"]),
            "Dev": _pd("Open", []),
        }, ma_cn="OK.01"),
        _row({
            "Analysis": _pd("In-progress", ["A"]),
            "Dev": _pd("Open", []),
        }, ma_cn="SKIP.01"),
        _row({
            "Analysis": _pd("Closed", ["A"]),
            "Dev": _pd("Closed", ["B"]),
            "Config Local": _pd("Assigned", []),
        }, ma_cn="CFG.01"),
        _row({
            "Analysis": _pd("Closed", ["A"]),
            "Dev": _pd("In-progress", ["B"]),
            "Config Local": _pd(None, [], end_off=2),
        }, ma_cn="CFG.SKIP"),
        _row({
            "Analysis": _pd("Closed", ["A"]),
            "Dev": _pd(None, [], start_off=10, end_off=20),
        }, ma_cn="FUTURE.01"),
    ])
    m = DashboardEngine(today=TODAY).compute_all(data)
    phases = {(i["ma_cn"], i["phase"]) for i in m["unassigned_tasks"]}
    assert ("OK.01", "Dev") in phases
    assert ("CFG.01", "Config Local") in phases
    assert ("SKIP.01", "Dev") not in phases
    assert ("CFG.SKIP", "Config Local") not in phases
    assert ("FUTURE.01", "Dev") not in phases
    assert m["summary"]["unassigned_count"] == 2
    assert m["summary"]["unassigned_records"] == 2


def test_unassigned_tasks_include_rlog_id():
    """Payload unassigned kèm rlog_id từ phase.extra (không đổi logic flag)."""
    analysis = _pd("Closed", ["A"], end_off=-10)
    analysis.extra = {"RlogID": "25265"}
    row = _row({
        "Analysis": analysis,
        "Dev": _pd("Open", []),
    }, ma_cn="R.01")
    data = _parsed([row])
    items = DashboardEngine(today=TODAY).compute_all(data)["unassigned_tasks"]
    assert len(items) == 1
    assert items[0]["ma_cn"] == "R.01"
    assert items[0]["phase"] == "Dev"
    assert items[0]["rlog_id"] == "25265"
