# Changelog — PMO Phase A–F + BA UX (+ Issues 2026-08)

> Cập nhật: **2026-08-06**. Tài liệu ngắn cho reviewer: phạm vi đã giao, file chính, hạn chế.
> Verify: `tests/test_*pmo*` · `test_ba_ux*` · `test_sqlite*` · `test_stalled*` · `test_status_aliases*` · `test_drill_down*`.

---

## Wave 2026-08-06 — DQ bỏ qua function đã Closed toàn bộ + filter Status cho «Chưa PIC»

**Phản hồi user:** Data Quality flag 1300+ issue trong đó phần lớn là các function
đã Closed nhiều tháng trước (blank Priority/FIT-GAP/Complexity, phase overlap,
estimate MH lệch…). Rule cũ ép PM backfill meta của kho đã đóng — không actionable.

**Đã giao — `analyzer/data_quality.py`:**

- Thêm `is_row_fully_done(row)`: True khi function có ≥1 phase Closed/Cancelled
  và không phase nào còn Open/Assigned/In-progress/Resolved/Pending. Blank status
  coi như "phase không áp dụng".
- `compute_data_quality`, `count_missing_deadlines`, `count_anomalies` **skip
  toàn bộ** row fully-done. Row vẫn tính vào `total_rows` + `clean_rows` để
  `clean_pct` phản ánh đúng.
- Duplicate `ma_cn` cũng bỏ qua: nếu **mọi** copies đều Closed → không flag; chỉ
  flag các copies chưa done khi có ≥2 copies chưa done.

**Đã giao — section «Chưa PIC» (`section-unassigned`):**

- Thêm dropdown Status cục bộ (`#unassignedStatusFilter`) — options = unique
  statuses trong dataset hiện tại, preserve chọn cũ khi re-render, auto reset về
  «Tất cả» nếu status cũ không còn (VD sau sync ra data mới).
- `renderUnassignedSection` áp filter trước khi phân trang; count text phản ánh
  scope lọc: `Đang xem 1–5/12 (lọc status=Open, tổng 47 task chưa có PIC)`.
- Backend `/export-fl-reimport?kinds=unassigned` nhận thêm `l_status` để file
  xuất khớp bảng đang lọc.
- Drill-down `analyzer/drill_down.py::_filter_unassigned` nhận `filters["status"]`
  — nút Chi tiết đi qua `openUnassignedDrill()` để đồng bộ scope với table.

Tests: `tests/test_data_quality.py` (+5 case fully-done), `tests/test_unassigned_status_filter.py`
(6 case FE + backend), `tests/test_drill_down.py::test_unassigned_drill_status_filter`.

---

## Wave 2026-08d — `?v=` của JS/CSS ghim theo bản đang chạy (bỏ trạng thái lai)

**Phản hồi:** section Thiếu/Trùng FID vẫn hiện filter dropdown đơn cũ (không thấy
multi-select + menu 2 chế độ đã ship), và bấm nút xuất thì báo lỗi.

**Điều tra — không phải lỗi export.** Process đang chạy khởi động **09:42**, còn
các file đã sửa có mtime **15:12–15:26**. `start.bat` chạy `debug=False` nên
`use_reloader=False` và Jinja `auto_reload=False`: template đã biên dịch nằm
trong RAM, `.py` không nạp lại. Nhưng `static_ver()` là hàm gọi **lúc render**,
nên `?v=` cập nhật ngay theo mtime trên đĩa. Đo trên server đang chạy:

| Thành phần | Trạng thái thực tế |
|---|---|
| HTML | **cũ** (`fidModuleFilter`, `exportFidIssuesFL`, nút "Xuất FL update FID") |
| JS | **mới** (`?v=` đổi → browser buộc phải tải lại) |
| Backend | **cũ** (chưa có `/export-fid-issues`, chưa hiểu `kinds`) |

Nút của HTML cũ gọi vào shim của JS mới, shim gọi endpoint/tham số backend cũ
chưa có → lỗi. Đây là lỗi của **cập nhật một nửa**, không phải lỗi logic.

Đã giao:

- `_static_ver()` trả **stamp cố định theo process** (`_BUILD_STAMP`) khi
  template không bám đĩa; vẫn trả mtime khi chạy `--debug`. Điều kiện là
  *template có nạp lại theo đĩa hay không* (`_templates_track_disk()`), chứ
  không phải `app.debug` trực tiếp — ai set `TEMPLATES_AUTO_RELOAD` tường minh
  thì vẫn đúng.
- Chuỗi phiên bản nay định danh **bản đang chạy**, không phải file trên đĩa. Hệ
  quả: chưa restart thì không gì đổi (dễ hiểu, tự khắc nghĩ tới restart); restart
  thì HTML + JS + backend đổi cùng nhau.

**Đánh đổi:** mỗi lần restart browser tải lại toàn bộ asset thay vì chỉ file đã
sửa. Không đáng kể vì phục vụ từ localhost. Đổi lại là bỏ được cả một lớp bug
"sửa xong mà lỗi ở chỗ không liên quan" cực khó truy.

