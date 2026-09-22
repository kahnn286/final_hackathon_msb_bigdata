# Data Reliability Squad — UI Redesign Spec

> Tài liệu này dành cho AI coding agent (Antigravity). Đọc hết mục 0–3 trước, sau đó làm **từng Phase** ở mục 12. Không làm nhiều Phase trong một lần.
> Ngôn ngữ UI: **tiếng Việt** (giữ thuật ngữ kỹ thuật tiếng Anh: incident, quarantine, lineage, DQ test, Maker/Checker). Code + comment: tiếng Anh hoặc Việt đều được, nhưng nhất quán với codebase hiện tại.

---

## 0. Mục tiêu

Redesign **DataOps Console** (dashboard tại `/`) và lớp giao diện của **Copilot chat** (Chainlit tại `/chat`, đang nhúng qua iframe) để:

1. Nhìn như một công cụ vận hành (Datadog / Linear / Airflow) chứ không phải poster: gọn, ít màu, số liệu rõ.
2. **Kể được câu chuyện của sản phẩm** trong 10 giây đầu: *Có sự cố → Maker điều tra → Người duyệt → Vá → Checker nghiệm thu độc lập*.
3. **Mọi số liệu là số thật** từ DuckDB / state của agent, không hardcode.
4. Chat panel không còn bị tràn ngang, không lệch màu (nút gửi màu hồng, nền khác dashboard).

Đây là demo cho hackathon: ưu tiên **rõ ràng, đúng, ổn định** hơn là hiệu ứng.

---

## 1. Hiện trạng & vấn đề cần sửa

Nguồn: 2 screenshot + `web/frontend/dashboard.py`, `components.py`, `rendering.py`, `ui.py`, `web/server.py`.

| # | Vấn đề | Bằng chứng | Hướng sửa |
|---|--------|-----------|-----------|
| 1 | **Toàn bộ số liệu hardcode** trong HTML (1,000 / 15 NULLs / 98.5% SLA / "Last sync: 2 min ago"). `dashboard.py` import `db` nhưng không dùng. | `dashboard.py` | Endpoint `GET /ui/state` + polling (mục 7) |
| 2 | Số liệu tự mâu thuẫn: "15 NULLs" nhưng bảng ghi "5 tests failed"; "0 lost" trong khi chưa quarantine dòng nào. | Screenshot 1 | Tách rõ *rows lỗi* vs *tests fail* vs *rows đã cách ly* (mục 6.4) |
| 3 | Header nhồi 4 chip → bị wrap 2 dòng ("Data Reliability / Squad"), chip "SLA Health 98.5%" là số bịa. | Screenshot 2 | Header gọn 1 dòng, gom trạng thái hệ thống (6.1) |
| 4 | Chat panel: welcome message là **bảng 4 cột** trong khung ~440px → thanh cuộn ngang, chữ bị bóp dọc từng từ ("OFFLINE (mô phỏng)"). | Screenshot 2 (`welcome_message()` ở `rendering.py`) | Đổi sang danh sách gọn; đưa bảng vai trò lên dashboard (8.4) |
| 5 | Chainlit dùng theme mặc định: nút gửi **hồng** lệch hẳn palette xanh của dashboard, font khác. | Screenshot 2 | `public/theme.json` + `custom_css` (mục 8) |
| 6 | Emoji dùng làm icon, cả 3 source card đều là `📦` → không phân biệt được, nhìn rẻ. | `dashboard.py` | SVG icon set (mục 5.5) |
| 7 | Click vào source card **không làm gì cụ thể**: `openDuoWindow(streamName)` bỏ qua tham số. | `dashboard.py` JS | Context chip + (tuỳ chọn) truyền context sang chat (6.10) |
| 8 | Màu/glow/gradient loạn: glow đỏ, glow indigo, nút gradient, 3 kiểu radius (6/10/14/20). | CSS | Design tokens thống nhất (mục 5) |
| 9 | DAG chỉ là 5 ô + mũi tên `➔`, không có số liệu, không thể hiện blast radius. | `dashboard.py` | Lineage có số + trạng thái (6.7) |
| 10 | Text thừa/lặp: "Cần Duyệt Phê Duyệt", tiêu đề section IN HOA dài, "Ready 24/7". | `dashboard.py` | Copy deck (mục 10) |
| 11 | HTML nằm trong **f-string Python** → phải escape `{{ }}` mọi CSS/JS, rất khó sửa, dễ vỡ. | `dashboard.py` | Tách ra file tĩnh (mục 9) |
| 12 | Nút Refresh = `location.reload()` → **reload iframe → tạo session Chainlit mới → `on_chat_start` chạy lại: gọi LLM điều tra lại + bắn thêm Email/Zalo.** Iframe cũng load ngay cả khi panel đang đóng. | `dashboard.py`, `ui.py::on_chat_start` | Lazy-load iframe; Refresh dùng `fetch`; dedupe notification theo `incident_id` (mục 8.6) |
| 13 | Dashboard không biết trạng thái workflow (đang điều tra / chờ duyệt / đã vá / audit pass-fail) vì state nằm trong `cl.user_session`. | `ui.py` | Module state dùng chung (mục 7.3) |

---

## 2. Nguyên tắc thiết kế

1. **Một câu chuyện, một điểm nhấn.** Incident đang mở là thứ duy nhất được phép "nổi" (viền + nền tint đỏ). Mọi thứ khác trung tính.
2. **Màu = ý nghĩa.** Xanh lá/vàng/đỏ chỉ dùng cho *trạng thái*. Accent xanh dương cho hành động chính. Tím chỉ dành cho **Checker**. Không dùng màu để trang trí.
3. **Không chỉ dựa vào màu**: mọi trạng thái = chấm màu **+ chữ** (accessibility, và demo chiếu máy chiếu bị phai màu vẫn đọc được).
4. **Số liệu là công dân hạng nhất**: font mono, `tabular-nums`, căn phải trong bảng, không nhảy layout khi số đổi.
5. **Trung thực**: nếu Notification đang dry-run, LLM đang offline (mô phỏng), hoặc cross-model tắt → hiển thị đúng như vậy, không nói "Active".
6. **Ít chuyển động**: chỉ animate (a) chấm "live", (b) step đang chạy của stepper, (c) badge cần duyệt. Tôn trọng `prefers-reduced-motion`.

---

## 3. Ràng buộc kỹ thuật (đừng phá)

