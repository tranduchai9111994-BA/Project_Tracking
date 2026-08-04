# Lộ trình nâng cấp iHRP Tracker — 3 gói chính

> Mỗi mục = 1 prompt gửi Cursor. Cursor làm xong → report → bạn verify → quyết định next.
> Thứ tự: Gói A (reorder flow) → Gói B (BA task management) → Gói C (smart suggestion).
> `pytest -q` trước và sau mỗi mục. Không gộp mục.

---

# GÓI A: REORDER DASHBOARD THEO FLOW CÂU HỎI PM

**Triết lý:** Dashboard trả lời 5 câu hỏi theo đúng thứ tự PM nghĩ:
```
Q1. Dự án đang tới đâu rồi?
Q2. Phân hệ nào đang risk, phân hệ nào an toàn?
Q3. Khâu nào (BA/Dev/Test/Config/UAT) đang có rủi ro?
Q4. Cụ thể đầu việc nào đang rủi ro? (trễ, chưa PIC, overload)
Q5. Cần bổ sung nguồn lực gì?
BONUS: Gợi ý dashboard nên bật thêm cho giai đoạn hiện tại.
```

Các section không thuộc 5 câu hỏi → **MẶC ĐỊNH ẨN**, chỉ hiện khi user bật.

---

## A1. Tách section thành 2 nhóm: CORE (luôn hiện) và EXTENDED (mặc định ẩn)

**File sửa:** `static/js/dashboard.js`, `templates/index.html`

**CRUD:**
- **READ:** Đọc `localStorage` key `ihrp.visible_sections` — mảng section-id đang hiện.
- **CREATE:** Lần đầu (chưa có key) → set mặc định = danh sách CORE bên dưới.
- **UPDATE:** Khi user bật/tắt section → cập nhật mảng + re-render sidebar.
- **DELETE:** Nút "Mặc định" reset về CORE list.

**Danh sách CORE (5 nhóm, luôn hiện, đúng thứ tự):**

```javascript
const DEFAULT_CORE_SECTIONS = [
  // Q1 — Dự án đang tới đâu?
  'section-summary',           // Cards + Insight + Completion forecast

  // Q2 — Phân hệ nào risk, phân hệ nào safe?
  'section-module',            // Bảng Module (đã có cột % done, còn lại, MH)

  // Q3 — Khâu nào có rủi ro?
  'section-matrix',            // Phase × Module matrix + bottleneck highlight

  // Q4 — Đầu việc cụ thể nào rủi ro?
  'section-overdue',           // Trễ deadline
  'section-unassigned',        // Chưa PIC
  'section-stalled',           // Đình trệ

  // Q5 — Cần bổ sung nguồn lực?
  'section-forecast-manpower', // Manpower MH/MD/MM + tuyển

  // BONUS — Gợi ý dashboard nên bật
  'section-smart-suggest',     // MỚI — xem mục A7
];
```

**Danh sách EXTENDED (mặc định ẨN):**
```javascript
const DEFAULT_EXTENDED_SECTIONS = [
  'section-tasktype',
  'section-phase',
  'section-giaidoan',
  'section-gantt',
  'section-forecast-gantt',
  'section-gantt-calendar',
  'section-burndown',
  'section-rlog',
  'section-aging-wip',
  'section-sla',
  'section-dataquality',
  'section-risk',
  'section-uat-quality',
  'section-capacity',
  'section-pic-overload',
  'section-pic-upcoming',
  'section-baseline',
  'section-evm',
  'section-scope-creep',
  'section-effort',
  'section-duration',
  'section-process',
  'section-pic-workload',
  'section-priority',
  'section-complexity',
  'section-fitgap',
  'section-function-diff',
  'section-kanban',
  'section-bookmarks',
  'section-pm',
  'section-digest',
  'section-compare',
  'section-custom-dashboards',
  'section-history',
];
```

**Verify:** Mở dashboard → chỉ thấy 8 section (7 CORE + 1 smart-suggest). Sidebar chỉ hiện 8 mục. Bấm toggle section từ View menu → section ẩn hiện lên, sidebar cập nhật.

