"""
web/notifications.py — Hệ thống Notification đa kênh (Web, Email, Zalo Bot)
==========================================================================

Quản lý việc gửi cảnh báo và yêu cầu phê duyệt (Human-in-the-loop) đến kỹ sư điều hành:
  1. Web UI Notification (banner / callout)
  2. Email Notification (SMTP HTML/Text qua standard library)
  3. Zalo Bot Notification (Zalo Webhook / Zalo OA API)

Thiết kế an toàn:
- Nếu chưa cấu hình Token Zalo hoặc SMTP, hệ thống tự động chuyển sang chế độ Dry-Run
  (ghi log giả lập rõ ràng trên console) mà KHÔNG làm gián đoạn hay gây lỗi app.
"""

from __future__ import annotations

import json
import logging
import smtplib
import urllib.request
import urllib.error
from datetime import datetime, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Any, Dict, List, Optional

import config

logger = logging.getLogger("dra.notifications")


class EmailNotifier:
    """Gửi email cảnh báo qua SMTP."""

    def __init__(self) -> None:
        self.host = config.SMTP_HOST
        self.port = config.SMTP_PORT
        self.user = config.SMTP_USER
        self.password = config.SMTP_PASSWORD
        self.use_tls = config.SMTP_USE_TLS
        self.sender = config.SMTP_FROM
        self.recipient = config.NOTIFICATION_EMAIL
        self.is_configured = bool(self.host and self.recipient)

    def send_incident_alert(
        self,
        incident_id: str,
        incident_type: str,
        target_table: str,
        source_system: str,
        severity: str,
        description: str,
        action_url: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Gửi email thông báo phát hiện sự cố dữ liệu."""
        target_url = action_url or config.PUBLIC_UI_URL
        subject = f"[DRA ALERT - {severity.upper()}] Sự cố {incident_type} trên {target_table} ({incident_id})"
        
        text_body = f"""=====================================================
DATA RELIABILITY AGENT — CẢNH BÁO SỰ CỐ DỮ LIỆU
=====================================================
Mã sự cố: {incident_id}
Mức độ: {severity.upper()}
Loại sự cố: {incident_type}
Bảng dữ liệu: {target_table}
Nguồn phát sinh: {source_system}
Thời gian: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}

Mô tả:
{description}

👉 Truy cập hệ thống để theo dõi hoặc phê duyệt khắc phục:
{target_url}
"""

        html_body = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
  body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; background-color: #0f172a; color: #f8fafc; padding: 24px; }}
  .card {{ background-color: #1e293b; border-radius: 12px; padding: 24px; max-width: 600px; margin: 0 auto; border: 1px solid #334155; }}
  .badge {{ display: inline-block; padding: 4px 12px; border-radius: 9999px; font-weight: bold; font-size: 12px; text-transform: uppercase; }}
  .badge-CRITICAL, .badge-HIGH {{ background-color: #ef4444; color: #ffffff; }}
  .badge-MEDIUM {{ background-color: #f59e0b; color: #ffffff; }}
  .badge-LOW {{ background-color: #10b981; color: #ffffff; }}
  .field {{ margin-bottom: 12px; }}
  .field-label {{ color: #94a3b8; font-size: 13px; font-weight: 500; }}
  .field-value {{ color: #f8fafc; font-size: 15px; font-weight: 600; margin-top: 2px; }}
  .button {{ display: inline-block; background-color: #3b82f6; color: #ffffff; text-decoration: none; padding: 12px 24px; border-radius: 8px; font-weight: bold; margin-top: 18px; }}
</style>
</head>
<body>
  <div class="card">
    <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px;">
      <h2 style="margin: 0; color: #38bdf8; font-size: 20px;">🛡️ Data Reliability Squad Alert</h2>
      <span class="badge badge-{severity.upper()}">{severity.upper()}</span>
    </div>
    <div class="field">
      <div class="field-label">Mã sự cố</div>
      <div class="field-value"><code>{incident_id}</code></div>
    </div>
    <div class="field">
      <div class="field-label">Bảng mục tiêu & Nguồn</div>
      <div class="field-value">{target_table} (Nguồn: {source_system})</div>
    </div>
    <div class="field">
      <div class="field-label">Chi tiết sự cố</div>
      <div class="field-value" style="font-weight: normal; color: #cbd5e1; background: #0f172a; padding: 12px; border-radius: 6px; font-size: 13px;">{description}</div>
    </div>
    <div style="text-align: center;">
      <a href="{target_url}" class="button">Truy Cập Web UI Để Xem & Duyệt</a>
    </div>
  </div>
</body>
</html>"""

        return self._dispatch(subject, text_body, html_body)

    def _dispatch(self, subject: str, text: str, html: str) -> Dict[str, Any]:
        if not self.is_configured:
            logger.info(
                f"[EMAIL MOCK] (Chưa cấu hình SMTP) -> Gửi tới {self.recipient}: {subject}"
            )
            return {"ok": True, "mode": "mock", "recipient": self.recipient, "subject": subject}

        try:
            msg = MIMEMultipart("alternative")
            msg["Subject"] = subject
            msg["From"] = self.sender
            msg["To"] = self.recipient
            msg.attach(MIMEText(text, "plain", "utf-8"))
            msg.attach(MIMEText(html, "html", "utf-8"))

            with smtplib.SMTP(self.host, self.port, timeout=10) as server:
                if self.use_tls:
                    server.starttls()
                if self.user and self.password:
                    server.login(self.user, self.password)
                server.sendmail(self.sender, [self.recipient], msg.as_string())

            logger.info(f"[EMAIL SENT] Đã gửi thành công tới {self.recipient}")
            return {"ok": True, "mode": "live", "recipient": self.recipient}
        except Exception as exc:
            logger.error(f"[EMAIL ERROR] Không thể gửi email: {exc}")
            return {"ok": False, "error": str(exc), "recipient": self.recipient}