- **HTML trả `Cache-Control: no-cache, must-revalidate`** (`_no_cache_html`).
  Trước đó HTML không mang chỉ thị cache nào (chỉ `Vary: Cookie`) nên browser áp
  heuristic và có thể dùng lại bản cũ — mà bản cũ nhúng `?v=` cũ, nên bundle JS
  cũng bị ghim theo bản cũ, đúng cái `_BUILD_STAMP` sinh ra để tránh. Chỉ chạm
  response `text/html`; JSON API và file Excel tải về không bị ảnh hưởng (có
  test chốt). File static không cần sửa: Flask đã trả `no-cache` + ETag theo mtime.

**Vẫn cần restart sau mỗi lần sửa `.py` hoặc `templates/`** — chế độ PRODUCTION
không auto-reload, và thay đổi này không làm nó reload. Nó chỉ đảm bảo trạng
thái luôn nhất quán, không nửa mới nửa cũ.

**Không chữa được tab đang mở.** Tab mở từ trước vẫn chạy bundle JS đã nạp trong
bộ nhớ cho tới khi reload — không có cơ chế server nào can thiệp được. Triệu
chứng điển hình: toast `... is not defined` với tên hàm không tồn tại trong
source hiện tại (đã gặp: `apFetch is not defined` ở Báo cáo tuần, trong khi
`loadWeeklyGap` dùng `apiJson`). Cách nhận biết: grep tên hàm đó trong repo —
không thấy ở đâu, kể cả git history, thì đó là bundle cũ trong tab, không phải
bug code.

Verify: `tests/test_static_ver.py` (13 test), gồm bất biến "touch file mà stamp
không đổi", "mọi asset dùng chung 1 stamp", và "header HTML không lây sang JSON
/ file tải về".

### Badge «Bản đang chạy» + Restart / Tải lại / Reset giao diện

Bịt khoảng trống lớn nhất còn lại: **không có cách nào biết server đang chạy code
cũ**, ngoài việc đoán.

- **Badge trên header** (`#buildStatusBtn`): bình thường là icon mờ; khi có `.py`
  hoặc template đã sửa sau lúc server khởi động thì đổi vàng + hiện «Cần restart»;
  khi JS/CSS trên đĩa mới hơn thời điểm trang được nạp thì hiện «Cần tải lại».
  Poll 60 giây và kiểm ngay khi tab được focus.
- **Panel chi tiết**: liệt kê từng file đã sửa kèm giờ và nhãn `restart`/`reload`,
  cho biết interpreter đang phục vụ (venv hay Python hệ thống — hay bị nhầm khi
  truy lỗi thiếu package sau restart), và số file đang theo dõi.
- **♻️ Restart server**: gọi `start.bat` qua `restart_helper.bat`, kèm overlay tự
  poll `/api/health` rồi tải lại trang khi server mới lên. Đo thực tế 8–10 giây.
  Chỉ admin, chỉ localhost. Chỉ Windows (`start.sh` không dọn process giữ port).
- **🔄 Tải lại giao diện**: `location.reload()`. Cố ý **không** gọi là "refresh
  cứng": JS không thể bỏ qua HTTP cache — `location.reload(true)` bị mọi browser
  hiện đại bỏ qua. Mà cũng không cần: server đã gửi `no-cache` cho cả HTML lẫn
  JS/CSS nên một lần reload thường là đủ.
- **🧹 Reset giao diện**: xoá `localStorage`, có xác nhận liệt kê rõ mất gì. Đây là
  thứ reload *không* chữa được — tuỳ chọn cũ trỏ tới module/section đã biến mất.
- **Bản mới trên GitHub**: chỉ `git fetch` + báo ahead/behind, kèm cảnh báo số file
  chưa commit. **Không tự pull** — xem lý do ở `docs/ARCHITECTURE.md`.

Sửa kèm ở `start.bat`: thêm `IHRP_NO_BROWSER=1` (restart không mở tab mới vì người
dùng đã có tab) và `IHRP_RESTART=1` (không treo ở `pause` kèm thông báo `[LOI]` sai
lệch khi bị lần restart sau taskkill).

Bốn bug đã gặp trong lúc làm, đều đã có test chốt:
`os.path.commonpath` raise khi khác ổ đĩa (stdlib ở `C:`, project ở `D:`); venv nằm
trong project làm site-packages bị tính là source (317 file thay vì 29);
`list2cmdline` escape quote kiểu MSVC nên lệnh lồng trong `cmd /c` im lặng không
chạy mà `Popen` vẫn báo thành công; Job Object kill hậu duệ làm server vừa lên lại
chết.

Verify: `tests/test_build_info.py` (49 test).

### Lint JS (`no-undef`) — bịt điểm mù ReferenceError

`ReferenceError` là loại bug suite Python không thấy được: chỉ nổ lúc chạy trên
browser, thường trong nhánh `catch`, nên chỉ hiện ra dưới dạng toast mơ hồ. Thêm
ESLint + rule `no-undef`, gọi được cả từ `npm run lint` và từ pytest
(`tests/test_js_no_undef.py`, tự bỏ qua nếu máy không có Node).

- `eslint.config.mjs` tự sinh danh sách globals dùng chung bằng cách parse AST
  (espree) mọi file trong `static/js` — vì đây là classic script chia sẻ global
  scope, ESLint xét từng file riêng sẽ báo sai 81 lỗi giả. Tự sinh nên không lạc
  hậu; liệt kê tay sẽ khiến người ta tắt rule cho đỡ ồn.