- Stack: **FastAPI + Chainlit (mount tại `/chat`) cùng 1 process, cùng port**. Dashboard trả về ở `GET /` và `GET /dashboard`.
- **Không thêm build step** (không React/Vite/npm). Vanilla HTML + CSS + ES modules JS. Chỉ cho phép font từ Google Fonts (đã dùng sẵn).
- Giữ nguyên các endpoint `/api/*`, `/health`, và các `cl.action_callback("approve" | "reject" | "audit")`.
- **Không sửa logic trong `ai/` và `data/`** (chỉ được *đọc* từ chúng). Nếu cần thêm helper thì thêm vào `web/`.
- `mount_chainlit(...)` phải được gọi **sau** khi khai báo mọi route/mount khác (như hiện tại).
- Có thể chạy được bằng `uvicorn main:app` như cũ; app vẫn chạy khi **OFFLINE** (chưa có `DRA_API_KEY`).
- **Không đụng vào `.env`** và không in secret ra log/UI.

---

## 4. Information Architecture & Layout

### 4.1 Desktop (≥ 1280px)

```
┌───────────────────────────────────────────────────────────────────────────────────────────────┐
│ TOPBAR (56px)  ◈ Data Reliability Squad  v2.0      ● Warehouse · Notify: dry-run · Cross-model │
│                                                                              [⟳]  [◧ Copilot ①]│
├─────────────────────────────────────────────────────────────────────┬─────────────────────────┤
│ MAIN  (scroll-y · content max-width 1200 · padding 24 · gap 24)     │ COPILOT DOCK  400–440px │
│                                                                     │ ┌─────────────────────┐ │
│ ┌ INCIDENT HERO ─────────────────────────────────────────────────┐  │ │ (M) Maker  (C) Check│ │
│ │ [HIGH] INC-2026-DQ01 · 15 dòng customer_id NULL     [Điều tra] │  │ │ ctx: mobile_app_v3  │ │
│ │ fact_orders · mobile_app_v3 v3.4.1 · blast radius: 2 marts     │  │ ├─────────────────────┤ │
│ │ ①Phát hiện ─ ②Điều tra ─ ③Chờ duyệt ─ ④Vá ─ ⑤Nghiệm thu ─ ⑥Xong │  │ │                     │ │
│ └────────────────────────────────────────────────────────────────┘  │ │   iframe  /chat     │ │
│                                                                     │ │                     │ │
│ [ Rows 1,000 ] [ Rows lỗi 15 ] [ Đã cách ly 0/15 ] [ DQ tests 5/6 ] │ │                     │ │
│                                                                     │ └─────────────────────┘ │
│ Nguồn dữ liệu                                                       │                         │
│ [ERP Core      ] [Web Checkout ] [Mobile App v3 ⚠ ]                 │                         │
│                                                                     │                         │
│ ┌ Lineage (8 cols) ────────────────────┐ ┌ Squad + Guardrails (4) ┐ │                         │
│ │ Sources → fact_orders → DQ → Marts   │ │ Maker / Checker / locks │ │                         │
│ └──────────────────────────────────────┘ └─────────────────────────┘ │                         │
│                                                                     │                         │
│ [ Bảng ] [ DQ tests ] [ Hoạt động của Agent ]                       │                         │
│ ┌ data table ──────────────────────────────────────────────────┐    │                         │
└─────────────────────────────────────────────────────────────────────┴─────────────────────────┘
```

- Copilot dock **mặc định mở** ở ≥1440px, **mặc định đóng** ở 1280–1439px. Kéo cạnh trái để đổi độ rộng (min 360, max 640), lưu vào `localStorage`.
- Nút **Expand** (↔) trong header dock: mở rộng lên 60% màn hình khi cần đọc báo cáo dài; bấm lại để thu về.

### 4.2 Tablet (768–1279px)
- Dock trở thành **drawer overlay** từ bên phải (width 420, có backdrop mờ, `Esc` để đóng).
- Sources: 3 cột → 1 hàng cuộn ngang hoặc 1 cột. Lineage cuộn ngang trong container riêng.

### 4.3 Mobile (< 768px)
- Topbar chỉ còn logo + nút Copilot. Chip trạng thái vào popover "Hệ thống".
- KPI 2×2. Sources 1 cột. Bảng → dạng card list (mỗi hàng 1 card).
- Copilot = **full-screen sheet** với nút đóng rõ ràng. FAB góc phải dưới, có badge khi cần duyệt.

---

## 5. Design Tokens

### 5.1 Màu (dark-only ở v1, nhưng khai báo bằng CSS variables để sau này thêm light)

```css
:root {
  /* Surfaces */
  --bg:          #0B0F14;
  --surface-1:   #11171F;   /* card, panel */
  --surface-2:   #161D27;   /* table header, input */
  --surface-3:   #1D2632;   /* hover */
  --border:      #232D3A;
  --border-strong:#2E3A4A;

  /* Text */
  --text:        #E6EBF2;
  --text-muted:  #9AA7B8;
  --text-subtle: #7D8A9C;   /* ≥ 4.5:1 trên --surface-1, đừng làm nhạt hơn */

  /* Brand / role */
  --accent:      #5CC8FF;   /* hành động chính, focus ring */
  --accent-weak: rgba(92,200,255,.12);
  --maker:       #5CC8FF;
  --checker:     #A78BFA;   /* CHỈ dùng cho Checker / audit */

  /* Status (dùng kèm chữ, không dùng đơn độc) */
  --ok:          #34D399;  --ok-bg:     rgba(52,211,153,.10);
  --warn:        #FBBF24;  --warn-bg:   rgba(251,191,36,.10);
  --danger:      #F87171;  --danger-bg: rgba(248,113,113,.10);
  --neutral:     #94A3B8;  --neutral-bg:rgba(148,163,184,.10);

  /* Shape */
  --radius-sm: 6px;  --radius-md: 8px;  --radius-lg: 12px;   /* chỉ 3 giá trị này */
  --shadow-pop: 0 8px 24px rgba(0,0,0,.35);                   /* chỉ cho popover/drawer */

  /* Space: bội số của 4 */
  --s1:4px; --s2:8px; --s3:12px; --s4:16px; --s5:24px; --s6:32px;

  /* Type */
  --font-ui:   'Plus Jakarta Sans', system-ui, -apple-system, 'Segoe UI', sans-serif;
  --font-mono: 'JetBrains Mono', ui-monospace, 'SF Mono', Menlo, monospace;
}
```

### 5.2 Type scale