class ZaloBotNotifier:
    """Gửi cảnh báo và yêu cầu phê duyệt tới Zalo Bot / Zalo OA."""

    def __init__(self) -> None:
        self.webhook_url = config.ZALO_WEBHOOK_URL
        self.oa_token = config.ZALO_OA_TOKEN
        self.user_id = config.ZALO_USER_ID
        self.is_configured = bool(self.webhook_url or (self.oa_token and self.user_id))

    def send_incident_card(
        self,
        incident_id: str,
        incident_type: str,
        target_table: str,
        source_system: str,
        severity: str,
        description: str,
        action_url: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Gửi thẻ thông báo Zalo dạng Card văn bản cấu trúc."""
        target_url = action_url or config.PUBLIC_UI_URL
        sev_icon = "🔴" if severity.upper() in ("CRITICAL", "HIGH") else ("🟡" if severity.upper() == "MEDIUM" else "🟢")
        
        message_text = (
            f"🚨 [DATA QUALITY ALERT] {sev_icon} {severity.upper()}\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"📌 Mã sự cố: {incident_id}\n"
            f"📂 Bảng: {target_table}\n"
            f"📡 Nguồn dữ liệu: {source_system}\n"
            f"⚠️ Phân loại: {incident_type}\n"
            f"📝 Mô tả: {description[:200]}\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"👉 Truy cập Web UI để duyệt kế hoạch vá:\n{target_url}"
        )

        return self._send_zalo(message_text, target_url)

    def _send_zalo(self, text: str, url: str) -> Dict[str, Any]:
        if not self.is_configured:
            logger.info(
                f"[ZALO BOT MOCK] (Chưa cấu hình Zalo Webhook/OA) -> Tin nhắn mô phỏng:\n{text}"
            )
            return {"ok": True, "mode": "mock", "message": text, "url": url}

        # 1. Gửi qua Webhook (nếu có cấu hình Webhook)
        if self.webhook_url:
            try:
                payload = json.dumps({"text": text, "url": url}).encode("utf-8")
                req = urllib.request.Request(
                    self.webhook_url,
                    data=payload,
                    headers={"Content-Type": "application/json"},
                )
                with urllib.request.urlopen(req, timeout=5) as resp:
                    status = resp.getcode()
                    return {"ok": status in (200, 201, 204), "mode": "webhook", "status": status}
            except Exception as exc:
                logger.error(f"[ZALO WEBHOOK ERROR] Lỗi gửi webhook: {exc}")
                return {"ok": False, "error": str(exc), "mode": "webhook"}

        # 2. Gửi qua Zalo OA OpenAPI (nếu có OA Token & User ID)
        if self.oa_token and self.user_id:
            try:
                endpoint = "https://openapi.zalo.me/v3.0/oa/message/cs"
                payload = json.dumps({
                    "recipient": {"user_id": self.user_id},
                    "message": {"text": text}
                }).encode("utf-8")
                req = urllib.request.Request(
                    endpoint,
                    data=payload,
                    headers={
                        "Content-Type": "application/json",
                        "access_token": self.oa_token,
                    },
                )
                with urllib.request.urlopen(req, timeout=5) as resp:
                    res_body = json.loads(resp.read().decode("utf-8"))
                    return {"ok": res_body.get("error") == 0, "mode": "oa", "response": res_body}
            except Exception as exc:
                logger.error(f"[ZALO OA ERROR] Lỗi gửi Zalo OA: {exc}")
                return {"ok": False, "error": str(exc), "mode": "oa"}

        return {"ok": False, "error": "No valid Zalo transport"}


class TelegramBotNotifier:
    """Gửi cảnh báo và yêu cầu phê duyệt tới Telegram Bot / Group."""

    def __init__(self) -> None:
        self.token = config.TELEGRAM_BOT_TOKEN
        self.chat_id = config.TELEGRAM_CHAT_ID or config.TELEGRAM_USER_ID
        self.is_configured = bool(self.token and self.chat_id)

    def send_incident_card(
        self,
        incident_id: str,
        incident_type: str,
        target_table: str,
        source_system: str,
        severity: str,
        description: str,
        action_url: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Gửi thẻ cảnh báo Telegram dạng HTML format."""
        target_url = action_url or config.PUBLIC_UI_URL
        sev_upper = severity.upper()
        sev_icon = "🔴" if sev_upper in ("CRITICAL", "HIGH") else ("🟡" if sev_upper == "MEDIUM" else "🟢")

        message_html = (
            f"🚨 <b>[DATA RELIABILITY ALERT]</b> {sev_icon} <b>{sev_upper}</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"📌 <b>Mã sự cố:</b> <code>{incident_id}</code>\n"
            f"📂 <b>Bảng:</b> <code>{target_table}</code>\n"
            f"📡 <b>Nguồn dữ liệu:</b> <code>{source_system}</code>\n"
            f"⚠️ <b>Phân loại:</b> {incident_type}\n"
            f"📝 <b>Mô tả:</b> {description[:250]}\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"👉 <a href='{target_url}'>Mở Web UI để duyệt kế hoạch vá</a>"
        )

        if not self.is_configured:
            logger.info(
                f"[TELEGRAM MOCK] (Chưa cấu hình Telegram Token/ChatID) -> Tin nhắn mô phỏng:\n{message_html}"
            )
            return {"ok": True, "mode": "mock", "message": message_html, "chat_id": self.chat_id}

        try:
            endpoint = f"https://api.telegram.org/bot{self.token}/sendMessage"
            payload = json.dumps({
                "chat_id": self.chat_id,
                "text": message_html,
                "parse_mode": "HTML",
                "disable_web_page_preview": False,
            }).encode("utf-8")

            req = urllib.request.Request(
                endpoint,
                data=payload,
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=8) as resp:
                res_body = json.loads(resp.read().decode("utf-8"))
                ok = bool(res_body.get("ok", False))
                return {
                    "ok": ok,
                    "mode": "telegram",
                    "chat_id": self.chat_id,
                    "response": res_body,
                }
        except Exception as exc:
            logger.error(f"[TELEGRAM ERROR] Lỗi gửi tin nhắn Telegram: {exc}")
            return {"ok": False, "error": str(exc), "mode": "telegram", "chat_id": self.chat_id}


import time

_sent_cache: Dict[str, float] = {}
_DEDUPE_TTL = 600  # 10 phút


class NotificationHub:
    """Trung tâm điều phối thông báo hợp nhất có cơ chế chống spam (dedupe)."""

    _email = EmailNotifier()
    _zalo = ZaloBotNotifier()
    _telegram = TelegramBotNotifier()

    @classmethod
    def notify_incident(
        cls,
        incident_id: str,
        incident_type: str,
        target_table: str,
        source_system: str,
        severity: str,
        description: str,
        action_url: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Bắn thông báo sự cố qua tất cả các kênh đã kết nối (tự dedupe trong 10 phút)."""
        now = time.time()
        last_sent = _sent_cache.get(incident_id, 0)
        if (now - last_sent) < _DEDUPE_TTL:
            logger.info(f"[NOTIFY DEDUPE] Bỏ qua gửi lặp lại cho incident {incident_id}")
            return {
                "deduped": True,
                "incident_id": incident_id,
                "message": "Đã gửi thông báo trước đó trong vòng 10 phút",
            }

        _sent_cache[incident_id] = now
        target_url = action_url or config.PUBLIC_UI_URL

        email_res = cls._email.send_incident_alert(
            incident_id=incident_id,
            incident_type=incident_type,
            target_table=target_table,
            source_system=source_system,
            severity=severity,
            description=description,
            action_url=target_url,
        )

        zalo_res = cls._zalo.send_incident_card(
            incident_id=incident_id,
            incident_type=incident_type,
            target_table=target_table,
            source_system=source_system,
            severity=severity,
            description=description,
            action_url=target_url,
        )

        telegram_res = cls._telegram.send_incident_card(
            incident_id=incident_id,
            incident_type=incident_type,
            target_table=target_table,
            source_system=source_system,
            severity=severity,
            description=description,
            action_url=target_url,
        )

        return {
            "deduped": False,
            "incident_id": incident_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "email": email_res,
            "zalo": zalo_res,
            "telegram": telegram_res,
        }


__all__ = ["EmailNotifier", "ZaloBotNotifier", "TelegramBotNotifier", "NotificationHub"]


