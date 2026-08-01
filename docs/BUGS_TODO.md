# Bug Tracker + TODO — cập nhật 2026-08-01

**Trạng thái sản phẩm:** Core + multi-project + Forecast + Chiều PM + Integrations +
Public API + LAN + Archive + **PMO A–F** + **BA UX** — **đã ship**.

Kiến trúc: [`ARCHITECTURE.md`](ARCHITECTURE.md) · Catalog: [`FEATURE_CATALOG.md`](FEATURE_CATALOG.md) ·  
Changelog PMO/BA: [`CHANGELOG_PMO_BA.md`](CHANGELOG_PMO_BA.md).

Resume P2 còn lại: root `_WIP_RESUME_NOTES.md` (pointer ngắn).

```bash
pytest -q
```

---

## ✅ Đã ship (tóm tắt — không liệt kê hết commit)

| Gói | Nội dung |
|-----|----------|
| Core / V3–V4 | Multi-project, DQ, bookmarks, digest, custom dash, palette, present… |
| Integrations | Registry API, 4 auth + DB, Mapping Wizard, `verify_ssl`, sync polish |
| Share | Public REST/iframe/PNG, LAN secure, Help unified |
| Forecast / PM | Forecast Gantt/Manpower, PIC Overload, Rlog, Chiều PM, MoM |
| Ops | Archive T-AA, disk janitor (synced prune + PPTX dedupe), history Nguồn |
| **PMO A–F** | Baseline SV, completion forecast, EVM, scope creep, pmo-risk+cascade, UAT Quality, `meta.db` dual-write |
| **BA UX** | Diff, saved views, insight trends, DQ highlights, bulk tags, critical path heuristic, FL verify, bottleneck, PIC upcoming, Module còn lại, insight strip collapse, DQ help |

---

## 🟡 P2 còn pending

### T-B. API Registry Catalog (`api-registry-catalog`)

1. Column metadata: `source_app`, `visibility`, `owner_contact`, `env`, `docs_url`, health/latency…
2. UI filter + detail (curl, schema preview, test connection)
3. Export/Import registry JSON; Import Postman

### T-C. Hoàn thiện `form_login` flow (`form-login-integration-flow`)

1. UI wizard login → selectors → download URL → test  
2. Cookie jar bền; CSRF UX; 2FA OTP optional  

> `form_login` **đã dùng được** (POST form + CSRF cơ bản). T-C = wizard + jar bền + 2FA.

---

## 🟢 Nice-to-have / gaps sản phẩm

| Item | Ghi chú |
|------|---------|
| SOVI-style ratio estimate (Manpower) | **Đã có** `estimate_ratio` (hệ số chỉnh được; không khóa số SOVI) |
| SQLite cutover full | Chỉ meta slice hiện tại |
| Critical path CPM thật | Hiện heuristic Gantt Calendar |
| FL verify cell-diff tổng quát | Hiện chỉ yellow-hit PIC/Status |
| Auto-cleanup digests | `purge_old_digests` còn mở |
| Presentation HUD Prev/Next | Nice-to-have |

---

## Session tiếp theo

1. Đọc [`SYSTEM_OVERVIEW.md`](SYSTEM_OVERVIEW.md) + [`FEATURE_CATALOG.md`](FEATURE_CATALOG.md) (không dùng UPGRADE_*.md làm SSOT).  
2. `pytest -q` trước mỗi commit.  
3. Ưu tiên **T-B** rồi **T-C**; xóa/ cập nhật `_WIP_RESUME_NOTES.md` khi xong.  
4. Không push trừ khi user yêu cầu.
