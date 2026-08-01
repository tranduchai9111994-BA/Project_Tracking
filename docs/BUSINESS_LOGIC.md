# Business Logic — Rule nghiệp vụ end-to-end

> Cập nhật: **2026-08-01**. Rule triển khai trong `analyzer/*` (+ FE filter).  
> Không hardcode tên cột Excel — luôn qua `ParsedData` / `PhaseGroup.task_type`.

---

## 1. Parse Function List

**Module:** `parser/excel_parser.py`

1. Đọc header row 1.
2. Phase group = pattern `PhaseName - Attribute` (Start, End, Status, PIC, Estimate MH, Note, RlogID, Defect…).
3. Meta: Module, Priority, Complexity, FIT/GAP, Giai đoạn, Tên CN, Mã CN, Quy trình, Mã dự án… (keyword match).
4. Status số (1, 2, 8…) ở cột Status → bỏ qua (Estimate MH lệch cột).
5. Estimate MH: reject datetime / outlier lớn; log `estimate_mh_rejected`.
6. PIC: split `,` `;` `+` `\n`; blacklist token status lệch cột.

**Task type** (`PhaseGroup.task_type`): map regex tên phase → Phân tích / Lập trình / Kiểm thử / Cấu hình UAT / UAT / Tài liệu / Cấu hình Golive.

---

## 2. Overdue (trễ deadline)

**Module:** `analyzer/overdue.py` (+ dashboard_engine)

Một phase **overdue** khi:

- Có **End** date hợp lệ  
- `End < today`  
- Status **không** phải Closed / Cancelled  

**Ngoại lệ:** End quá hạn nhưng Status trống, và **phase sau** đã Closed → không coi overdue.

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

---

## 4. Stalled (đình trệ)

**Module:** `analyzer/stalled.py`

Transition “phase trước Closed → phase chờ chưa start” chỉ **stalled** khi:

1. Phase trước = Closed  
2. Phase chờ status None / Open (chưa làm)  
3. **End của phase chờ tồn tại và `end < today`**  
4. Function **chưa** fully done (phase cuối Closed **hoặc** mọi phase ∈ {Closed, Cancelled})

**Không End** trên phase chờ → **không** stalled.

---

## 5. Data Quality

**Module:** `analyzer/data_quality.py`

| Rule | Ý nghĩa |
|------|---------|
| Missing deadline | Thiếu End khi đã tới lượt (cùng gate unassigned) |
| Phase overlap ngày | Hai phase giao ngày — **trừ** whitelist **Config Local ↔ Config UAT** |
| Estimate MH lệch duration | MH vs khoảng Start–End bất thường |
| Invalid status / duplicate… | Severity High / Medium / Low |

UI: filter Module/severity; **highlight** badge trên Module overview / Matrix; help topic `dataquality`.

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

1. Còn phase mở có End → `max(End còn mở)` — `open_max`  
2. Else có Closed có End → `max(End Closed)` — `closed_max`  
3. Else → không có tháng  

Có thể gắn lớp baseline SV khi đã chọn baseline snapshot.

---

## 8. Forecast Manpower (MH / MD / MM & tuyển)

**Module:** `analyzer/forecast_manpower.py`

| Cơ sở (`basis`) | Cách tính MH / phase |
|-----------------|----------------------|
| **unit** | Estimate MH; trống → **mặc định 8** |
| **duration** | Ngày làm Start→End (bỏ T7/CN) × 8; thiếu ngày → fallback unit/default |

| Đơn vị | Quy đổi |
|--------|---------|
| Man-hour | MH |
| Man-day | MH ÷ 8 |
| Man-month | MH ÷ 160 |

**Pool:** Lập trình (riêng) vs Triển khai chung (Phân tích + Kiểm thử + Cấu hình* + UAT + Tài liệu…). Chỉ phase chưa Closed/Cancelled.

```
people_needed = ceil(remaining_MH / (target_months × 160))
hire_needed   = max(0, people_needed − headcount_hiện_tại)
```

**Bổ sung (không thay Manpower):** `analyzer/estimate_ratio.py` — seed BA/Dev + hệ số Des/Test/Doc/UAT…; params trong `estimation_params.json` (project/global). Không ghi đè Estimate MH trên FL.

---

## 9. PIC Overload (đa dự án)

**Module:** `analyzer/pic_overload.py`

Task **active** ngày D: phase có Start–End giao D, status ≠ Closed/Cancelled, PIC multi-parse — **mọi project**.

