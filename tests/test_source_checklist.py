"""Tests cho analyzer.source_checklist — checklist lấy source test Rlog."""
from datetime import date, timedelta

from parser.excel_parser import ParsedData, FunctionRow, PhaseData, PhaseGroup
from analyzer.source_checklist import (
    compute_source_checklist,
    detect_taker_phase,
    _is_config_local_phase,
)


TODAY = date(2026, 7, 31)


def _pg(*names: str) -> list[PhaseGroup]:
    groups = []
    for n in names:
        attrs = {"Start": 1, "End": 2, "Status": 3, "PIC": 4}
        if n == "Analysis":
            attrs["RlogID"] = 5
        groups.append(PhaseGroup(name=n, attributes=attrs))
    return groups


def _row(
    ma,
    *,
    rlog_id="25001",
    dev_status="Closed",
    dev_end=None,
    dev_pics=None,
    taker_phase="Config Local",
    taker_pics=None,
    taker_status=None,
    taker_start=None,
    module="PR",
):
    phases = {
        "Analysis": PhaseData(
            status="Closed",
            end_date=date(2026, 3, 1),
            extra={"RlogID": rlog_id} if rlog_id else {},
        ),
        "Dev": PhaseData(
            status=dev_status,
            end_date=dev_end,
            pics=dev_pics if dev_pics is not None else ["DevA"],
        ),
    }
    if taker_phase:
        phases[taker_phase] = PhaseData(
            status=taker_status,
            start_date=taker_start,
            pics=taker_pics if taker_pics is not None else [],
        )
    return FunctionRow(
        row_num=2,
        meta={"ma_cn": ma, "ten_cn": f"Func {ma}", "module": module},
        phases=phases,
    )


def _data(rows, phases=("Analysis", "Dev", "Config Local", "Test")) -> ParsedData:
    return ParsedData(
        headers={},
        meta_columns={},
        phase_groups=_pg(*phases),
        rows=rows,
        all_modules=["PR"],
        all_phases=list(phases),
        all_pics=["DevA", "CfgA"],
        all_statuses=["Open", "In-progress", "Closed"],
        all_priorities=[],
        all_complexities=[],
        all_giai_doan=[],
        all_processes=[],
    )


# ── Detect phase người lấy source ───────────────────────────────────────────

def test_is_config_local_phase():
    assert _is_config_local_phase("Config Local")
    assert _is_config_local_phase("config-local")
    assert _is_config_local_phase("Cấu hình Local")
    assert not _is_config_local_phase("Config UAT")
    assert not _is_config_local_phase("Localization")


def test_detect_taker_phase_config_local():
    d = _data([])
    assert detect_taker_phase(d) == ("Config Local", "config_local")


def test_detect_taker_phase_fallback_next_after_dev():
    """Không có Config Local → phase ngay sau Dev theo thứ tự cột."""
    d = _data([], phases=("Analysis", "Dev", "Test", "UAT"))
    assert detect_taker_phase(d) == ("Test", "next_after_dev")


def test_detect_taker_phase_none_when_dev_is_last():
    d = _data([], phases=("Analysis", "Dev"))
    assert detect_taker_phase(d) == (None, "none")


# ── Điều kiện cảnh báo ─────────────────────────────────────────────────────

def test_pending_when_taker_has_no_pic():
    rows = [_row("A.01", dev_end=TODAY, taker_pics=[])]
    out = compute_source_checklist(_data(rows), today=TODAY)
    assert out["summary"]["total_pending"] == 1
    it = out["days"][0]["items"][0]
    assert it["state"] == "pending"
    assert it["reason"] == "no_taker"
    assert it["severity"] == "high"
    assert it["taker_phase"] == "Config Local"


def test_done_when_taker_has_pic_and_started():
    rows = [_row("A.02", dev_end=TODAY, taker_pics=["CfgA"], taker_start=TODAY)]
    out = compute_source_checklist(_data(rows), today=TODAY)
    assert out["summary"]["total_pending"] == 0
    assert out["summary"]["total_done"] == 1
    assert out["days"][0]["items"][0]["state"] == "done"


def test_done_when_taker_status_in_progress_without_start():
    rows = [_row("A.03", dev_end=TODAY, taker_pics=["CfgA"], taker_status="In-progress")]
    out = compute_source_checklist(_data(rows), today=TODAY)
    assert out["summary"]["total_done"] == 1


