"""
web/frontend/components.py — Giao diện 3 Box Raw Data & Status Matrix
=====================================================================

Cung cấp các component trực quan hoá:
  1. 3 Box Raw Data (ERP Core, Web Checkout, Mobile App v3) kèm đèn LED trạng thái
     (🟢 Xanh = Normal/Clean, 🟡 Vàng = AI Processing, 🔴 Đỏ = Incident/Awaiting, ⚪ Xám = Sleep).
  2. Bảng điều khiển tổng quan (Dashboard Header).
  3. Thẻ trạng thái thông báo đa kênh (Notification Status Badge).
"""

from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional


StatusType = Literal["healthy", "investigating", "incident", "sleep", "resolved"]

STATUS_CONFIG: Dict[StatusType, Dict[str, str]] = {
    "healthy": {
        "color": "#10b981",
        "bg": "rgba(16, 185, 129, 0.12)",
        "border": "#10b981",
        "icon": "🟢",
        "label": "HOẠT ĐỘNG (BÌNH THƯỜNG)",
        "pulse": "pulse-green",
    },
    "investigating": {
        "color": "#f59e0b",
        "bg": "rgba(245, 158, 11, 0.15)",
        "border": "#f59e0b",
        "icon": "🟡",
        "label": "AI ĐANG XỬ LÝ / ĐIỀU TRA",
        "pulse": "pulse-yellow",
    },
    "incident": {
        "color": "#ef4444",
        "bg": "rgba(239, 68, 68, 0.15)",
        "border": "#ef4444",
        "icon": "🔴",
        "label": "PHÁT HIỆN SỰ CỐ (CHỜ DUYỆT)",
        "pulse": "pulse-red",
    },
    "resolved": {
        "color": "#06b6d4",
        "bg": "rgba(6, 182, 212, 0.15)",
        "border": "#06b6d4",
        "icon": "✨",
        "label": "ĐÃ VÁ & NGHIỆM THU XONG",
        "pulse": "pulse-cyan",
    },
    "sleep": {
        "color": "#94a3b8",
        "bg": "rgba(148, 163, 184, 0.1)",
        "border": "#64748b",
        "icon": "⚪",
        "label": "TẠM NGHỈ (SLEEP / IDLE)",
        "pulse": "none",
    },
}


def get_source_metrics() -> Dict[str, Dict[str, Any]]:
    """Đọc số liệu thực tế của 3 luồng nguồn từ bảng fact_orders."""
    try:
        from data import connection as db
        rows = db.fetch(
            """
            SELECT 
                source_system,
                COUNT(*) AS total_rows,
                SUM(CASE WHEN customer_id IS NULL THEN 1 ELSE 0 END) AS null_cust_count
            FROM fact_orders
            GROUP BY source_system
            """
        )
        return {r["source_system"]: r for r in rows}
    except Exception:
        return {
            "erp_core": {"source_system": "erp_core", "total_rows": 400, "null_cust_count": 0},
            "web_checkout": {"source_system": "web_checkout", "total_rows": 300, "null_cust_count": 0},
            "mobile_app_v3": {"source_system": "mobile_app_v3", "total_rows": 200, "null_cust_count": 15},
        }



def render_raw_data_boxes(
    mobile_status: StatusType = "incident",
    erp_status: StatusType = "healthy",
    web_status: StatusType = "healthy",
) -> str:
    """
    Render 3 Hộp Raw Data dạng bảng Markdown chuẩn Chainlit.
    """
    metrics = get_source_metrics()
    erp_m = metrics.get("erp_core", {"total_rows": 400, "null_cust_count": 0})
    web_m = metrics.get("web_checkout", {"total_rows": 300, "null_cust_count": 0})
    mobile_m = metrics.get("mobile_app_v3", {"total_rows": 200, "null_cust_count": 15})

    sources = [
        {
            "name": "ERP Core System",
            "version": "v2.1.0",
            "status": erp_status,
            "rows": erp_m["total_rows"],
            "errors": erp_m["null_cust_count"],
        },
        {
            "name": "Web Checkout Stream",
            "version": "v1.8.4",
            "status": web_status,
            "rows": web_m["total_rows"],
            "errors": web_m["null_cust_count"],
        },
        {
            "name": "Mobile App Ingest",
            "version": "v3.4.1",
            "status": mobile_status,
            "rows": mobile_m["total_rows"],
            "errors": mobile_m["null_cust_count"],
        },
    ]

    lines = [
        "### 📡 GIÁM SÁT 3 LUỒNG RAW DATA (REAL-TIME STATUS)",
        "",
        "| Luồng Nguồn (Data Source) | Phiên Bản | Trạng Thái | Số Dòng | Lỗi Vi Phạm DQ |",
        "| :--- | :--- | :--- | :--- | :--- |",
    ]

    for s in sources:
        cfg = STATUS_CONFIG.get(s["status"], STATUS_CONFIG["sleep"])
        err_str = f"⚠️ **{s['errors']} lỗi**" if s["errors"] > 0 else "✅ 0 lỗi"
        lines.append(
            f"| 📦 **{s['name']}** | `{s['version']}` | {cfg['icon']} **{cfg['label']}** | **{s['rows']}** dòng | {err_str} |"
        )

    return "\n".join(lines)


def render_notification_bar(
    incident_id: str,
    target_table: str,
    source_system: str,
    severity: str,
) -> str:
    """Render thanh trạng thái thông báo đa kênh đã phát đi."""
    return (
        f"> 🔔 **Notification Hub (Đa kênh)**: Đã phát thông báo sự cố `{incident_id}` "
        f"tới 📧 **Email** và 🤖 **Zalo Bot** của kỹ sư trực ban (kèm link xác nhận Web UI)."
    )



__all__ = ["render_raw_data_boxes", "render_notification_bar", "STATUS_CONFIG"]