- 3 hook tuỳ chọn (`_authRefreshHeader`, `_sgApplyNavOrder`,
  `renderSidebarGroups`) đổi từ `typeof X` sang `typeof window.X`. Hành vi không
  đổi; dạng `window.X` nói rõ đây là hàm do script khác cấp. **Ba hook này hiện
  không được định nghĩa ở đâu trong repo**, nên các nhánh đó chưa từng chạy — giữ
  nguyên vì là điểm mở rộng có chủ ý, không phải bug.
- Bỏ `playwright-core` khỏi `package.json`: không code nào trong repo dùng, chỉ
  còn sót trong `node_modules` từ script debug ad-hoc.

Đã kiểm bằng mutation test: tiêm lại đúng `apFetch` vào `loadWeeklyGap` thì test
fail và chỉ ra `dashboard.js:25835:28`; hoàn nguyên thì pass.

---

## Wave 2026-08d — Nút 📥 trên thanh tab Issues + option «Xuất tất cả tab»

**Phản hồi:** bấm nút export trên thanh tab mục Issues thì báo lỗi; muốn thêm
option xuất được tất cả tab thành các sheet tương ứng để gửi 1 lần.

**Nguyên nhân — không phải lỗi export, mà là lỗi khai báo.** Handler của nút
`📥` trên thanh tab chỉ đọc `tab.export` (chart key). Config `tabs` của hub
Issues **không tab nào khai key này** (9 tab issue mỗi tab một endpoint riêng,
không đi qua `/export-chart`), nên cả 9 tab đều rơi vào nhánh else → toast
*"Tab này chưa có export riêng"*. Nút xuất nằm trong thân section vẫn chạy bình
thường, nên bug chỉ hiện ở đường vào thanh tab.

Đã giao:

- **Config tab nhận thêm `exportFn` / `extraParamsFn` / `flKinds` /
  `singleList`** — nối 9 tab Issues vào đúng hàm xuất của chúng, kèm filter cục
  bộ của section để file khớp lưới đang xem (giống hệt nút trong thân section).
- **Option `Tất cả tab (1 file nhiều sheet)`** ở nhóm mới `Gộp nhiều tab`.
  Truyền `forceFull` để bỏ qua nhánh "focus 1 nhóm vấn đề" — người bấm đã chọn
  "tất cả" mà nhận đúng 1 sheet thì không cách nào đoán ra vì sao.
- **File tổng hợp từ 8 → 12 sheet.** Trước đó nó thiếu đúng 4 tab (FID, Lấy
  source test, Thời gian dài, Báo cáo tuần) nên PM vẫn phải xuất rời 4 file rồi
  gửi kèm — tức là "tổng hợp" chưa gửi được một lần. Risk + Bookmark dồn về
  cuối để thứ tự sheet khớp thứ tự tab trên UI.
- **2 endpoint xuất riêng mới** cho `Lấy source test` và `Thời gian dài` — hai
  tab này trước đây không có nút xuất nào. Dùng lại đúng writer sheet của file
  tổng hợp qua `_send_single_issue_sheet`; viết exporter riêng sẽ nhân đôi định
  nghĩa cột và hai bên lệch nhau ngay lần sửa cột đầu tiên.

**Hạn chế đã biết:** 4 sheet mới trong file gộp dùng ngưỡng/lookback **mặc định
của analyzer**, không đọc ô nhập trên UI (endpoint xuất riêng từng tab mới đọc).
Cần đúng ngưỡng đang xem thì xuất riêng tab đó. Đã ghi rõ trong help.

Vì `exportFn` là **string tên hàm**, sai chính tả chết im lặng —
`tests/test_tab_bar_export.py` (35 test) kiểm mọi tên trong config đều tồn tại
thật trong `dashboard.js`, cộng bất biến "mọi tab Issues đều khai được đường
xuất" để bug gốc không quay lại khi thêm tab mới.

---

## Wave 2026-08d — Sheet Chi_tiet: thêm cột FID, tự ẩn cột Rlog ID khi FL không có

**Phản hồi:** xuất «Cả hai» ở Tiến độ theo module thì sheet Chi_tiet thiếu FID, còn
cột Rlog ID trống trơn.

**Điều tra — cột Rlog ID không phải lỗi đọc.** Quét 9 snapshot của dự án:

| Snapshot | Số cột | `Analysis - RlogID` | Dòng có Rlog | Dòng có FID |
|---|---|---|---|---|
| 28–29/07 | 68 | có | 74–78 | 309 |
| 30/07 → 05/08 | 65 | **không còn** | 0 | 308–315 |

FL nguồn **bỏ cột `Analysis - RlogID` từ 30/07** (68 → 65 cột). Parser vẫn đọc đúng khi
cột tồn tại — chạy lại bản 29/07 vẫn ra 78 giá trị (VD `TMS.FR.13 → 25259`). Không có
gì để sửa ở phía đọc; muốn có dữ liệu thì phải thêm lại cột vào FL.

Đã giao:

- **Cột `FID`** vào mọi sheet Chi_tiet của export-chart, đứng ngay sau `Mã CN` cho dễ
  đối chiếu. Đo trên FL 05/08: 315/389 dòng có giá trị.
