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
    "Chất lượng",
    "Rủi ro & Chất lượng",
    "Chiều PM",
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
            "Cột «Còn lại» / «MH còn» = function hoặc Estimate MH chưa Closed — ưu tiên module còn nhiều việc",
            "Có thể sort theo bất kỳ cột nào bằng cách click header",
            "Badge cam «DQ N» = N lỗi Data Quality của module — click → nhảy sang section Data Quality đã lọc module đó",
            "📥 Xuất Excel qua nút export Module Overview (Tổng hợp / Chi tiết)",
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
        purpose: "Heatmap 2D — hàng = module, cột = phase, cell = % Closed. Nhận diện nhanh 'module + phase' nào đang stuck (bottleneck).",
        steps: [
            "Cell càng xanh = càng gần 100% Closed",
            "Cell đỏ = <30% → bottleneck cần chú ý",
            "Click 1 cell → drill xem function chi tiết của (module, phase)",
            "Footer matrix có gợi ý bottleneck (ô thấp + nhiều volume)",
        ],
        example: "Cell 'HR × UAT' đỏ 20%, còn 'HR × Analysis' xanh 90% → HR đang stuck ở UAT.",
        tips: [
            "Có thể toggle hiển thị số tuyệt đối / % qua chart config",
            "Reorder cột phase theo thứ tự thực tế của dự án qua Settings → Phase aliases",
            "Cell tô cam + «DQ N» = có lỗi Data Quality — click cell → mở Data Quality lọc theo module × phase đó",
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
        title: "Timeline (Gantt-style)",
        purpose: "Timeline mỗi function/module/quy trình với start/end theo phase. Local filter Status/Phase/Priority + Chỉ còn việc mở + Có/Chưa có date (kết hợp global filter).",
        steps: [
            "Nhóm: Module | Quy trình | Function · Scale: Tuần | Tháng | Quý",
            "Local filter: Status (multi, gồm Overdue-only), Phase, Priority (nếu có), checkbox Chỉ còn việc mở, toggle Có date / Chưa có date",
            "Hover thanh → tooltip; click function → drill-down chi tiết",
        ],
        example: "Lọc Status=In-progress + Chỉ còn việc mở để chỉ thấy bar đang làm, bỏ 100% Closed.",
        tips: [
            "Global Module/Process/PIC vẫn áp trước; local filter thu hẹp thêm trên dữ liệu đã cascade",
            "Dòng '(Chưa có date)' = nhóm/function chưa có Start–End — dùng toggle 'Chưa có date' để soi",
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
    "forecast-manpower": {
        category: "Tiến độ & Timeline",
        title: "Forecast Manpower — MH / MD / MM & tuyển",
        purpose: "Ước lượng khối lượng còn lại theo Estimate MH (hoặc Duration), quy đổi MD/MM, và tính cần bao nhiêu người / tuyển thêm theo Dev riêng vs Triển khai chung.",
        steps: [
            "Chọn cơ sở Unit (Estimate MH, trống = 8) hoặc Duration (ngày làm Start→End × 8 MH)",
            "Chọn đơn vị hiển thị: MH / MD / MM",
            "Nhập Target tháng + số người Dev / Triển khai hiện tại",
            "Xem pool + từng công đoạn: còn lại, người cần, tuyển thêm, cột ghi chú phương pháp",
            "Xuất Excel: Tổng hợp | Chi tiết | Cả hai",
        ],
        example: "Còn 320 MH Dev, target 1 tháng (160 MH/người) → cần 2 người. Đang có 1 → tuyển thêm 1.",
        tips: [
            "Lập trình = pool riêng; Phân tích/Test/Config/UAT/Golive = Triển khai chung",
            "1 MD = 8 MH; 1 MM = 160 MH (20 ngày × 8h) trong section này",
            "Filter Module/Quy trình + global filter đều được tôn trọng",
            "Muốn ước lượng parametric (hệ số Des/Test/Doc/UAT) → xem section «Ước lượng theo hệ số» (không ghi đè FL)",
        ],
    },
    "estimate-ratio": {
        category: "Tiến độ & Timeline",
        title: "Ước lượng theo hệ số (parametric)",
        purpose: "Tính MM/MH theo công đoạn bằng seed BA/Dev + hệ số chỉnh được (Des, Test, Doc, UAT…). Bổ sung cho Forecast Manpower — không thay unit/duration và không ghi đè Estimate MH trên Function List.",
        steps: [
            "Seed mỗi function: Estimate MH phase BA/Dev (nếu có) → bảng lookup Complexity×FIT/GAP → BA/Dev mặc định trong params",
            "Áp hệ số: Des=BA×r, Test=Dev×r, Doc=Dev×r; Config/Migration ưu tiên MH trên FL nếu có",
            "Tuỳ chọn overhead dự án: UAT ≈ % tổng gồm UAT, Golive=%UAT, PM%",
            "Chỉnh hệ số trên form → Tính lại; Lưu params dự án → estimation_params.json",
            "Copy MH gợi ý để đối chiếu Forecast Manpower (không tự ghi FL)",
        ],
        example: "BA=1 MD, Dev=2 MD → Des=0.25, Test=0.6, Doc=0.3 MD. Bật UAT 15% → UAT = 0.15/0.85 × build.",
        tips: [
            "Defaults là gợi ý PMO (chỉnh được) — không khóa số liệu một dự án mẫu",
            "File: uploads/projects/<slug>/estimation_params.json; global: uploads/estimation_params.json",
            "MM ở đây dùng md_per_mm (mặc định 22) — có thể khác MM=160 MH của Forecast Manpower",
            "Cảnh báo vàng khi nhiều function phải dùng seed mặc định",
        ],
    },
    "baseline": {
        category: "Tiến độ & Timeline",
        title: "Baseline vs Actual — Schedule Variance",
        purpose: "So sánh End hiện tại với End trong snapshot baseline (kế hoạch gốc approved) → SV ngày; kèm bảng Planned/Actual legacy trong cùng file nếu có.",
        steps: [
            "Chọn 1 snapshot làm baseline (dropdown section hoặc Settings → Archive)",
            "SV = end_hiện_tại − end_baseline (ngày). SV>0 = trễ · SV<0 = sớm",
            "Xem Milestone / Module / chi tiết function×phase",
            "📥 Xuất SV: Excel Tong_hop (milestone+module) + Chi_tiet. 📥 Legacy: Planned/Actual trong file",
        ],
        example: "Baseline W20; hiện tại UAT dời +14 ngày → Milestone UAT tô đỏ, module HR avg SV +9d.",
        tips: [
            "Baseline không tự lưu — phải đánh dấu explicit",
            "Phase Cancelled hoặc thiếu End ở một phía → không so sánh",
        ],
    },
    "completion-forecast": {
        category: "Tiến độ & Timeline",
        title: "Dự báo ngày xong (velocity)",
        purpose: "Ước tính ngày hoàn thành linear từ remaining phases ÷ velocity Closed/tuần (4 tuần gần nhất), kèm 3 kịch bản.",
        steps: [
            "Xem banner Insight hoặc chip trên Burndown",
            "remaining = phase chưa Closed/Cancelled; velocity = TB Closed 4 tuần",
            "3 kịch bản: Lạc quan (best 4w) · Khả năng cao (avg) · Bi quan (worst 4w >0)",
            "Band tin cậy = ngày optimistic → pessimistic",
            "📥 Xuất Excel: tổng hợp + Closed theo tuần + 3 scenarios",
        ],
        example: "Còn 80 phase; best=20, avg=10, worst=5 → ~4 / 8 / 16 tuần.",
        tips: [
            "Velocity = 0 hoặc chưa có lịch sử Closed → không dự báo được",
            "Filter Module/Phase trên Burndown ảnh hưởng phạm vi dự báo",
        ],
    },
    "evm-scurve": {
        category: "Tiến độ & Timeline",
        title: "EVM S-curve",
        purpose: "Đường EV / PV / AC theo tuần từ lịch sử snapshot (cùng công thức SPI/CPI).",
        steps: [
            "Upload nhiều lần để có chuỗi snapshot",
            "Mỗi điểm = EVM tính với today = ngày snapshot",
            "PV cần baseline; không baseline vẫn xem EV/AC",
            "📥 Xuất Excel S-curve",
        ],
        example: "EV tăng chậm hơn PV → SPI < 1 trên nhiều tuần.",
        tips: ["Giữ snapshot (Settings) đủ dài để thấy xu hướng"],
    },
    "exec-dashboard": {
        category: "Chiều PM",
        title: "PM Executive Dashboard",
        purpose: "Một trang tổng hợp cho PM: % xong, SPI/CPI, forecast, scope creep, milestone, top 5 risk.",
        steps: [
            "Mở section Executive (nhóm Forecast)",
            "Đọc 6 card tóm tắt + milestone + top risks",
            "📥 Xuất Excel 1 trang cho họp status",
        ],
        example: "SPI 0.9 · creep 12% · forecast 15/09 → cần đẩy scope/CR.",
        tips: ["Cần baseline để SPI có nghĩa; mitigation hiện ở top risks nếu đã nhập"],
    },
    "risk-trend": {
        category: "Rủi ro & Chất lượng",
        title: "Risk trend + mitigation",
        purpose: "Xu hướng avg/high-risk theo snapshot; gắn owner · hạn · ghi chú mitigation (không phải JIRA).",
        steps: [
            "Xem chart xu hướng trên section Risk",
            "Nhập Owner / Target / Note ngay trên từng dòng risk",
            "Dữ liệu lưu trong project store (risk_mitigations.json)",
        ],
        example: "High-risk 12→8 sau 2 tuần + mitigation owner BA.",
        tips: ["Mitigation theo Mã CN; có thể dùng key module:X cho cả module"],
    },
    "dq-ownership": {
        category: "Rủi ro & Chất lượng",
        title: "DQ ownership + SLA",
        purpose: "Gán PIC + hạn xử lý cho từng Data Quality issue; theo dõi resolution rate tuần.",
        steps: [
            "Mở Data Quality → cột PIC phụ trách / Hạn / SLA",
            "Tick «xong» khi đã sửa trên FL",
            "Card Ownership hiện rate WoW vs snapshot trước",
        ],
        example: "20 issue mở tuần trước, 12 còn lại + 5 marked → rate ~65%.",
        tips: ["Key ổn định: ma_cn|phase|code"],
    },
    "insight-module-deltas": {
        category: "Tiến độ & Timeline",
        title: "Insight Δ theo module",
        purpose: "OD / UA / ST delta theo từng module (không chỉ tổng dự án).",
        steps: [
            "Mở rộng Insight strip",
            "Xem bảng top module biến động vs snapshot trước",
            "Chip Δmod trên thanh Insight tóm tắt 3 module nổi bật",
        ],
        example: "HR: OD+3 / UA−1 · TMS: ST+2.",
        tips: ["Cần ≥2 snapshot"],
    },
    "forecast-gantt": {
        category: "Tiến độ & Timeline",
        title: "Forecast — UAT / Golive theo tháng",
        purpose: "Nhìn tháng dự kiến UAT / Golive (và các milestone) từ Function List; so SV với baseline nếu đã đánh dấu.",
        steps: [
            "Xem tháng UAT / Golive trên badge + Gantt theo tháng",
            "1 dự án: thêm Phân tích / Dev / Cấu hình xong",
            "Nếu có baseline: diamond + chip SV (trễ/sớm)",
            "📥 Xuất Excel bảng milestone / module",
        ],
        example: "UAT dự kiến 09/2026, baseline 08/2026 → SV +1 tháng (trễ).",
        tips: [
            "Rule open_max / closed_max — xem hint dưới tiêu đề",
            "Tôn trọng Global filter",
        ],
    },
    "estimate-ratio": {
        category: "Tiến độ & Timeline",
        title: "Ước lượng theo hệ số",
        purpose: "Parametric: seed BA/Dev rồi nhân hệ số Des/Test/Doc/UAT… — không ghi đè FL, không thay Forecast Manpower.",
        steps: [
            "Chỉnh seed BA/Dev MD, MD/MM, hệ số → ↻ Tính lại",
            "Xem bảng công đoạn (MD/MH/MM) + % seed mặc định",
            "📋 Copy MH → Forecast để đối chiếu thủ công",
            "💾 Lưu params dự án (estimation_params.json) · 📥 Xuất Excel",
        ],
        example: "80 fn × seed Dev 2 MD → Test = 30% Dev → cộng UAT 15% tổng gồm UAT.",
        tips: [
            "1 MM ở đây = md_per_mm × MD (mặc định 22) — khác MM=160 MH của Forecast Manpower",
            "Lookup Complexity×FIT/GAP trong params nếu có",
        ],
    },
    "pic-upcoming": {
        category: "Phân tích chuyên sâu",
        title: "PIC × tuần tới",
        purpose: "Ma trận PIC × tuần: số task chưa Closed/Cancelled có End (hoặc Start) rơi vào các tuần tới.",
        steps: [
            "Chọn số tuần (2–8) → bảng heatmap cường độ",
            "Click ô có số → drill workload PIC",
            "📥 Xuất Excel: ma trận + chi tiết task",
        ],
        example: "BaoLQ31 có 6 task W32 → cần san tải trước khi vào UAT.",
        tips: [
            "Ô PIC nhiều người được tách (dấu phẩy / ; / xuống dòng)",
            "Tôn trọng Global filter Module / Quy trình / PIC",
        ],
    },
    "insight-strip": {
        category: "Tổng quan",
        title: "Insight strip",
        purpose: "Thanh thu gọn các tín hiệu nhanh (dự báo xong, FL verify, trend, auto-diff) để Module Overview cao hơn.",
        steps: [
            "Bấm thanh Insight để Mở rộng / Thu gọn (nhớ localStorage)",
            "Chip tóm tắt hiện ngay cả khi collapsed",
            "Bên trong: Auto-diff · Trends · Dự báo ngày xong · FL re-import",
        ],
        example: "Chip «📅 15/09/2026 · OD ↓3 · Δ +2 fn» → mở rộng xem chi tiết.",
        tips: [
            "Mặc định collapsed sau upload để ưu tiên bảng Module",
            "Export riêng từng khối (Dự báo / FL) khi cần gửi mail",
        ],
    },
    "auto-diff": {
        category: "Tổng quan",
        title: "Auto-diff (sau upload/sync)",
        purpose: "Badge nhanh so với snapshot trước: function mới, bị xoá, status rollback, PIC đổi.",
        steps: [
            "Upload / sync xong → badge hiện trong Insight",
            "Bấm badge để xem list · hoặc mở Function Diff đầy đủ",
            "Xuất chi tiết qua section Function Diff (📥)",
        ],
        example: "+5 function mới · 2 status rollback · 3 PIC đổi so với snapshot hôm qua.",
        tips: [
            "Cần ≥2 snapshot để so sánh",
            "Rollback = status «lùi» (vd Closed → In-progress) — cần xác minh",
        ],
    },
    "summary-trends": {
        category: "Tổng quan",
        title: "Trends (snapshot)",
        purpose: "Chip delta Overdue / Unassigned / Stalled giữa 2 snapshot gần nhất + sparkline ngắn.",
        steps: [
            "Cần ≥2 snapshot trong History",
            "↑ đỏ thường xấu với Overdue; ↓ xanh = cải thiện",
            "Xem thêm So sánh snapshot (section Compare)",
        ],
        example: "Overdue 74→61 ↓13 · Unassigned 12→15 ↑3.",
        tips: [
            "Không xuất Excel riêng (quá mỏng) — dùng Compare / Digest nếu cần báo cáo",
        ],
    },
    "fl-verify": {
        category: "Import/Export",
        title: "FL re-import verify",
        purpose: "Sau khi re-import Function List đã tô vàng (PIC/Status), kiểm tra ô vàng đã được điền chưa.",
        steps: [
            "Xuất FL re-import từ header / PIC Overload / banner",
            "Điền ô vàng trên Excel → upload lại",
            "Banner hiện số đã fix / còn trống · 📥 xuất lại nếu cần",
        ],
        example: "FL verify 12/15 — còn 3 ô PIC trống cần điền.",
        tips: [
            "Không tự invent PIC — chỉ đối chiếu với schema re-import",
        ],
    },
    "accounts": {
        category: "Tùy chỉnh",
        title: "Tài khoản & đăng nhập",
        purpose: "Đăng nhập session bảo vệ dashboard; admin tạo user / đặt lại mật khẩu.",
        steps: [
            "Lần đầu: đăng nhập admin / admin (đổi mật khẩu ngay)",
            "Menu Tài khoản → đổi mật khẩu của tôi",
            "Admin: tạo viewer/admin mới, reset mật khẩu user khác",
        ],
        example: "Tạo user viewer cho BA chỉ xem; giữ admin cho PM.",
        tips: [
            "Có thể tắt auth bằng biến môi trường (deploy nội bộ) — xem docs LAN",
            "Public API dùng token riêng, không dùng session admin",
        ],
    },
    "earned-value": {
        category: "Tiến độ & Timeline",
        title: "Earned Value (SPI / CPI)",
        purpose: "Đo tiến độ lịch (SPI) và hiệu quả effort (CPI) theo Estimate MH và baseline; kèm S-curve theo tuần.",
        steps: [
            "EV = Estimate MH × % status (Closed 100%, In-progress 50%…)",
            "PV = MH lẽ ra xong theo lịch baseline tới hôm nay (cần đánh dấu baseline)",
            "AC ≈ số ngày làm thực tế × 8 MH (proxy khi không có timesheet)",
            "SPI = EV÷PV · CPI = EV÷AC (<1 = chậm / vượt effort)",
            "S-curve: EV/PV/AC theo snapshot tuần (📥 Xuất S-curve)",
        ],
        example: "SPI 0.85 + CPI 1.1 → chậm lịch nhưng effort đang tiết kiệm hơn ước lượng.",
        tips: [
            "Chưa baseline → SPI = N/A; vẫn xem được EV/AC/CPI",
            "Ô Estimate MH trống dùng mặc định 8 MH (giống Forecast Manpower)",
        ],
    },
    "scope-creep": {
        category: "Tiến độ & Timeline",
        title: "Scope Creep — CR vs Scope gốc",
        purpose: "Đo tỷ lệ function phát sinh (Change Request) so với scope gốc để đàm phán effort với khách.",
        steps: [
            "Primary: cột Excel tự nhận (CR / Change Request / Phát sinh / Scope Creep / exact «CR»)",
            "Fallback (không có cột): tag «CR» trong drill-down hoặc Mã CN trong Cài đặt",
            "Scope creep % = số CR ÷ tổng function; Effort = Σ Estimate MH (trống → 8 MH)",
            "Xem breakdown theo module + danh sách CR (MH lớn trước) để chuẩn bị đàm phán",
        ],
        example: "12/80 function là CR (15%) · 320 MH CR vs 1800 MH gốc → cần change order.",
        tips: [
            "Ưu tiên thêm cột «Phát sinh» trên Function List — nguồn đáng tin hơn tag thủ công",
            "Có cột «Ngày phát sinh» (tuỳ chọn) để theo dõi khi nào CR được raise",
        ],
    },
    "uat-quality": {
        category: "Chất lượng",
        title: "UAT Quality — Defect / Reopen / Cycle",
        purpose: "Đo chất lượng giao hàng qua defect, feedback, reopen rate và số vòng UAT — không chỉ Open/Closed.",
        steps: [
            "Auto-detect cột: Defect/Bug/Số lỗi, Feedback/Phản hồi, Reopen, UAT cycle/Số vòng UAT",
            "Tổng defect & feedback theo function → rollup theo module",
            "Reopen rate = (# fn reopen>0) ÷ (# UAT Closed|Resolved ∪ reopen>0) × 100",
            "TB vòng UAT + số function ≥ 2 vòng; thiếu cột → empty + tag «UAT issue» (không bịa số)",
        ],
        example: "HR: 24 defect, reopen 18%, TB 1.6 vòng UAT → cần sẵn sàng trước khi vào UAT lại.",
        tips: [
            "Thêm cột «Số lỗi» / «Reopen» / «Số vòng UAT» trên Excel để có số liệu thật",
            "Không có cột: gắn tag «UAT issue» hoặc ghi chú function — chỉ qualitative",
            "Exact header Bug/Defect được nhận; cột «Debug» không bị nhầm",
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
        purpose: "Phát hiện bottleneck chuyển giao: phase trước Closed, phase sau chưa bắt đầu, và End của phase chờ đã quá hạn (end < hôm nay). Deadline chưa tới hoặc chưa có End → không hiện. Bỏ qua function đã xong toàn trình (phase cuối Closed / mọi phase Closed|Cancelled).",
        steps: [
            "Với mỗi cặp phase liền nhau: pred Closed + phase sau None/Open + End phase chờ < hôm nay → vào danh sách",
            "Không có End trên phase chờ → không stalled (tránh false positive «chưa plan»)",
            "Nếu Golive (phase cuối) đã Closed, hoặc mọi phase Closed/Cancelled → không đưa vào list/transitions",
            "Cột 'Chờ (ngày)' = hôm nay − ngày End của phase đã Closed; sort giảm dần theo wait_days",
            "Funnel chart (trái): tổng số function Closed theo từng phase",
            "Transitions (phải): cặp 'từ → sang' bị kẹt nhiều nhất",
            "Bấm Chi tiết / 📥 để drill-down hoặc xuất Excel",
        ],
        example: "Analysis Closed, Dev Open/blank nhưng Dev End còn tương lai → không đình trệ. Dev End đã qua mà vẫn Open → stalled. Golive Closed dù Dev blank → không vào list.",
        tips: [
            "Wait_days > 7 tô cam, > 14 tô đỏ — ưu tiên escalate dòng đỏ trước",
            "Transitions cho biết chặng chuyển giao nào tắc nhiều nhất",
            "Thường thiếu PIC phase sau hoặc chờ handover — xem thêm section Chưa PIC",
        ],
    },
    "risk": {
        category: "Danh sách vấn đề",
        title: "High Risk (điểm rủi ro cao)",
        purpose: "Function được đánh giá risk score cao dựa nhiều yếu tố: trễ, priority, complexity, PIC overload, cascade delay module…",
        steps: [
            "Score 0-100 (càng cao càng risk); cap 100",
            "Yếu tố mới Phase D: PIC overload +15; cascade module +10",
            "Card Resource / Dependency tóm tắt góc nhìn PM",
            "Tick «Overload đa dự án» để feed PIC overload cross-project",
        ],
        example: "Function ESS.FR.10 score 85: 'Overdue + Must-have + PIC overload' → họp focus.",
        tips: [
            "Thứ tự module (Cài đặt) quyết định predecessor cho cascade",
            "Gate mặc định = phase Config/Cấu hình; Closed < 70% → block downstream",
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
        title: "Data Quality — DQ (chất lượng dữ liệu)",
        purpose: "DQ = Data Quality. Section phát hiện lỗi/thiếu trong Function List (thiếu deadline, overlap ngày, estimate lệch, status sai, trùng Mã CN…) để clean Excel trước khi báo cáo.",
        steps: [
            "Mở section: sidebar «Data Quality», hoặc Ctrl+K → gõ Data Quality, hoặc click badge cam «DQ» trên Module Overview / Phase Matrix",
            "Xem summary cards (Clean %, High/Medium/Low, thiếu deadline, bất thường) → filter Module / severity / loại issue",
            "Đọc cột «Gợi ý» rồi sửa trên file Excel gốc → upload lại (không sửa trên dashboard)",
        ],
        example: "Dev In-progress thiếu End → missing_deadline. Hai phase chồng lịch → phase_overlap. Estimate MH lệch duration → estimate_vs_duration. Closed thiếu End → closed_no_end (rule riêng).",
        tips: [
            "Badge «DQ N» (cam) trên Module Overview / ô Phase Matrix = N issue DQ — click để drill vào section này đã lọc đúng module (× phase)",
            "Card tổng quan «Chưa cập nhật deadline» / «Bất thường» click → lọc đúng nhóm issue tương ứng",
            "Score Clean % = (total − affected) / total",
            "Các loại hay gặp: thiếu End khi đang làm, End < Start, phase overlap, estimate lệch, trùng Mã CN, thiếu PIC/Priority/Complexity/FIT-GAP, status không hợp lệ",
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
        purpose: "Kanban view function theo tuần: cột = trạng thái tuần (Chưa làm / Đang làm / Quá hạn / …), card = function.",
        steps: [
            "Tự động group theo ngữ cảnh tuần (overdue / in-progress / next week…)",
            "Filter local Module/Process/PIC/Role — AND với global filter phía trên",
            "Badge «Đang lọc» phản ánh local filter đang áp",
        ],
        example: "Global Module=8 selected, local Module=HR → board chỉ còn card HR.",
        tips: [
            "Kanban dùng data đã upload — không sync realtime với external tool",
            "Local filter không UNION với global — chọn HR sẽ không còn thẻ PR/TMS",
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
