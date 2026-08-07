# Business Logic — Rule nghiệp vụ end-to-end

> Cập nhật: **2026-08-04**. Rule triển khai trong `analyzer/*` (+ FE filter).  
> Không hardcode tên cột Excel — luôn qua `ParsedData` / `PhaseGroup.task_type`.

---

## 1. Parse Function List

**Module:** `parser/excel_parser.py`

1. Đọc header row 1.
2. Phase group = pattern `PhaseName - Attribute` (Start, End, Status, PIC, Estimate MH, Note, RlogID, Defect…).
3. Meta: Module, Priority, Complexity, FIT/GAP, Giai đoạn, Tên CN, Mã CN, Quy trình, FID, Mã dự án… (keyword match).
4. Status số (1, 2, 8…) ở cột Status → bỏ qua (Estimate MH lệch cột).
5. Estimate MH: reject datetime / outlier lớn; log `estimate_mh_rejected`.
6. PIC: split `,` `;` `+` `\n`; blacklist token status lệch cột.
7. **Normalize status** (`_normalize_status(value, has_pic)`):
   - Canonical: Open, Assigned, In-progress, Resolved, Closed, Pending, Cancelled
   - **Not Started / Chưa bắt đầu:** không PIC → `Open`; có PIC → `Assigned`
   - Alias tĩnh: Finished/Done/Complete/Hoàn thành → `Closed`; In Progress → `In-progress`; …
   - Status lạ / unknown → `None` (blank)

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

**Module:** `analyzer/stalled.py` (+ `dashboard_engine._stalled_tasks`, `drill_down._filter_stalled`, `risk_scorer`)

Transition **stalled** khi:

1. Phase trước = **Closed**
2. Phase sau chưa bắt đầu (`None` / `Open` / thiếu phase)
3. Function **chưa** fully done (phase cuối Closed **hoặc** mọi phase ∈ {Closed, Cancelled})
4. **Gate thêm:** mọi phase **trước** index hiện tại đã Closed/Cancelled (`prev_phases_all_closed`)  
   → nếu Analysis chưa Closed thì **không** flag stalled các cặp phase phía sau

**Nới rule (2026-08):** **không** yêu cầu End của phase chờ đã quá.  
`waiting_phase_deadline_passed` vẫn tồn tại (helper) nhưng **không** còn là điều kiện bắt buộc của `is_stalled_transition`.

---

## 4b. Module overview — Còn lại & Đánh giá

**Module:** `dashboard_engine._one_overview_entry` + `drill_down` (`scope`)

| Trường | Ý nghĩa |
|--------|---------|
| **Còn lại** | Function chưa Closed **phase cuối** (Golive…) |
| **Drill mặc định** | `scope=remaining` — chỉ list khớp cột Còn lại |
| **Filter Tất cả** | `scope=all` — toàn module/process |
| **risk_level** | Theo **%** overdue / stalled (không flag risk chỉ vì `stalled_count > 0`): risk nếu overdue>20% **hoặc** stalled>20%; warning nếu overdue>10% / stalled>10% / progress<50%; còn lại safe. `risk_reason` cho tooltip. |

---

## 5. Data Quality

**Module:** `analyzer/data_quality.py`

| Rule | Ý nghĩa |
|------|---------|
| Missing deadline | Thiếu End khi đã tới lượt (cùng gate unassigned) |
| Phase overlap ngày | Hai phase giao ngày — **trừ** whitelist **Config Local ↔ Config UAT** |
| Estimate MH lệch duration | MH vs khoảng Start–End bất thường |
| Invalid status / duplicate… | Severity High / Medium / Low |

### Bỏ qua function chưa tới deadline Analysis (rule PMO 06/08/2026b)

Gate theo phase **Phân tích** (`task_type` / tên chứa `analy`):

| Tình trạng Analysis | DQ |
|---|---|
| Có End/Start **> today** (chưa tới deadline) | **Skip toàn bộ** function — không đưa lên DQ |
| Đã tới deadline nhưng **chưa Closed** | Chỉ flag issue của **phase Analysis** («cái gần nhất»). Không flag Config / Document / Dev overlap phía sau — phân tích chưa xong thì task sau chưa actionable |
| **Closed** (hoặc không có phase Analysis) | Quét DQ bình thường |

Áp dụng trong `compute_data_quality`, `count_missing_deadlines`, `count_anomalies`.

### Bỏ qua function đã Closed toàn bộ (rule PMO 06/08/2026)

`is_row_fully_done(row)` = True ⇔ có ít nhất 1 phase `Closed`/`Cancelled` **và**
không phase nào ở trạng thái active (`Open`/`Assigned`/`In-progress`/`Resolved`/
`Pending`). Blank status coi như "phase không áp dụng" — không cản kết luận done.