| Token | Size / line-height | Weight | Dùng cho |
|-------|-------------------|--------|----------|
| `display` | 28 / 34 | 700 | Số KPI (mono) |
| `title` | 20 / 28 | 700 | Tiêu đề incident |
| `h3` | 15 / 22 | 600 | Section title |
| `body` | 14 / 22 | 400 | Nội dung |
| `small` | 12 / 18 | 500 | Meta, label, chip |
| `mono-sm` | 12 / 18 | 500 | ID, tên bảng, source_system |

Section title: **Sentence case**, không IN HOA (bỏ kiểu "3 LUỒNG RAW DATA SOURCES & PIPELINE INGESTION"). Label nhỏ trên KPI được phép uppercase + `letter-spacing: .04em`, cỡ 11–12.

### 5.3 Elevation & border
Card = `surface-1` + border 1px `--border`. **Không glow, không gradient nền card.** Hover card: đổi border sang `--border-strong` + nền `--surface-2` (không `translateY`).

### 5.4 Trạng thái → token (map với `STATUS_CONFIG` trong `components.py`)

| key | Nhãn mới | Màu | Ghi chú |
|-----|----------|-----|---------|
| `healthy` | Bình thường | `--ok` | chấm tĩnh |
| `investigating` | Đang điều tra | `--warn` | chấm pulse chậm |
| `incident` | Có sự cố · chờ duyệt | `--danger` | chấm pulse chậm, card có viền trái 3px đỏ |
| `resolved` | Đã xử lý · đã nghiệm thu | `--accent` (hoặc `--ok`) | tick icon |
| `sleep` | Tạm nghỉ | `--neutral` | chấm rỗng |

Status pill = `[● Nhãn]`, nền `*-bg`, chữ màu status, border 1px cùng màu 30% opacity, cao 24px, radius full.

### 5.5 Icon
Dùng **inline SVG sprite** (bộ Lucide, ISC license, stroke 1.75, 16/20px, `currentColor`). Không dùng emoji làm icon trong dashboard. Cần tối thiểu: `shield-check`, `database`, `radio`, `git-branch`, `triangle-alert`, `circle-check`, `circle-dashed`, `loader` (spin), `refresh-cw`, `panel-right-open`, `panel-right-close`, `maximize-2`, `bot`, `user-check`, `search-check`, `lock`, `lock-open`, `play`, `x`, `chevron-right`, `bell`.
Mỗi source có icon riêng: ERP = `database`, Web Checkout = `shopping-cart`, Mobile = `smartphone`.

### 5.6 Motion
- Transition chung: `150ms ease-out` (color, border, background).
- Dock mở/đóng: `250ms cubic-bezier(.4,0,.2,1)` (transform, không animate width để tránh reflow iframe).
- `@media (prefers-reduced-motion: reduce)` → tắt toàn bộ pulse/spin, giữ chấm tĩnh.

---

## 6. Component spec

### 6.1 Topbar (56px, sticky)
- **Trái:** icon `shield-check` + "Data Reliability Squad" (16/700) + chip `Maker · Checker v2.0` (mono-sm).
- **Phải, theo thứ tự:**
  1. **System chips** (ẩn dưới 1100px, gom vào popover "Hệ thống"):
     - `● Warehouse online` — hover tooltip: đường dẫn DB + tổng số dòng `fact_orders`.
     - `Notify: live | dry-run` — `live` chỉ khi có SMTP/Zalo config; ngược lại `dry-run` (vàng nhạt). Tooltip liệt kê từng kênh (Email, Zalo).
     - `Cross-model: bật | tắt` — từ `/api/models` (`cross_model_enabled`).
  2. Nút icon **Refresh** (`refresh-cw`) — gọi lại `/ui/state`, **không reload trang**. Có `aria-label`.
  3. Nút **Copilot** (`panel-right-*`): secondary style (không gradient), `aria-pressed`, label cố định "Copilot" (không đổi innerHTML). Badge số góc trên phải khi `status == WAITING_FOR_APPROVAL` (pulse nhẹ).
- **Bỏ:** chip "SLA Health 98.5%" (số bịa). Nếu muốn giữ khái niệm, dùng KPI "DQ tests" thật (6.4).

### 6.2 Incident Hero
Vị trí: đầu trang, full width. Là component quan trọng nhất.

**Anatomy**
```
[SeverityChip HIGH]  [StatusPill Chờ duyệt]                          [Primary CTA]
INC-2026-DQ01 (mono)                                                  [Secondary: Xem payload]
15 dòng customer_id NULL trong fact_orders                            ← title 20/700
mobile_app_v3 · v3.4.1 · phát hiện lúc 02:30 · Blast radius: 2 marts (mart_daily_revenue, mart_customer_ltv)
──────────────────────────────────────────────────────────────────────────────
<WorkflowStepper />
```

**States** (map từ `state.status`)
| status | Hero | CTA chính |
|--------|------|-----------|
| `IDLE` (không có incident) | nền `surface-1`, icon `circle-check` xanh, "Không có sự cố đang mở", meta "DQ tests gần nhất: 6/6 pass · lúc HH:MM" | "Chạy lại DQ tests" |
| `INVESTIGATING` | viền trái vàng, spinner, "Maker đang điều tra…" | "Xem tiến trình" (mở Copilot) |
| `WAITING_FOR_APPROVAL` | viền trái **đỏ 3px** + nền `--danger-bg` (6%) | **"Xem báo cáo & duyệt"** (mở Copilot) |
| `EXECUTING` | viền trái vàng, "Maker đang thực thi remediation…" | disabled + spinner |
| `AUDITING` | viền trái **tím** (Checker), "Checker đang nghiệm thu độc lập…" | "Xem tiến trình" |
| `RESOLVED` + `audit_verdict=AUDIT_PASSED` | viền trái xanh, badge "AUDIT PASSED" | "Xem biên bản" |
| `RESOLVED` + `AUDIT_FAILED` | viền trái đỏ, badge "AUDIT FAILED", câu "Máy đối chiếu ra kết quả khác LLM" nếu có | "Nghiệm thu lại" |
| `REJECTED` | viền trái neutral, "Đã từ chối remediation — chưa thay đổi dữ liệu" | "Yêu cầu phương án khác" |
| `FAILED` | viền trái đỏ, hiển thị lỗi ngắn | "Thử lại" |

### 6.3 Workflow Stepper
6 bước ngang (dọc trên mobile), nằm cuối Hero:

`Phát hiện (dbt) → Điều tra (Maker) → Chờ duyệt (Người) → Vá (Maker) → Nghiệm thu (Checker) → Hoàn tất`