- **Cột `Rlog ID` tự ẩn** khi FL không khai cột đó. Điều kiện là *có khai cột* chứ không
  phải *có giá trị* — file mới khai mà điền lác đác vẫn phải hiện, nếu ẩn thì PM không
  biết còn thiếu chỗ nào. Không suy đoán được (`parsed_data=None`) thì vẫn hiện.
- Gom `DETAIL_META_COLUMNS` + `_meta_cell_values` thành `_detail_meta(parsed_data)` trả
  về **cặp (columns, values_fn)**. Trước đó 9 call site lấy header và ghi ô ở hai chỗ
  rời nhau; ẩn/thêm cột kiểu đó là lệch cả sheet mà openpyxl **không báo lỗi gì** —
  dữ liệu vẫn ghi, chỉ nằm sai cột. Trả về cặp thì không thể lệch.
- Sheet Chi_tiet của `pic_workload` trước đây tự dựng danh sách cột riêng nên không theo
  cơ chế ẩn (kiểm chứng bắt được: vẫn hiện Rlog ID trong khi 6 chart kia đã ẩn). Nay
  dùng chung bộ meta, kèm theo được thêm 2 cột `Complexity` + `Mã dự án` cho đồng bộ.

Kiểm chứng 7 chart × 2 bản FL: bản 65 cột ẩn Rlog ở cả 7, bản 68 cột hiện ở cả 7.
Verify: `tests/test_chart_detail_columns.py` (19 test), gồm bất biến «số ô == số header».

---

## Wave 2026-08d — Thống nhất icon theo chiều dữ liệu (📥 ra / ⬆ vào)

**Vấn đề:** 📥 và 📤 là hai khay giấy trông gần giống nhau, chỉ khác hướng mũi tên,
mà lại bị dùng lẫn cho cả hai chiều dữ liệu — có chỗ đứng cạnh nhau trong cùng hàng nút:

- section «Chiều PM»: `📤 Kế hoạch (.xlsx)` và `📤 Weekly (.pptx)` thực ra là **input
  file (upload)**, đặt ngay cạnh `📥 Xuất chiều PM` (export)
- section «Quản lý đầu việc BA»: `📥 Import` sát `📥 Xuất tất cả` — **cùng icon, ngược nghĩa**
- sticky bar: `📤` = upload, trong khi `📤 Xuất ▾` ở header = export

Quy ước đã chốt: **📥 = chiều RA** (xuất / tải về), **⬆ = chiều VÀO** (import / upload),
**bỏ hẳn 📤**, và ⬇ không dùng cho action nữa. Chọn giữ 📥 = xuất vì nó đã dùng ở 96 nút
đúng nghĩa — đổi ngược lại theo semantics Unicode (📤 outbox = đi ra) sẽ phải sửa ~101 nút
mà không giải quyết thêm gì. Sau wave: 📤 còn **0** lần xuất hiện.

Đã đổi 13 chỗ: 4 nút upload (`⬆ Nạp Kế hoạch`, `⬆ Nạp Weekly` — thêm cả `title` giải thích,
`⬆ Import project từ .zip`, `⬆ Import` BA, sticky `⬆`), modal `⬆ Import đầu việc từ Excel`,
2 nút xuất đang dùng 📤 (`📥 Xuất ▾` header, `📥 Xuất Excel tuần này`), `📥 Tải` ở Digest,
`📝 Áp seed calibrate` (⬇ nhưng không phải tải về), toast sync `🔄 N chức năng đã kéo về`,
và 3 tiêu đề tĩnh sang icon trung tính (`📅 Lịch sinh Digest`, `📂 Digest lưu trữ`,
`📄 Mẫu Function List`) để 📥 chỉ còn một nghĩa.

**Bẫy đã xử lý:** `📤 Xuất ▾` nằm trong `i18n.js` ở **cả bản vi và en** — sửa HTML mà bỏ
i18n thì đổi ngôn ngữ là icon nhảy về cũ.

Verify: `tests/test_icon_convention.py` (31 test) — chặn 📤 và ⬇-action quay lại, và quét
nhãn quanh mỗi icon để phát hiện 📥 gắn lên nút Import hoặc ⬆ gắn lên nút Xuất.

---

## Wave 2026-08d — Hai chế độ xuất cho tab issue: «Danh sách lỗi» / «FL để import»

**Yêu cầu:** chỉ xuất record có vấn đề; với record có vấn đề thì cho chọn xuất lỗi
hay xuất import; bản xuất lỗi thì lưới đang N cột thì xuất N cột để lọc + update tay.

**Vấn đề đo được:** nút «Xuất FL update FID» ở tab Thiếu FID xuất **224–256 dòng ×
65 cột**, trong khi chỉ có **47 dòng** lỗi FID. Nguyên nhân: `/export-fl-reimport`
luôn union overdue + unassigned + stalled + anomaly + FID, không có cách giới hạn.

Đã giao:

| Chế độ | Endpoint | Nội dung |
|---|---|---|
| Danh sách lỗi | `/export-fid-issues` (mới) | 7 cột đúng như lưới + cột trống «FID cần cập nhật» tô vàng, AutoFilter, sheet `Loi_FID` |
| FL để import | `/export-fl-reimport?kinds=fid` | FL 65 cột, header dòng 1, sheet `Function List` |

