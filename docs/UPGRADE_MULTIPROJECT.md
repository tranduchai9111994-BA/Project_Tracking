# UPGRADE_MULTIPROJECT.md — Nâng cấp quản lý đa dự án

> ⚠️ **HISTORICAL** — kế hoạch multi-project cũ (đã ship từ lâu). Không dùng làm SSOT.  
> Hiện tại: [ARCHITECTURE.md](ARCHITECTURE.md) § storage · [FEATURE_CATALOG.md](FEATURE_CATALOG.md).

## Tổng quan

Hiện tại app chỉ xử lý 1 file tại 1 thời điểm, không lưu gì sau khi tắt.
Bản nâng cấp này biến app thành **công cụ quản lý portfolio** — PM mở lên là thấy
tất cả dự án đang triển khai, chọn dự án nào thì vào dashboard dự án đó.

**Không dùng database** — tất cả lưu bằng file JSON + folder structure,
giữ nguyên triết lý "copy folder đi đâu cũng chạy được".

> **Cursor: đọc file này + docs/ARCHITECTURE.md + docs/DATA_MODEL.md trước khi code.**
> Code PHẢI tương thích với parser auto-detect hiện tại, KHÔNG hardcode cột.

---

## 1. CẤU TRÚC THƯ MỤC MỚI

```
ihrp-tracker/
├── data/                                ← THƯ MỤC GỐC DỮ LIỆU (mới)
│   ├── projects.json                    ← Danh sách dự án
│   │
│   ├── MPHG_iHRP/                       ← Folder 1 dự án
│   │   ├── project.json                 ← Metadata dự án
│   │   ├── current.xlsx                 ← File Function List mới nhất
│   │   ├── snapshots/
│   │   │   ├── index.json               ← Danh sách snapshots
│   │   │   ├── 2026-07-01.xlsx
│   │   │   ├── 2026-07-15.xlsx
│   │   │   └── 2026-07-28.xlsx
│   │   └── exports/                     ← Các file đã export
│   │       ├── Overdue_Report_20260728.xlsx
│   │       └── PIC_SonHN6_20260728.xlsx
│   │
│   ├── ABC_HRM/                         ← Folder dự án khác
│   │   ├── project.json
│   │   ├── current.xlsx
│   │   ├── snapshots/
│   │   └── exports/
│   │
│   └── XYZ_Payroll/                     ← Thêm bao nhiêu dự án cũng được
│       └── ...
```

### File: data/projects.json

```json
{
    "version": 1,
    "last_active_project": "MPHG_iHRP",
    "projects": [
        {
            "id": "MPHG_iHRP",
            "name": "MPHG - Triển khai iHRP",
            "client": "Mai Phương Holdings Group",
            "description": "Triển khai 7 phân hệ: TMS, HRM, PRM, SYS, APP, PIT, ESS",
            "created_at": "2026-05-15T10:00:00",
            "updated_at": "2026-07-28T10:30:00",
            "color": "#2563eb",
            "status": "active"
        },
        {
            "id": "ABC_HRM",
            "name": "ABC Corp - HRM Phase 1",
            "client": "ABC Corporation",
            "description": "Triển khai HRM + TMS",
            "created_at": "2026-06-01T08:00:00",
            "updated_at": "2026-07-20T14:00:00",
            "color": "#16a34a",
            "status": "active"
        }
    ]
}
```

### File: data/{project_id}/project.json

```json
{
    "id": "MPHG_iHRP",
    "name": "MPHG - Triển khai iHRP",
    "client": "Mai Phương Holdings Group",
    "description": "Triển khai 7 phân hệ: TMS, HRM, PRM, SYS, APP, PIT, ESS",
    "created_at": "2026-05-15T10:00:00",
    "updated_at": "2026-07-28T10:30:00",
    "color": "#2563eb",
    "status": "active",
    "settings": {
        "overdue_threshold_days": 0,
        "long_duration_threshold_days": 3,
        "risk_score_weights": {
            "must_have": 20,
            "overdue": 20,
            "no_pic": 15,
            "long_duration": 10
        }
    },
    "stats": {
        "total_functions": 375,
        "overall_pct": 50.4,
        "overdue_count": 74,
        "modules": ["TMS", "HRM", "PRM", "SYS", "APP", "PIT", "ESS"],
        "last_upload": "2026-07-28T10:30:00"
    }
}
```