- Mỗi bước: vòng tròn 24px + label 12px + dòng phụ (actor) 11px muted.
- Trạng thái: `done` (check xanh), `active` (viền accent/tím, pulse), `pending` (rỗng, muted), `error` (đỏ).
- Bước "Chờ duyệt" hiển thị icon `user-check` và nhãn "Con người" — đây là điểm khác biệt, phải nổi bật hơn (viền dashed khi đang chờ).
- Bước "Nghiệm thu" dùng màu `--checker`.
- Derive từ `state.status` + `state.audit_verdict` (bảng ở 7.3).

### 6.4 KPI Strip (4 ô, grid `repeat(auto-fit, minmax(200px,1fr))`)
Mỗi ô: label (11 uppercase muted) → giá trị (28 mono) → sub (12 muted). Cao cố định 96px.

| KPI | Giá trị | Sub | Ghi chú |
|-----|---------|-----|---------|
| Tổng bản ghi | `1,000` | `3 nguồn · fact_orders` | |
| Dòng vi phạm DQ | `15` (đỏ nếu >0, xanh nếu 0) | `không đạt: not_null_customer_id` | phân biệt với *tests fail* |
| Đã cách ly | `0 / 15` → sau vá `15 / 15` | `chờ duyệt` → `bảo toàn 100%, 0 mất` | **Thay** "0 lost" gây hiểu nhầm |
| DQ tests đạt | `5 / 6` | `1 test fail` | Số thật từ `DQ_CHECKS` |

Không viền màu trên đầu ô (bỏ `::before` 3px). Chỉ giá trị đổi màu.

### 6.5 Source Card (×3) — là `<button>`, không phải `<div onclick>`
**Anatomy** (cao ~176px, có `min-height` để 3 card đều nhau)
```
[icon] ERP Core System                           [● Bình thường]
       erp_core · v2.1.0  (mono-sm chip)
Đơn hàng doanh nghiệp đồng bộ định kỳ.            ← 13 muted, 1 dòng, ellipsis
──────────────────────────────────────────────
Tổng dòng          Vi phạm DQ         Đồng bộ
400  ▓▓▓▓░ 40%      0                   2 phút trước
```
- Thanh nhỏ dưới "Tổng dòng" = tỷ lệ so với tổng (400/1000). Cao 4px, `--accent-weak` nền, `--accent` fill. Đơn giản, không cần thư viện.
- "Đồng bộ" = `now - MAX(ingested_at)` theo `source_system` (**dữ liệu thật**, format tiếng Việt: "vừa xong", "2 phút trước", "3 giờ trước").
- **Incident state**: viền trái 3px `--danger`, nền `--danger-bg`, dòng mô tả đổi thành "15 dòng `customer_id IS NULL` ở batch cuối", "Vi phạm DQ" = `15` đỏ. **Không** glow, không lơ lửng.
- Footer: trái = trạng thái phụ ("Chờ duyệt"), phải = link `Mở Copilot →`. **Chỉ một** link, bỏ câu "Cần Duyệt Phê Duyệt".
- Click = mở Copilot + set context chip (6.10).
- Focus: `outline: 2px solid var(--accent); outline-offset: 2px`.

### 6.6 Squad & Guardrails card (cột phải, span 4)
Thay cho bảng vai trò đang nhét trong chat.

**Squad** (2 dòng)
```
(M) Maker · Agent 1 — Data SRE        ● idle | working | offline (mô phỏng)
    đọc + ghi (chỉ sau khi duyệt)      model: gpt-…  (mono-sm, ellipsis)
(C) Checker · Agent 2 — Data Auditor  ● idle | working | offline (mô phỏng)
    chỉ đọc · nghiệm thu độc lập       model: …
```
Avatar tròn 28px: Maker nền `--accent-weak` chữ `--maker`; Checker nền tím 12% chữ `--checker`.

**Guardrails** (4 dòng, icon + chữ + trạng thái)
| Guardrail | Nguồn dữ liệu | Hiển thị |
|-----------|---------------|----------|
| Ghi dữ liệu | `tools.is_remediation_unlocked()` | `lock` "Đang khoá — chờ duyệt" / `lock-open` "Đã mở cho lần vá này" |
| Checker chỉ đọc | hằng số | `lock` "Không có tool ghi" |
| Cross-model | `/api/models` | "Bật · Maker≠Checker" / "Tắt · cùng model, cùng điểm mù" (vàng) |
| Đối chiếu bằng Python | hằng số | "Máy thắng khi lệch LLM" |

Đây là phần giúp giám khảo hiểu ngay *vì sao hệ thống đáng tin*. Giữ chữ ngắn.

### 6.7 Lineage (span 8) — SVG inline, không thư viện
Node (rounded 8px, `surface-2`, border) nối bằng đường cong SVG:

```
[3 nguồn]──▶[fact_orders 1,000]──▶[DQ tests 5/6 ✓]──▶[quarantine_fact_orders 0]
                     │                                         
                     └──────────────▶[mart_daily_revenue ⚠ stale]
                                   └▶[mart_customer_ltv ⚠ stale]
```
- Mỗi node: tên (mono-sm) + 1 số (row count) + status dot.
- Edge đi qua node lỗi đổi màu `--danger` (30% opacity); marts phụ thuộc bị ảnh hưởng = `--warn` + nhãn "cần rebuild sau vá" (đây là **blast radius**).
- Sau khi RESOLVED: quarantine node sáng lên với số dòng, marts về `--ok`.
- Cuộn ngang trong container khi hẹp; `min-width: 720px` cho SVG.
- Có `<title>`/`aria-label` mô tả toàn bộ luồng cho screen reader.

### 6.8 Data Tabs (span 12)
Tab bar dạng underline (không pill), phím mũi tên chuyển tab. Nhớ tab đang chọn.

**Tab 1 — Bảng (Warehouse tables)**
| Cột | Nội dung |
|-----|----------|
| Tên bảng | mono, có badge layer: `FACT` `DIM` `MART` `QUARANTINE` |
| Số dòng | mono, căn phải, `tabular-nums` (mart chưa build → "—") |
| DQ | status pill (Đạt / n test fail / Chờ / Cần rebuild) |
| Cập nhật | tương đối |
| Khuyến nghị | 1 dòng muted, ellipsis |
Bảng hệ thống (`dq_test_results`, `agent_audit_log`, `dq_baseline_snapshot`) ẩn mặc định, có toggle "Hiện bảng hệ thống".
Header sticky, hàng cao 44px, hover `--surface-2`.

