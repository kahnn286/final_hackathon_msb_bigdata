"""
web/state.py — State dùng chung giữa Chainlit (Copilot) và Dashboard
===================================================================

Chainlit và FastAPI chạy cùng 1 process nên dùng in-memory dict + lock:
- Không ghi vào DuckDB để tránh xung đột lock single-writer.
- Cung cấp hàm get_state() và set_state() an toàn đa luồng.
"""

from __future__ import annotations

import threading
from datetime import datetime, timezone
from typing import Any, Dict, Optional

_lock = threading.Lock()
_state: Dict[str, Any] = {
    "incident_id": "INC-2026-DQ01",
    "status": "WAITING_FOR_APPROVAL",  # IDLE | INVESTIGATING | WAITING_FOR_APPROVAL | EXECUTING | AUDITING | RESOLVED | REJECTED | FAILED
    "audit_verdict": None,             # None | "AUDIT_PASSED" | "AUDIT_FAILED"
    "maker": "idle",                   # idle | working | offline
    "checker": "idle",                 # idle | working | offline
    "updated_at": datetime.now(timezone.utc).isoformat(),
}


def set_state(**changes: Any) -> None:
    """Cập nhật các trường state."""
    with _lock:
        _state.update(changes)
        _state["updated_at"] = datetime.now(timezone.utc).isoformat()


def get_state() -> Dict[str, Any]:
    """Lấy bản sao state hiện tại."""
    with _lock:
        return dict(_state)


__all__ = ["set_state", "get_state"]