- `kinds` ∈ `overdue|unassigned|stalled|dq|fid`. Không truyền → union như cũ, nên nút
  «Xuất FL chỉnh sửa» ở Archive không đổi hành vi. `kinds` sai → 400 kèm danh sách hợp lệ.
- Chỉ compute những metric cần cho `kinds` đang chọn (bỏ `compute_all` khi không dùng).
- Menu `openExportModePicker` tách 2 nhóm: **Danh sách lỗi** (Tổng hợp/Chi tiết/Cả hai,
  hoặc 1 dòng «Theo lưới đang xem» khi tab chỉ có 1 dạng list) và **FL để import**.
  Nối cho cả 5 tab: Trễ hạn · Chưa PIC · Đình trệ · Data Quality · Thiếu FID.
- Filter cục bộ forward sang FL-import qua `l_module` / `l_phase` / `l_pic` /
  `l_waiting_phase` / `fid_module` / `fid_type` — tránh đúng loại lệch "lọc còn 5 dòng
  mà file ra 40 dòng".

**Bug phát hiện khi làm:** `overdue_list[].pic` là **list** chứ không phải string, nên
bộ so khớp ban đầu (`str(val) in keep`) luôn ra 0 dòng. Đã sửa thành so giao nhau cho
mọi field dạng list.

**RED FLAG đã xử lý — upload nhầm file FL rút gọn.** Upload thay thế toàn bộ dữ liệu
project, không merge theo Mã CN, và trước đây **không có cảnh báo nào** khi số dòng tụt
(chỉ chặn khi 0 dòng). Thu file import từ 224 → 47 dòng làm rủi ro này nặng thêm nhiều:
một lần upload nhầm là project rơi từ 389 → 47 chức năng, dashboard/badge/EVM sai ngay
mà không ai biết vì sao. Nay:

- Warning `row_count_drop` mức critical khi số dòng < 70% bản trước, kèm tên + số dòng
  bản trước và hướng dẫn khôi phục snapshot. Chỉ cảnh báo, không chặn.
- Cảnh báo critical chuyển sang **banner cố định** `#uploadCriticalWarn` (dismiss được)
  thay vì toast — toast tự tắt sau 3.5s và chỉ có 1 element dùng chung nên các cảnh báo
  critical cũ (`empty_rows`, `no_phases`) cũng từng bị đè/trôi mất.

Kiểm chứng trên snapshot MPHG 2026-08-05: xuất lỗi 47 → 30 (lọc module có FID) → 16
(chỉ Trùng FID); FL import `kinds=fid` 47 dòng (union không kinds vẫn 224);
`kinds=stalled&l_waiting_phase=Config Prod` → 1 dòng.

**Hạn chế còn lại:** file «Danh sách lỗi» của các tab khác vẫn dùng exporter sẵn có
(cột theo từng report, chưa đồng bộ 1:1 với lưới như tab FID) và chưa có cột trống
để điền tay.

Verify: `tests/test_export_issue_modes.py` (29 test).

---

## Wave 2026-08d — Filter Module/Loại multi cho section «Thiếu / Trùng FID»

**Yêu cầu:** cho chọn nhiều module, mặc định bỏ check `APP` vì APP không có FID.

**Đã đổi mặc định thành suy từ dữ liệu thay vì hardcode `APP`.** Quét snapshot MPHG
2026-08-05 cho thấy **`ESS` cũng 0/4 row có FID**, không chỉ APP — hardcode một tên
module sẽ bỏ sót đúng loại noise đó, và sang dự án khác thì mặc định vô nghĩa
(trái nguyên tắc auto-detect của project). Điều kiện dùng: module không có row nào
điền FID → `modules_without_fid`.

| Module | rows | có FID | Dev Closed | issue đang báo |
|---|---|---|---|---|
| APP | 14 | **0** | 13 | 13 thiếu |
| ESS | 4 | **0** | 4 | 4 thiếu |
| HR | 96 | 93 | 94 | 1 thiếu + 9 trùng |
| PR | 96 | 66 | 61 | 5 thiếu + 2 trùng |
| TMS | 84 | 65 | 67 | 4 thiếu + 4 trùng |

Kết quả: 47 issue → **30 issue thật** (14 thiếu + 16 trùng), Dev Closed 327 → 310.

Đã giao:

- `fidModuleFilter` / `fidTypeFilter` (native single select) → 2 `createMultiSelect`
  (`fidModule`, `fidType`). Loại issue cũng multi theo yêu cầu.
- Mặc định module = tất cả trừ `modules_without_fid`; lưu theo project
  (`fidModuleSel:<slug>`), module mới xuất hiện tự check nếu module đó có dùng FID.
  Nút **↺ Mặc định** trả cả 2 filter về gốc.
- **4 card chạy theo filter** kèm ghi chú `toàn bộ: N`. Card nằm trong section nên
  để lệch thì PM đọc 47 mà đếm được 30 dòng. `Dev đã Closed` tính lại từ
  `module_stats.dev_closed` (frontend không tự suy được từ danh sách issue).
