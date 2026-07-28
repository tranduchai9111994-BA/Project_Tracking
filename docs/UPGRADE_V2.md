# UPGRADE_V2.md — Nâng cấp Dashboard nâng cao

## Tổng quan

Bản nâng cấp thêm **8 dashboard nâng cao** + **hệ thống so sánh snapshot** vào app hiện tại.
Tất cả logic KHÔNG hardcode cột — kế thừa hệ thống auto-detect của parser hiện có.

> **Cursor: đọc kỹ file này + docs/ARCHITECTURE.md + docs/DATA_MODEL.md trước khi code.**
> Mọi tính năng mới PHẢI tích hợp vào kiến trúc hiện tại, KHÔNG tạo project mới.

---

## PHẦN A — HỆ THỐNG SO SÁNH SNAPSHOT (Compare Mode)

### A1. Mô tả

Cho phép PM upload 2 file Function List (file cũ + file mới) hoặc app tự lưu snapshot mỗi lần upload,
rồi so sánh để biết:

- Tăng/giảm bao nhiêu % hoàn thành giữa 2 lần
- Bao nhiêu function **mới phát sinh** (có trong file mới, không có trong file cũ)
- Bao nhiêu function **bị xóa/hủy**
- Bao nhiêu function **đổi trạng thái** (VD: Assigned → Closed)
- Tốc độ close trung bình (functions closed / ngày)

### A2. Cơ chế lưu Snapshot

```
uploads/
├── snapshots/
│   ├── 2026-07-01_functionlist.xlsx    ← bản cũ nhất
│   ├── 2026-07-15_functionlist.xlsx
│   └── 2026-07-28_functionlist.xlsx    ← bản mới nhất
│   └── snapshot_index.json             ← metadata
```

**snapshot_index.json:**
```json
[
    {
        "date": "2026-07-28",
        "filename": "2026-07-28_functionlist.xlsx",
        "total_functions": 375,
        "total_closed_last_phase": 189,
        "overall_pct": 50.4,
        "overdue_count": 74,
        "upload_time": "2026-07-28T10:30:00"
    }
]
```

**Logic:**
- Mỗi lần upload file mới qua `/api/upload` → tự động lưu 1 bản snapshot
  với tên `{date}_functionlist.xlsx`
- Nếu cùng ngày upload nhiều lần → ghi đè snapshot cùng ngày
- Giữ tối đa 30 snapshots gần nhất
- Cho phép upload thủ công file cũ để so sánh qua `/api/upload-compare`

### A3. API mới

```
POST /api/upload-compare       → Upload file cũ để so sánh với file hiện tại
GET  /api/snapshots            → Danh sách snapshots đã lưu
GET  /api/compare?old=<date>&new=<date>  → So sánh 2 snapshot
DELETE /api/snapshots/<date>   → Xóa 1 snapshot
```

### A4. So sánh logic (CompareEngine)

Tạo file mới: `analyzer/compare_engine.py`