**Tab 2 — DQ tests**
List 6 check trong `DQ_CHECKS`: tên test, cột, loại (chip `not_null` / `unique` / `accepted_values`…), số dòng vi phạm, status pill, thời điểm chạy gần nhất. Nút **"Chạy lại"** (gọi `POST /ui/dq/run`, có loading state trên nút + toast kết quả).

**Tab 3 — Hoạt động của Agent**
Timeline từ `agent_audit_log` (dùng `data.audit.read_audit_log(limit)`; **đọc `data/audit.py` để biết đúng tên cột** trước khi map). Mỗi dòng: giờ (mono) · actor chip (Maker xanh / Checker tím) · tool (icon + tên) · badge `ĐỌC` (neutral) hoặc `GHI` (vàng) · tóm tắt 1 dòng. Tự cập nhật theo polling, dòng mới highlight 1.5s. Đây là bằng chứng "mọi tool call đều được ghi lại".

### 6.9 Trạng thái phổ quát
- **Loading lần đầu:** skeleton (khối `surface-2` shimmer, tắt khi reduced-motion) đúng kích thước component để không nhảy layout.
- **Error / mất kết nối:** banner mỏng dưới topbar "Mất kết nối tới server — đang thử lại… (dữ liệu lúc HH:MM:SS)"; giữ nguyên dữ liệu cũ, làm mờ nhẹ.
- **Empty:** mỗi tab/list có empty state 1 câu + icon.
- **Toast:** góc dưới trái, 4s, `role="status"`.

### 6.10 Copilot Dock
**Header (48px):** trái: 2 avatar Maker/Checker chồng nhẹ + chấm trạng thái từng agent; giữa: title "Copilot"; phải: `maximize-2` (expand), `x` (đóng).
**Context bar (32px)** dưới header: chip `Ngữ cảnh: mobile_app_v3 · INC-2026-DQ01`. Click source card → cập nhật chip. (Xem "Context sang chat" bên dưới.)
**Body:** `<iframe src="/chat" title="Copilot chat">`.
- **Lazy-load:** chỉ set `iframe.src` lần đầu dock được mở (tránh chạy `on_chat_start` khi chưa ai xem). Đóng dock = ẩn (`inert` + `visibility`), **không** unload iframe (giữ session).
- **Rail thu gọn 44px** khi đóng ở desktop: icon chat + badge cần duyệt.
- **Resize handle** 6px ở cạnh trái, cursor `col-resize`, bàn phím: `←/→` khi focus.
- Phím tắt: `C` mở/đóng Copilot (bỏ qua khi đang gõ trong input), `Esc` đóng drawer (tablet/mobile).

**Context sang chat (tuỳ chọn, Phase 3+ — cần verify):** Chainlit iframe cùng origin nên có thể (a) thêm query `?src=mobile_app_v3` và đọc lại trong `on_chat_start`, hoặc (b) dashboard `POST /ui/focus` lưu vào `state.py` để `ui.py` đọc. Chọn cách đơn giản nhất chạy được; nếu không ổn thì **chỉ hiển thị context chip** (không bắt buộc chat phải đổi hành vi). Không làm hỏng luồng `on_chat_start` hiện tại.

---

## 7. Data contract

### 7.1 `GET /ui/state` (router mới `web/backend/ui_api.py`, same-origin, read-only)

```json
{
  "generated_at": "2026-09-20T15:48:03+07:00",
  "system": {
    "service": "Data Reliability Squad",
    "version": "2.0",
    "warehouse": { "online": true, "path": "data/warehouse.duckdb", "fact_orders_rows": 1000 },
    "notifications": { "email": "dry_run", "zalo": "dry_run" },
    "models": {
      "maker":   { "model": "gpt-x", "offline": false },
      "checker": { "model": "claude-y", "offline": false },
      "cross_model_enabled": true
    },
    "remediation_unlocked": false
  },
  "kpis": {
    "total_rows": 1000,
    "violating_rows": 15,
    "quarantined_rows": 0,
    "quarantine_expected": 15,
    "tests_total": 6,
    "tests_passed": 5
  },
  "sources": [
    { "key": "erp_core",      "name": "ERP Core System",     "version": "v2.1.0",
      "rows": 400, "violations": 0,  "last_ingested_at": "2026-09-20T15:46:00+07:00", "status": "healthy" },
    { "key": "web_checkout",  "name": "Web Checkout Stream", "version": "v1.8.4",
      "rows": 300, "violations": 0,  "last_ingested_at": "2026-09-20T15:47:00+07:00", "status": "healthy" },
    { "key": "mobile_app_v3", "name": "Mobile App Ingest",   "version": "v3.4.1",
      "rows": 200, "violations": 15, "last_ingested_at": "2026-09-20T15:45:30+07:00", "status": "incident" }
  ],
  "tables": [
    { "name": "fact_orders", "layer": "fact", "rows": 1000, "dq": "fail", "failed_tests": 1,
      "updated_at": "…", "recommendation": "Cách ly 15 dòng lỗi từ SDK 3.4.1" },
    { "name": "dim_customers", "layer": "dim", "rows": 400, "dq": "pass", "failed_tests": 0 },
    { "name": "quarantine_fact_orders", "layer": "quarantine", "rows": 0, "dq": "pending" },
    { "name": "mart_daily_revenue", "layer": "mart", "rows": null, "dq": "stale" }
  ],
  "dq_tests": [
    { "test_name": "not_null_fact_orders_customer_id", "column": "customer_id", "type": "not_null",
      "failures": 15, "status": "fail", "last_run_at": "…" }
  ],
  "lineage": {
    "nodes": [ { "id": "fact_orders", "label": "fact_orders", "rows": 1000, "state": "incident" } ],
    "edges": [ { "from": "fact_orders", "to": "mart_daily_revenue", "state": "affected" } ]
  },
  "incident": {
    "id": "INC-2026-DQ01",
    "status": "WAITING_FOR_APPROVAL",
    "severity": "HIGH",
    "type": "DATA_QUALITY",
    "title": "15 dòng customer_id NULL trong fact_orders",
    "target_table": "fact_orders",
    "source": "mobile_app_v3",
    "detected_at": "…",
    "blast_radius": ["mart_daily_revenue", "mart_customer_ltv"],
    "audit_verdict": null,
    "agents": { "maker": "idle", "checker": "idle" }
  },
  "activity": [
    { "ts": "…", "actor": "maker", "tool": "tool_query_duckdb", "kind": "read", "summary": "SELECT … FROM fact_orders" }
  ]
}
```
Khi không có incident: `incident: null`.