**Report lại:** Chụp screenshot dashboard chỉ có CORE sections + sidebar. Liệt kê section đã ẩn.

---

## A2. Nâng cấp section Module (Q2) — thêm cột Risk Level per module

**File sửa:** `analyzer/dashboard_engine.py`, `templates/index.html`, `static/js/dashboard.js`

**Logic bổ sung cho mỗi module:**
```python
# Trong compute_module_overview hoặc compute_all
module_risk_level = 'safe'  # default
if module_overdue_pct > 20 or module_stalled_count > 0:
    module_risk_level = 'risk'
elif module_overdue_pct > 10 or module_progress_pct < 50:
    module_risk_level = 'warning'
# else: 'safe'
```

**CRUD:**
- **READ:** `GET /api/projects/<slug>/dashboard` → `module_overview[].risk_level` (thêm field).
- FE: cột mới "Đánh giá" hiện badge:
  - 🟢 An toàn — `background: var(--bg-success)`
  - 🟡 Cần theo dõi — `background: var(--bg-warning)`
  - 🔴 Rủi ro — `background: var(--bg-danger)`
- Cho phép **sort theo risk_level** (risk lên đầu).

**Verify:** Bảng Module hiện cột Đánh giá, sort risk lên trên. Global filter chọn 1 module → toàn bộ dashboard lọc theo module đó.

**Report lại:** Screenshot bảng Module có cột mới. Liệt kê rule tính risk_level.

---

## A3. Nâng cấp section Matrix (Q3) — highlight khâu rủi ro rõ hơn

**File sửa:** `analyzer/dashboard_engine.py` (phase_status_matrix), FE

**Hiện tại:** Matrix có bottleneck field nhưng visual chưa rõ.

**Bổ sung:**
- Cell có >30% overdue: tô nền đỏ nhạt + tooltip "X% trễ hạn".
- Cell có >50% chưa bắt đầu mà đã qua Start date: tô nền cam nhạt.
- Hàng tổng (summary row dưới cùng) per phase: hiện % risk và badge tương tự module.
- Cột tổng (summary column bên phải) per module: hiện overall phase health.

**CRUD:**
- **READ:** Response `phase_matrix` thêm `cell_risk_class` per cell (`risk` | `warning` | `safe`).
- FE: apply CSS class `matrix-cell--risk`, `matrix-cell--warning`.

**Verify:** Matrix hiện highlight đỏ/cam trên cell rủi ro. Hover tooltip giải thích.

**Report lại:** Screenshot matrix có highlight. Liệt kê rule tô màu.

---

## A4. Gom 3 section cảnh báo (Q4) thành 1 section có tabs

**File sửa:** `templates/index.html`, `static/js/dashboard.js`

**Hiện tại:** `section-overdue`, `section-unassigned`, `section-stalled` là 3 section riêng biệt.

**Đổi thành:** 1 section `section-issues` chứa 3 tabs:

```html
<section id="section-issues" class="dashboard-card">
  <h3>⚠️ Đầu việc rủi ro</h3>
  <div class="section-tabs">
    <button class="tab active" data-tab="overdue">
      Trễ hạn <span class="tab-badge tab-badge--danger">3</span>
    </button>
    <button class="tab" data-tab="unassigned">
      Chưa PIC <span class="tab-badge tab-badge--warning">1</span>
    </button>
    <button class="tab" data-tab="stalled">
      Đình trệ <span class="tab-badge tab-badge--muted">0</span>
    </button>
  </div>
  <div class="tab-pane active" id="tab-overdue">
    <!-- nội dung section-overdue hiện tại MOVE vào đây -->
  </div>
  <div class="tab-pane" id="tab-unassigned">
    <!-- nội dung section-unassigned hiện tại MOVE vào đây -->
  </div>
  <div class="tab-pane" id="tab-stalled">
    <!-- nội dung section-stalled hiện tại MOVE vào đây -->
  </div>
</section>
```

**CRUD:**
- **READ:** Active tab lưu `localStorage` key `ihrp.tab.section-issues`.
- **UPDATE:** Click tab → switch pane + save to localStorage.
- Badge count lấy từ `summary.total_overdue`, `summary.unassigned_count`, stalled count đã có.

