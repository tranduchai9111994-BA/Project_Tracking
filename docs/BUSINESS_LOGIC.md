# Business Logic — Rule nghiệp vụ end-to-end

> Cập nhật: **2026-07-31**. Mọi rule dưới đây triển khai trong `analyzer/*` (+ một phần FE filter).
> Không hardcode tên cột Excel — luôn qua `ParsedData` / `PhaseGroup.task_type`.

---

## 1. Parse Function List

**Module:** `parser/excel_parser.py`

1. Đọc header row 1.
2. Phase group = pattern `PhaseName - Attribute` (Start, End, Status, PIC, Estimate MH, Note…).
3. Meta: Module, Priority, Complexity, FIT/GAP, Giai đoạn, Tên CN, Mã CN, Quy trình, Mã dự án… (keyword match).
4. Status số (1, 2, 8…) ở cột Status → bỏ qua (Estimate MH lệch cột).
5. Estimate MH: reject datetime / outlier lớn; log `estimate_mh_rejected`.
6. PIC: split `,` `;` `+` `\n`.

**Task type** (`PhaseGroup.task_type`): map regex tên phase → Phân tích / Lập trình / Kiểm thử / Cấu hình UAT / UAT / Tài liệu / Cấu hình Golive.

---

## 2. Overdue (trễ deadline)

**Module:** `analyzer/overdue.py` (+ dashboard_engine)

Một phase **overdue** khi:

- Có **End** date hợp lệ  
- `End < today`  
- Status **không** phải Closed / Cancelled  

**Ngoại lệ:** End quá hạn nhưng Status trống, và **phase sau** đã Closed → không coi overdue (tránh false positive khi bỏ quên status).

Date accept: `datetime`, `dd/MM/yyyy`, `yyyy-MM-dd`.

---

## 3. Unassigned (thiếu PIC)

**Module:** `analyzer/unassigned.py`

Flag thiếu PIC khi **tất cả** đúng:

1. Phase **in-scope**: chưa Closed/Cancelled; có status hoặc có Start/End (phase đầu blank hoàn toàn → không flag).  
2. **Phase liền trước** trong `all_phases` đã **Closed** (phase đầu không cần predecessor).  
   - Predecessor Cancelled **không** unlock phase sau.  
3. **Đã tới ngày Start** (`start <= today`).  
   - Không có Start: chỉ flag nếu `End <= today` **hoặc** status ∈ {Open, Assigned, In-progress}.  
   - Start tương lai → **không** flag.

DQ blank PIC / missing deadline cùng chiều dùng chung gate.

UI: cột **Rlog ID**; subtitle giải thích rule.

---

## 4. Stalled (đình trệ)

**Module:** `analyzer/stalled.py`

Transition “phase trước Closed → phase chờ chưa start” chỉ **stalled** khi:

1. Phase trước = Closed  
2. Phase chờ status None / Open (chưa làm)  
3. **End của phase chờ tồn tại và `end < today`** (đã quá hạn)  
4. Function **chưa** fully done:
   - Phase **cuối** (thường Golive) Closed → loại, **hoặc**  
   - Mọi phase ∈ {Closed, Cancelled}

**Không End** trên phase chờ → **không** stalled (kể cả Analysis Closed + Dev chưa plan).

Funnel / transitions / table / export / badge đều từ cùng `items`.

---

## 5. Data Quality

**Module:** `analyzer/data_quality.py`

| Rule | Ý nghĩa |
|------|---------|
| Missing deadline | Thiếu End khi đã tới lượt (cùng gate unassigned) |
| Phase overlap ngày | Hai phase giao ngày — **trừ** whitelist **Config Local ↔ Config UAT** (song song hợp lệ) |
| Estimate MH lệch duration | MH vs khoảng Start–End bất thường |
| … | Severity High / Medium / Low |

Filter: global + local Module / severity / type. Export Excel tôn trọng filter.

---

## 6. Rlog tuần

**Module:** `analyzer/rlog_weekly.py`

| Khái niệm | Logic |
|-----------|--------|
| Rlog | Function có attribute phase chứa `Rlog` (thường `Analysis - RlogID`) |
| Coded tuần này | Dev **Closed** + End ∈ tuần ISO hiện tại |
| Kế hoạch tuần tới | Dev chưa Closed/Cancelled + End ∈ tuần sau **hoặc** Start–End giao tuần sau |
| Fallback | Không có RlogID filled → đếm mọi function (subtitle ghi rõ) |

---

## 7. Forecast Gantt (UAT / Golive theo tháng)

**Module:** `analyzer/forecast_gantt.py`

Milestone (map `task_type`): Phân tích xong · Dev xong · Cấu hình xong · UAT với KH · Golive với KH.

**Tháng milestone:**

1. Còn phase mở (không Closed/Cancelled) có End → `max(End còn mở)` — `open_max`  
2. Else có Closed có End → `max(End Closed)` — `closed_max`  
3. Else → không có tháng  

**Gantt bar:** `min(Start)→max(End)`; marker tháng forecast.  
**Tree:** Rows=Project → hàng cha project + hàng con milestone indent.  
**Đánh giá lý do hợp lý:** ok / warn / risk (thiếu End, % Closed cao nhưng tháng xa…).

