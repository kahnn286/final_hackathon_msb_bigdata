"""
_verify_merged.py — Kiểm tra tích hợp sau khi merge UI vào hackathon2
"""

import sys
import json

def test_config():
    import config
    print("[1/5] Checking config...")
    assert hasattr(config, "SMTP_HOST"), "Missing SMTP_HOST"
    assert hasattr(config, "ZALO_WEBHOOK_URL"), "Missing ZALO_WEBHOOK_URL"
    assert hasattr(config, "TELEGRAM_BOT_TOKEN"), "Missing TELEGRAM_BOT_TOKEN"
    assert hasattr(config, "PUBLIC_UI_URL"), "Missing PUBLIC_UI_URL"
    print(" -> Config OK")

def test_state_and_notifications():
    print("[2/5] Checking web.state and web.notifications...")
    from web import state as ui_state
    from web.notifications import NotificationHub

    ui_state.set_state(status="INVESTIGATING", maker="working")
    st = ui_state.get_state()
    assert st["status"] == "INVESTIGATING"
    assert st["maker"] == "working"

    notif = NotificationHub.notify_incident(
        incident_id="INC-TEST-001",
        incident_type="DATA_QUALITY",
        target_table="fact_orders",
        source_system="mobile_app_v3",
        severity="HIGH",
        description="Test verification notification",
    )
    assert notif["email"]["ok"] is True
    assert "telegram" in notif
    print(" -> State & Notifications OK")

def test_ui_api_state():
    print("[3/5] Checking ui_api state builder...")
    from web.backend.ui_api import _build_state_sync
    state = _build_state_sync()
    assert "system" in state, "Missing system in state"
    assert "kpis" in state, "Missing kpis in state"
    assert "sources" in state, "Missing sources in state"
    assert "tables" in state, "Missing tables in state"
    assert "dq_tests" in state, "Missing dq_tests in state"
    assert "lineage" in state, "Missing lineage in state"
    print(f" -> UI state generated: {len(state['tables'])} tables, {len(state['sources'])} sources, {len(state['dq_tests'])} tests.")

def test_fastapi_app():
    print("[4/5] Checking FastAPI app & routes...")
    from web.server import create_app
    app = create_app()
    routes = [r.path for r in app.routes]
    print(f" -> Total routes registered: {len(routes)}")
    assert "/" in routes, "Missing / route"
    assert "/dashboard" in routes, "Missing /dashboard route"
    assert "/ui/state" in routes, "Missing /ui/state route"
    assert "/ui/dq/run" in routes, "Missing /ui/dq/run route"
    assert "/health" in routes, "Missing /health route"
    assert "/lineage" in routes, "Missing /lineage route"
    assert "/query" in routes, "Missing /query route"
    assert "/pipeline" in routes, "Missing /pipeline route"
    print(" -> All core routes present OK")

def test_static_files():
    print("[5/5] Checking static dashboard files & Chainlit public theme...")
    from pathlib import Path
    import config

    dash_idx = config.PROJECT_ROOT / "web" / "frontend" / "static" / "dashboard" / "index.html"
    dash_svg = config.PROJECT_ROOT / "web" / "frontend" / "static" / "dashboard" / "icons.svg"
    dash_css = config.PROJECT_ROOT / "web" / "frontend" / "static" / "dashboard" / "styles" / "tokens.css"
    dash_js = config.PROJECT_ROOT / "web" / "frontend" / "static" / "dashboard" / "js" / "main.js"
    theme = config.PROJECT_ROOT / "public" / "theme.json"
    copilot_css = config.PROJECT_ROOT / "public" / "copilot.css"
    avatars = config.PROJECT_ROOT / "public" / "avatars" / "data_sre_agent.png"

    assert dash_idx.is_file(), f"Missing {dash_idx}"
    assert dash_svg.is_file(), f"Missing {dash_svg}"
    assert dash_css.is_file(), f"Missing {dash_css}"
    assert dash_js.is_file(), f"Missing {dash_js}"
    assert theme.is_file(), f"Missing {theme}"
    assert copilot_css.is_file(), f"Missing {copilot_css}"
    assert avatars.is_file(), f"Missing {avatars}"
    print(" -> All static, SVG, JS, CSS, and avatar assets verified OK")

if __name__ == "__main__":
    test_config()
    test_state_and_notifications()
    test_ui_api_state()
    test_fastapi_app()
    test_static_files()
    print("\n>>> ALL 5 INTEGRATION CHECKS PASSED SUCCESSFULLY! <<<")