```python
class CompareEngine:
    """So sánh 2 ParsedData objects."""

    def compare(self, old: ParsedData, new: ParsedData) -> CompareResult:
        """
        So sánh dựa trên Mã CN (unique identifier).
        Nếu file không có Mã CN → fallback sang STT + Tên CN.
        """

@dataclass
class CompareResult:
    # Tổng quan
    old_total: int
    new_total: int
    delta_total: int                     # new - old (dương = thêm mới)

    old_overall_pct: float
    new_overall_pct: float
    delta_pct: float                     # new - old (dương = tiến bộ)

    old_overdue: int
    new_overdue: int
    delta_overdue: int

    # Chi tiết function
    new_functions: list[dict]            # Functions có trong new mà không có trong old
    removed_functions: list[dict]        # Functions có trong old mà không có trong new
    status_changes: list[StatusChange]   # Functions đổi status

    # Chi tiết theo module
    module_deltas: dict[str, ModuleDelta]

    # Chi tiết theo phase
    phase_deltas: dict[str, PhaseDelta]

    # Velocity
    velocity: VelocityMetrics

@dataclass
class StatusChange:
    ma_cn: str
    ten_cn: str
    module: str
    phase: str
    old_status: str
    new_status: str
    direction: str                       # "forward" | "backward" | "lateral"

@dataclass
class ModuleDelta:
    module: str
    old_pct: float
    new_pct: float
    delta_pct: float
    new_count: int                       # Functions mới phát sinh
    closed_count: int                    # Functions mới close trong khoảng thời gian

@dataclass
class PhaseDelta:
    phase: str
    old_closed_pct: float
    new_closed_pct: float
    delta_pct: float

@dataclass
class VelocityMetrics:
    days_between: int                    # Số ngày giữa 2 snapshot
    functions_closed: int                # Tổng function mới close
    close_rate_per_day: float            # functions_closed / days_between
    est_days_remaining: float            # (remaining / close_rate) nếu giữ tốc độ
    functions_new: int                   # Tổng function mới phát sinh
    net_progress: int                    # closed - new (dương = giảm backlog)
```

### A5. Dashboard Compare (Frontend)

Thêm section mới phía trên dashboard chính, chỉ hiện khi có ≥ 2 snapshots:

```
┌──────────────────────────────────────────────────────────────┐
│  📊 SO SÁNH VỚI LẦN TRƯỚC                                   │
│  So sánh: [2026-07-15 ▼] → [2026-07-28 ▼]                  │
├────────────┬────────────┬────────────┬────────────────────────┤
│  Tiến độ   │ Overdue    │ Mới phát   │ Tốc độ close          │
│  +5.2% ▲   │ -3 ▼       │ +12 tasks  │ 2.5 func/ngày         │
│  45.2→50.4 │ 77→74      │            │ Còn ~75 ngày          │
├────────────┴────────────┴────────────┴────────────────────────┤
│  MODULE DELTA CHART (grouped bar: old% vs new% per module)   │
├───────────────────────────────────────────────────────────────┤
│  STATUS FLOW (Sankey-style hoặc table)                       │
│  Assigned→Closed: 45  |  Open→Assigned: 12  |  New: 12      │
├───────────────────────────────────────────────────────────────┤
│  DANH SÁCH FUNCTION MỚI PHÁT SINH                            │
│  (table, sortable, exportable)                                │
└───────────────────────────────────────────────────────────────┘
```

**Delta Cards styling:**
- Giá trị dương (tiến bộ): ▲ xanh lá, border-green
- Giá trị âm (thụt lùi): ▼ đỏ, border-red
- Overdue giảm = tốt → xanh lá; Overdue tăng = xấu → đỏ
- Function mới phát sinh luôn hiện cam (cảnh báo scope creep)

---

## PHẦN B — DASHBOARD PHÂN TÍCH NÂNG CAO

### B1. 🚨 Bảng cảnh báo Task không có PIC (Unassigned Tasks)

**Vấn đề thực tế:** Dữ liệu thật cho thấy ~288 task active KHÔNG có PIC phụ trách.
Đây là rủi ro lớn vì không ai chịu trách nhiệm.

**Logic phát hiện:**
```python
def detect_unassigned(data: ParsedData) -> list[dict]:
    """
    Task được coi là UNASSIGNED khi:
    1. Phase có Status (không null, không Closed/Cancelled)
    2. NHƯNG tất cả PIC cols của phase đó đều empty
    """
    results = []
    for row in data.rows:
        for phase_name, pd in row.phases.items():
            if pd.status and pd.status not in ("Closed", "Cancelled", None):
                if not pd.pics:  # Không có PIC nào
                    results.append({
                        "ma_cn": row.meta.get("ma_cn"),
                        "ten_cn": row.meta.get("ten_cn"),
                        "module": row.meta.get("module"),
                        "phase": phase_name,
                        "status": pd.status,
                        "priority": row.meta.get("priority"),
                    })
    return results
```

