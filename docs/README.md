# iHRP Function List Tracker — Docs

Dashboard **local** cho PM/BA triển khai **iHRP / HRIS**: upload hoặc sync Function List Excel → auto-detect cột → metrics đa chiều → Forecast / PMO / BA UX → export · Public API · LAN.

> **Dành cho đánh giá ngoài (Claude / reviewer):** bắt đầu từ mục [Gợi ý đọc cho review](#gợi-ý-đọc-cho-review-claude) bên dưới.  
> **Ngày đồng bộ docs với code:** 2026-08-01.

---

## Cách chạy

```
start.bat          # Windows
./start.sh         # macOS/Linux
```

Mở `http://127.0.0.1:5000` (mặc định bind localhost). Credential: copy `.env.example` → `.env`.

```bash
pytest -q
```

---

## Gợi ý đọc cho review (Claude)

Đọc theo thứ tự này để nắm **sản phẩm hiện tại** (không phải roadmap cũ):

| # | File | Mục đích review |
|---|------|-----------------|
| 1 | **[SYSTEM_OVERVIEW.md](SYSTEM_OVERVIEW.md)** | Sản phẩm là gì, ai dùng, data flow, IA sidebar, gaps trung thực |
| 2 | **[FEATURE_CATALOG.md](FEATURE_CATALOG.md)** | Checklist feature đã ship (Core · PMO A–F · BA UX 1–11) + map UI/API |
| 3 | **[BUSINESS_LOGIC.md](BUSINESS_LOGIC.md)** | Công thức / rule: overdue, unassigned, stalled, forecast, EVM, SV… |
| 4 | **[ARCHITECTURE.md](ARCHITECTURE.md)** | Folder, persistence (JSON + `meta.db` slice), API surface, security |
| 5 | **[CHANGELOG_PMO_BA.md](CHANGELOG_PMO_BA.md)** | Gói PMO Phase A–F + BA UX đã ship — phạm vi & hạn chế |
| 6 | [DATA_MODEL.md](DATA_MODEL.md) | Schema parse + store JSON / SQLite |
| 7 | [DASHBOARD_SPEC.md](DASHBOARD_SPEC.md) | Spec UI section (lịch sử + default order; một số section mới tóm tắt ở FEATURE_CATALOG) |

Guides chuyên đề (khi cần sâu): Integrations, Public API, LAN, Archive, Chiều PM, Help.

---

## Mục lục đầy đủ

### Lớp tổng quan & catalog

| File | Nội dung |
|------|----------|
| [SYSTEM_OVERVIEW.md](SYSTEM_OVERVIEW.md) | Big picture, người dùng, kiến trúc 3 lớp, nhóm dashboard |
| [FEATURE_CATALOG.md](FEATURE_CATALOG.md) | Catalog feature ↔ section ↔ API ↔ module |
| [BUSINESS_LOGIC.md](BUSINESS_LOGIC.md) | Rule nghiệp vụ end-to-end |
| [ARCHITECTURE.md](ARCHITECTURE.md) | Stack, storage, module map, API, frontend |
| [CHANGELOG_PMO_BA.md](CHANGELOG_PMO_BA.md) | Tóm tắt roadmap PMO/BA đã ship |
| [DATA_MODEL.md](DATA_MODEL.md) | ParsedData + JSON / `meta.db` |
| [DASHBOARD_SPEC.md](DASHBOARD_SPEC.md) | Spec UI chi tiết (nhiều section V1–V4) |

### Guides chuyên đề

| File | Khi nào đọc |
|------|-------------|
| [INTEGRATIONS_GUIDE.md](INTEGRATIONS_GUIDE.md) | Registry API, auth, smart mapping, `verify_ssl` |
| [IHRP_TASKDAILY_API_SETUP.md](IHRP_TASKDAILY_API_SETUP.md) | Ví dụ sync iHRP Task Daily |
| [PUBLIC_API_GUIDE.md](PUBLIC_API_GUIDE.md) | REST + iframe + PNG + token |
| [LAN_DEPLOY_GUIDE.md](LAN_DEPLOY_GUIDE.md) | LAN, firewall, bind localhost |
| [ARCHIVE_GUIDE.md](ARCHIVE_GUIDE.md) | Archive / restore + disk janitor (startup) |
| [PM_DIMENSION_GUIDE.md](PM_DIMENSION_GUIDE.md) | KeHoachDuAn + Weekly PPT |
| [HELP_CONTENT_GUIDE.md](HELP_CONTENT_GUIDE.md) | Thêm topic help (`dataquality`, EVM…) |
| [BUGS_TODO.md](BUGS_TODO.md) | Done / backlog P2 (Registry catalog, form_login wizard) |
| [UPGRADE_V2.md](UPGRADE_V2.md) / [UPGRADE_MULTIPROJECT.md](UPGRADE_MULTIPROJECT.md) | **Historical** — không phản ánh architecture hiện tại |

---

## Feature highlights (đã ship)

- Core: auto-detect FL · overdue / status / PIC · multi-project · snapshot · archive · disk janitor  
- Forecast: UAT/Golive theo tháng · Manpower MH/MD/MM · PIC Overload · Rlog · Chiều PM  
- **PMO A–F:** Baseline SV · Completion forecast · EVM · Scope creep/CR · Risk+cascade+overload · UAT Quality · SQLite `meta.db` dual-write (meta slice)  
- **BA UX:** Auto-diff · saved filters · insight trends · DQ highlights · bulk tags · critical path (heuristic) · FL re-import verify · bottleneck · PIC upcoming · Module còn lại · insight strip collapse · DQ help  
- Export chart Tong_hop/Chi_tiet · Public API · LAN · Help unified  

**Hạn chế (trung thực):** SQLite chỉ meta; critical path heuristic; FL verify chỉ ô yellow-hit trước đó. Ước lượng theo hệ số (`estimate_ratio`) đã có — không khóa số SOVI. Chi tiết → [SYSTEM_OVERVIEW § Gaps](SYSTEM_OVERVIEW.md#10-gaps--hạn-chế-trung-thực).

---

## Development

```bash
pytest -q
```

Resume / WIP cũ: root `_WIP_RESUME_NOTES.md` (chỉ còn pointer P2 T-B/T-C — không phải source of truth sản phẩm).