**Quan trọng:** Giữ nguyên API routes `/api/projects/<slug>/overdue`, `/unassigned`, `/stalled` — chỉ thay đổi FE layout.

**Verify:** 1 section "Đầu việc rủi ro" với 3 tabs + badge count. Click tab switch mượt. Refresh giữ tab cuối.

**Report lại:** Screenshot section tabs. Confirm 3 API routes vẫn hoạt động.

---

## A5. Section Forecast Manpower (Q5) — auto-fill target + warning

**File sửa:** `analyzer/forecast_manpower.py`, FE

**Sửa 1 — Target default:**
```python
# Thay target_months default = 1 thành:
from analyzer.forecast_gantt import compute_forecast_gantt
forecast = compute_forecast_gantt(...)
golive_month = forecast.get('golive_month')  # e.g. '12/2026'
if golive_month:
    target_months = max(1, ceil((golive_date - today).days / 30))
else:
    target_months = 3  # fallback
```

**Sửa 2 — Warning seed nổi bật:**
```javascript
if (seedPct > 50) {
  // Wrap bảng kết quả trong border warning
  tableWrapper.classList.add('seed-warning-active');
  // Banner trên bảng
  showBanner(`⚠️ ${seedPct}% function dùng estimate mặc định — 
    kết quả mang tính THAM KHẢO. Nhập Estimate MH thực tế trên FL.`,
    'warning');
}
```

**CRUD:** Không có CRUD mới — chỉ sửa logic tính + FE display.

**Verify:** Mở Forecast Manpower → target pre-fill = số tháng đến Golive (không phải 1). Bảng có border cam + banner khi seed > 50%.

**Report lại:** Screenshot Manpower với target auto-fill + warning banner. In ra target_months đã tính.

---

## A6. Sidebar redesign cho CORE flow

**File sửa:** `templates/index.html` (sidebar), `static/js/dashboard.js`, `static/css/style.css`

**Sidebar mới chỉ hiện CORE sections:**
```
🔍 Tìm section...           ← search bar
─────────────────────────────
📊 Tổng quan                 ← Q1
📦 Phân hệ                   ← Q2, badge risk count
📋 Ma trận khâu              ← Q3
⚠️ Đầu việc rủi ro     3 1 0 ← Q4, 3 badge counts
👥 Nguồn lực                 ← Q5
─────────────────────────────
💡 Gợi ý dashboard           ← BONUS
─────────────────────────────
📂 Thêm dashboard...    ▾    ← expandable list section ẩn
```

**"Thêm dashboard"** khi expand hiện checkbox list toàn bộ EXTENDED sections, tick = bật.

**CRUD:**
- **READ:** `localStorage` `ihrp.visible_sections`.
- **UPDATE:** Tick checkbox → thêm section vào visible list → section hiện lên trên dashboard + sidebar.
- **DELETE:** Untick → ẩn section + remove khỏi sidebar.

**Verify:** Sidebar gọn 7 mục. Bấm "Thêm dashboard" → thấy list checkbox. Tick "Burndown" → section hiện lên. Untick → ẩn lại. Refresh giữ state.

**Report lại:** Screenshot sidebar gọn + "Thêm dashboard" expanded.

---

## A7. Section Smart Suggest (BONUS) — gợi ý dashboard nên bật

**File MỚI:** `analyzer/smart_suggest.py`
**File sửa:** `app.py` (thêm route), FE (thêm section)

**Logic gợi ý dựa trên data hiện tại:**