**Dashboard UI:**
- Bảng giống Overdue Table, có filter Module/Phase
- Summary card riêng: "🚨 X task chưa có PIC"
- Highlight đỏ cho task Must-have chưa có PIC
- Button export Excel riêng

### B2. ⏱️ Duration Analysis — Task kéo dài bất thường

**Vấn đề thực tế:** UAT trung bình 11.6 ngày, có task Analysis kéo dài 105 ngày.

**Logic phát hiện:**
```python
def detect_long_duration(data: ParsedData, threshold_days: int = 3) -> list[dict]:
    """
    Task có duration > threshold khi:
    1. Phase có cả Start date và End date (hoặc From/To, Planned/Actual)
    2. duration = End - Start > threshold_days
    3. Status KHÔNG phải Closed/Cancelled (đang kéo dài)

    Ngoài ra, tính cả ELAPSED duration cho task đang chạy:
    4. Có Start date, KHÔNG có End date, Status = In-progress
    5. elapsed = today - Start > threshold_days
    """
    results = []
    today = date.today()

    for row in data.rows:
        for phase_name, pd in row.phases.items():
            duration = None
            duration_type = None  # "planned" hoặc "elapsed"

            if pd.start_date and pd.end_date:
                duration = (pd.end_date - pd.start_date).days
                duration_type = "planned"
            elif pd.start_date and not pd.end_date and pd.status == "In-progress":
                duration = (today - pd.start_date).days
                duration_type = "elapsed"

            if duration and duration > threshold_days:
                results.append({
                    "ma_cn": row.meta.get("ma_cn"),
                    "ten_cn": row.meta.get("ten_cn"),
                    "module": row.meta.get("module"),
                    "phase": phase_name,
                    "start_date": pd.start_date.isoformat(),
                    "end_date": pd.end_date.isoformat() if pd.end_date else None,
                    "duration_days": duration,
                    "duration_type": duration_type,
                    "status": pd.status,
                    "pic": pd.pics,
                    "priority": row.meta.get("priority"),
                    "estimate_mh": pd.estimate_mh,
                })
    results.sort(key=lambda x: x["duration_days"], reverse=True)
    return results
```

**Dashboard UI:**

```
┌─────────────────────────────────────────────────────────────┐
│ ⏱️ PHÂN TÍCH DURATION                                       │
├──────────────┬──────────────┬──────────────┬────────────────┤
│ Ngưỡng cảnh  │ TB duration  │ Task > 3 ngày│ Task > 7 ngày │
│ báo: [3▼] ng │ 8.3 ngày     │ 76           │ 42            │
├──────────────┴──────────────┴──────────────┴────────────────┤
│                                                             │
│  BOX PLOT / DISTRIBUTION CHART theo Phase                   │
│  (hiển thị min/Q1/median/Q3/max mỗi phase)                 │
│                                                             │
│  Analysis  ──┤    ████████████████         ├──   median=11d │
│  Dev       ──┤ ██                          ├──   median=1d  │
│  Config UAT──┤ █                           ├──   median=1d  │
│  UAT       ──┤      ███████████████████    ├──   median=8d  │
│                                                             │
├─────────────────────────────────────────────────────────────┤
│  SCATTER PLOT: Duration vs Estimate MH                      │
│  (phát hiện task ước lượng ít nhưng kéo dài)                │
│  Trục X: Estimate MH  |  Trục Y: Actual Duration (days)    │
│  Điểm đỏ: task đang In-progress (elapsed)                  │
│  Điểm xanh: task đã có End date                             │
├─────────────────────────────────────────────────────────────┤
│  BẢNG CHI TIẾT (filterable)                                 │
│  Filter: [Phase ▼] [Module ▼] [>3 ngày ▼] [Loại: All ▼]   │
│  Columns: Mã CN | Tên CN | Module | Phase | Start | End |  │
│           Duration | Loại | Status | PIC | Estimate MH      │
│  [📥 Xuất Excel]                                            │
└─────────────────────────────────────────────────────────────┘
```

