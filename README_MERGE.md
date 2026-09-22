# 📋 DataOps Console & Copilot UI Redesign — Hướng Dẫn & Tổng Hợp Thay Đổi (Merge Guide)

Tài liệu này tổng hợp toàn bộ các file đã chỉnh sửa, các module mới được bổ sung, và kiến trúc hệ thống giao diện/API mới để các thành viên trong team dễ dàng review, hiểu luồng và thực hiện merge code vào nhánh chính.

---

## 🌟 1. Tổng quan các tính năng & cải tiến chính

1. **Kiến trúc Single Process (FastAPI + Chainlit cùng port 8000):**
   - Phục vụ **DataOps Console** tại `GET /` và `GET /dashboard`.
   - Mount **Copilot Chat (Chainlit)** tại `GET /chat` và nhúng dạng Dock/Drawer bên phải.
2. **Số liệu thật 100% (No Hardcode):**
   - API `GET /ui/state` truy vấn trực tiếp từ DuckDB và runtime state của Maker/Checker.
   - Hỗ trợ endpoint `POST /ui/dq/run` để kích hoạt kiểm tra chất lượng dữ liệu.
3. **Trung tâm Thông báo Đa kênh & Cảnh báo (Notification Hub & Center):**
   - **Quả chuông 🔔 ở Topbar:** Hiển thị badge số lượng cảnh báo, mở Popover xem nhanh sự cố, kênh bắn tin (Email, Zalo) và shortcut mở Copilot.
   - **Tab "Sự cố & Cảnh báo":** Bảng tra cứu lịch sử sự cố, blast radius và trạng thái xử lý.
   - **Multi-channel Notifications (`web/notifications.py`):** Bắn alert qua Web, SMTP Email và Zalo Bot / Webhook.
4. **Trực quan hóa Lineage & Đội Maker · Checker:**
   - Sơ đồ tương tác SVG: *Nguồn Upstream → fact_orders → DQ Sentry → Quarantine → Marts*.
   - Bảng giám sát Agent & Guardrails: Khóa ghi dữ liệu, Cross-model check, kiểm định Python.
5. **Tối ưu Responsive toàn diện (Desktop / Tablet / Mobile):**
   - Sử dụng **CSS Container Queries (`@container`)** giúp dashboard tự co giãn khi mở/đóng Copilot Dock.
   - Trên Tablet/Mobile (< 1280px), Copilot Dock chuyển thành Drawer trượt với nền mờ (Backdrop).

---

## 📁 2. Danh mục chi tiết các File trong Project

### 🔄 A. Các File Chỉnh Sửa (Modified Files)

| Đường dẫn File | Loại | Tóm tắt thay đổi |
| :--- | :--- | :--- |
| `config.py` | Backend / Config | Bổ sung các biến cấu hình cho Static directory, Chainlit paths, Notification (Email, Zalo, Webhook), và UI settings. |
| `.env.example` | Config Template | Cập nhật các biến môi trường mẫu cho Email SMTP, Zalo OA/Webhook, API keys. |
| `web/server.py` | FastAPI App | Tích hợp mount static `/static/dashboard`, khai báo router `ui_router` (`/ui/state`, `/ui/dq/run`), và cấu hình route cho dashboard. |
| `web/frontend/ui.py` | Chainlit App | Sửa lỗi truy cập `severity`, tích hợp bắn thông báo qua `NotificationHub`, đồng bộ trạng thái runtime giữa Chainlit session và Dashboard. |
| `web/frontend/rendering.py` | UI Rendering | Chuẩn hóa format tin nhắn Copilot, loại bỏ bảng 4 cột gây vỡ khung chat, thêm thanh tóm tắt notification bar. |

---

### 🆕 B. Các File Thêm Mới (Untracked / New Files)