---

## 2. LUỒNG SỬ DỤNG MỚI

### Khi mở app lần đầu (chưa có dự án)

```
┌─────────────────────────────────────────────────────────┐
│  📊 iHRP Function List Tracker                          │
│                                                         │
│  Chào mừng! Bạn chưa có dự án nào.                     │
│                                                         │
│  ┌───────────────────────────────────────────┐          │
│  │  ➕ TẠO DỰ ÁN MỚI                        │          │
│  │                                           │          │
│  │  Tên dự án:  [MPHG - Triển khai iHRP   ] │          │
│  │  Khách hàng: [Mai Phương Holdings Group ] │          │
│  │  Mô tả:     [Triển khai 7 phân hệ...   ] │          │
│  │  Màu:       [🔵] [🟢] [🟡] [🔴] [🟣]     │          │
│  │                                           │          │
│  │  [Tạo dự án & Upload Function List]       │          │
│  └───────────────────────────────────────────┘          │
└─────────────────────────────────────────────────────────┘
```

### Khi mở app (đã có dự án)

```
┌─────────────────────────────────────────────────────────┐
│  📊 iHRP Function List Tracker                          │
│                                                         │
│  Chọn dự án:                             [➕ Dự án mới] │
│                                                         │
│  ┌─────────────────────────┐ ┌─────────────────────────┐│
│  │ 🔵 MPHG - iHRP          │ │ 🟢 ABC Corp - HRM      ││
│  │ Mai Phương Holdings      │ │ ABC Corporation         ││
│  │                          │ │                         ││
│  │ 375 functions            │ │ 120 functions           ││
│  │ ████████░░░ 50.4%        │ │ ██████████░ 85.2%       ││
│  │ ⚠️ 74 overdue            │ │ ⚠️ 5 overdue            ││
│  │                          │ │                         ││
│  │ Cập nhật: 28/07/2026     │ │ Cập nhật: 20/07/2026    ││
│  │                          │ │                         ││
│  │ [📂 Mở] [⚙️] [🗑️]       │ │ [📂 Mở] [⚙️] [🗑️]      ││
│  └─────────────────────────┘ └─────────────────────────┘│
│                                                         │
│  ┌─────────────────────────┐                            │
│  │ 📁 XYZ - Payroll         │                            │
│  │ XYZ Company              │                            │
│  │                          │                            │
│  │ ⏸️ Chưa upload file       │                            │
│  │                          │                            │
│  │ [📂 Mở] [⚙️] [🗑️]       │                            │
│  └─────────────────────────┘                            │
└─────────────────────────────────────────────────────────┘
```

### Sau khi chọn dự án → vào Dashboard (giống hiện tại)

Khác biệt:
- Header hiển thị **tên dự án + màu** thay vì text chung
- Thêm nút **← Về danh sách dự án** ở góc trái header
- Thêm **dropdown đổi dự án nhanh** ở header (không cần quay về trang chủ)
- Upload file mới → tự lưu vào đúng folder dự án + tạo snapshot

---

## 3. API MỚI

### Project CRUD

```
GET    /api/projects                    → Danh sách tất cả dự án + stats tóm tắt
POST   /api/projects                    → Tạo dự án mới
                                          Body: { name, client, description, color }
GET    /api/projects/<id>               → Chi tiết 1 dự án
PUT    /api/projects/<id>               → Cập nhật metadata dự án
DELETE /api/projects/<id>               → Xóa dự án (cần confirm, xóa cả folder)
```

### Upload scoped to project