**Slider ngưỡng:** Cho PM tự chỉnh ngưỡng cảnh báo (mặc định 3 ngày).

### B3. 🔄 Pipeline Flow — Phân tích bottleneck giữa các phase

**Ý tưởng:** Phát hiện task bị "kẹt" giữa 2 phase — VD: Analysis Closed nhưng Dev chưa Assigned.

**Logic:**
```python
def detect_stalled_tasks(data: ParsedData) -> list[dict]:
    """
    Với mỗi function, kiểm tra cặp phase liên tiếp:
    - Phase trước đã Closed
    - Phase sau vẫn là None/Open (chưa bắt đầu)
    → Task bị stalled, cần escalate.

    Thêm: tính wait_days = today - phase_trước.end_date
    """
    results = []
    phases = [pg.name for pg in data.phase_groups]
    today = date.today()

    for row in data.rows:
        for i in range(len(phases) - 1):
            current_phase = phases[i]
            next_phase = phases[i + 1]

            curr_pd = row.phases.get(current_phase)
            next_pd = row.phases.get(next_phase)

            if (curr_pd and curr_pd.status == "Closed" and
                next_pd and next_pd.status in (None, "Open")):

                wait_days = 0
                if curr_pd.end_date:
                    wait_days = (today - curr_pd.end_date).days

                results.append({
                    "ma_cn": row.meta.get("ma_cn"),
                    "ten_cn": row.meta.get("ten_cn"),
                    "module": row.meta.get("module"),
                    "completed_phase": current_phase,
                    "waiting_phase": next_phase,
                    "completed_date": curr_pd.end_date.isoformat() if curr_pd.end_date else None,
                    "wait_days": wait_days,
                    "priority": row.meta.get("priority"),
                })

    results.sort(key=lambda x: x["wait_days"], reverse=True)
    return results
```

**Dashboard UI:**
- **Funnel chart**: Total → Analysis Done → Dev Done → Config Done → UAT Done → Golive
  (hiển thị drop-off ở mỗi bước)
- **Bảng Stalled Tasks** với cột "Chờ X ngày" highlight đỏ nếu > 7 ngày
- **Phase Transition Heatmap**: ma trận phase×phase, ô (i,j) = số task đã qua phase i nhưng chưa bắt đầu j

### B4. 📊 Effort Analysis — Man-hour Estimate vs Actual

**Logic:**
```python
def effort_analysis(data: ParsedData) -> dict:
    """
    Tổng hợp Estimate MH theo:
    - Module × Phase
    - PIC (ai đang gánh nhiều MH nhất)
    - So sánh MH planned vs thực tế (dựa trên duration × 8h/day)
    """
    return {
        "by_module_phase": ...,     # Heatmap: Module × Phase → total MH
        "by_pic": ...,              # Bar chart: PIC → total MH remaining
        "total_estimated": float,
        "total_closed_mh": float,   # MH của task đã Closed
        "remaining_mh": float,
        "burn_rate": float,         # MH closed / tuần gần nhất
        "est_weeks_remaining": float,
    }
```

**Dashboard UI:**
- **MH Heatmap**: Module × Phase, ô hiển thị tổng MH, màu đậm = nhiều effort
- **PIC Effort Bar Chart**: Horizontal bar, stack = Closed MH + Remaining MH
- **Burndown indicator**: Tổng MH remaining + burn rate → ước lượng thời gian còn lại

### B5. 📅 Timeline Gantt-style — Trực quan hóa schedule

**Logic:**
Với mỗi module, lấy min(Start) và max(End) của từng phase → vẽ thanh ngang.

```python
def timeline_data(data: ParsedData) -> dict:
    """
    Cho mỗi Module × Phase:
    - earliest_start: min(start_date) của tất cả functions
    - latest_end: max(end_date) của tất cả functions
    - pct_closed: % đã Closed
    → Vẽ Gantt chart đơn giản
    """
```