### 7.2 Nguồn dữ liệu (dùng hàm đã có, không viết lại logic)

| Trường | Lấy từ |
|--------|--------|
| `sources[*].rows / violations` | `web.frontend.components.get_source_metrics()` (đã có fallback) + thêm `MAX(ingested_at)` cùng query |
| `kpis.tests_*`, `dq_tests` | `data.dq.DQ_CHECKS` + `db.scalar(check.count_sql)`; hoặc bảng `dq_test_results` theo `latest_run_id()` |
| `kpis.quarantined_rows` | `data.audit.detect_quarantine_table("fact_orders")` + `db.row_count(...)` |
| `system.models` | `ai.llm.LLMSettings.from_env()` / `.for_auditor(avoid_model=…)` (giống `/api/models`) |
| `system.notifications` | so sánh `config.SMTP_HOST`, `config.ZALO_WEBHOOK_URL`, `config.ZALO_OA_TOKEN` với rỗng → `live` / `dry_run` |
| `system.remediation_unlocked` | `ai.tools.is_remediation_unlocked()` |
| `activity` | `data.audit.read_audit_log(limit)` |
| `incident.*` | `data.incidents.build_sample_incident_payload()` (thông tin tĩnh) + `web/state.py` (trạng thái động) |

Mọi hàm DB chạy trong `run_in_threadpool`. Bọc `try/except`: lỗi một phần → trả phần còn lại + `"errors": ["…"]`, đừng 500 cả response.

### 7.3 `web/state.py` — state dùng chung giữa Chainlit và dashboard
Chainlit chạy cùng process với FastAPI nên dùng dict + lock in-process là đủ (**không ghi vào DuckDB** để khỏi dính khoá single-writer).

```python
# web/state.py
from __future__ import annotations

import threading
from datetime import datetime, timezone
from typing import Any, Dict, Optional

_lock = threading.Lock()
_state: Dict[str, Any] = {
    "incident_id": None,
    "status": "IDLE",          # IDLE | INVESTIGATING | WAITING_FOR_APPROVAL | EXECUTING | AUDITING | RESOLVED | REJECTED | FAILED
    "audit_verdict": None,     # None | "AUDIT_PASSED" | "AUDIT_FAILED"
    "maker": "idle",           # idle | working | offline
    "checker": "idle",
    "updated_at": None,
}


def set_state(**changes: Any) -> None:
    with _lock:
        _state.update(changes)
        _state["updated_at"] = datetime.now(timezone.utc).isoformat()


def get_state() -> Dict[str, Any]:
    with _lock:
        return dict(_state)
```

**Hook points trong `ui.py`** (chỉ thêm 1 dòng `set_state(...)` mỗi chỗ, không đổi logic):

| Vị trí | Gọi |
|--------|-----|
| `on_chat_start`, sau `agent.load_incident` | `set_state(incident_id=…, status="INVESTIGATING", maker="working", audit_verdict=None)` |
| Sau `send_agent_report` | `set_state(status="WAITING_FOR_APPROVAL", maker="idle")` |
| `on_approve`, trước khi chạy remediation | `set_state(status="EXECUTING", maker="working")` |
| `run_independent_audit`, đầu / cuối | `set_state(status="AUDITING", checker="working")` → `set_state(status="RESOLVED", checker="idle", audit_verdict=audit.verdict)` |
| `on_reject` | `set_state(status="REJECTED", maker="idle")` |
| Các `except` lớn | `set_state(status="FAILED", maker="idle", checker="idle")` |

**Mapping Stepper** (`status`, `audit_verdict` → 6 bước)

| status | Phát hiện | Điều tra | Chờ duyệt | Vá | Nghiệm thu | Hoàn tất |
|--------|:-:|:-:|:-:|:-:|:-:|:-:|
| INVESTIGATING | done | **active** | – | – | – | – |
| WAITING_FOR_APPROVAL | done | done | **active** | – | – | – |
| EXECUTING | done | done | done | **active** | – | – |
| AUDITING | done | done | done | done | **active** | – |
| RESOLVED + PASSED | done | done | done | done | done | done |
| RESOLVED + FAILED | done | done | done | done | **error** | – |
| REJECTED | done | done | **error** (Từ chối) | – | – | – |

### 7.4 Polling phía client
- `fetch('/ui/state')` mỗi **4s** khi tab visible và không lỗi; **2s** khi `status ∈ {INVESTIGATING, EXECUTING, AUDITING}`; dừng khi `document.hidden`.
- Lỗi → backoff 4s → 8s → 15s (max), hiện banner mất kết nối (6.9).
- Render bằng hàm thuần `render(state)`; **diff nhẹ**: chỉ cập nhật node có giá trị đổi để không làm mất focus / hover / selection.
- Có `aria-live="polite"` cho vùng Hero để screen reader đọc khi status đổi.

### 7.5 `POST /ui/dq/run`
Wrapper của `data.dq.run_all_checks()` (giống `/api/dq/run` nhưng không cần Bearer). Trả `{ total, failed, results }`. Chỉ ghi vào `dq_test_results`, không đụng dữ liệu nghiệp vụ.
> Ghi chú bảo mật: `/ui/*` không qua `require_token` vì cùng origin với dashboard. Không được thêm bất kỳ route `/ui/*` nào có thể **ghi dữ liệu nghiệp vụ** hoặc gọi `execute_remediation`.

---

## 8. Chainlit — theme & chat polish

### 8.1 `public/theme.json` (tạo thư mục `public/` ở project root)
Chainlit 2.x đọc HSL dạng `"H S% L%"` (không bọc `hsl()`). Giá trị dưới đây xấp xỉ palette ở 5.1, chỉnh mắt lại sau khi chạy thử:

```json
{
  "custom_fonts": [
    "https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap"
  ],
  "variables": {
    "dark": {
      "--font-sans": "'Plus Jakarta Sans', system-ui, sans-serif",
      "--background": "212 30% 7%",
      "--foreground": "214 30% 92%",
      "--card": "214 30% 10%",
      "--card-foreground": "214 30% 92%",
      "--popover": "214 30% 10%",
      "--popover-foreground": "214 30% 92%",
      "--primary": "201 100% 68%",
      "--primary-foreground": "212 30% 7%",
      "--secondary": "214 27% 13%",
      "--secondary-foreground": "214 30% 92%",
      "--muted": "214 27% 13%",
      "--muted-foreground": "214 15% 65%",
      "--accent": "214 27% 16%",
      "--accent-foreground": "214 30% 92%",
      "--destructive": "0 91% 71%",
      "--border": "213 24% 18%",
      "--input": "213 24% 18%",
      "--ring": "201 100% 68%",
      "--radius": "0.5rem"
    }
  }
}
```