Những row fully-done **bị skip toàn bộ** trong `compute_data_quality`,
`count_missing_deadlines`, `count_anomalies`:

- Không flag `missing_deadline`, `blank_pic`, `blank_priority`, `blank_complexity`,
  `blank_fitgap`, `phase_overlap`, `estimate_vs_duration`, `closed_no_end`,
  `end_before_start`, `invalid_status`.
- Không tính vào `by_severity` / `by_code` / `affected_rows`; nhưng **vẫn tính
  vào `total_rows` và `clean_rows`** để `clean_pct` phản ánh đúng "bao nhiêu
  function không có issue".
- Không tính vào duplicate: nếu tất cả copies của cùng `ma_cn` đều fully-done
  thì duplicate không còn actionable → không đếm. Chỉ khi ít nhất 2 copies vẫn
  chưa done mới flag `duplicate_ma_cn` cho các copy chưa done đó.

Lý do: MPHG có 1310+ issue DQ, đa số là function đã đóng nhiều tháng trước, ép
PM backfill Priority/FIT-GAP không còn actionable. Rule này bám sát nguyên tắc
"DQ dùng để clean data trước khi báo cáo cấp trên" — báo cáo là cho công việc
đang chạy, không phải xới lại kho đóng.

UI: filter Module/severity; **highlight** badge trên Module overview / Matrix; help topic `dataquality`.

---

## 5b. FID Check (Issues hub)

**Module:** `analyzer/fid_check.py` · API `/fid-check` · section `section-fid-check`

Khi phase **Dev** (tên chứa dev/coding) đã **Closed**:

- `missing_fid` — cột FID trống  
- `duplicate_fid` — cùng FID trên >1 function  

Export FL re-import có thể tô vàng cột FID (`fid_issues=1`).

### Hai chế độ xuất cho tab issue (2026-08d)

Mỗi tab issue cho chọn 2 kiểu file, **chỉ gồm record có vấn đề của đúng tab đó**:

| Chế độ | Endpoint | Nội dung | Import lại được? |
|---|---|---|---|
| **Danh sách lỗi** | `/export-fid-issues` (FID), `/export-overdue`, `/export-stalled`, `/export-data-quality`, `/export-chart` | Đúng các cột của lưới + 1 cột trống để điền tay | ❌ sheet `Loi_FID` |
| **FL để import** | `/export-fl-reimport?kinds=<kind>` | FL đầy đủ 65 cột, header dòng 1, tô vàng ô cần sửa | ✅ sheet `Function List` |

`kinds` ∈ `overdue \| unassigned \| stalled \| dq \| fid` (comma-sep). **Không truyền
`kinds` → union đầy đủ như trước** để nút «Xuất FL chỉnh sửa» ở Archive không đổi
hành vi. Trước khi có `kinds`, đứng ở tab Thiếu FID bấm xuất ra **224–256 dòng**
của mọi loại issue trong khi chỉ có **47 dòng** lỗi FID.

Filter cục bộ của widget cũng được forward để file khớp bảng:

| Param | Tab | Field so khớp |
|---|---|---|
| `l_module` | overdue / unassigned / stalled | `module` |
| `l_phase`, `l_pic` | overdue | `phase`, `pic` |
| `l_waiting_phase` | stalled | `waiting_phase` |
| `fid_module`, `fid_type` | FID | `module`, `issue_type` |

`pic` trong `overdue_list` là **list** nên bộ so khớp phải kiểm tra giao nhau, không
so string — so string sẽ luôn ra 0 dòng.

### Cảnh báo tụt số dòng khi upload (2026-08d)

Upload **thay thế toàn bộ** dữ liệu project, **không merge** theo Mã CN. Việc thu
nhỏ file «FL để import» xuống vài chục dòng làm rủi ro upload nhầm nặng hơn: dashboard,
badge, EVM sai ngay mà không có dấu hiệu gì. Nay nếu file mới có số dòng
`< ROW_DROP_WARN_RATIO` (0.70) so với bản upload trước → warning `row_count_drop`
mức `critical`, kèm tên/số dòng bản trước và hướng dẫn khôi phục snapshot.

Chỉ cảnh báo, **không chặn** — thu hẹp scope thật cũng là việc hợp lệ. Cảnh báo
critical hiển thị bằng **banner cố định** `#uploadCriticalWarn` chứ không phải toast,
vì toast tự tắt sau 3.5s là quá yếu cho lỗi mất dữ liệu (và chỉ có 1 element toast
dùng chung nên nhiều cảnh báo sẽ đè nhau).

### Module "không dùng FID" (2026-08d)