```python
def compute_smart_suggestions(state, project_settings):
    suggestions = []
    summary = state['summary']
    
    # Giai đoạn dự án
    progress = summary['overall_progress_pct']
    
    # --- Gợi ý theo metrics ---
    if summary.get('total_overdue', 0) > 10:
        suggestions.append({
            'section_id': 'section-aging-wip',
            'title': 'WIP tồn đọng',
            'reason': f'{summary["total_overdue"]} function trễ — bật WIP để xem đầu việc tồn đọng lâu nhất và ưu tiên xử lý.',
            'priority': 'high',
        })
    
    if summary.get('high_risk_count', 0) > 20:
        suggestions.append({
            'section_id': 'section-risk',
            'title': 'Risk Score chi tiết',
            'reason': f'{summary["high_risk_count"]} function rủi ro cao — bật Risk Score để xem yếu tố gây rủi ro.',
            'priority': 'high',
        })

    if summary.get('dq_high_count', 0) > 5:
        suggestions.append({
            'section_id': 'section-dataquality',
            'title': 'Chất lượng dữ liệu',
            'reason': f'{summary["dq_high_count"]} lỗi data nghiêm trọng — bật DQ để làm sạch FL.',
            'priority': 'high',
        })
    
    # --- Gợi ý theo giai đoạn ---
    if progress < 30:
        # Giai đoạn đầu — focus phân tích + scope
        suggestions.append({
            'section_id': 'section-scope-creep',
            'title': 'Theo dõi Scope Creep',
            'reason': 'Dự án đầu giai đoạn — bật Scope Creep để kiểm soát phát sinh sớm.',
            'priority': 'medium',
        })
        suggestions.append({
            'section_id': 'section-rlog',
            'title': 'Rlog tuần',
            'reason': 'Giai đoạn phân tích — theo dõi Rlog coded/plan hàng tuần.',
            'priority': 'medium',
        })
    
    elif 30 <= progress < 70:
        # Giai đoạn giữa — focus dev + test + overload
        suggestions.append({
            'section_id': 'section-pic-overload',
            'title': 'PIC Overload',
            'reason': 'Giai đoạn dev/test cao điểm — kiểm tra ai đang quá tải.',
            'priority': 'high',
        })
        suggestions.append({
            'section_id': 'section-burndown',
            'title': 'Burndown + Velocity',
            'reason': f'Tiến độ {progress:.0f}% — theo dõi tốc độ Closed/tuần.',
            'priority': 'medium',
        })
        suggestions.append({
            'section_id': 'section-baseline',
            'title': 'Baseline SV',
            'reason': 'So sánh tiến độ thực tế vs kế hoạch gốc.',
            'priority': 'medium',
        })
    
    elif progress >= 70:
        # Giai đoạn cuối — focus UAT + golive + capacity
        suggestions.append({
            'section_id': 'section-uat-quality',
            'title': 'UAT Quality',
            'reason': f'Tiến độ {progress:.0f}% — sắp UAT/Golive, theo dõi defect/reopen.',
            'priority': 'high',
        })
        suggestions.append({
            'section_id': 'section-forecast-gantt',
            'title': 'Forecast UAT/Golive',
            'reason': 'Giai đoạn cuối — xem milestone tháng dự kiến.',
            'priority': 'high',
        })
        suggestions.append({
            'section_id': 'section-evm',
            'title': 'EVM (SPI/CPI)',
            'reason': 'Gần kết thúc — đánh giá hiệu suất tổng thể bằng Earned Value.',
            'priority': 'medium',
        })
        suggestions.append({
            'section_id': 'section-capacity',
            'title': 'Capacity PIC',
            'reason': 'Kiểm tra công suất còn lại per PIC cho giai đoạn UAT.',
            'priority': 'medium',
        })

    # Loại bỏ section đã bật (đang trong visible list)
    visible = project_settings.get('visible_sections', [])
    suggestions = [s for s in suggestions if s['section_id'] not in visible]
    
    # Sort: high trước medium
    suggestions.sort(key=lambda x: 0 if x['priority'] == 'high' else 1)
    
    return suggestions
```

**API:**
```
GET /api/projects/<slug>/smart-suggestions
→ { "suggestions": [...], "project_phase": "mid", "progress_pct": 52.3 }
```