| Grain | Overload mặc định |
|-------|-------------------|
| Ngày | concurrent > **5** → ngày đỏ |
| Tuần | ≥ **2** ngày đỏ **hoặc** task-days > **25** |
| Tháng | ≥ **5** ngày đỏ **hoặc** task-days > **100** |

Threshold chỉnh Settings. Dùng lại trong PMO risk (Phase D).

---

## 10. Capacity PIC (1 project)

**Module:** `analyzer/advanced_metrics.compute_capacity_load`

Remaining MH (chưa Closed) theo PIC vs `capacity_mh_per_week`.  
Overload nếu `weeks_needed > 4`.

Khác Manpower: Capacity = so với công suất PIC đã cấu hình; Manpower = ước lực lượng / tuyển theo công đoạn.

---

## 11. Baseline Schedule Variance (Phase A)

**Module:** `analyzer/baseline_sv.py`

Khác `advanced_metrics.compute_baseline_variance` (Planned/Actual **cùng file**): module này so **cross-snapshot**.

```
SV (ngày) = end_hiện_tại − end_baseline
```

- Baseline = snapshot được đánh dấu (`baseline_snapshot_id` trong settings).  
- Closed → End (fallback last_updated); Cancelled bỏ qua.  
- SV > 0 = trễ; < 0 = sớm. Chỉ khi cả hai bên có End.  
- Có rollup theo function / milestone / module.

---

## 12. Completion forecast (Phase B)

**Module:** `analyzer/completion_forecast.py`

```
remaining = số phase-record chưa Closed/Cancelled (có status hoặc date)
velocity  = Closed/tuần trung bình 4 tuần (burndown)
weeks_needed = remaining / velocity
forecast_date = today + ceil(weeks_needed) tuần
```

Edge: remaining=0 → done; không lịch sử / velocity=0 → không dự báo (`no_history` / `zero_velocity`).

---

## 13. Earned Value — EVM (Phase C)

**Module:** `analyzer/earned_value.py` — đơn vị MH

| Đại lượng | Định nghĩa |
|-----------|------------|
| **BAC** | Σ Estimate MH mọi phase ≠ Cancelled (trống → 8) |
| **EV** | Σ pct(status) × MH; Closed=100%, Resolved=90%, In-progress=50%, Assigned=25%, Open/Pending/blank=0% |
| **PV** | Theo lịch **baseline**: End≤today→100%; Start>today→0%; giữa khoảng → tỉ lệ ngày làm; không baseline → PV/SPI = N/A |
| **AC** | Proxy không timesheet: Closed Start→End ×8 MH/ngày làm; đang làm Start→today; không Start → không cộng |
| **SPI** | EV / PV |
| **CPI** | EV / AC |

SPI/CPI < 1 = chậm / vượt effort; > 1 = sớm / tiết kiệm.

---

## 14. Scope creep / CR (Phase C)

**Module:** `analyzer/scope_creep.py`

Detection theo thứ tự:

1. Cột Excel auto-detect (header CR / Change Request / Phát sinh / Scope Creep…).  
2. Fallback: tag `CR` hoặc `cr_function_codes` trong settings.

Effort MH: Σ Estimate MH phase ≠ Cancelled (trống → DEFAULT_MH).  
Metrics: số CR vs scope gốc, % creep, MH CR / MH tổng, theo module.

---

## 15. PMO Risk + cascade + overload (Phase D)

**Module:** `risk_scorer.compute_pmo_risk` + `module_dependency.compute_module_cascade`

- Risk score function 0–100 (priority, complexity, overdue, thiếu PIC, duration, stalled, note…).  
- **Resource:** PIC trong tập overload (single-project hoặc set từ `/pic-overload` đa dự án) → cộng điểm / rollup.  
- **Dependency:** cascade delay theo thứ tự module (heuristic đơn giản — không phải graph phụ thuộc FL đầy đủ).  
- API trả resource + dependency + risk list cho UI/PM.

### Risk score (nhắc nhanh)

| Yếu tố | Điểm |
|--------|------|
| Priority Must / Should | +20 / +10 |
| Complexity High / Medium | +15 / +5 |
| Có phase overdue | +20 |
| Mỗi 7 ngày overdue | +10 (cap +30) |
| Phase active không PIC | +15 |
| Duration > threshold | +10 |
| Đình trệ | +10 |
| Risk/Blocker note | +5 |
| PIC overload / cascade (Phase D) | điểm bổ sung theo implement |