- Banner `fidScopeBanner` phân biệt module bị ẩn vì *không dùng FID* và module do
  user tự bỏ chọn.
- Export FL nhận `fid_module` / `fid_type` để file khớp bảng.

**Hạn chế đã biết:**

- Badge sidebar **cố ý** vẫn là 47 (số toàn bộ), như các tab issue khác. Chênh lệch
  được giải thích ở banner + ghi chú trên card.
- `export-fl-reimport` là **union** overdue/unassigned/stalled/anomaly/FID, nên
  bỏ APP khỏi phần FID không có nghĩa APP biến mất khỏi file — nó vẫn có thể vào
  qua issue loại khác. Đúng thiết kế: file là "FL các CN cần sửa", FID chỉ là 1 lý do.
- Module nhỏ mà team chỉ *chưa kịp* điền FID sẽ bị ẩn oan (không phân biệt được với
  "không dùng FID" khi n nhỏ như ESS = 4 row). Banner nêu rõ + lựa chọn được nhớ.

Verify: `tests/test_fid_module_filter.py` (17 test).

---

## Fix 2026-08-05 — Tab «Báo cáo tuần» và «Thời gian dài» chết hoàn toàn

**Triệu chứng:** mở tab Báo cáo tuần → toast `Lỗi tải báo cáo tuần: apiFetch is not defined`,
bảng trống. Tab Thời gian dài không báo gì nhưng cũng luôn trống.

Ba bug xếp lớp, phải sửa cả ba mới chạy được:

| # | File | Bug | Hệ quả |
|---|------|-----|--------|
| 1 | `dashboard.js` | `loadWeeklyGap` / `loadDurationFlag` gọi `apiFetch(...)` — hàm không tồn tại (helper thật là `apiJson`) | 2 tab không gọi được API. Báo cáo tuần hiện toast; Thời gian dài `catch` chỉ `console.error` nên im lặng |
| 2 | `weekly_gap_report.py` · `duration_flag.py` | đọc `pd.pic` trong khi `PhaseData` chỉ có `pics` (list) | API 500 `AttributeError` ngay khi có ≥1 dòng khớp; kéo theo `/export-weekly-gap` cũng 500 |
| 3 | `weekly_gap_report.py` | đọc `row.meta["fitgap"]` trong khi parser lưu `fit_gap` | cột FIT/GAP luôn rỗng, filter "chỉ GAP"/"chỉ FIT" luôn ra 0 dòng |

**Sửa:** dùng `apiJson`; `pic = ", ".join(pd.pics or [])` (khớp `advanced_metrics` /
`forecast_manpower`); đọc `fit_gap` với fallback `fitgap` (khớp `generic_chart`).
`loadDurationFlag` giờ báo toast thay vì swallow lỗi.

Kiểm chứng trên snapshot MPHG 2026-08-05: Báo cáo tuần 26 dòng (tuần 32) / 67 dòng (tuần 33),
FIT 66 + GAP 1; Thời gian dài 13 dòng, trung bình 152 ngày, tối đa 249 ngày.

Verify: `tests/test_weekly_gap_duration_flag.py` — 2 module này trước đó **không có test nào**,
đó là lý do bug sống sót. Test kèm một lint chặn cả lớp lỗi #1: mọi `await foo(...)` trong
`dashboard.js` phải có `foo` được định nghĩa (allow-list global CDN như `html2canvas`).

---

## Fix 2026-08-05 — Select «Hiển thị 10/20/50» không có tác dụng

**Triệu chứng:** ở bảng *Dev Closed — Thiếu / Trùng FID*, chọn 10 dòng/trang vẫn ra 50 dòng.

**Nguyên nhân:** 3 bảng tự giữ `pageSize` riêng trong state cục bộ và dùng nó để cắt trang,
trong khi `renderPager` ghi lựa chọn của user vào `pageState[key].size`. Callback chỉ đồng bộ
`page` mà không đồng bộ `size` → số dòng không đổi. Nặng hơn: pager tính `totalPages` theo
size mới (10) còn bảng vẫn cắt theo size cũ (50), nên bấm sang trang 2 ra bảng rỗng.

| Bảng | Key | Size cũ (hardcode) |
|------|-----|--------------------|
| Dev Closed — Thiếu / Trùng FID | `fid` | 50 |
| Thời gian dài | `dur` | 20 |
| Báo cáo tuần GAP | `weeklyGap` | 25 |

Ba bảng này còn mặc định 50/20/25 trong khi quy ước toàn app là 10 (`PAGE_DEFAULT_SIZE`);
riêng 20 và 25 không nằm trong danh sách option `[10, 20, 50]` nên select hiển thị sai giá trị
đang áp dụng.

**Cách sửa:** `pageState[key]` là nguồn duy nhất cho page + size; cả 3 bảng cắt trang qua
`_pageSlice(key, items)` như mọi bảng khác, nhờ đó nhận luôn "Tất cả" (`size=0`) và tự clamp
trang khi filter làm danh sách co lại. Khai báo sẵn `fid`/`dur`/`weeklyGap` +
`baTasks`/`picOverload`/`picOverloadDetail` trong `pageState`, và `_pageSlice` ghi ngược state
khi key chưa khai báo (trước đây dùng object tạm nên mất kết quả clamp).