**FE section:**
```html
<section id="section-smart-suggest" class="dashboard-card">
  <h3>💡 Gợi ý dashboard cho giai đoạn hiện tại</h3>
  <p class="text-secondary">
    Dự án đang ở giai đoạn <strong>Phát triển</strong> (52.3%) — 
    các dashboard sau có thể hữu ích:
  </p>
  <div class="suggest-list">
    <!-- Mỗi suggestion = 1 card -->
    <div class="suggest-card suggest-card--high">
      <div class="suggest-header">
        <span class="suggest-title">📊 PIC Overload</span>
        <span class="suggest-priority">Khuyến nghị</span>
      </div>
      <p class="suggest-reason">
        Giai đoạn dev/test cao điểm — kiểm tra ai đang quá tải.
      </p>
      <button class="suggest-btn" onclick="toggleSection('section-pic-overload', true)">
        Bật dashboard này
      </button>
    </div>
    <!-- ... more cards -->
  </div>
</section>
```

**CRUD:**
- **READ:** `GET /api/projects/<slug>/smart-suggestions`.
- **UPDATE:** Click "Bật dashboard này" → thêm section vào `visible_sections` → section hiện lên + suggestion card biến mất (hoặc đổi thành "✓ Đã bật").
- Khi data thay đổi (upload mới) → re-compute suggestions.

**Verify:**
1. Dự án 52% → gợi ý PIC Overload, Burndown, Baseline SV.
2. Bấm "Bật" PIC Overload → section hiện lên sidebar + dashboard, suggestion card đổi "✓ Đã bật".
3. Dự án 80% → gợi ý UAT Quality, Forecast Gantt, EVM.
4. Tất cả suggestion đã bật → section hiện "🎉 Không có gợi ý thêm — đã bật đủ dashboard cho giai đoạn này."

**Report lại:** Screenshot section Smart Suggest với 3+ gợi ý. Bấm 1 cái → confirm section hiện lên.

---

# GÓI B: BA TASK MANAGEMENT (QUẢN LÝ ĐẦU VIỆC GIAI ĐOẠN PHÂN TÍCH)

> Section MỚI hoàn toàn. Mục đích: BA Lead quản lý đầu việc triển khai dạng tab, 
> track họp, sản phẩm, nợ khách hàng — không thay thế FL, mà bổ sung FL.

---

## B1. Data model — `ba_tasks` store

**File MỚI:** `analyzer/ba_task_store.py`
**File lưu:** `uploads/projects/<slug>/ba_tasks.json`

```python
# Schema ba_tasks.json
{
  "tasks": [
    {
      "id": "task_uuid",
      "title": "Khảo sát quy trình chấm công TMS",
      "module": "TMS",
      "type": "task",              # task | meeting | deliverable | customer_debt
      "status": "in_progress",     # open | in_progress | done | blocked | cancelled
      "priority": "high",          # high | medium | low
      "assignee": "Nhi",           # PIC
      "created_at": "2026-08-03",
      "due_date": "2026-08-10",
      "done_date": null,
      "week_iso": "2026-W31",      # tuần tạo (auto)
      "tags": ["khảo sát", "TMS"],
      "notes": "Chờ KH gửi form lương",
      "linked_functions": ["HR.01", "HR.02"],  # link đến Mã CN trong FL (optional)
      "alert_level": null,         # auto-compute: overdue | upcoming | blocked
      "meeting_info": null,        # chỉ khi type=meeting
      "deliverable_info": null,    # chỉ khi type=deliverable
      "debt_info": null,           # chỉ khi type=customer_debt
    }
  ],
  "settings": {
    "default_assignee": null,
    "week_start_day": "monday",
    "auto_alert_days_before": 2,
  }
}
```

**Sub-schema cho từng type:**

```python
# meeting_info (type=meeting)
{
  "meeting_date": "2026-08-05",
  "time": "14:00",
  "attendees": ["KH: Anh Minh", "FPT: Nhi, Hải"],
  "location": "Online Teams",
  "agenda": "Review TMS config",
  "mom_notes": "Đã thống nhất rule chấm công...",
  "action_items": ["Nhi cập nhật config", "KH gửi danh sách ca"],
}

# deliverable_info (type=deliverable)
{
  "deliverable_name": "URD Module TMS v1.0",
  "format": "docx",
  "target_date": "2026-08-15",
  "submitted_date": null,
  "approved_date": null,
  "reviewer": "PM",
}

# debt_info (type=customer_debt)
{
  "description": "KH chưa gửi danh sách ca làm việc",
  "requested_date": "2026-07-28",
  "responsible_party": "KH - Anh Minh",
  "blocking_tasks": ["task_uuid_1"],  # task bị chặn bởi nợ này
  "follow_up_count": 2,
  "last_follow_up": "2026-08-01",
}
```