```
POST   /api/projects/<id>/upload        → Upload Function List cho dự án cụ thể
                                          (thay thế POST /api/upload hiện tại)
                                          Tự động: lưu current.xlsx + tạo snapshot
GET    /api/projects/<id>/dashboard     → Metrics dashboard của dự án
                                          (thay thế GET /api/dashboard)
GET    /api/projects/<id>/overdue       → Overdue list, có filter
GET    /api/projects/<id>/export-overdue → Export Excel
```

### Snapshot scoped to project

```
GET    /api/projects/<id>/snapshots     → Danh sách snapshots của dự án
GET    /api/projects/<id>/compare?old=<date>&new=<date>
DELETE /api/projects/<id>/snapshots/<date>
```

### Quick switch (không cần reload trang)

```
POST   /api/set-active-project          → Body: { project_id }
                                          Lưu last_active_project
GET    /api/active-project              → Trả project_id đang active
```

### Portfolio overview (tổng hợp cross-project)

```
GET    /api/portfolio/summary           → Tổng hợp tất cả dự án
```

---

## 4. BACKEND IMPLEMENTATION

### Tạo file mới: project_manager.py

```python
"""
Quản lý dự án — CRUD + file storage.
Tất cả dữ liệu lưu trong data/ folder, không dùng database.
"""
import json
import os
import shutil
from datetime import datetime
from dataclasses import dataclass, asdict
from typing import Optional


DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
PROJECTS_INDEX = os.path.join(DATA_DIR, "projects.json")
MAX_SNAPSHOTS_PER_PROJECT = 30


@dataclass
class ProjectInfo:
    id: str                              # Slug, dùng làm folder name
    name: str                            # Tên hiển thị
    client: str
    description: str
    color: str                           # Hex color
    status: str                          # "active" | "archived"
    created_at: str                      # ISO datetime
    updated_at: str
    settings: dict                       # Overdue threshold, risk weights...
    stats: dict                          # Cache: total, pct, overdue...


class ProjectManager:
    """Quản lý danh sách dự án và file storage."""

    def __init__(self):
        os.makedirs(DATA_DIR, exist_ok=True)
        if not os.path.exists(PROJECTS_INDEX):
            self._save_index({"version": 1, "last_active_project": None, "projects": []})

    # === CRUD ===

    def list_projects(self) -> list[dict]:
        """Trả danh sách dự án kèm stats."""
        index = self._load_index()
        return index["projects"]

    def create_project(self, name: str, client: str = "",
                       description: str = "", color: str = "#2563eb") -> ProjectInfo:
        """
        Tạo dự án mới.
        - id = slugify(name): lowercase, thay space bằng _, bỏ ký tự đặc biệt
        - Tạo folder data/{id}/
        - Tạo data/{id}/project.json
        - Tạo data/{id}/snapshots/
        - Tạo data/{id}/exports/
        - Thêm vào projects.json
        """

    def get_project(self, project_id: str) -> ProjectInfo:
        """Đọc project.json, raise nếu không tồn tại."""

    def update_project(self, project_id: str, **kwargs) -> ProjectInfo:
        """Cập nhật name, client, description, color, settings."""

    def delete_project(self, project_id: str) -> bool:
        """
        Xóa dự án:
        - Xóa folder data/{id}/ (shutil.rmtree)
        - Xóa khỏi projects.json
        - Nếu là last_active_project → set None
        """

    def archive_project(self, project_id: str) -> ProjectInfo:
        """Đánh dấu status = 'archived', không xóa file."""

    # === File management ===

    def save_upload(self, project_id: str, file_stream, filename: str) -> str:
        """
        Lưu file upload:
        1. Lưu vào data/{id}/current.xlsx (overwrite)
        2. Copy vào data/{id}/snapshots/{date}.xlsx
        3. Cập nhật snapshots/index.json
        4. Nếu snapshot cùng ngày đã tồn tại → overwrite
        5. Nếu > MAX_SNAPSHOTS → xóa cũ nhất
        6. Return filepath
        """

    def get_current_file(self, project_id: str) -> Optional[str]:
        """Trả path đến current.xlsx, None nếu chưa upload."""

    def get_snapshots(self, project_id: str) -> list[dict]:
        """Đọc snapshots/index.json."""

    def get_snapshot_file(self, project_id: str, date_str: str) -> Optional[str]:
        """Trả path đến snapshots/{date}.xlsx."""

    def delete_snapshot(self, project_id: str, date_str: str) -> bool:
        """Xóa 1 snapshot."""

    def get_export_dir(self, project_id: str) -> str:
        """Trả path data/{id}/exports/, tạo nếu chưa có."""

    # === Stats cache ===

    def update_stats(self, project_id: str, stats: dict):
        """
        Cập nhật stats cache trong project.json.
        Gọi sau mỗi lần parse file thành công.
        Stats: { total_functions, overall_pct, overdue_count, modules, last_upload }
        """

    # === Active project ===

    def get_last_active(self) -> Optional[str]:
        """Trả project_id được mở gần nhất."""

    def set_last_active(self, project_id: str):
        """Lưu last_active_project."""

    # === Helpers ===

    def _slugify(self, text: str) -> str:
        """
        'MPHG - Triển khai iHRP' → 'mphg_trien_khai_ihrp'
        - Lowercase
        - Bỏ dấu tiếng Việt (unicodedata.normalize)
        - Thay space, dash bằng _
        - Bỏ ký tự đặc biệt
        - Nếu trùng id đã có → thêm _2, _3...
        """

    def _load_index(self) -> dict:
        with open(PROJECTS_INDEX, "r", encoding="utf-8") as f:
            return json.load(f)

    def _save_index(self, data: dict):
        with open(PROJECTS_INDEX, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def _project_dir(self, project_id: str) -> str:
        return os.path.join(DATA_DIR, project_id)
```