Một số module không dùng FID (VD ở MPHG: `APP`, `ESS` — 0/14 và 0/4 row có FID),
nên `missing_fid` cho chúng là noise. Backend trả thêm:

| Field | Nội dung |
|---|---|
| `module_stats` | `{module: {rows, with_fid, dev_closed}}` |
| `modules_without_fid` | module có `with_fid == 0` |

UI bỏ check các module này theo mặc định. Điều kiện suy từ **dữ liệu**, không
hardcode mã module — FL đổi mã hoặc dự án khác vẫn đúng.

Đánh đổi đã chấp nhận: module nhỏ mà team chỉ *chưa kịp* điền FID cũng bị coi là
"không dùng FID" và ẩn mặc định. Giảm thiểu bằng banner ghi rõ module bị ẩn kèm
lý do + lựa chọn được nhớ theo project, PM chỉnh 1 lần là xong. Nếu **mọi**
module đều `with_fid == 0` (VD file thiếu cột FID) thì check hết — thà hiện dư
còn hơn bảng trống làm PM tưởng đã đủ FID.

Filter cục bộ (`fid_module`, `fid_type`) áp cả vào `export-fl-reimport` để file
xuất khớp bảng. Module rỗng đi qua wire bằng token `__no_module__` (CSV không
chở được chuỗi rỗng), UI hiển thị `(Chưa có Module)`.

4 card tổng hợp chạy theo filter, kèm ghi chú `toàn bộ: N`. Badge sidebar **cố
ý** giữ số toàn bộ — badge là chỉ báo "dự án còn N vấn đề" như các tab issue khác.

---

## 5b2. Checklist lấy source test Rlog (Issues hub)

**Module:** `analyzer/source_checklist.py` · API `/source-checklist` · section `section-source-checklist`

Quy trình: mỗi Rlog có phase Dev **đến hạn** (End date rơi vào lookback, không cần Dev.Closed) đều phải làm checklist lấy source đưa lên môi trường test, **người lấy source là người config local**. Bỏ ràng buộc Dev.Closed để Config Local chuẩn bị sớm ngay khi dev push — tránh chờ dev đóng phase mới làm.

| Khái niệm | Logic |
|-----------|--------|
| Ngày Dev đến hạn | End date của phase Dev, **không phụ thuộc Status** (chỉ loại `Cancelled`) — thay đổi Aug 2026, trước đây yêu cầu `Closed` |
| Field payload | `coded_date` (giữ tên BC — nghĩa mới = End date Dev), thêm `dev_status` để UI phân biệt Closed vs In-progress |
| Phase người lấy source | Auto-detect tên chứa `local` + (`config`/`cấu hình`/`cfg`); fallback phase ngay sau Dev (`taker_phase_source = next_after_dev`) |
| Đã lấy source | Phase taker có PIC **và** đã bắt đầu (có Start, hoặc Status ∈ Assigned/In-progress/Resolved/Closed/Pending) |
| `no_taker` | Phase taker không có PIC → severity **high** |
| `not_started` | Có PIC nhưng chưa Start và Status Open/trống → **medium**, ≥3 ngày kể từ Dev đến hạn → **high** |
| `no_taker_phase` | Function thiếu hẳn phase taker → **high** |
| Không cần lấy | Dev.Status = **Cancelled** hoặc phase taker **Cancelled** → `not_required`, không cảnh báo |
| Cửa sổ quét | `lookback_days` mặc định **14** (clamp 1–365); ngày ngoài cửa sổ (kể cả tương lai) đếm vào `out_of_window` |
| Scope Rlog | Theo `rlog_weekly`: có RlogID filled → chỉ function có RlogID; ngược lại mọi function |

Output group 2 cấp: `days[]` (sort giảm dần theo ngày, pending xếp trước done trong ngày) → `items[]`.

---

## 5c. Thời gian dài (Duration flag)

**Module:** `analyzer/duration_flag.py` · API `/duration-flag` · section `section-duration-flag`

Phase có cả Start + End, status **chưa** Closed/Cancelled, `(end - start).days > threshold` (mặc định **60**). Bỏ outlier date. Phase đã Closed dù kế hoạch dài ngày cũng **không** đưa vào (đã xong — không actionable). UI chỉnh ngưỡng + filter phase.

---

## 5d. Báo cáo tuần GAP

**Module:** `analyzer/weekly_gap_report.py` + `exporter/weekly_gap_exporter.py`  
API `/weekly-gap-report`, `/export-weekly-gap` · section `section-weekly-gap`

**“Sẽ xong tuần này”** khi phase chưa Closed/Cancelled và:

- End nằm trong tuần Mon–Fri của `week_offset`, **hoặc**
- Status = In-progress và End ≤ cuối tuần  