**CRUD API:**
```
GET    /api/projects/<slug>/ba-tasks                    # list + filter
GET    /api/projects/<slug>/ba-tasks/<id>               # detail
POST   /api/projects/<slug>/ba-tasks                    # create 1
PUT    /api/projects/<slug>/ba-tasks/<id>               # update 1
DELETE /api/projects/<slug>/ba-tasks/<id>               # delete 1
POST   /api/projects/<slug>/ba-tasks/bulk               # create nhiều
POST   /api/projects/<slug>/ba-tasks/import             # import Excel
GET    /api/projects/<slug>/ba-tasks/export             # export Excel
GET    /api/projects/<slug>/ba-tasks/export-weekly      # export tuần
GET    /api/projects/<slug>/ba-tasks/stats              # thống kê cho biểu đồ
```

**Verify:** API CRUD hoạt động. `pytest tests/test_ba_task_store.py -q` pass.

**Report lại:** Liệt kê toàn bộ routes + response schema. Screenshot Postman/curl test.

---

## B2. API implementation — CRUD + filter + import/export

**File sửa:** `app.py` (thêm routes), `analyzer/ba_task_store.py`

**Filter params (GET list):**
```
?type=task|meeting|deliverable|customer_debt
&status=open|in_progress|done|blocked
&assignee=Nhi
&module=TMS
&week=2026-W31
&priority=high
&alert=overdue|upcoming|blocked
&tag=khảo sát
&sort=due_date|created_at|priority
&order=asc|desc
```

**Auto-compute `alert_level`** (khi read/list):
```python
def compute_alert(task):
    if task['status'] in ('done', 'cancelled'):
        return None
    if task['due_date'] and task['due_date'] < today:
        return 'overdue'
    if task['status'] == 'blocked':
        return 'blocked'
    if task['due_date'] and (task['due_date'] - today).days <= settings['auto_alert_days_before']:
        return 'upcoming'
    return None
```

**Import Excel:**
- Upload `.xlsx` → parse sheet 1 → map columns (title, module, assignee, due_date, type, notes).
- Dùng Column Mapping Wizard pattern đã có (`column_mapping.py`) — preview trước confirm.
- Mỗi row → 1 task, status default = `open`.

**Export tuần:**
- `GET /ba-tasks/export-weekly?week=2026-W31`
- Sheet 1: Đầu việc trong tuần (filter week_iso hoặc due_date trong tuần).
- Sheet 2: Họp trong tuần (type=meeting, meeting_date trong tuần).
- Sheet 3: Sản phẩm đến hạn (type=deliverable, target_date trong tuần).
- Sheet 4: Nợ KH đang chờ (type=customer_debt, status ≠ done).

**Verify:** Create → Read → Update → Delete → Import Excel → Export weekly → filter by type/status/week.

**Report lại:** Curl test cho mỗi endpoint. Screenshot export Excel.

---

## B3. FE Section — Tab layout

**File sửa:** `templates/index.html`, `static/js/dashboard.js`, `static/css/style.css`