Đa dự án: chọn 1/nhiều slug.

---

## 8. Forecast Manpower (MH / MD / MM & tuyển)

**Module:** `analyzer/forecast_manpower.py`

| Cơ sở (`basis`) | Cách tính MH / phase |
|-----------------|----------------------|
| **unit** | Estimate MH; trống → **mặc định 8** |
| **duration** | Ngày làm Start→End (bỏ T7/CN) × 8; thiếu ngày → fallback unit/default |

| Đơn vị hiển thị | Quy đổi |
|-----------------|--------|
| Man-hour | MH |
| Man-day | MH ÷ 8 |
| Man-month | MH ÷ 160 (20 ngày × 8h) |

**Pool:**

- **Lập trình (riêng)** = task_type Lập trình  
- **Triển khai chung** = Phân tích + Kiểm thử + Cấu hình* + UAT + Tài liệu + …

Chỉ phase chưa Closed/Cancelled tính **còn lại**.

**Tuyển thêm:**

```
people_needed = ceil(remaining_MH / (target_months × 160))
hire_needed   = max(0, people_needed − headcount_hiện_tại)
```

Cột **Ghi chú / phương pháp** mô tả cơ sở + số liệu.  
Export: Tong_hop + Chi_tiet (`mode`).

---

## 9. PIC Overload (đa dự án)

**Module:** `analyzer/pic_overload.py`

Task **active** ngày D: phase có Start–End giao D, status ≠ Closed/Cancelled, PIC multi-parse — **mọi project**.

| Grain | Overload mặc định |
|-------|-------------------|
| Ngày | concurrent > **5** → ngày đỏ |
| Tuần | ≥ **2** ngày đỏ **hoặc** task-days > **25** |
| Tháng | ≥ **5** ngày đỏ **hoặc** task-days > **100** |

Threshold chỉnh Settings. Badge OVERDUE+, so sánh tuần trước, deep-link project.

---

## 10. Capacity PIC (trong 1 project)

**Module:** `analyzer/advanced_metrics.compute_capacity_load`

Remaining MH (chưa Closed) theo PIC vs `capacity_mh_per_week`.  
Overload nếu `weeks_needed > 4`.

Khác Forecast Manpower: Capacity = so với công suất PIC đã cấu hình; Manpower = ước lượng lực lượng / tuyển theo công đoạn.

---

## 11. FL Re-import export

**Module:** `exporter/fl_reimport_export.py` + `fl_export_schema.py`

- Union issues: overdue, unassigned, stalled, anomalies (+ missing deadline…).  
- Xuất **đúng header** Function List (schema mẫu per-project hoặc FL hiện tại).  
- **Chỉ 1 sheet** `Function List` — không sheet hướng dẫn, không ghi Remark Tracker.  
- **Tô vàng:** PIC / Status cần sửa.  
- **Tô xanh nhạt:** From phase sau = To trước **+1 ngày làm** (bỏ T7/CN); chỉ fill ô trống.  
- Text 1 dòng (`wrap_text=False`).

Upload mẫu → auto-detect → review mapping → lưu `fl_export_schema.json`.

---

## 12. Weekly MoM

**Module:** `exporter/weekly_mom.py`

Sheets: Cover · Master plan · Gantt · MoM_Wxx · **Risk Analysis** · PM Dashboard · (optional) PM Lịch trình.

- Kế hoạch tuần: Start hoặc End trong tuần ISO (không flood overlap dài).  
- Swap Start>End khi FL sai.  
- Risk đa chiều: overdue, unassigned, stalled, DQ high, risk score, Rlog thiếu PIC…  
- Heading H1/H2/H3 màu đồng bộ mẫu PM.

---

## 13. Chiều PM

**Modules:** `parser/pm_plan_parser.py`, `pm_weekly_parser.py`, `analyzer/pm_store.py`

- KeHoachDuAn: WBS / lịch trình UAT–Golive / deliverables / đội.  
- Weekly PPT: done tuần / next / risk.  
- Auto-hydrate nếu có file trong `pm/` thiếu JSON.  
- Join FL optional (module/PIC trùng).

→ [PM_DIMENSION_GUIDE.md](PM_DIMENSION_GUIDE.md).

---

## 14. Sync refresh

Sau Đồng bộ API thành công:

1. BE: pop + **eager-reload** `_state` từ snapshot mới.  
2. FE: cập nhật Sync time (parse ISO naive đúng) + `cacheBust` dashboard + hủy filter-fetch cũ + reset pageState lazy sections.

---

## 15. Status chuẩn hóa (tham chiếu)

Hợp lệ: `Open`, `Assigned`, `In-progress`, `Resolved`, `Closed`, `Pending`, `Cancelled`.

Closed / Cancelled = “xong / bỏ” cho hầu hết rule tiến độ.  
Blank status xử lý tùy rule (overdue ngoại lệ; unassigned/stalled có điều kiện riêng).

---

## Xem thêm

- [SYSTEM_OVERVIEW.md](SYSTEM_OVERVIEW.md) — big picture  
- [FEATURE_CATALOG.md](FEATURE_CATALOG.md) — map UI/API  
- [DATA_MODEL.md](DATA_MODEL.md) — schema field  