**Dashboard UI:**
- Gantt chart nằm ngang (dùng HTML div hoặc Chart.js horizontal floating bar)
- Trục Y: Module / Phase
- Trục X: Timeline (ngày)
- Thanh màu: xanh = đã Closed, vàng = đang làm, đỏ = overdue
- Đường dọc: TODAY marker

### B6. 🏷️ Phân tích theo Quy trình (Business Process)

**Logic:**
Group functions theo cột "Quy trình" thay vì theo Module.

```python
def process_analysis(data: ParsedData) -> list[dict]:
    """
    Mỗi quy trình:
    - Tổng function
    - % Closed (across all phases)
    - Module(s) liên quan
    - Overdue count
    - PIC(s) chính
    """
```

**Dashboard UI:**
- Treemap chart: mỗi ô = 1 quy trình, kích thước = số function, màu = % hoàn thành
- Hoặc table sortable với mini progress bars

### B7. ⚡ Risk Score — Điểm rủi ro tổng hợp cho mỗi Function

**Logic:**
Tính điểm rủi ro 0-100 cho mỗi function dựa trên nhiều yếu tố:

```python
def compute_risk_score(row: FunctionRow, today: date) -> int:
    """
    Tính điểm rủi ro (0-100):

    +20: Priority = Must-have
    +10: Priority = Should-have
    +15: Complexity = High
    +5:  Complexity = Medium
    +20: Có ít nhất 1 phase overdue
    +10: Thêm mỗi 7 ngày overdue (max +30)
    +15: Không có PIC ở phase đang active
    +10: Duration > ngưỡng (3 ngày)
    +10: Bị stalled (phase trước done, phase sau chưa bắt đầu)
    +5:  Có Risk/Blocker note không rỗng

    Cap at 100.
    """
```

**Dashboard UI:**
- **Top 20 High-Risk Functions** table, sort theo risk score giảm dần
- Mỗi row hiển thị: Mã CN, Tên, Module, Risk Score (progress bar đỏ), các risk factors (tags)
- Color coding: ≥80 đỏ, ≥50 cam, ≥30 vàng, <30 xanh

### B8. 📈 Weekly Digest — Tóm tắt tuần tự động

**Logic:**
Khi có ≥ 2 snapshots, tự tính:

```python
def weekly_digest(old: ParsedData, new: ParsedData, days_between: int) -> dict:
    """
    Sinh bản tóm tắt:
    - Tổng function closed trong kỳ
    - Top 3 module tiến bộ nhiều nhất
    - Top 3 module cần chú ý (overdue tăng hoặc progress giảm)
    - Top PIC productive (close nhiều nhất)
    - Cảnh báo: function mới phát sinh, PIC quá tải
    - Dự báo: với tốc độ hiện tại, bao lâu nữa hoàn thành
    """
```

**Dashboard UI:**
- Card dạng "report" style, có thể print/PDF
- Tự động render khi có compare data
- Button "📄 In báo cáo tuần" → mở print dialog hoặc export PDF

---

## PHẦN C — NÂNG CẤP EXPORT

### C1. Export Overdue nâng cao

Thêm các sheet vào file Excel export:

| Sheet              | Nội dung                                          |
|--------------------|----------------------------------------------------|
| Overdue_Report     | (giữ nguyên hiện tại)                              |
| Unassigned_Tasks   | Task chưa có PIC                                   |
| Long_Duration      | Task kéo dài > ngưỡng                              |
| Stalled_Tasks      | Task bị kẹt giữa 2 phase                           |
| High_Risk          | Top functions theo risk score                       |
| Summary            | Tổng hợp: bao nhiêu mỗi loại, biểu đồ mini        |

### C2. Export theo PIC

Cho phép export file riêng cho từng PIC (hoặc nhóm PIC):
- Chỉ chứa task của PIC đó
- Highlight task overdue + task cần PIC nhận thêm
- Mục đích: gửi email cho member tự review + replan

**API:**
```
GET /api/export-by-pic?pic=SonHN6  → Download Excel chỉ chứa task của SonHN6
GET /api/export-full-report        → Download Excel đầy đủ tất cả sheets
```