**Section structure:**
```html
<section id="section-ba-tasks" class="dashboard-card">
  <div class="section-header">
    <h3>📋 Quản lý đầu việc BA</h3>
    <div class="section-actions">
      <button onclick="openBaTaskModal('create')">+ Thêm</button>
      <button onclick="importBaTasks()">📥 Import</button>
      <button onclick="exportBaTasksWeekly()">📤 Xuất tuần</button>
    </div>
  </div>

  <div class="section-tabs">
    <button class="tab active" data-tab="all">
      Tất cả <span class="tab-badge">24</span>
    </button>
    <button class="tab" data-tab="tasks">
      Đầu việc <span class="tab-badge">15</span>
    </button>
    <button class="tab" data-tab="meetings">
      Cuộc họp <span class="tab-badge tab-badge--accent">3</span>
    </button>
    <button class="tab" data-tab="deliverables">
      Sản phẩm <span class="tab-badge tab-badge--accent">4</span>
    </button>
    <button class="tab" data-tab="debts">
      Nợ KH <span class="tab-badge tab-badge--danger">2</span>
    </button>
  </div>

  <!-- Tab: Tất cả — unified table with alert highlights -->
  <div class="tab-pane active" id="tab-all">
    <!-- Bảng tổng hợp, highlight row theo alert_level -->
  </div>

  <!-- Tab: Đầu việc -->
  <div class="tab-pane" id="tab-tasks">
    <!-- Bảng filter type=task, có inline edit status -->
  </div>

  <!-- Tab: Cuộc họp -->
  <div class="tab-pane" id="tab-meetings">
    <!-- Card layout per meeting: date, attendees, agenda, MoM -->
  </div>

  <!-- Tab: Sản phẩm bàn giao -->
  <div class="tab-pane" id="tab-deliverables">
    <!-- Timeline: deliverable_name → target_date → status -->
  </div>

  <!-- Tab: Nợ KH -->
  <div class="tab-pane" id="tab-debts">
    <!-- Highlight list: mô tả nợ, ngày yêu cầu, follow_up_count, blocking -->
  </div>
</section>
```

**Highlight rules:**
```css
.ba-task-row--overdue  { border-left: 3px solid var(--fill-danger); background: var(--bg-danger); }
.ba-task-row--upcoming { border-left: 3px solid var(--fill-warning); background: var(--bg-warning); }
.ba-task-row--blocked  { border-left: 3px solid var(--fill-muted); background: var(--surface-0); opacity: 0.8; }
.ba-task-row--done     { opacity: 0.5; text-decoration: line-through; }
```

**CRUD FE:**
- **CREATE:** Modal form (title, type, module, assignee, due_date, priority, notes, linked_functions). Type chọn → hiện thêm fields tương ứng (meeting_info, deliverable_info, debt_info).
- **READ:** Bảng list + filter bar (type, status, module, assignee, week selector).
- **UPDATE:** Click row → modal edit. Inline edit cho status (dropdown nhanh trên bảng).
- **DELETE:** Nút xóa trên modal + confirm dialog.

**Verify:** Tạo 1 task, 1 meeting, 1 deliverable, 1 debt → thấy đúng tab. Edit status inline. Delete. Filter by module.

**Report lại:** Screenshot mỗi tab. Confirm CRUD hoạt động.

---

## B4. Biểu đồ thống kê BA tasks

**File sửa:** `static/js/dashboard.js` (phần section-ba-tasks)

**Thêm panel charts nhỏ phía trên bảng (trong tab "Tất cả"):**

| Chart | Loại | Data |
|-------|------|------|
| Đầu việc theo status | Donut chart | open/in_progress/done/blocked/cancelled |
| Đầu việc theo tuần | Bar chart | count per week (4 tuần gần nhất + tuần tới) |
| Nợ KH theo thời gian chờ | Horizontal bar | mỗi debt → số ngày chờ, sort dài nhất lên trên |
| Sản phẩm timeline | Timeline/Gantt nhỏ | deliverable target_date, tô màu theo submitted/approved/pending |

**Dùng Chart.js** (đã có CDN). Mỗi chart nhỏ max 200px height.

**API:** `GET /api/projects/<slug>/ba-tasks/stats` trả pre-computed data cho charts.

**Verify:** Tab "Tất cả" hiện 4 mini charts phía trên bảng. Data khớp.

**Report lại:** Screenshot charts + confirm data đúng.

---

## B5. Export tuần đẹp + tuần selector

**File MỚI:** `exporter/ba_task_exporter.py`

**Tuần selector trên FE:**
```html
<div class="week-selector">
  <button onclick="prevWeek()">◀</button>
  <span>Tuần 31 (28/07 – 03/08/2026)</span>
  <button onclick="nextWeek()">▶</button>
  <button onclick="exportBaTasksWeekly()">📤 Xuất Excel tuần này</button>
</div>
```