### Sửa app.py — Route mới

```python
from project_manager import ProjectManager

pm = ProjectManager()

# --- Trang chủ: hiện danh sách dự án ---
@app.route("/")
def index():
    """Nếu có last_active → redirect đến dự án đó, nếu không → trang chọn dự án."""
    last = pm.get_last_active()
    if last and request.args.get("home") != "1":
        return redirect(f"/project/{last}")
    return render_template("home.html")

# --- Dashboard dự án ---
@app.route("/project/<project_id>")
def project_dashboard(project_id):
    """Render dashboard cho 1 dự án cụ thể."""
    pm.set_last_active(project_id)
    project = pm.get_project(project_id)
    return render_template("dashboard.html", project=project)

# --- API: Projects ---
@app.route("/api/projects", methods=["GET"])
def api_list_projects():
    return jsonify({"projects": pm.list_projects()})

@app.route("/api/projects", methods=["POST"])
def api_create_project():
    data = request.json
    project = pm.create_project(
        name=data["name"],
        client=data.get("client", ""),
        description=data.get("description", ""),
        color=data.get("color", "#2563eb"),
    )
    return jsonify({"success": True, "project": asdict(project)})

@app.route("/api/projects/<project_id>", methods=["PUT"])
def api_update_project(project_id):
    project = pm.update_project(project_id, **request.json)
    return jsonify({"success": True, "project": asdict(project)})

@app.route("/api/projects/<project_id>", methods=["DELETE"])
def api_delete_project(project_id):
    pm.delete_project(project_id)
    return jsonify({"success": True})

# --- API: Upload scoped to project ---
@app.route("/api/projects/<project_id>/upload", methods=["POST"])
def api_project_upload(project_id):
    """Upload file → lưu vào project folder → parse → return metrics."""
    file = request.files["file"]
    filepath = pm.save_upload(project_id, file.stream, file.filename)

    parser = FunctionListParser()
    data = parser.parse(filepath)

    engine = DashboardEngine()
    metrics = engine.compute_all(data)

    # Cache stats
    pm.update_stats(project_id, {
        "total_functions": metrics["summary"]["total_functions"],
        "overall_pct": metrics["summary"]["overall_progress_pct"],
        "overdue_count": metrics["summary"]["total_overdue"],
        "modules": metrics["structure"]["all_modules"],
        "last_upload": datetime.now().isoformat(),
    })

    return jsonify({"success": True, "metrics": metrics})

# --- API: Dashboard scoped to project ---
@app.route("/api/projects/<project_id>/dashboard")
def api_project_dashboard(project_id):
    """Parse current.xlsx và trả metrics."""
    filepath = pm.get_current_file(project_id)
    if not filepath:
        return jsonify({"error": "Dự án chưa có file Function List."}), 404

    parser = FunctionListParser()
    data = parser.parse(filepath)
    engine = DashboardEngine()
    metrics = engine.compute_all(data)
    return jsonify({"success": True, "metrics": metrics})

# --- API: Export scoped to project ---
@app.route("/api/projects/<project_id>/export-overdue")
def api_project_export(project_id):
    """Export vào project exports folder."""
    filepath = pm.get_current_file(project_id)
    # ... parse, compute, export vào pm.get_export_dir(project_id)

# ... (tương tự cho snapshots, compare)
```