Filter FIT/GAP/All. Excel: Sheet1 pivot Module×Phase; Sheet2 chi tiết (vàng In-progress, cam quá hạn).

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

- Baseline = bản đã chốt trong chuỗi baseline (mục 11a); `baseline_snapshot_id` giờ
  chỉ còn là con trỏ "baseline đang hiệu lực" cho tương thích ngược.
- Closed → End (fallback last_updated); Cancelled bỏ qua.  
- SV > 0 = trễ; < 0 = sớm. Chỉ khi cả hai bên có End.  
- Có rollup theo function / milestone / module.

---

## 11a. Chuỗi baseline bất biến (re-baseline)

**Module:** `analyzer/baseline_manager.py`

Baseline không còn là một field trỏ vào `snapshots/`. Mỗi lần PM bấm «Chốt baseline»,
file `.xlsx` và pickle được **copy** sang `uploads/projects/<slug>/baselines/` kèm
`sha256` và `version` tăng dần (v1, v2, v3...).

Lý do phải copy chứ không trỏ:

| Rủi ro của cách cũ | Cách chuỗi baseline xử lý |
|---|---|
| Snapshot bị prune khi vượt cap (`MAX_SNAPSHOTS`) → baseline biến mất | File nằm ngoài `snapshots/` nên prune không với tới |
| Upload lần 2 cùng ngày ghi đè snapshot → nội dung baseline âm thầm đổi | Bản chốt giữ nguyên; lệch checksum chỉ bật cờ `source_drifted` để UI cảnh báo |

- `resolve_latest(as_of)` = baseline có `snapshot_date` lớn nhất mà `<= as_of`.
  Đây chính là "baseline gần nhất" — bản mới kéo về sẽ so với nó.
- Xóa 1 baseline → con trỏ legacy tự lùi về bản còn lại gần nhất.
- Project cũ chỉ có `baseline_snapshot_id`: lần đầu đọc sẽ tự pin bản đó vào chuỗi
  (migration êm). Nếu file snapshot đã mất thì fallback đường cũ, không raise.

## 11b. Mốc so sánh và delta bảng Module

**Module:** `analyzer/compare_base.py` + `analyzer/module_delta.py`

Mốc so sánh có 4 chế độ, vì "bản trước" và "tuần trước" trong hệ thống này KHÁC nhau
(snapshot chỉ 1 bản/ngày và chỉ sinh khi upload/sync):

| mode | Chọn gì | Nhãn ví dụ |
|---|---|---|
| `baseline` | baseline gần nhất đã chốt | `Baseline v2 — Approved 07 · 01/07/2026` |
| `week` | bản gần nhất có ngày `<= today − 7` | `Tuần trước · 29/07/2026` |
| `previous` | `snapshots[1]` (quy ước cũ của function-diff) | `Bản trước · 03/08/2026` |
| `date` | 1 bản cụ thể do user chọn | `Bản 20/07/2026` |

Không tìm được mốc → trả `error` tiếng Việt, không raise; UI hiện banner và tắt delta.

Delta join theo `(module, process)` trên hai list do `_overview_by()` sinh ra (không
tự tính lại để khỏi lệch công thức với bảng gốc). Mỗi nhóm có 8 số:

```
total_delta / total_delta_pct
progress_delta (điểm phần trăm) / progress_delta_pct (tương đối)
overdue_delta / overdue_delta_pct
remaining_delta / remaining_delta_pct
```

Quy ước bắt buộc:

- **Tiến độ đã là phần trăm** → chiều "số lượng" của nó là **điểm phần trăm** (pp):
  72% → 78% là `+6pp`, không phải `+6%`. Chiều "%" mới là tương đối (`+8.3%`).
- `*_delta_pct` = `None` khi giá trị mốc bằng 0 → UI hiện `—`, không chia 0.
- Nhóm chỉ có ở bản hiện tại → `is_new=True`, mọi delta `None` (hiện "Mới", không `+100%`).
- Nhóm chỉ có ở bản mốc → vào `removed[]` và hiện thành ghi chú dưới bảng, không chèn
  row giả để không phá drill-down.
- `polarity` quyết định màu: Tiến độ tăng là tốt, Trễ tăng là xấu, Còn lại giảm là tốt,
  SL tăng là trung tính (dấu hiệu scope creep → tô cam).
- Global filter được áp lên **cả** bản mốc trước khi tính, nếu không hai bên so trên hai
  tập function khác nhau.
- Module bị **đổi tên** giữa hai bản sẽ hiện thành một nhóm mới + một nhóm đã mất
  (chưa map tên).

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
- **Gantt lịch trình PM (Phase A–B):** UI bars từ `plan.schedule` Start–End; overdue khi chưa xong + End < today; actual slip khi có Ngày hoàn thành.

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