#### 1. Backend & State Management (`web/`)
- [`web/backend/ui_api.py`](file:///d:/Hackathon/Fix_issue/hackathon/web/backend/ui_api.py): Endpoint `GET /ui/state` (tổng hợp DuckDB rows, vi phạm DQ, trạng thái nguồn, KPIs, lineage, activity logs) và `POST /ui/dq/run`.
- [`web/state.py`](file:///d:/Hackathon/Fix_issue/hackathon/web/state.py): Module quản lý trạng thái chia sẻ (Shared Runtime State) giữa Chainlit session và Dashboard (trạng thái: `IDLE`, `INVESTIGATING`, `WAITING_FOR_APPROVAL`, `EXECUTING`, `AUDITING`, `RESOLVED`, `REJECTED`).
- [`web/notifications.py`](file:///d:/Hackathon/Fix_issue/hackathon/web/notifications.py): `NotificationHub` xử lý gửi thông báo đa kênh (Email SMTP, Zalo Webhook/OA, Web in-app).
- [`web/frontend/dashboard.py`](file:///d:/Hackathon/Fix_issue/hackathon/web/frontend/dashboard.py): Helper phục vụ static file `index.html` của DataOps Console.
- [`web/frontend/components.py`](file:///d:/Hackathon/Fix_issue/hackathon/web/frontend/components.py): Các helper rendering card/badge cho giao diện.

#### 2. Frontend Console tĩnh (`web/frontend/static/dashboard/`)
- [`index.html`](file:///d:/Hackathon/Fix_issue/hackathon/web/frontend/static/dashboard/index.html): Cấu trúc DOM chính của Console: Topbar, Incident Hero, KPI strip, Sources, Lineage, Squad/Guardrails, Data Tabs (4 tabs), và Copilot Dock kèm Backdrop.
- [`icons.svg`](file:///d:/Hackathon/Fix_issue/hackathon/web/frontend/static/dashboard/icons.svg): Bộ biểu tượng SVG vector chuẩn hóa (Shield, Bell, Database, Branch, Lock, Play, Refresh...).
- **Thư mục Styles (`styles/`):**
  - [`tokens.css`](file:///d:/Hackathon/Fix_issue/hackathon/web/frontend/static/dashboard/styles/tokens.css): Hệ thống Design Tokens (Màu HSL/Hex, Khoảng cách `--s1`→`--s6`, Bo góc, Typography).
  - [`base.css`](file:///d:/Hackathon/Fix_issue/hackathon/web/frontend/static/dashboard/styles/base.css): Reset CSS, typography helpers, status pills, LED pulse dots.
  - [`components.css`](file:///d:/Hackathon/Fix_issue/hackathon/web/frontend/static/dashboard/styles/components.css): Toàn bộ CSS component, Notification Dropdown, Stepper, Lineage, Data Tables, Drawer, và CSS Container Queries + Media Queries.
- **Thư mục Javascript ES Modules (`js/`):**
  - [`main.js`](file:///d:/Hackathon/Fix_issue/hackathon/web/frontend/static/dashboard/js/main.js): Entry point, khởi tạo tabs, polling dữ liệu realtime (mỗi 4s), xử lý dropdown thông báo.
  - [`render.js`](file:///d:/Hackathon/Fix_issue/hackathon/web/frontend/static/dashboard/js/render.js): Hàm render thuần DOM: Topbar, Notifications Dropdown, Hero banner, Stepper 6 bước, KPIs, Sources, Squad & Guardrails, Tables, Incidents tab, DQ tests, Activity logs.
  - [`api.js`](file:///d:/Hackathon/Fix_issue/hackathon/web/frontend/static/dashboard/js/api.js): Giao tiếp API `fetchState()` và `runDqChecks()`.
  - [`copilot.js`](file:///d:/Hackathon/Fix_issue/hackathon/web/frontend/static/dashboard/js/copilot.js): Quản lý Copilot dock/drawer (mở/đóng, lazy load iframe, resize, backdrop, phím tắt `C` và `Esc`).
  - [`lineage.js`](file:///d:/Hackathon/Fix_issue/hackathon/web/frontend/static/dashboard/js/lineage.js): Render SVG tương tác cho sơ đồ Data Lineage & Blast Radius.
  - [`format.js`](file:///d:/Hackathon/Fix_issue/hackathon/web/frontend/static/dashboard/js/format.js): Helper format số liệu, thời gian tương đối (`vừa xong`, `5 phút trước`), escape HTML an toàn.

#### 3. Tùy biến Theme Chainlit (`public/`)
- [`public/theme.json`](file:///d:/Hackathon/Fix_issue/hackathon/public/theme.json): Cấu hình palette màu tối đồng bộ với Dashboard.
- [`public/copilot.css`](file:///d:/Hackathon/Fix_issue/hackathon/public/copilot.css): Custom CSS cho iframe Chainlit (ẩn các thành phần thừa, font Plus Jakarta Sans).
- `public/avatars/`: Avatar cho Maker (`data_sre_agent.png`), Checker (`data_auditor.png`), và System (`system.png`).

#### 4. Tài liệu kỹ thuật & Specs
- [`UI_REDESIGN_SPEC.md`](file:///d:/Hackathon/Fix_issue/hackathon/UI_REDESIGN_SPEC.md): Toàn bộ đặc tả kỹ thuật thiết kế UI/UX và ràng buộc kiến trúc.
- `docker-compose.yml`: File cấu hình container môi trường chạy nếu cần đóng gói Docker.

---

## 🚀 3. Hướng Dẫn Chạy & Kiểm Thử (Verification Guide)

### Khởi động ứng dụng:
```bash
# Cài đặt dependency (nếu chưa)
pip install -r requirements.txt

# Chạy ứng dụng duy nhất
python main.py
# Hoặc:
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

### Truy cập các trang:
1. **DataOps Console:** `http://localhost:8000/` hoặc `http://localhost:8000/dashboard`
2. **Copilot Chat (Độc lập):** `http://localhost:8000/chat`
3. **Swagger API Docs:** `http://localhost:8000/docs`
4. **Health Check:** `http://localhost:8000/health`
5. **UI State JSON:** `http://localhost:8000/ui/state`

---

## 🔒 4. Lưu ý khi Merge Code

- **Không có xung đột với AI Core:** Toàn bộ logic lõi của 2 Agent (`ai/agent.py`, `ai/auditor.py`, `ai/tools.py`) và Data Layer (`data/`) **hoàn toàn được giữ nguyên**, UI chỉ đóng vai trò đọc dữ liệu và điều khiển.
- **Không có Build Step:** Không cần cài đặt Node.js/npm hay chạy Vite. Toàn bộ frontend là Vanilla HTML/CSS/JS Native Modules.