**Excel output (4 sheets):**
- **Đầu việc tuần**: table format, highlight overdue rows đỏ, upcoming vàng.
- **Cuộc họp**: card-style (merge cell cho agenda/MoM), border màu.
- **Sản phẩm bàn giao**: timeline table, status badge.
- **Nợ KH**: highlight đỏ cho debt > 7 ngày chưa giải quyết.

Header mỗi sheet: `Dự án: {project_name} | Tuần {week_num} ({date_range}) | Xuất lúc: {now}`.

**Verify:** Chọn tuần → Xuất → mở Excel → 4 sheets format đẹp. Overdue tô đỏ.

**Report lại:** Screenshot Excel 4 sheets.

---

# GÓI C: SMART SUGGEST CHI TIẾT (phụ thuộc A7)

> Nếu A7 đã pass, bổ sung thêm logic gợi ý.

---

## C1. Gợi ý theo calendar — deadline sắp tới

**Thêm vào `smart_suggest.py`:**

```python
# Nếu có >10 function End trong 2 tuần tới → gợi ý PIC upcoming
upcoming_2w = count_functions_ending_within(state, days=14)
if upcoming_2w > 10:
    suggestions.append({
        'section_id': 'section-pic-upcoming',
        'title': 'PIC tuần tới',
        'reason': f'{upcoming_2w} function đến hạn trong 2 tuần — kiểm tra phân bổ PIC.',
        'priority': 'high',
    })
```

## C2. Gợi ý theo data quality

```python
# Nếu DQ issues > 5% tổng function → gợi ý FL re-import
dq_pct = summary['dq_issue_count'] / summary['total_functions'] * 100
if dq_pct > 5:
    suggestions.append({
        'section_id': 'section-function-diff',
        'title': 'Function Diff + FL Re-import',
        'reason': f'{dq_pct:.0f}% function có lỗi data — xuất FL chỉnh sửa rồi import lại.',
        'priority': 'medium',
    })
```

## C3. Gợi ý theo lịch sử trend

```python
# Nếu overdue tăng 3 tuần liên tiếp → gợi ý Burndown + Baseline
trend = get_overdue_trend(snapshots, weeks=3)
if all(trend[i] < trend[i+1] for i in range(len(trend)-1)) and len(trend) >= 3:
    suggestions.append({
        'section_id': 'section-burndown',
        'title': 'Burndown + Velocity',
        'reason': 'Overdue tăng 3 tuần liên tiếp — xem velocity có đang chậm lại.',
        'priority': 'high',
    })
```

**Verify:** Tạo data giả (overdue tăng 3 tuần) → suggestion Burndown hiện lên.

**Report lại:** Liệt kê tất cả rule gợi ý + screenshot.

---

# CHECKLIST TỔNG

| Mục | Phụ thuộc | Est. effort | Deliverable |
|-----|-----------|-------------|-------------|
| A1 | — | Nhỏ | Core/extended split + localStorage |
| A2 | A1 | Nhỏ | Module risk_level column |
| A3 | A1 | Nhỏ | Matrix cell highlight |
| A4 | A1 | Trung bình | Issues tabs section |
| A5 | — | Nhỏ | Manpower auto-target + warning |
| A6 | A1,A4 | Trung bình | Sidebar redesign |
| A7 | A1,A6 | Trung bình | Smart suggest section + API |
| B1 | — | Nhỏ | Data model + JSON store |
| B2 | B1 | Trung bình | API CRUD + import/export |
| B3 | B2 | Lớn | FE tabs + modal + inline edit |
| B4 | B3 | Trung bình | 4 mini charts |
| B5 | B2 | Trung bình | Weekly Excel export |
| C1 | A7 | Nhỏ | Calendar suggestion |
| C2 | A7 | Nhỏ | DQ suggestion |
| C3 | A7 | Nhỏ | Trend suggestion |

**Thứ tự gửi Cursor:** A1 → A2 → A3 → A4 → A5 → A6 → A7 → B1 → B2 → B3 → B4 → B5 → C1 → C2 → C3.

Mỗi mục xong → Cursor report → bạn verify → next.