Verify: `tests/test_pager_size_wiring.py` — chặn tái diễn bằng cách assert mọi key `renderPager`
đều có trong `pageState`, mọi size mặc định là `PAGE_DEFAULT_SIZE`, và 3 hàm render không còn
`pageSize` cục bộ.

**Chưa làm (khác phạm vi):** bảng *Aging WIP* chỉ có ◀ ▶, cố định 30 dòng/trang, không có select
số dòng. Bảng *Data Quality* dùng pager riêng (5/10/20) nhưng nhất quán nội bộ nên vẫn đúng.

---

## Wave 2026-08c — Filter Phase chờ cho section Đình trệ

| Deliverable | Module / UI | Ghi chú |
|-------------|-------------|---------|
| Multi-select «Phase chờ» | `section-stalled` | Lọc theo cột **Phase chờ** (`waiting_phase`), không phải phase vừa xong; mặc định mọi phase **trừ Document** |
| Nhận diện phase không hardcode | `_stalledIsDocPhase` | Match keyword bỏ dấu (`document` / `tai lieu`); không có phase nào ngoài Document → check tất cả |
| Nhớ lựa chọn + phát hiện phase mới | localStorage `stalledPhaseSel:<slug>` | Lưu cả `known` phase → phase mới ở lần import sau tự được check (trừ Document); nút `↺ Mặc định` reset |
| Drill + Excel nhận cùng filter | `drill_down` `waiting_phase` · `export-stalled?waiting_phase=` | Tránh file xuất nhiều dòng hơn bảng đang xem |
| Banner scope ghi tỷ lệ | `_updateStalledScopeBanner` | `hiện N/M task (badge sidebar đếm toàn bộ)` + liệt kê phase đang ẩn |

**Sửa bug kèm theo:** `_filter_stalled` so sánh `module` bằng `==` trong khi FE gửi
`module="HR,PR"` → drill «Chi tiết» trả 0 item khi chọn nhiều Module. Giờ tách theo dấu phẩy.

**Cố ý KHÔNG lọc:** Funnel Closed/Phase (là tiến độ toàn trình), badge Đình trệ ở sidebar,
`summary.stalled_count` và `stalled_pct` — mấy số này còn nuôi risk level bảng Module và EVM,
đổi ngầm sẽ làm lệch chỗ khác. Chênh lệch được nói rõ trên banner thay vì sửa số.

Verify: `tests/test_stalled_phase_filter.py` · `test_stalled_local_filter.py`.

---

## Wave 2026-08b — Baseline chain & delta bảng Module

| Deliverable | Module / UI | Ghi chú |
|-------------|-------------|---------|
| Chuỗi baseline bất biến (v1, v2, v3…) | `baseline_manager.py` · `baselines/` | Copy xlsx + pickle kèm sha256; miễn nhiễm prune snapshot và ghi đè cùng ngày; cờ `source_drifted` khi bản gốc đổi |
| API baseline chain | `/baselines` GET/POST · `/baselines/<id>` DELETE | Giữ nguyên `/baseline` cũ; tự migrate `baseline_snapshot_id` vào chain lần đầu đọc |
| Resolver mốc so sánh | `compare_base.py` | 4 mode `baseline\|week\|previous\|date` + `off`; nhãn tiếng Việt luôn ghi ngày thật; thiếu mốc trả `error`, không raise |
| Delta bảng Tổng quan Module | `module_delta.py` · `/module-overview?compare=` | 8 số/nhóm; Tiến độ dùng **pp** cho chiều số lượng; base=0 → `None`; nhóm mới → `is_new`; nhóm mất → `removed[]` |
| UI bảng A | `section-module` | thead 2 hàng, dropdown mốc, segmented Số lượng/%/Cả 2, nút Chốt baseline, column picker |
| Quản lý baseline tập trung | `section-baseline` | Bảng version/ngày/nhãn/người chốt/checksum + xóa; nút Baseline ở Archive trỏ sang API mới |
| Export bảng A đủ cột | `excel_exporter` `module_overview` | Thêm Còn lại, Đánh giá, 8 cột delta; `group_by` không còn bị bỏ qua |

**Sửa tài liệu sai:** mô tả cột `Tiến độ` trong `DASHBOARD_SPEC.md` và help popup ghi
"% Closed phase cuối" trong khi code tính `closed_records / (SL × số_phase)`.

**Hạn chế:** module đổi tên giữa 2 bản hiện thành 1 nhóm mới + 1 nhóm mất (chưa map tên).
Snapshot vẫn 1 bản/ngày nên mốc "Tuần trước" có thể lùi về ngày gần nhất trước đó.

Verify: `tests/test_baseline_chain.py` · `test_compare_base.py` · `test_module_delta.py`.

---

## Wave 2026-08 — Issues hub & rule vận hành

