# Hướng dẫn thêm nội dung Help — Unified Help System (T34 Task 4)

Tài liệu này dành cho developer khi thêm section mới vào dashboard và cần
đăng ký nội dung trợ giúp (help) cho user.

Hệ thống help gồm 4 phần:
1. **Section-level help modal**: nút `?` cạnh title mỗi section → mở modal có nội dung cấu trúc.
2. **Global Help menu**: mở bằng Ctrl+/ hoặc nút ❓ header — search toàn bộ topic.
3. **Onboarding tour**: 8 bước cho user lần đầu vào project mới.
4. **Command Palette**: entry `❓ Trợ giúp: <topic>` trong Ctrl+K.

Toàn bộ nội dung nằm ở **`static/js/help_content.js`** — object `HELP_CONTENT`.

---

## 1. Thêm topic mới

Mở `static/js/help_content.js` và thêm entry vào `HELP_CONTENT`. Key nên khớp
`id` section (bỏ prefix `section-`), hoặc 1 danh từ ngắn.

```js
const HELP_CONTENT = {
    // ... existing topics
    "my-new-section": {
        category: "Phân tích chuyên sâu",   // 1 trong 7 category chuẩn
        title: "Tên section (hiển thị trong modal + Command Palette)",
        purpose: "1-2 câu — mục đích section. VD: 'Hiển thị top 10 function critical cần escalate.'",
        steps: [
            "Bước 1 — hành động cụ thể",
            "Bước 2 — hành động tiếp theo",
            "Bước 3 — output mong đợi",
        ],
        example: "1 tình huống thực tế minh họa. VD: 'Nếu top 10 có 5 function Must-have chưa PIC → escalate PM.'",
        tips: [
            "Tip 1 — insight hoặc caveat",
            "Tip 2 — link đến section liên quan",
        ],
        learn_more: "docs/DASHBOARD_SPEC.md#my-new-section",   // optional
    },
};
```

### Categories chuẩn (định nghĩa ở `HELP_CATEGORIES`)

Chọn 1 trong 7 category — thứ tự hiển thị trong Global Help modal theo thứ tự
định nghĩa. Nếu category mới → thêm vào cả `HELP_CATEGORIES` (để control order):

| Category | Dành cho |
|----------|----------|
| Tổng quan | Summary cards, filter, snapshot compare |
| Tiến độ & Timeline | Module overview, phase, giai đoạn, Gantt, burndown, SLA, capacity, baseline |
| Phân tích chuyên sâu | Task type, PIC workload, priority, FIT/GAP, effort, duration, dependency |
| Danh sách vấn đề | Overdue, unassigned, stalled, high-risk, aging WIP, data quality, bookmark, digest, function diff |
| Tùy chỉnh | Custom dashboards, kanban, upload history |
| Public API | Public API tab (Settings) |
| Import/Export | Upload wizard, xuất PDF, xuất all issues, integrations |

---

## 2. Attach nút `?` vào section

Có 2 cách wire nút `?` tự động:

### Cách A (khuyến nghị): thêm `data-help-id` vào `<h2>`/`<h3>` title

```html
<section id="section-my-new-section" class="dashboard-card">
    <h3 class="text-lg font-semibold" data-help-id="my-new-section">
        📊 Tên section
    </h3>
    <!-- ... -->
</section>
```

`data-help-id` value = key trong `HELP_CONTENT` (không có prefix "section-").

### Cách B (tương thích cũ): dùng `data-help="section-X"`

Nếu section đã có `data-help` cho chart-help popover cũ, không cần đổi:

```html
<h3 data-help="section-my-new-section">📊 Tên section</h3>
```

Hệ thống unified help sẽ tự strip prefix `section-` và lookup key `my-new-section`
trong `HELP_CONTENT`. Nếu key không tồn tại → skip (không inject nút).

Nút `?` được inject bởi `attachUnifiedSectionHelp()` — chạy tự động sau:
- `DOMContentLoaded`
- `applyDashboardResponse()` (mỗi lần render dashboard xong)

Idempotent — chạy nhiều lần không tạo trùng nút.

---

## 3. Cập nhật Onboarding Tour (optional)

Nếu section mới quan trọng đến mức cần vào tour cho user mới, edit
`_TOUR_STEPS` trong `static/js/dashboard.js`:

```js
const _TOUR_STEPS = [
    // ... existing 8 steps
    {
        selector: "#section-my-new-section",   // CSS selector target
        title: "Bước 9: Tên bước",
        desc: "1 câu ngắn giải thích. Nên < 100 chars.",
    },
];
```

Selector có thể là comma-separated (tour sẽ pick element visible đầu tiên).
Cập nhật `localStorage.setItem("ihrp_onboarded_<slug>", "1")` nếu muốn reset
để test.

Reset tour cho project hiện tại (mở DevTools console):
```js
localStorage.removeItem("ihrp_onboarded_" + currentProjectSlug);
startOnboardingTour();  // force start
```

---

## 4. Guideline viết nội dung

### Ngôn ngữ

- **Tiếng Việt**. Không mix Anh.
- **PM/BA hiểu**. Tránh technical jargon (VD "cache TTL", "weighted average" —
  dùng "lưu tạm", "tính trung bình có trọng số").
- **Ngắn gọn**. Purpose = 1-2 câu; step = 1 câu/mỗi; example = 1 câu; tip < 20 chars/mỗi.

### Structure

- `purpose` — TRẢ LỜI câu hỏi "Section này để làm gì?".
- `steps` — TRẢ LỜI câu "Tôi phải làm gì để dùng?". Bao gồm thao tác click,
  filter, threshold.
- `example` — TRẢ LỜI "Khi nào thì section này hữu ích?". Dùng số cụ thể (VD
  "5 function", "20%").
- `tips` — TRẢ LỜI "Điều gì tôi cần lưu ý?". Bao gồm edge case, config, keyboard
  shortcut, link đến section liên quan.

### Ví dụ good

```js
"overdue": {
    category: "Danh sách vấn đề",
    title: "Overdue List (danh sách trễ)",
    purpose: "Danh sách chi tiết function trễ deadline (bất kỳ phase nào). Filter theo module/PIC/phase, xuất Excel để gửi team.",
    steps: [
        "Filter local (module/PIC/phase) — kết hợp với global filter",
        "Sort desc theo số ngày trễ",
        "Bấm 'Xuất Excel' → download list",
    ],
    example: "Filter Module=HR → 12 function HR trễ, xuất Excel gửi HR lead xin update.",
    tips: [
        "Overdue = phase có End < today VÀ status ≠ Closed/Cancelled",
        "Fill row: đỏ ≥30 ngày, cam ≥14, vàng ≥7",
    ],
},
```

### Ví dụ bad (đừng viết)

```js
"overdue": {
    category: "Overdue",   // ❌ category không có trong 7 chuẩn
    title: "OverdueList",   // ❌ camelCase, không phải Vietnamese
    purpose: "This section shows overdue functions.",   // ❌ English + technical
    steps: [
        "Chạy hàm compute_overdue với ParsedData",   // ❌ technical, user không biết
    ],
    example: "See docs/DASHBOARD_SPEC.md",   // ❌ không giá trị thực tế
    tips: [],   // ❌ empty
},
```

---

## 5. Test

Sau khi thêm topic mới, verify:

1. Mở dashboard → click nút `?` trên title section mới → modal mở với đúng nội dung.
2. Ctrl+/ → gõ tên section → thấy trong list → click → mở modal.
3. Ctrl+K → gõ "trợ giúp <tên section>" → thấy entry → click → mở modal.
4. `pytest tests/test_help_system.py -q` — verify test không fail (nếu có
   test khớp category count / smoke test).

---

## 6. Không viết help ở đâu

- **Không viết help trong docstring Python** — chỉ user-facing (JS content).
- **Không viết help trong Jira/Confluence** — content phải version-controlled
  cùng codebase để đồng bộ với UI.
- **Không đặt trong DB** — quá dynamic, không đảm bảo consistency giữa
  environment (dev/staging/prod).

---

## 7. Reference

- Content: `static/js/help_content.js`
- System JS: `static/js/dashboard.js` — `T34 Task 4 — UNIFIED HELP SYSTEM` section
- Modal HTML: `templates/index.html` — id `sectionHelpModal`, `globalHelpModal`, `onboardingTourOverlay`
- CSS: `static/css/style.css` — `.unified-help-btn`, `.help-block-modal`
- Tests: `tests/test_help_system.py`

Feedback + feature request: liên hệ dev team.
