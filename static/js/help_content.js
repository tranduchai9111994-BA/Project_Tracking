/**
 * T34 Task 4 — Unified Help System.
 *
 * Nội dung help cho ~35 section dashboard. Viết ngôn ngữ PM/BA hiểu — không
 * technical. Mỗi entry có structure:
 *   {
 *     category: string  // grouping (Tổng quan / Tiến độ / …)
 *     title:    string  // tên hiển thị (không bao gồm icon)
 *     purpose:  string  // 1-2 câu — mục đích section
 *     steps:    string[] // numbered list — cách dùng step-by-step
 *     example:  string  // 1 tình huống thực tế minh họa
 *     tips:     string[] // bulleted tips + caveats
 *     learn_more?: string // path file docs/*.md để đào sâu (optional)
 *   }
 *
 * Key = data-help-id (thường trùng với section id không tiền tố "section-").
 */

const HELP_CATEGORIES = [
    "Tổng quan",
    "Tiến độ & Timeline",
    "Phân tích chuyên sâu",
    "Danh sách vấn đề",
    "Tùy chỉnh",
    "Public API",
    "Import/Export",
];

const HELP_CONTENT = {
    // ==================== TỔNG QUAN ====================
    "summary": {
        category: "Tổng quan",
        title: "Thẻ tổng quan (Summary Cards)",
        purpose: "Hiển thị 6 chỉ số cốt lõi của dự án: tổng function, tiến độ, trễ, chưa PIC, aging, high-risk. Xem nhanh sức khỏe dự án trong 3 giây.",
        steps: [
            "Xem 6 số để nắm nhanh tình hình chung",
            "Click nút 🔍 trên card 'Trễ' / 'Chưa PIC' / 'High-risk' → drill-down xem chi tiết từng function",
            "Filter global (Module/Quy trình/PIC) thay đổi → 6 số tự cập nhật ngay",
        ],
        example: "Nếu 'Trễ' > 20% tổng function → cần họp escalation team ngay tuần này.",
        tips: [
            "Click 62.8% tiến độ KHÔNG drill được — dùng biểu đồ Module Overview / Task Type Progress bên dưới để breakdown",
            "6 card đều tính distinct function, không phải phase-record → không lặp",
            "% Progress dùng công thức weighted_all — coi phase blank là 'chưa done'",
        ],
        learn_more: "docs/DASHBOARD_SPEC.md#summary-cards",
    },
    "globalfilter": {
        category: "Tổng quan",
        title: "Filter global (Module × Quy trình × PIC)",
        purpose: "Lọc toàn bộ dashboard theo Module + Quy trình + PIC. Mọi biểu đồ và số đếm ở mọi section đều apply filter này.",
        steps: [
            "Chọn Module (multi-select) → dropdown Quy trình auto lọc theo module đó",
            "Chọn Quy trình (nếu cần zoom sâu hơn)",
            "Chọn PIC (nếu chỉ quan tâm 1 người)",
            "Nút 'Reset' xoá toàn bộ filter",
        ],
        example: "Filter Module=HR + PIC=SonHN6 → thấy 25 function của Son thuộc module HR, các chart cập nhật hết.",
        tips: [
            "Có thể lưu filter đang chọn thành 'Saved View' để lần sau bấm 1 nút restore",
            "Filter global không ảnh hưởng đến sidebar navigation",
            "Badge 'X function được lọc / Y tổng' hiện luôn ngay filter bar",
        ],
    },
    "compare": {
        category: "Tổng quan",
        title: "Snapshot Compare (so sánh 2 mốc)",
        purpose: "So sánh state hiện tại vs 1 snapshot đã lưu (VD tuần trước) → thấy chức năng mới, chức năng đã done, chức năng regress.",
        steps: [
            "Tạo snapshot mới sau mỗi lần upload file (backend tự tạo)",
            "Chọn snapshot cũ để so sánh trong dropdown",
            "Xem 3 bảng: 'Function mới thêm', 'Function đã done', 'Function regress'",
        ],
        example: "Snapshot tuần trước có 380 function, hôm nay 388 → thấy 8 function mới thêm với priority + module.",
        tips: [
            "Snapshot auto tự lưu mỗi lần upload — không cần thao tác thủ công",
            "Có thể xoá snapshot cũ để tiết kiệm disk (giữ 20 snapshot gần nhất mặc định)",
        ],
    },

    // ==================== TIẾN ĐỘ & TIMELINE ====================
    "module": {
        category: "Tiến độ & Timeline",
        title: "Module Overview (tổng quan từng module)",
        purpose: "Bảng % tiến độ từng module theo cột (Total / Closed / Trễ / % Progress). So sánh module nào chậm hơn hẳn.",
        steps: [
            "Đọc cột '% Progress' — module nào <30% (đỏ) là cảnh báo",
            "Click cell 'Trễ' của 1 module → drill xem function trễ cụ thể",
            "Cột 'Total' + 'Closed' cho biết tỷ lệ tổng, không chỉ %",
        ],
        example: "Module HR: 80% progress, module SI: 20% progress → cần review sao SI chậm hẳn.",
        tips: [
            "Bảng dùng weighted_all — coi mọi phase blank là 'chưa done', không phải 'không tính'",
            "Có thể sort theo bất kỳ cột nào bằng cách click header",
        ],
    },
    "phase": {
        category: "Tiến độ & Timeline",
        title: "Phase Progress Stacked (bar stacked theo status)",
        purpose: "Bar stacked mỗi phase (Analysis / Dev / Test / UAT / Golive) — segment mỗi màu = 1 status (Closed / In-progress / Open / ...).",
        steps: [
            "Nhìn từ trái sang phải để thấy funnel: từ Analysis → Golive giảm dần",
            "Segment xanh = Closed (đã done); vàng = In-progress; đỏ = Open (chưa động)",
            "Click segment 'Open' của UAT → drill xem function chưa động UAT",
        ],
        example: "Analysis 90% Closed, Dev 70% Closed, UAT 30% Closed → bottleneck ở UAT.",
        tips: [
            "Nếu phase có nhiều segment 'Open' đỏ nhiều → team đang plan tương lai chưa vào cuộc",
            "Chart config → có thể tắt segment cụ thể (VD ẩn Closed để zoom vào phần chưa done)",
        ],
    },
    "matrix": {
        category: "Tiến độ & Timeline",
        title: "Phase × Module Status Matrix",
        purpose: "Heatmap 2D — hàng = module, cột = phase, cell = % Closed. Nhận diện nhanh 'module + phase' nào đang stuck.",
        steps: [
            "Cell càng xanh = càng gần 100% Closed",
            "Cell đỏ = <30% → cần chú ý",
            "Click 1 cell → drill xem function chi tiết của (module, phase)",
        ],
        example: "Cell 'HR × UAT' đỏ 20%, còn 'HR × Analysis' xanh 90% → HR đang stuck ở UAT.",
        tips: [
            "Có thể toggle hiển thị số tuyệt đối / % qua chart config",
            "Reorder cột phase theo thứ tự thực tế của dự án qua Settings → Phase aliases",
        ],
    },
    "giaidoan": {
        category: "Tiến độ & Timeline",
        title: "Giai đoạn Progress (theo Wave)",
        purpose: "% Closed từng phase × giai đoạn (Wave 1 / Wave 2 / …). Tracking rollout theo đợt.",
        steps: [
            "Cột 'Total' cho biết số function của mỗi giai đoạn",
            "Cột 'closed_pct' = weighted_all — tỷ lệ Closed trên tổng function của giai đoạn",
            "Click % của phase → drill",
        ],
        example: "Giai đoạn 1 đã 90% golive, giai đoạn 2 mới 30% analysis → team đang song song 2 wave.",
        tips: [
            "Chỉ hiện nếu file có cột 'Giai đoạn' hoặc 'Wave'",
            "Cấu hình phase mapping trong Settings → Phase Aliases nếu tên phase custom",
        ],
    },
    "gantt": {
        category: "Tiến độ & Timeline",
        title: "Gantt cũ (theo module)",
        purpose: "Timeline plot mỗi module với start/end của mọi phase (thanh chồng nhau). Ưa dùng để quan sát overlap giữa modules.",
        steps: [
            "Trục Y = module, trục X = thời gian",
            "Thanh dài = phase kéo dài, màu = phase category",
            "Hover thanh → tooltip hiện tên function + phase + PIC",
        ],
        example: "Thấy Module HR và SI có Analysis chạy song song từ tháng 1 → cần allocate resource.",
        tips: [
            "Chart cũ — Gantt Calendar (bên dưới) là bản Excel-style mới hơn, đầy đủ hơn",
        ],
    },
    "gantt-calendar": {
        category: "Tiến độ & Timeline",
        title: "Gantt Calendar (Excel-style timeline)",
        purpose: "Timeline Excel-style với header 3 tầng (Month / Week / Day) — mỗi row = 1 module (hoặc phân hệ), cell trong ô có bar % completion. Marker đỏ chỉ 'Today'.",
        steps: [
            "Toggle Group by (Module / Phân hệ / Function)",
            "Toggle Granularity (Day / Week / Month) — auto-suggest theo range",
            "Bấm 'Xuất Excel' để download file .xlsx (merge cell Month/Week + fill màu)",
        ],
        example: "Nhìn cột 'W28' thấy nhiều module có bar % cao → tuần này team đang deliver mạnh.",
        tips: [
            "Bar màu = phase category (Analysis xanh / Dev cam / Test tím / UAT vàng / Golive xanh lá)",
            "Marker đỏ 'Today' luôn hiện — quan sát nhanh việc đang làm hôm nay",
        ],
        learn_more: "docs/DASHBOARD_SPEC.md#gantt-calendar",
    },
    "burndown": {
        category: "Tiến độ & Timeline",
        title: "Burndown & Velocity",
        purpose: "Đo velocity: mỗi tuần done bao nhiêu function → dự đoán ngày complete theo trend hiện tại.",
        steps: [
            "Đường đỏ = burndown thực tế (remaining function)",
            "Đường xanh nhạt = trend extrapolation",
            "So sánh với deadline (line đứt) — nếu đường đỏ chậm hơn → cần accelerate",
        ],
        example: "Trend hiện tại dự đoán done ngày 15/10, deadline 30/09 → phải cắt scope hoặc thêm resource.",
        tips: [
            "Chỉ hiện nếu có history data (≥ 2 snapshot)",
            "Velocity chart tách riêng — xem tuần nào done nhiều nhất",
        ],
    },
    "sla": {
        category: "Tiến độ & Timeline",
        title: "SLA Violations (vi phạm cam kết)",
        purpose: "Track function vi phạm SLA — VD Must-have phải xong trong 3 ngày, Should-have 7 ngày, Could-have 14 ngày.",
        steps: [
            "Đặt threshold SLA trong Settings → SLA config",
            "Bảng hiện function vượt threshold theo priority",
            "Xuất Excel để gửi PM/leadership",
        ],
        example: "3 function Must-have vượt 5 ngày SLA → escalate ngay chiều nay.",
        tips: [
            "SLA default: Must=3d / Should=7d / Could=14d — chỉnh theo dự án",
        ],
    },
    "capacity": {
        category: "Tiến độ & Timeline",
        title: "Capacity Load (khối lượng vs sức chứa)",
        purpose: "So sánh remaining MH của mỗi PIC vs capacity (MD/tuần) — nhìn ai overload/underload để rebalance.",
        steps: [
            "Vào Settings → Capacity → nhập MD/tuần cho từng PIC",
            "Chart hiện bar: PIC nào bar >100% capacity = overload đỏ",
            "Bấm bar → drill xem function của PIC đó",
        ],
        example: "SonHN6 có 120% capacity (120 MH cần / 100 MH có) → cần move 1 task sang PIC khác.",
        tips: [
            "Nếu chưa set capacity → mặc định 5 MD/tuần (40 MH) cho mọi PIC",
            "1 MD = 8 MH; 1 MM = 22 MD (định nghĩa chuẩn)",
        ],
    },
    "baseline": {
        category: "Tiến độ & Timeline",
        title: "Baseline Variance",
        purpose: "So sánh actual end_date vs baseline (plan ban đầu) → phát hiện function bị dời deadline.",
        steps: [
            "Cần snapshot baseline trước (Settings → Baseline)",
            "Bảng hiện variance = actual - baseline (âm = trước hạn, dương = trễ)",
        ],
        example: "5 function trong module HR bị dời deadline +14 ngày so baseline → cần root cause.",
        tips: [
            "Baseline không tự lưu — user phải set explicit tại thời điểm bắt đầu dự án",
        ],
    },
    "section-rlog": {
        category: "Tiến độ & Timeline",
        title: "Rlog coded tuần này & kế hoạch tuần tới",
        purpose: "Theo dõi số Rlog (request/release log) được code xong trong tuần ISO hiện tại và danh sách sẽ code tuần tới.",
        steps: [
            "Rlog = function có giá trị RlogID (cột phase auto-detect chứa 'Rlog', thường Analysis - RlogID)",
            "Coded tuần này = phase Dev Closed và End date nằm trong tuần ISO (Mon–Sun)",
            "Kế hoạch tuần tới = Dev chưa Closed/Cancelled, deadline hoặc Start–End giao tuần sau",
            "Nếu file không có RlogID → fallback đếm mọi function (subtitle ghi rõ)",
        ],
        example: "Tuần W31 coded 5 Rlog; tuần tới plan 4 Rlog Dev End trong W32 → PM ưu tiên assign PIC.",
        tips: [
            "Tôn trọng Global Filter (Module / Quy trình / PIC / Mã dự án)",
            "Snapshot sync thiếu cột RlogID sẽ fallback sang 'mọi function'",
        ],
    },

    // ==================== PHÂN TÍCH CHUYÊN SÂU ====================
    "tasktype": {
        category: "Phân tích chuyên sâu",
        title: "Task Type Progress (progress theo loại công việc)",
        purpose: "Bar chart % Closed theo loại công việc: Phân tích / Lập trình / Config & Test / UAT / Golive. Xem loại nào đang lag.",
        steps: [
            "Bar dài = nhiều function của loại đó",
            "Màu trong bar = tỷ lệ Closed",
            "Click bar → drill",
        ],
        example: "Phân tích 90% Closed, Config & Test 40% Closed → team QA đang bottleneck.",
        tips: [
            "'Task type' derive từ phase group name (Analysis → phân tích, Dev → lập trình,...)",
        ],
    },
    "pic": {
        category: "Phân tích chuyên sâu",
        title: "PIC Workload (khối lượng theo người)",
        purpose: "Bar chart xếp PIC theo số function đang gánh. Xem ai gánh nhiều nhất, ai chưa được giao.",
        steps: [
            "Toggle 'Include Closed' để chỉ đếm task chưa done",
            "Click 1 PIC → xuất Excel báo cáo riêng cho PIC đó (Overdue + Active)",
        ],
        example: "SonHN6 đang gánh 45 function, các PIC khác trung bình 10 → cần cân bằng lại.",
        tips: [
            "Case-insensitive match — 'SonHN6' và 'SONHN6' cùng bucket",
            "Multi-PIC / 1 phase → count cho cả 2 (không half)",
        ],
    },
    "priority": {
        category: "Phân tích chuyên sâu",
        title: "Priority / Complexity / FIT-GAP Pie",
        purpose: "3 doughnut chart cạnh nhau: phân bố Priority (Must/Should/Could), Complexity (Low/Medium/High), FIT vs GAP (customization).",
        steps: [
            "Segment lớn = số nhiều",
            "Click segment → drill xem function của loại đó",
        ],
        example: "70% function là FIT + 30% GAP → dự án chủ yếu customize, effort dev cao hơn dự kiến.",
        tips: [
            "FIT/GAP dựa vào cột 'FIT/GAP' trong file — có thể mix cả 2 giá trị trong 1 cell",
        ],
    },
    "fitgap-dashboard": {
        category: "Phân tích chuyên sâu",
        title: "FIT/GAP Analytics",
        purpose: "Phân tích chi tiết FIT vs GAP theo module: tỷ lệ, % Closed, ai đang xử lý GAP.",
        steps: [
            "Bảng chính: mỗi row = module, cột = FIT count / GAP count / total",
            "Widget aging: hiện GAP nào chưa xử lý quá lâu",
        ],
        example: "Module PR có 60% GAP nhưng 90% GAP vẫn Open sau 60 ngày → PM nên priorityize.",
        tips: [
            "GAP thường tốn effort 3-5× so với FIT → track riêng để escalate sớm",
        ],
    },
    "effort": {
        category: "Phân tích chuyên sâu",
        title: "Effort Analysis (Man-hour)",
        purpose: "Tổng hợp Estimate MH theo Module × Phase, per PIC, và burndown MH.",
        steps: [
            "Toggle đơn vị MH / MD / MM",
            "Chart 'Effort by Module × Phase' — matrix heatmap",
            "Chart 'Effort by PIC' — bar chart",
        ],
        example: "Tổng effort ước lượng 12,000 MH ~ 68 MM → cần 6 người full-time trong 12 tháng.",
        tips: [
            "MH lệch cột (VD parser gặp datetime ở cột MH) → parser tự set None, không đếm",
            "Chart burndown MH riêng — xem MH remaining theo thời gian",
        ],
    },
    "process": {
        category: "Phân tích chuyên sâu",
        title: "Process Analysis (theo Quy trình)",
        purpose: "Progress từng quy trình (BP.01, BP.02, ...). Zoom vào workflow-level thay vì module-level.",
        steps: [
            "Xem tile từng quy trình + % Closed + số function",
            "Lọc local Module (multi-select) và/hoặc Tình trạng (Tốt ≥80% / Trung bình / Thấp / Có overdue)",
            "Badge đếm và banner scope cập nhật theo filter; tôn trọng global filter",
        ],
        example: "Quy trình 'TMS.BP.01 - Chấm công' có 15 function, 60% Closed → tracking chi tiết đủ tin cậy.",
        tips: [
            "'Quy trình' derive từ cột 'Quy trình' / 'Process' — nếu file không có → section này ẩn",
            "Local filter AND với global filter (Module/Process/PIC/Mã dự án)",
        ],
    },
    "slow": {
        category: "Phân tích chuyên sâu",
        title: "Slow Heatmap (function chậm nhất)",
        purpose: "Heatmap function có duration bất thường (planned vs actual) → identify bottleneck.",
        steps: [
            "Đặt threshold slow trong Settings",
            "Cell càng đỏ = duration càng lâu",
        ],
        example: "1 function ở Dev kéo dài 45 ngày (threshold 14) → cần check tại sao dev block.",
        tips: [
            "Duration = actual end - actual start; nếu chưa có end → tính từ start đến today",
        ],
    },
    "duration": {
        category: "Phân tích chuyên sâu",
        title: "Duration Analysis (task kéo dài)",
        purpose: "Distribution duration theo phase + list task > threshold + scatter Estimate MH vs Duration.",
        steps: [
            "Đặt threshold (default 3 ngày)",
            "Bảng liệt kê task > threshold — sort desc theo duration",
            "Scatter chart: X = Estimate MH, Y = Duration → tìm outlier",
        ],
        example: "Estimate 4h nhưng dev 5 ngày → estimation sai hoặc dev bị block.",
        tips: [
            "Có 2 loại duration: 'planned' (có Start + End) và 'elapsed' (In-progress, chưa End)",
        ],
    },
    "deps": {
        category: "Phân tích chuyên sâu",
        title: "Dependency Blockers",
        purpose: "Function bị block do dependency chưa xong (function khác đang delay).",
        steps: [
            "Cần cột 'Function liên quan' trong file",
            "Bảng hiện function A block bởi function B (chưa Close phase X)",
        ],
        example: "Function REPORT.01 chờ FUNC.05 (Dev chưa Close 15 ngày) → escalate FUNC.05.",
        tips: [
            "Nếu file không có cột 'Function liên quan' → section ẩn",
        ],
    },

    // ==================== DANH SÁCH VẤN ĐỀ ====================
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
    "unassigned": {
        category: "Danh sách vấn đề",
        title: "Unassigned Tasks (chưa có PIC)",
        purpose: "Phase đã tới Start và tới lượt (phase trước Closed, hoặc phase đầu in-scope) nhưng chưa gán PIC. Không báo khi Start còn tương lai; không báo Dev/Config khi Analysis chưa xong.",
        steps: [
            "Sort: overdue trước, sau đó Must-have trước",
            "Xuất Excel gửi PM để phân công",
        ],
        example: "Analysis Closed + Dev Start đã qua thiếu PIC → vào list. Dev Start tháng sau → không báo dù trống PIC.",
        tips: [
            "Tới lượt = phase liền trước Closed + Start đã đến",
            "Không có Start: End đã đến hoặc status Open/Assigned/In-progress",
            "In-scope = chưa Closed/Cancelled + có status hoặc Start/End",
            "Fill row: đỏ = đã overdue nhưng vẫn chưa PIC",
        ],
    },
    "stalled": {
        category: "Danh sách vấn đề",
        title: "Task bị đình trệ",
        purpose: "Phát hiện function bị kẹt giữa hai phase: phase trước đã Closed nhưng phase kế tiếp chưa ai bắt đầu — bottleneck chuyển giao. Bỏ qua function đã xong toàn trình (phase cuối Closed, hoặc mọi phase Closed/Cancelled).",
        steps: [
            "Với mỗi cặp phase liền nhau: phase trước Status = Closed, phase sau chưa có tiến triển → vào danh sách",
            "Nếu Golive (phase cuối) đã Closed, hoặc mọi phase Closed/Cancelled → không đưa vào list/transitions",
            "Cột 'Chờ (ngày)' = hôm nay − ngày End của phase đã Closed; sort giảm dần theo wait_days",
            "Funnel chart (trái): tổng số function Closed theo từng phase",
            "Transitions (phải): cặp 'từ → sang' bị kẹt nhiều nhất",
            "Bấm Chi tiết / 📥 để drill-down hoặc xuất Excel",
        ],
        example: "HR-045 Analysis Closed 01/07, Dev vẫn Open → chờ 27 ngày → cần escalate Dev team. Function đã Golive Closed dù Dev blank → không vào list.",
        tips: [
            "Wait_days > 7 tô cam, > 14 tô đỏ — ưu tiên escalate dòng đỏ trước",
            "Transitions cho biết chặng chuyển giao nào tắc nhiều nhất",
            "Thường thiếu PIC phase sau hoặc chờ handover — xem thêm section Chưa PIC",
        ],
    },
    "risk": {
        category: "Danh sách vấn đề",
        title: "High Risk (điểm rủi ro cao)",
        purpose: "Function được đánh giá risk score cao dựa nhiều yếu tố: trễ, priority cao, complexity cao, PIC overload, ...",
        steps: [
            "Score 0-100 (thang càng cao càng risk)",
            "Fill row: đỏ ≥80, cam ≥50, vàng ≥30",
            "Cột 'Risk Factors' list các yếu tố cụ thể",
        ],
        example: "Function ESS.FR.10 score 85: 'Overdue 30d + Must-have + Complexity High' → cần focus meeting.",
        tips: [
            "Threshold chỉnh trong Settings → Risk (advanced)",
        ],
    },
    "aging-wip": {
        category: "Danh sách vấn đề",
        title: "Aging WIP (In-progress quá lâu)",
        purpose: "Function ở trạng thái In-progress quá threshold (default 14 ngày) — có thể bị forgot hoặc dev stuck.",
        steps: [
            "Đặt threshold trong widget",
            "Bảng list function + số ngày aging + PIC",
            "Xuất Excel",
        ],
        example: "3 function In-progress 60+ ngày → cần status update từ PIC.",
        tips: [
            "Aging tính từ Start date; fallback End date nếu Start rỗng",
        ],
    },
    "dataquality": {
        category: "Danh sách vấn đề",
        title: "Data Quality (lỗi dữ liệu)",
        purpose: "Detect lỗi dữ liệu trong file: Mã CN trùng, missing field, status invalid, Closed thiếu End, và «Thiếu End khi đang làm» (chưa cập nhật deadline).",
        steps: [
            "Bảng issues + severity (High/Medium/Low)",
            "Filter loại «Thiếu End khi đang làm» / card «Chưa cập nhật deadline» để xem WIP thiếu End",
            "Cột 'Gợi ý' cho biết cách fix — Closed thiếu End là rule riêng, không gộp với WIP",
        ],
        example: "Phase Dev status=In-progress nhưng End trống → issue missing_deadline. Phase Closed thiếu End → closed_no_end.",
        tips: [
            "Fix ở file gốc → upload lại, không sửa trên dashboard",
            "Score 'Clean %' = (total - affected) / total",
            "Card tổng quan «Chưa cập nhật deadline» click → lọc đúng loại issue này",
        ],
    },
    "my-bookmarks": {
        category: "Danh sách vấn đề",
        title: "Bookmark (function đã star)",
        purpose: "Danh sách function đã bookmark (icon ⭐) để quick access — VD function quan trọng cần theo dõi hàng tuần.",
        steps: [
            "Bấm ⭐ ở drill-down modal / trong bảng function search",
            "Section này hiện tất cả function đã bookmark",
            "Bấm ⭐ lần nữa để bỏ",
        ],
        example: "Bookmark 5 function critical cho tuần này → mở dashboard là thấy ngay trong section này.",
        tips: [
            "Bookmark lưu ở `bookmarks.json` theo Mã CN — tồn tại xuyên upload",
        ],
    },
    "my-digests": {
        category: "Danh sách vấn đề",
        title: "Weekly Digest (báo cáo tuần)",
        purpose: "Auto-generate báo cáo tuần theo lịch (VD Thứ Hai 9h sáng). Digest tóm tắt: mới, done, trễ, high-risk.",
        steps: [
            "Bật digest trong Settings → Digest",
            "Chọn day/hour",
            "Server tự gen mỗi tuần — lưu vào section này",
        ],
        example: "Sáng thứ Hai mở dashboard → thấy digest tuần trước: +5 function mới, -8 done, 3 mới trễ.",
        tips: [
            "Digest lưu tối đa 10 bản gần nhất",
        ],
    },
    "function-diff": {
        category: "Danh sách vấn đề",
        title: "Function Diff (so sánh 2 snapshot)",
        purpose: "So chi tiết 2 snapshot: thấy field nào của function nào bị đổi (VD PIC đổi, End date đổi).",
        steps: [
            "Chọn snapshot A và B",
            "3 tab: Function added / Function removed / Function changed",
            "Tab 'changed' hiện diff level cell",
        ],
        example: "Function A.01 tuần trước PIC=Alice, tuần này PIC=Bob → thấy trong tab 'changed'.",
        tips: [
            "Tương tự Snapshot Compare nhưng chi tiết hơn (cell-level diff)",
        ],
    },

    // ==================== TÙY CHỈNH ====================
    "custom-dashboards": {
        category: "Tùy chỉnh",
        title: "Custom Dashboards",
        purpose: "Tự tạo dashboard chart theo yêu cầu — VD 'Function trễ theo module trong quý này'. Wizard hoặc chat.",
        steps: [
            "Bấm ➕ Dashboard trên header",
            "Chọn tab Wizard (dùng form) hoặc Chat (mô tả tự nhiên)",
            "Cấu hình dimension/measure/filter",
            "Save → chart xuất hiện ở section này",
        ],
        example: "Tạo 'Bar chart function High complexity chưa Close theo Module' → 1 chart custom.",
        tips: [
            "Có thể export/import chart config qua JSON để share",
            "Chart config chart_id unique — tự sinh nếu trùng",
        ],
    },
    "kanban": {
        category: "Tùy chỉnh",
        title: "Kanban (theo tuần)",
        purpose: "Kanban view function theo tuần: cột = 'Tuần trước' / 'Tuần này' / 'Tuần sau' / 'Xa hơn', card = function.",
        steps: [
            "Tự động group theo end_date của phase active",
            "Kéo thả (chưa hỗ trợ) — chỉ để visualize",
        ],
        example: "Nhìn Kanban thấy tuần này có 15 function cần close → tập trung xử lý.",
        tips: [
            "Kanban dùng data đã upload — không sync realtime với external tool",
        ],
    },
    "history": {
        category: "Tùy chỉnh",
        title: "Upload History (lịch sử upload)",
        purpose: "Lịch sử các lần upload/sync — tên file, timestamp, số function. Chỉ giữ 10 lần gần nhất.",
        steps: [
            "Xem timestamp để biết data này refresh khi nào",
            "Có thể restore snapshot cũ (trong 10 bản gần nhất) nếu cần",
        ],
        example: "Thấy file gần nhất upload lúc Thứ Hai 9h → data hôm nay là cũ 4 ngày, cần refresh.",
        tips: [
            "Auto reminder nếu >7 ngày chưa upload — Settings → Upload reminder",
        ],
    },

    // ==================== PUBLIC API ====================
    "public-api": {
        category: "Public API",
        title: "Public API (chia sẻ ra ngoài)",
        purpose: "Cấp token cho bên thứ 3 truy cập read-only qua REST / iframe / PNG. Dùng cho partner, Confluence, email báo cáo.",
        steps: [
            "Settings → tab 🌐 Public API",
            "Bấm ➕ Tạo token mới → nhập tên + chọn scope",
            "Copy token 1 lần duy nhất (server không lưu plaintext)",
            "3 tab snippet: REST curl / iframe HTML / PNG img",
        ],
        example: "Cấp token cho Confluence page hiển thị chart Module Overview → dán iframe snippet vào Confluence.",
        tips: [
            "Token có thể revoke bất cứ lúc nào — status thành 'revoked'",
            "Scope * = full access; scope cụ thể (VD 'module-overview') để restrict",
        ],
        learn_more: "docs/PUBLIC_API_GUIDE.md",
    },

    // ==================== IMPORT/EXPORT ====================
    "upload": {
        category: "Import/Export",
        title: "Upload Excel (Column Mapping Wizard)",
        purpose: "Upload file Excel Function List. Nếu header không chuẩn iHRP → mở Wizard để map cột thủ công.",
        steps: [
            "Drag & drop file .xlsx vào upload zone (hoặc click chọn)",
            "Wizard mở → preview 5 dòng đầu + suggestion tự động",
            "Sửa mapping nếu cần → nút 🔍 Test parse → confirm",
            "Nút 'Skip wizard' để dùng auto-detect (file chuẩn iHRP)",
        ],
        example: "Upload file khách hàng có header 'Function Code' → Wizard map tự động thành 'Mã CN'.",
        tips: [
            "Lưu preset mapping để lần sau apply nhanh cho vendor giống nhau",
            "Test parse cho biết mapping có tạo ra data iHRP đúng không",
        ],
        learn_more: "docs/INTEGRATIONS_GUIDE.md#smart-mapping",
    },
    "export-all-issues": {
        category: "Import/Export",
        title: "Xuất toàn bộ vấn đề (Excel multi-sheet)",
        purpose: "1 nút xuất Excel workbook chứa mọi loại vấn đề (Overdue + Chưa PIC + Đình trệ + High Risk + Aging WIP + Data Quality + Bookmark) — mỗi loại 1 sheet.",
        steps: [
            "Bấm 📊 Xuất vấn đề trên header",
            "File .xlsx download có 8 sheet (Cover + 7 loại)",
            "Cover có hyperlink → click nhảy đến sheet",
        ],
        example: "Chuẩn bị họp escalation Thứ Hai → 1 file .xlsx có toàn bộ vấn đề, gửi email luôn.",
        tips: [
            "Apply global filter hiện tại — VD filter Module=HR → chỉ export vấn đề của HR",
            "Sheet Overdue dedup theo Mã CN, phase merged (không lặp)",
        ],
    },
    "export-pdf": {
        category: "Import/Export",
        title: "Xuất PDF báo cáo tuần",
        purpose: "Xuất PDF chọn lọc các chart quan trọng + comment/summary — báo cáo tuần cho leadership.",
        steps: [
            "Bấm 📄 Xuất PDF trên header",
            "Modal mở: tích chọn các chart muốn có trong PDF",
            "Nhập comment cho mỗi chart + tóm tắt chung",
            "Bấm 'Xuất PDF' → download",
        ],
        example: "Chọn 5 chart top + comment 'Tuần này focus module HR' → PDF 6 trang cho leadership.",
        tips: [
            "Comment tự lưu vào `.project_store` — lần sau tự pre-fill",
            "Render toàn bộ qua html2canvas để đảm bảo tiếng Việt + emoji không lỗi",
        ],
    },
    "integrations": {
        category: "Import/Export",
        title: "API Registry (integrations)",
        purpose: "Cấu hình integration lấy data tự động từ system nguồn — REST API, DB view, form_login. Chỉ cần 1 nút sync.",
        steps: [
            "Bấm 🔌 API Registry trên header",
            "➕ Tạo integration mới → chọn auth method",
            "Điền endpoint + field mapping",
            "Bấm 'Sync' → data tự parse + tạo snapshot",
        ],
        example: "Config integration lấy data từ iHRP DB view mỗi sáng thay vì upload Excel thủ công.",
        tips: [
            "Credentials lưu trong .env, không lưu trong integrations.json",
            "Support: form_login, basic_auth, bearer, api_key, database",
        ],
        learn_more: "docs/INTEGRATIONS_GUIDE.md",
    },
};

// Export globals
window.HELP_CONTENT = HELP_CONTENT;
window.HELP_CATEGORIES = HELP_CATEGORIES;