### Backward Compatibility

Giữ route cũ `/api/upload`, `/api/dashboard` hoạt động bằng cách:
- Nếu chưa có dự án nào → tự tạo dự án "Default" và route vào đó
- Nếu có dự án → route vào `last_active_project`

```python
@app.route("/api/upload", methods=["POST"])
def api_upload_legacy():
    """Backward compatible: dùng active project hoặc tạo default."""
    project_id = pm.get_last_active()
    if not project_id:
        project = pm.create_project(name="Dự án mặc định")
        project_id = project.id
    return api_project_upload(project_id)
```

---

## 5. FRONTEND

### Tạo thêm templates/home.html — Trang chọn dự án

Trang này là **landing page** khi mở app:

```html
<!-- Layout: grid responsive, mỗi dự án là 1 card -->

<div id="projectGrid">
    <!-- Render bằng JS từ /api/projects -->
</div>

<!-- Modal tạo dự án mới -->
<div id="createModal" class="hidden">
    <input id="projName" placeholder="Tên dự án">
    <input id="projClient" placeholder="Khách hàng">
    <textarea id="projDesc" placeholder="Mô tả"></textarea>
    <div id="colorPicker">
        <!-- 8 màu preset: xanh, lá, vàng, đỏ, tím, cyan, hồng, cam -->
    </div>
    <button onclick="createProject()">Tạo dự án</button>
</div>
```

**Project Card design:**

```
┌─────────────────────────────────────┐
│ ● MPHG - Triển khai iHRP           │  ← dot màu dự án
│ Mai Phương Holdings Group           │
│                                     │
│ 375 chức năng  •  8 module          │
│                                     │
│ ████████████░░░░░░░░ 50.4%          │  ← progress bar màu dự án
│                                     │
│ ⚠️ 74 trễ deadline                   │  ← đỏ nếu > 0
│ 📅 Cập nhật: 28/07/2026 10:30       │
│                                     │
│ [📂 Mở dashboard]  [⚙️]  [📋]  [🗑️] │
└─────────────────────────────────────┘

📂 = Mở dashboard
⚙️ = Sửa thông tin dự án
📋 = Duplicate dự án (tạo mới copy settings)
🗑️ = Xóa (có confirm dialog)
```

**Card trạng thái đặc biệt:**
- Dự án chưa upload file: card nhạt, hiển thị "Kéo thả file vào đây hoặc click Mở"
- Dự án archived: card xám, opacity 60%, badge "Đã lưu trữ"
- Cập nhật > 7 ngày trước: badge vàng "Dữ liệu cũ"

### Sửa templates/index.html → templates/dashboard.html

Thay đổi header:

```html
<header>
    <div class="flex items-center gap-3">
        <!-- Nút về trang chủ -->
        <a href="/?home=1" class="text-white/70 hover:text-white">
            ← Dự án
        </a>

        <!-- Tên dự án + màu -->
        <div class="flex items-center gap-2">
            <span class="w-3 h-3 rounded-full" style="background: {{ project.color }}"></span>
            <h1 class="text-xl font-bold">{{ project.name }}</h1>
        </div>

        <!-- Dropdown đổi dự án nhanh -->
        <select id="projectSwitcher" onchange="switchProject(this.value)"
                class="bg-white/10 text-white rounded px-2 py-1 text-sm">
            <!-- Populate bằng JS -->
        </select>
    </div>
</header>
```