def test_not_started_severity_by_age():
    """Có PIC nhưng status Open + chưa Start → pending; ≥3 ngày thì lên high."""
    fresh = [_row("B.01", dev_end=TODAY, taker_pics=["CfgA"], taker_status="Open")]
    out = compute_source_checklist(_data(fresh), today=TODAY)
    it = out["days"][0]["items"][0]
    assert it["reason"] == "not_started"
    assert it["severity"] == "medium"

    old = [_row("B.02", dev_end=TODAY - timedelta(days=3),
                taker_pics=["CfgA"], taker_status="Open")]
    out2 = compute_source_checklist(_data(old), today=TODAY)
    assert out2["days"][0]["items"][0]["severity"] == "high"


def test_taker_cancelled_not_required():
    rows = [_row("C.01", dev_end=TODAY, taker_pics=[], taker_status="Cancelled")]
    out = compute_source_checklist(_data(rows), today=TODAY)
    assert out["summary"]["total_pending"] == 0
    assert out["summary"]["total_not_required"] == 1


def test_no_taker_phase_in_row():
    """Function thiếu hẳn phase Config Local → vẫn cảnh báo, reason riêng."""
    rows = [_row("C.02", dev_end=TODAY, taker_phase=None)]
    out = compute_source_checklist(_data(rows), today=TODAY)
    it = out["days"][0]["items"][0]
    assert it["reason"] == "no_taker_phase"
    assert it["severity"] == "high"


def test_dev_not_closed_still_included():
    """NGHIỆP VỤ MỚI: Config Local cần thấy row SỚM để chuẩn bị checklist
    trước khi dev đóng phase. Không lọc theo Dev.Status = Closed nữa —
    cứ có End date trong lookback là kéo vào (trừ Cancelled).
    """
    rows = [
        _row("D.01", dev_status="In-progress", dev_end=TODAY, taker_pics=[]),
        _row("D.02", dev_status=None, dev_end=TODAY, taker_pics=[]),
        _row("D.03", dev_status="Open", dev_end=TODAY, taker_pics=[]),
    ]
    out = compute_source_checklist(_data(rows), today=TODAY)
    assert out["summary"]["total_coded"] == 3
    ma = {it["ma_cn"] for it in out["days"][0]["items"]}
    assert ma == {"D.01", "D.02", "D.03"}
    # Item phải giữ dev_status để UI phân biệt được đã Closed hay chưa
    it_ip = next(it for it in out["days"][0]["items"] if it["ma_cn"] == "D.01")
    assert it_ip["dev_status"] == "In-progress"


def test_dev_cancelled_still_skipped():
    """Task hủy → không cần source. Đây là ngoại lệ duy nhất còn lại
    (sau khi bỏ ràng buộc Dev.Closed).
    """
    rows = [_row("D.04", dev_status="Cancelled", dev_end=TODAY, taker_pics=[])]
    out = compute_source_checklist(_data(rows), today=TODAY)
    assert out["summary"]["total_coded"] == 0
    assert out["days"] == []


def test_dev_without_end_skipped():
    """Không có End date → không có mốc để theo dõi, bỏ qua bất kể status."""
    rows = [
        _row("D.05", dev_status="Closed", dev_end=None, taker_pics=[]),
        _row("D.06", dev_status="In-progress", dev_end=None, taker_pics=[]),
    ]
    out = compute_source_checklist(_data(rows), today=TODAY)
    assert out["summary"]["total_coded"] == 0


def test_dev_status_field_present_for_closed_row():
    rows = [_row("D.07", dev_status="Closed", dev_end=TODAY, taker_pics=[])]
    out = compute_source_checklist(_data(rows), today=TODAY)
    assert out["days"][0]["items"][0]["dev_status"] == "Closed"


# ── Cửa sổ lookback + group theo ngày ──────────────────────────────────────

def test_lookback_window_excludes_old_coded():
    rows = [
        _row("E.01", dev_end=TODAY - timedelta(days=3), taker_pics=[]),
        _row("E.02", dev_end=TODAY - timedelta(days=20), taker_pics=[]),
    ]
    out = compute_source_checklist(_data(rows), today=TODAY, lookback_days=14)
    assert out["summary"]["total_coded"] == 1
    assert out["summary"]["out_of_window"] == 1
    assert out["window_start"] == (TODAY - timedelta(days=14)).isoformat()


def test_future_coded_date_out_of_window():
    rows = [_row("E.03", dev_end=TODAY + timedelta(days=2), taker_pics=[])]
    out = compute_source_checklist(_data(rows), today=TODAY)
    assert out["summary"]["total_coded"] == 0
    assert out["summary"]["out_of_window"] == 1