### C3. Export Compare Report

```
GET /api/export-compare?old=2026-07-15&new=2026-07-28
→ Download Excel gồm:
  - Sheet "So sánh tổng quan": delta cards dạng bảng
  - Sheet "Functions mới": danh sách function mới phát sinh
  - Sheet "Status Changes": danh sách đổi trạng thái
  - Sheet "Module Delta": so sánh % theo module
```

---

## PHẦN D — CẢI THIỆN UX

### D1. Dark mode toggle
- Lưu preference vào localStorage
- Tailwind dark mode class

### D2. Auto-refresh reminder
- Nếu file đã upload > 24h trước → hiện banner nhắc upload file mới
- Hiển thị "Dữ liệu từ: dd/MM/yyyy HH:mm"

### D3. Fullscreen chart
- Click vào bất kỳ chart → expand toàn màn hình (modal)
- Hữu ích khi present trong cuộc họp

### D4. Bookmark / Pin sections
- PM có thể pin các section quan tâm lên đầu
- Lưu vào localStorage

### D5. Search function
- Search bar ở header
- Tìm function theo Mã CN, Tên CN, Module, PIC
- Hiện popup kết quả nhanh với link đến section liên quan

---

## PHẦN E — IMPLEMENTATION PLAN CHO CURSOR

### Thứ tự ưu tiên (P1 → P3)

**P1 — Làm ngay (impact cao, effort vừa):**
1. B1: Unassigned Tasks (đơn giản, data sẵn, rủi ro cao)
2. B2: Duration Analysis (đơn giản, data sẵn)
3. B3: Pipeline/Stalled Tasks (bottleneck detection)
4. B7: Risk Score (tổng hợp từ B1+B2+B3)
5. C1: Export nâng cao (multi-sheet)

**P2 — Làm tiếp (impact cao, effort lớn):**
6. A: Compare Mode + Snapshot system (cần thêm storage logic)
7. B4: Effort/MH Analysis
8. C2: Export theo PIC
9. B8: Weekly Digest (cần compare mode)

**P3 — Nice to have:**
10. B5: Timeline Gantt
11. B6: Process Analysis (treemap)
12. C3: Export Compare
13. D1-D5: UX improvements

### Cách tích hợp vào code hiện tại

**Backend:**
```
analyzer/
├── dashboard_engine.py          ← THÊM methods mới vào class hiện có
├── compare_engine.py            ← FILE MỚI cho compare logic
├── risk_scorer.py               ← FILE MỚI cho risk score
```

**Frontend:**
```
templates/index.html             ← THÊM sections mới
static/js/
├── dashboard.js                 ← THÊM render functions
├── compare.js                   ← FILE MỚI cho compare UI
```

**API routes thêm vào app.py:**
```python
# Snapshot & Compare
POST /api/upload-compare
GET  /api/snapshots
GET  /api/compare
DELETE /api/snapshots/<date>

# Advanced analytics
GET  /api/unassigned
GET  /api/long-duration?threshold=3
GET  /api/stalled
GET  /api/risk-scores

# Advanced export
GET  /api/export-full-report
GET  /api/export-by-pic?pic=<name>
GET  /api/export-compare?old=<date>&new=<date>
```

### Lưu ý kỹ thuật

1. **Giữ nguyên parser auto-detect** — tất cả tính năng mới đều dùng `ParsedData` object hiện có
2. **Không dùng database** — snapshot lưu file + JSON index, đủ cho app local
3. **Chart.js plugins cần thiết:**
   - Gantt: dùng floating bar chart (Chart.js native)
   - Treemap: `chartjs-chart-treemap` (CDN)
   - Box plot: tự vẽ bằng floating bar
4. **Performance:** File 375 rows xử lý < 1 giây. Nếu file lớn (>2000 rows), 
   cân nhắc lazy loading cho scatter plot và timeline
5. **Test:** Luôn test với file mẫu `/uploads/sample_functionlist.xlsx`