### 8.2 `.chainlit/config.toml`
```toml
[UI]
name = "Data Reliability Squad"
default_theme = "dark"
custom_css = "/public/copilot.css"
# giữ cot = "full" để hiện từng tool call
```
(Kiểm tra tên key đúng với phiên bản Chainlit đang cài, config sinh bởi 2.11.0.)

### 8.3 `public/copilot.css` — chỉ chỉnh những thứ nhìn thấy được
Dùng DevTools để lấy selector thật của Chainlit (class có thể khác giữa các version). Mục tiêu:
- **Bảng trong tin nhắn**: `overflow-x: auto`, `font-size: 12px`, padding ô 6px 10px, header nền `--surface-2` — tránh tràn khung 400px.
- Ẩn readme button / phần header thừa khi chạy trong iframe (dashboard đã có header).
- Bo góc message 8px; tin nhắn của **Data Auditor** có viền trái tím `#A78BFA`, **Data SRE Agent** viền trái `#5CC8FF`, **System/dbt alert** trung tính.
- Action buttons: "Duyệt Remediation" = primary (nền accent, chữ tối); "Từ chối" = outline đỏ; "Nghiệm thu độc lập" = outline tím. Kiểm tra DOM để tìm selector ổn định (id/aria-label) — nếu không có, chấp nhận style chung của Chainlit thay vì hack selector mong manh.
- Composer (ô nhập): nền `--surface-1`, nút gửi dùng `--primary` (hết hồng).

### 8.4 Rút gọn nội dung chat (sửa `web/frontend/rendering.py` + `ui.py`)
Bỏ bảng 4 cột trong welcome, bỏ bảng "GIÁM SÁT 3 LUỒNG" trong chat (dashboard đã hiển thị live). Thay bằng:

```python
def welcome_message(maker_model, maker_offline, checker_model, checker_offline, checker_pool=None) -> str:
    """Welcome gọn: 2 dòng vai trò, không dùng bảng để không tràn khung chat hẹp."""
    same_model = maker_model == checker_model
    lines = [
        "**Data Reliability Squad** · sẵn sàng",
        "",
        f"- **Maker** (Agent 1) · {brain_badge(maker_model, maker_offline)} — điều tra & vá, chỉ ghi sau khi anh duyệt",
        f"- **Checker** (Agent 2) · {brain_badge(checker_model, checker_offline)} — chỉ đọc, nghiệm thu độc lập",
    ]
    if not maker_offline:
        lines += ["", "> Cross-model: **tắt** (cùng model, cùng điểm mù)" if same_model
                  else "> Cross-model: **bật** — Checker dùng model khác Maker"]
    lines += ["", "Đang nhận incident từ hàng đợi alert…"]
    return "\n".join(lines)
```
Trong `on_chat_start`: bỏ `render_raw_data_boxes(...)` khỏi 2 message (welcome và "thinking"); thay bằng 1 dòng, ví dụ `Mobile App · đang điều tra`. Giữ nguyên `render_raw_data_boxes` trong `components.py` (không xoá, có thể dùng lại).

### 8.5 Avatar theo agent
Thêm 3 ảnh PNG 64×64 vào `public/avatars/` (tên file theo author, Chainlit chuẩn hoá thường + thay khoảng trắng bằng `_` — kiểm tra docs): `data_sre_agent.png` (xanh), `data_auditor.png` (tím), `system.png` (xám). Có thể tạo bằng script Python/Pillow: vòng tròn màu + chữ M / C / S.

### 8.6 Chống spam thông báo / LLM khi reload (bug thật, nên sửa)
- Dashboard: iframe **lazy-load** + Refresh không reload (đã nêu ở 6.1, 6.10).
- `NotificationHub.notify_incident(...)`: thêm dedupe in-memory theo `incident_id` (TTL ~10 phút) — bỏ qua nếu vừa gửi, và trả về `{"deduped": true}` để UI ghi "Đã gửi trước đó". Đặt ở `web/notifications.py` hoặc ngay chỗ gọi trong `ui.py`.

---

## 9. Cấu trúc file & refactor

```
web/
├── frontend/
│   ├── dashboard.py            # rút gọn: chỉ trả FileResponse index.html (giữ get_dashboard_html() cho tương thích)
│   └── static/dashboard/
│       ├── index.html
│       ├── styles/
│       │   ├── tokens.css
│       │   ├── base.css        # reset, typography, utilities
│       │   └── components.css
│       ├── js/
│       │   ├── main.js         # bootstrap + polling loop
│       │   ├── api.js          # fetch + retry/backoff
│       │   ├── render.js       # render(state) → DOM (hàm thuần)
│       │   ├── copilot.js      # dock: open/close/resize/lazy iframe/shortcuts
│       │   ├── lineage.js      # dựng SVG lineage
│       │   └── format.js       # số, thời gian tương đối (vi-VN), escape
│       ├── icons.svg           # sprite
│       └── mock-state.json     # đúng schema 7.1, dùng ở Phase 1
├── backend/
│   ├── api.py                  # giữ nguyên
│   └── ui_api.py               # MỚI: /ui/state, /ui/dq/run
├── state.py                    # MỚI (7.3)
└── server.py                   # include ui_router + mount StaticFiles
public/                         # MỚI: theme.json, copilot.css, avatars/
```

`server.py`: thêm `app.include_router(ui_router)` và `app.mount("/static/dashboard", StaticFiles(directory=…), name="dashboard-static")` **trước** `mount_chainlit`. Route `/` và `/dashboard` trả `FileResponse(index.html)` với header `Cache-Control: no-cache`.

Quy tắc code frontend: không framework, không `innerHTML` với dữ liệu chưa escape (dùng `textContent` / `format.esc()`), không inline `onclick=`, mỗi component có một hàm render riêng.

---

## 10. Copy deck (tiếng Việt, thống nhất)