def test_lookback_clamped():
    out = compute_source_checklist(_data([]), today=TODAY, lookback_days=9999)
    assert out["lookback_days"] == 365
    out2 = compute_source_checklist(_data([]), today=TODAY, lookback_days=0)
    assert out2["lookback_days"] == 1


def test_group_by_day_desc_with_counts():
    rows = [
        _row("F.01", rlog_id="1", dev_end=TODAY, taker_pics=[]),
        _row("F.02", rlog_id="2", dev_end=TODAY, taker_pics=["CfgA"], taker_start=TODAY),
        _row("F.03", rlog_id="3", dev_end=TODAY - timedelta(days=2), taker_pics=[]),
    ]
    out = compute_source_checklist(_data(rows), today=TODAY)
    days = out["days"]
    assert [d["date"] for d in days] == [
        TODAY.isoformat(),
        (TODAY - timedelta(days=2)).isoformat(),
    ]
    assert days[0]["coded_count"] == 2
    assert days[0]["pending_count"] == 1
    assert days[0]["done_count"] == 1
    assert days[0]["weekday_label"] == "Thứ 6"  # 31/07/2026
    assert days[1]["days_since_coded"] == 2
    assert out["summary"]["days_with_coded"] == 2
    assert out["summary"]["days_with_pending"] == 2
    assert out["summary"]["max_days_pending"] == 2
    # Pending xếp trước done trong cùng ngày
    assert days[0]["items"][0]["state"] == "pending"


def test_by_taker_and_by_reason_summary():
    rows = [
        _row("G.01", rlog_id="1", dev_end=TODAY, taker_pics=["CfgA"], taker_status="Open"),
        _row("G.02", rlog_id="2", dev_end=TODAY, taker_pics=["CfgA"], taker_status="Open"),
        _row("G.03", rlog_id="3", dev_end=TODAY, taker_pics=[]),
    ]
    out = compute_source_checklist(_data(rows), today=TODAY)
    s = out["summary"]
    assert s["by_reason"] == {"not_started": 2, "no_taker": 1}
    assert s["by_taker"] == {"CfgA": 2}
    assert s["by_severity"]["high"] == 1
    assert s["by_severity"]["medium"] == 2


# ── Scope Rlog ─────────────────────────────────────────────────────────────

def test_scope_with_rlog_id_skips_rows_without():
    rows = [
        _row("H.01", rlog_id="25001", dev_end=TODAY, taker_pics=[]),
        _row("H.02", rlog_id=None, dev_end=TODAY, taker_pics=[]),
    ]
    out = compute_source_checklist(_data(rows), today=TODAY)
    assert out["rlog_scope"] == "with_rlog_id"
    assert out["summary"]["total_coded"] == 1
    assert out["days"][0]["items"][0]["ma_cn"] == "H.01"


def test_scope_all_functions_when_no_rlog_filled():
    rows = [_row("I.01", rlog_id=None, dev_end=TODAY, taker_pics=[])]
    out = compute_source_checklist(_data(rows), today=TODAY)
    assert out["rlog_scope"] == "all_functions"
    assert out["summary"]["total_coded"] == 1
    assert out["days"][0]["items"][0]["checklist_action"] == "Làm checklist lấy source test"


def test_checklist_action_mentions_rlog():
    rows = [_row("J.01", rlog_id="25123", dev_end=TODAY, taker_pics=[])]
    out = compute_source_checklist(_data(rows), today=TODAY)
    assert out["days"][0]["items"][0]["checklist_action"] == (
        "Làm checklist lấy source test cho Rlog 25123"
    )
    assert "người config local" in out["checklist_note"]


# ── API smoke ──────────────────────────────────────────────────────────────

def test_api_source_checklist_endpoint(flask_client, sample_xlsx_path):
    with open(sample_xlsx_path, "rb") as f:
        r = flask_client.post(
            "/api/upload",
            data={"file": (f, "sample.xlsx")},
            content_type="multipart/form-data",
        )
    assert r.status_code == 200, r.get_data(as_text=True)
    slug = r.get_json().get("project", {}).get("slug") or "default"

    r2 = flask_client.get(f"/api/projects/{slug}/source-checklist?lookback=30")
    assert r2.status_code == 200, r2.get_data(as_text=True)
    payload = r2.get_json()
    assert payload["lookback_days"] == 30
    assert "days" in payload and "summary" in payload
    assert payload["taker_phase_source"] in ("config_local", "next_after_dev", "none")