| Deliverable | Module / UI | Ghi chú |
|-------------|-------------|---------|
| Status map Not Started theo PIC | `excel_parser._normalize_status` | Không PIC→Open; có PIC→Assigned; Finished→Closed; unknown→blank |
| Stalled nới + gate prev Closed | `stalled.py` | Closed→Open ngay, không cần End; Analysis chưa Closed → bỏ cặp sau |
| FID check | `fid_check.py` · `section-fid-check` | Dev Closed thiếu/trùng FID; export FL tô vàng FID |
| Checklist lấy source test Rlog | `source_checklist.py` · `section-source-checklist` | Nhóm theo ngày Dev đến hạn (End trong lookback, KHÔNG cần Closed — chỉ loại Cancelled); người lấy source = PIC Config Local (fallback phase sau Dev); lookback 14 ngày |
| Thời gian dài | `duration_flag.py` · `section-duration-flag` | Start→End > ngưỡng (60 ngày) |
| Báo cáo tuần GAP | `weekly_gap_report` + `weekly_gap_exporter` | End trong tuần / In-progress ≤ EoW; Excel 2-sheet |
| Module risk theo % | `dashboard_engine` | risk >20% overdue\|stalled; warning >10% hoặc progress<50% |
| Drill Còn lại / Tất cả | `drill_down` `scope` | Mặc định khớp cột Còn lại |
| Rlog cột ẩn khi thiếu | `dashboard.js` `renderRlogWeekly` | Không hiện cột "—" trống |
| Expand Rlog panel | modal fullscreen | Nút ⛶ |

---

## PMO Phase A–F

| Phase | Deliverable | Module | API / UI chính |
|-------|-------------|--------|----------------|
| **A** | Đánh dấu snapshot baseline + Schedule Variance (ngày) theo function/milestone | `analyzer/baseline_sv.py` | `/baseline`, `/baseline-sv` · `section-baseline` |
| **B** | Dự báo ngày xong từ velocity Closed/tuần (4 tuần) | `analyzer/completion_forecast.py` | `/completion-forecast` (thường gắn Summary / Forecast) |
| **C** | EVM: BAC, EV, PV, AC → SPI, CPI (MH) | `analyzer/earned_value.py` | `/earned-value` · `section-evm` |
| **C** | Scope creep / CR (cột Excel hoặc tag/`cr_function_codes`) | `analyzer/scope_creep.py` | `/scope-creep` · `section-scope-creep` |
| **D** | Risk score + PIC overload + module cascade delay | `risk_scorer.compute_pmo_risk`, `module_dependency.py` | `/pmo-risk` · Risk section |
| **E** | UAT Quality: defect / feedback / reopen / cycle | `analyzer/uat_quality.py` | `/uat-quality` · `section-uat-quality` |
| **F** | SQLite WAL `meta.db` dual-write settings/bookmarks/tags | `analyzer/sqlite_store.py` + `project_store.py` | Transparent qua store helpers |

**Vẫn file-based sau Phase F:** ParsedData pickle, snapshots, capacity, saved_views, section/module order, chart configs/notes, integrations, PM plan/weekly, archive settings, upload history, custom dashboards…

---

## BA UX 1–11 (+ polish)

| # | Deliverable | Module / FE |
|---|-------------|-------------|
| 1 | Auto-diff FL hiện tại vs snapshot trước | `function_diff.py` · `section-function-diff` |
| 2 | Saved filter views | `saved_views` API + FE |
| 3 | Trend chips OD/UA/ST trên insight strip | FE `updateInsightStripChips` |
| 4 | DQ highlight Module / Matrix | FE + `data_quality.py` |
| 5 | Bulk tags | `/tags/bulk` |
| 6 | Critical path trên Gantt Calendar | `gantt_calendar._annotate_critical_path` (heuristic) |
| 7 | FL re-import verify sau sửa yellow cells | `fl_reimport_verify.py` |
| 8 | Bottleneck phase trong matrix/phase | `dashboard_engine` |
| 9 | PIC × tuần sắp tới | `pic_upcoming.py` · `section-pic-upcoming` |
| 10 | Rlog tuần (section + counts) | `rlog_weekly.py` |
| 11 | Module còn lại (SL + MH) | module overview fields |
| Polish | Insight strip collapse | `toggleInsightStrip` · LS key |
| Polish | Help topic Data Quality | `help_content.js` → `dataquality` |

---

## Ops liên quan (cùng giai đoạn sản phẩm)

- **Disk janitor** startup: `purge_old_exports`, `purge_excess_snapshots`, `purge_excess_synced_*`, `purge_duplicate_pm_weekly_*`.
- Archive T-AA vẫn dùng (xem [ARCHIVE_GUIDE.md](ARCHIVE_GUIDE.md)).

---

## Đã bổ sung sau review

- **Ước lượng theo hệ số** (`estimate_ratio.py`, `section-estimate-ratio`, `estimation_params.json`) — parametric BA/Dev + ratios; không thay Forecast Manpower.

## Chưa ship / cố ý hạn chế

1. **SQLite cutover full** — chưa; chỉ meta slice.  
2. **Critical path** — không phải CPM trên dependency graph.  
3. **FL verify** — không phải cell-diff tổng quát.  
4. **P2:** API Registry Catalog (T-B), form_login wizard đầy đủ (T-C) — [BUGS_TODO.md](BUGS_TODO.md).

---

## Gợi ý kiểm thử nhanh

```bash
pytest tests/test_baseline_sv_forecast.py tests/test_earned_value.py tests/test_scope_creep.py tests/test_pmo_risk_phase_d.py tests/test_uat_quality.py tests/test_sqlite_store.py tests/test_ba_ux_backlog.py -q
```