| Ngữ cảnh | Text |
|----------|------|
| Thuật ngữ | **Sự cố** (incident), **Duyệt / Từ chối**, **Nghiệm thu**, **Cách ly** (quarantine), **Vá** (remediation). Dùng nhất quán, không xen "Phê duyệt / Duyệt phê". |
| Status | Bình thường · Đang điều tra · Có sự cố · chờ duyệt · Đã xử lý · đã nghiệm thu · Tạm nghỉ |
| Hero CTA | "Xem báo cáo & duyệt" · "Xem tiến trình" · "Xem biên bản" · "Chạy lại DQ tests" |
| Section | "Nguồn dữ liệu" · "Lineage & blast radius" · "Đội Maker · Checker" · "Bảng trong warehouse" · "DQ tests" · "Hoạt động của Agent" |
| Source card action | "Mở Copilot →" |
| Guardrail khoá ghi | "Đang khoá — chờ anh duyệt" |
| Empty incident | "Không có sự cố đang mở" |
| Mất kết nối | "Mất kết nối tới server — đang thử lại…" |
| Thời gian | "vừa xong" · "2 phút trước" · "3 giờ trước" · "hôm qua" |
| Số | `1,000` (phân cách nghìn bằng dấu phẩy, giữ nhất quán với UI hiện tại) |

Xưng hô trong chat: giữ giọng "em/anh" như hiện tại. Dashboard dùng giọng trung tính, không xưng hô.

---

## 11. Accessibility, hiệu năng, chất lượng

- Contrast chữ ≥ 4.5:1 (body), ≥ 3:1 (chữ lớn / icon). Kiểm tra `--text-subtle`.
- Mọi phần tử tương tác là `<button>`/`<a>`, có `:focus-visible` rõ ràng; thứ tự Tab hợp lý: Topbar → Hero → KPI → Sources → Tabs → Dock.
- Tab list theo ARIA tabs pattern; dock có `role="complementary"` + `aria-label="Copilot"`.
- Hit target ≥ 36px desktop, ≥ 44px mobile.
- Không layout shift khi số cập nhật (`tabular-nums`, kích thước cố định).
- Không thư viện JS ngoài; tổng JS < 40KB, CSS < 30KB (chưa nén).
- Không `console.error` khi chạy bình thường; xử lý `AbortController` cho fetch khi tab ẩn.

---

## 12. Kế hoạch triển khai (mỗi Phase = 1 lượt làm việc với Antigravity)

### Phase 1 — Shell tĩnh + design system (chưa đụng backend)
**Prompt gợi ý:**
> Đọc `UI_REDESIGN_SPEC.md`, mục 0–6, 9, 11. Thực hiện **chỉ Phase 1**: tách dashboard ra file tĩnh theo mục 9, dựng tokens, layout, topbar, Incident Hero + Stepper, KPI, Source cards, Lineage SVG, Squad/Guardrails, Tabs, Copilot dock (lazy iframe, resize, expand, phím tắt C/Esc). Dữ liệu lấy từ `mock-state.json` theo schema mục 7.1. Cập nhật `server.py` để phục vụ file tĩnh và `GET /`. Không sửa `ai/`, `data/`, `ui.py`. Chạy `uvicorn main:app` để kiểm tra.

**Acceptance criteria**
- [ ] Đẹp và đúng spec ở 1440, 1280, 768, 390 px; không có thanh cuộn ngang ở body.
- [ ] Đổi `mock-state.json` sang từng trạng thái ở 6.2 → Hero + Stepper hiển thị đúng (làm 1 nút debug ẩn `?debug=1` để chuyển nhanh giữa các status).
- [ ] Không còn emoji làm icon, không glow/gradient, chỉ 3 giá trị radius.
- [ ] Iframe `/chat` **không** load cho tới khi mở dock lần đầu.
- [ ] Điều hướng bằng bàn phím hoạt động; `prefers-reduced-motion` tắt animation.

### Phase 2 — Dữ liệu thật
**Prompt gợi ý:**
> Thực hiện **chỉ Phase 2** (mục 7). Tạo `web/state.py`, `web/backend/ui_api.py` (`GET /ui/state`, `POST /ui/dq/run`), gắn hook `set_state(...)` trong `ui.py` theo bảng 7.3 (chỉ thêm dòng gọi, không đổi logic). Frontend chuyển từ mock sang `fetch('/ui/state')` + polling theo 7.4. Xử lý loading/error/empty theo 6.9.

**Acceptance criteria**
- [ ] Số trên dashboard khớp `GET /api/warehouse/summary` và truy vấn DuckDB trực tiếp.
- [ ] Chạy trọn luồng trong chat (điều tra → duyệt → vá → nghiệm thu) và Hero/Stepper đổi theo, trễ ≤ 4s.
- [ ] Bấm Refresh **không** reload iframe, không tạo thêm incident/notification.
- [ ] Tắt server 10s rồi bật lại: banner mất kết nối hiện rồi tự biến mất, không cần F5.
- [ ] Chạy được ở chế độ OFFLINE (không có `DRA_API_KEY`).
- [ ] `python -m compileall web` không lỗi.

### Phase 3 — Chat polish
**Prompt gợi ý:**
> Thực hiện **chỉ Phase 3** (mục 8). Tạo `public/theme.json`, `public/copilot.css`, avatar, cập nhật `.chainlit/config.toml`, rút gọn `welcome_message()` và bỏ bảng raw-data khỏi chat theo 8.4, thêm dedupe notification theo 8.6.

**Acceptance criteria**
- [ ] Panel chat rộng 400px: welcome không có thanh cuộn ngang; bảng trong báo cáo cuộn trong khung của nó.
- [ ] Nút gửi và nút chính cùng màu accent với dashboard; không còn hồng.
- [ ] Tin nhắn Maker / Checker phân biệt bằng viền/avatar.
- [ ] Reload dashboard nhiều lần chỉ bắn 1 notification cho cùng `incident_id` trong TTL.

### Phase 4 — Hoàn thiện
Skeleton loading, empty states, toast, tooltip, kiểm tra contrast, dọn CSS thừa, cập nhật `web/frontend/chainlit.md` cho khớp, chụp screenshot cho README/slide demo.

---

## 13. Không làm

- Không thêm framework/build tool; không CDN JS.
- Không hardcode số liệu trong HTML/JS (ngoài `mock-state.json` dùng cho Phase 1 / debug).
- Không đổi tên/route endpoint hiện có; không sửa logic `ai/` hoặc `data/`.
- Không tạo route `/ui/*` có khả năng ghi dữ liệu nghiệp vụ hoặc bypass bước duyệt.
- Không dùng gradient, glow, `translateY` hover, emoji làm icon trong dashboard.
- Không thêm chip/metric "cho đẹp" mà không có nguồn dữ liệu thật (ví dụ SLA %, "Ready 24/7").
- Không đọc, in, hay commit `.env`.