**Upload zone thay đổi:**
- POST đến `/api/projects/{project_id}/upload` thay vì `/api/upload`
- Hiển thị "Cập nhật file cho dự án: {tên dự án}"
- Nếu đã có file cũ: hiện thêm "File hiện tại: uploaded 28/07/2026. Kéo file mới vào để cập nhật."

### Tạo static/js/home.js — Logic trang chủ

```javascript
/**
 * Trang chủ — quản lý danh sách dự án.
 */

async function loadProjects() {
    const resp = await fetch("/api/projects");
    const data = await resp.json();
    renderProjectGrid(data.projects);
}

function renderProjectGrid(projects) {
    const grid = document.getElementById("projectGrid");

    if (projects.length === 0) {
        grid.innerHTML = `<div class="empty-state">...</div>`;
        return;
    }

    grid.innerHTML = projects
        .sort((a, b) => {
            // Active trước, archived sau. Trong mỗi nhóm: updated_at mới nhất trước
            if (a.status !== b.status) return a.status === "active" ? -1 : 1;
            return b.updated_at.localeCompare(a.updated_at);
        })
        .map(p => renderProjectCard(p))
        .join("");
}

function renderProjectCard(project) {
    const hasFile = project.stats?.total_functions > 0;
    const isStale = isDataStale(project.stats?.last_upload, 7);
    const isArchived = project.status === "archived";

    return `
    <div class="project-card ${isArchived ? 'opacity-60' : ''}"
         style="border-top: 4px solid ${project.color}">
        ...
    </div>`;
}

async function createProject() {
    const name = document.getElementById("projName").value.trim();
    if (!name) { showToast("Vui lòng nhập tên dự án", "red"); return; }

    const resp = await fetch("/api/projects", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({
            name: name,
            client: document.getElementById("projClient").value.trim(),
            description: document.getElementById("projDesc").value.trim(),
            color: selectedColor,
        }),
    });
    const data = await resp.json();
    if (data.success) {
        window.location.href = `/project/${data.project.id}`;
    }
}

async function deleteProject(projectId, projectName) {
    if (!confirm(`Xóa dự án "${projectName}"?\n\nTất cả dữ liệu, snapshots và báo cáo sẽ bị xóa vĩnh viễn.`)) {
        return;
    }
    // Double confirm cho an toàn
    if (!confirm("Xác nhận lần cuối: BẠN CHẮC CHẮN MUỐN XÓA?")) return;

    await fetch(`/api/projects/${projectId}`, { method: "DELETE" });
    loadProjects();
    showToast("Đã xóa dự án");
}

function switchProject(projectId) {
    window.location.href = `/project/${projectId}`;
}
```

---

## 6. PORTFOLIO OVERVIEW (Cross-project)

Thêm 1 section ở trang chủ (dưới project grid), hiển thị khi có ≥ 2 dự án active:

```
┌─────────────────────────────────────────────────────────┐
│ 📊 TỔNG QUAN PORTFOLIO                                  │
├──────────────┬──────────────┬──────────────┬────────────┤
│ Tổng dự án   │ Tổng function│ TB tiến độ   │ Tổng trễ   │
│ 3 active     │ 615          │ 62.0%        │ 91         │
├──────────────┴──────────────┴──────────────┴────────────┤
│                                                         │
│  GROUPED BAR: Tiến độ từng dự án                        │
│  (mỗi dự án 1 bar, màu = project.color)                │
│                                                         │
│  MPHG iHRP    ████████████░░░░░░░░  50.4%               │
│  ABC HRM      █████████████████░░░  85.2%               │
│  XYZ Payroll  ██████████████████░░  78.5%               │
│                                                         │
├─────────────────────────────────────────────────────────┤
│  TABLE: So sánh nhanh                                   │
│  Dự án | Functions | Tiến độ | Overdue | Cập nhật       │
│  MPHG  | 375       | 50.4%  | 74      | 28/07          │
│  ABC   | 120       | 85.2%  | 5       | 20/07          │
│  XYZ   | 120       | 78.5%  | 12      | 25/07          │
└─────────────────────────────────────────────────────────┘
```