Cap 100.

---

## 16. UAT Quality (Phase E)

**Module:** `analyzer/uat_quality.py`

Auto-detect cột: Defect/Bug, Feedback, Reopen, UAT cycle.  
Không có cột → empty state (không bịa số); optional tag `UAT issue` (qualitative).

Metrics: tổng defect, feedback, reopen rate, số vòng UAT, theo module/function — phục vụ chất lượng giao hàng chứ không chỉ Open/Closed.

---

## 17. Critical path (BA — heuristic)

**Module:** `gantt_calendar._annotate_critical_path`

Chọn **một** row (theo group_by hiện tại) có segment **chưa 100%** kết thúc **muộn nhất**.  
Gắn `on_critical_path` + `critical` trên segment unfinished.

**Không phải** Critical Path Method trên dependency graph giữa function.

---

## 18. Bottleneck & Module còn lại

**Module:** `dashboard_engine`

- **Bottleneck:** phase (trong matrix / phase stack) có nhiều WIP hoặc % Closed thấp nhất theo heuristic engine — field `bottleneck` trong payload matrix.  
- **Module còn lại:** `remaining` = function chưa xong phase cuối; `remaining_mh` = Σ MH phase còn mở.

---

## 19. PIC upcoming

**Module:** `analyzer/pic_upcoming.py`

Ma trận PIC × tuần sắp tới: phase chưa Closed/Cancelled có End (hoặc khoảng Start–End) giao tuần đó. Hỗ trợ lập lịch tuần / phát hiện dồn việc.

---

## 20. Function Diff & FL re-import

### Auto-diff

**Module:** `function_diff.py` — so current vs snapshot trước (theo `ma_cn`): thêm/xóa/đổi meta/phase (status, PIC, date…).

### FL re-import export

**Module:** `exporter/fl_reimport_export.py`

- Union issues: overdue, unassigned, stalled, anomalies…  
- 1 sheet Function List; vàng PIC/Status; xanh date-chain (+1 ngày làm); không sheet hướng dẫn.

### FL re-import verify

**Module:** `fl_reimport_verify.py`

So issue yellow-hit (PIC/Status) snapshot trước vs sau theo `ma_cn`: `fixed` / `still_empty` / `unchanged`.  
**Không** verify mọi ô / mọi loại thay đổi.

---

## 21. Weekly MoM

**Module:** `exporter/weekly_mom.py`

Sheets: Cover · Master plan · Gantt · MoM_Wxx · **Risk Analysis** · PM Dashboard · (optional) PM Lịch trình.

Risk đa chiều: overdue, unassigned, stalled, DQ high, risk score, Rlog thiếu PIC…

---

## 22. Chiều PM

**Modules:** `pm_plan_parser`, `pm_weekly_parser`, `pm_store`

- KeHoachDuAn: WBS / lịch trình UAT–Golive / deliverables / đội.  
- Weekly PPT: done / next / risk.  
- Auto-hydrate nếu có file trong `pm/` thiếu JSON.  
- Join FL optional (module/PIC).

→ [PM_DIMENSION_GUIDE.md](PM_DIMENSION_GUIDE.md).

---

## 23. Sync refresh & disk janitor

**Sync thành công:**

1. BE: pop + eager-reload `_state` từ snapshot mới.  
2. FE: Sync time + `cacheBust` dashboard + hủy filter-fetch cũ.

**Startup janitor** (`disk_janitor.py`): xóa export cũ, snapshot dư, giữ tối đa N `synced_*.xlsx`, xóa PPTX weekly trùng khi đã có `pm/weekly.pptx`.

---

## 24. Status chuẩn hóa (tham chiếu)

Hợp lệ: `Open`, `Assigned`, `In-progress`, `Resolved`, `Closed`, `Pending`, `Cancelled`.

Closed / Cancelled = “xong / bỏ” cho hầu hết rule tiến độ.  
Blank status xử lý tùy rule (overdue ngoại lệ; unassigned/stalled có điều kiện riêng).

---

## Xem thêm

- [SYSTEM_OVERVIEW.md](SYSTEM_OVERVIEW.md)  
- [FEATURE_CATALOG.md](FEATURE_CATALOG.md)  
- [CHANGELOG_PMO_BA.md](CHANGELOG_PMO_BA.md)  
- [DATA_MODEL.md](DATA_MODEL.md)  
