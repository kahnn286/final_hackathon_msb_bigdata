"""
web/frontend/dashboard.py — DataOps Console (phục vụ static index.html)
======================================================================
"""

from __future__ import annotations

from pathlib import Path
from fastapi.responses import FileResponse, HTMLResponse

import config

STATIC_DIR = config.PROJECT_ROOT / "web" / "frontend" / "static" / "dashboard"
INDEX_HTML = STATIC_DIR / "index.html"


def get_dashboard_response() -> FileResponse:
    """Trả về FileResponse index.html kèm header no-cache."""
    return FileResponse(
        path=str(INDEX_HTML),
        media_type="text/html",
        headers={"Cache-Control": "no-cache"},
    )


def get_dashboard_html() -> str:
    """Tương thích ngược: đọc nội dung file index.html."""
    try:
        return INDEX_HTML.read_text(encoding="utf-8")
    except Exception:
        return "<!DOCTYPE html><html><body><h1>Dashboard loading...</h1></body></html>"


__all__ = ["STATIC_DIR", "INDEX_HTML", "get_dashboard_response", "get_dashboard_html"]