**API:**
```
GET /api/portfolio/summary
→ {
    "total_projects": 3,
    "total_functions": 615,
    "avg_progress": 62.0,
    "total_overdue": 91,
    "projects": [
        { "id": "...", "name": "...", "color": "...", "stats": {...} },
        ...
    ]
  }
```

---

## 7. TÍNH NĂNG BỔ SUNG

### 7a. Duplicate dự án

Khi PM bắt đầu dự án mới có cấu trúc tương tự:
- Copy settings (thresholds, risk weights) từ dự án gốc
- Không copy data/snapshots
- Tiết kiệm thời gian cấu hình

### 7b. Archive dự án

Dự án đã hoàn thành → archive thay vì xóa:
- Vẫn giữ data, có thể xem lại
- Không hiện ở trang chủ mặc định (có toggle "Hiện dự án đã lưu trữ")
- Không chiếm chỗ trên portfolio overview

### 7c. Export cross-project

```
GET /api/portfolio/export
→ Excel file gồm:
  - Sheet "Tổng quan": bảng so sánh tất cả dự án
  - Sheet "{tên dự án}": module overview của từng dự án
  - Sheet "Overdue tổng hợp": gộp overdue tất cả dự án
```

### 7d. Import/Export Project (backup)

```
GET  /api/projects/<id>/export-backup  → Download zip toàn bộ folder dự án
POST /api/projects/import-backup       → Upload zip → tạo dự án từ backup
```

Hữu ích khi chuyển máy hoặc chia sẻ giữa PM.

---

## 8. IMPLEMENTATION PLAN

### Thứ tự ưu tiên

**Bước 1 — Nền tảng (bắt buộc):**
1. Tạo `project_manager.py` với CRUD cơ bản
2. Tạo `templates/home.html` + `static/js/home.js`
3. Đổi tên `templates/index.html` → `templates/dashboard.html`
4. Cập nhật `app.py`: route mới, backward compatible
5. Cập nhật `dashboard.js`: POST đến project-scoped API

**Bước 2 — Hoàn thiện UX:**
6. Project switcher dropdown trong dashboard header
7. Card design + color picker
8. Archive + duplicate
9. Portfolio overview section

**Bước 3 — Nâng cao:**
10. Import/Export backup
11. Cross-project export
12. Snapshot auto-save khi upload

### Lưu ý kỹ thuật

1. **Slugify tiếng Việt:** dùng `unicodedata.normalize("NFD", text)` để bỏ dấu
   - "MPHG - Triển khai iHRP" → "mphg_trien_khai_ihrp"
   - Kiểm tra trùng id trước khi tạo folder

2. **Thread safety:** app chạy local single-user nên không cần lock,
   nhưng tránh race condition khi save file (dùng temp file + rename)

3. **Folder cleanup:** Khi xóa dự án, dùng `shutil.rmtree()`,
   nhưng PHẢI có double-confirm ở frontend

4. **Migration:** Lần đầu chạy bản mới, nếu đã có file ở `uploads/`:
   - Tự tạo dự án "Default"
   - Move file vào `data/default/current.xlsx`
   - Hiện thông báo: "Dữ liệu cũ đã được chuyển vào dự án Default"

5. **Static files:** Tạo thêm `static/js/home.js` cho trang chủ.
   `dashboard.js` chỉ load ở trang dashboard, không load ở home.

6. **URL structure:**
   ```
   /                           → Trang chủ (danh sách dự án)
   /?home=1                    → Luôn về trang chủ (bypass auto-redirect)
   /project/<id>               → Dashboard dự án
   /project/<id>/settings      → (tương lai) Settings dự án
   ```
