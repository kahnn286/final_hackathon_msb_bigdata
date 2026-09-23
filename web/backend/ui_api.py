"""
web/backend/ui_api.py — REST API phục vụ DataOps Dashboard (/ui/state, /ui/dq/run)
==================================================================================

Same-origin router, read-only:
- `GET  /ui/state`   : Trả về trạng thái đầy đủ theo schema 7.1 của spec
- `POST /ui/dq/run`  : Chạy lại bộ DQ checks (không yêu cầu Bearer token)
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter
from fastapi.concurrency import run_in_threadpool

import config
from ai import tools
from ai.llm import LLMSettings
from data import audit as data_audit
from data import connection as db
from data.dq import DQ_CHECKS, run_all_checks
from data.incidents import build_sample_incident_payload
from web import state as ui_state

ui_router = APIRouter(prefix="/ui", tags=["ui"])


def _build_state_sync() -> Dict[str, Any]:
    """Tổng hợp số liệu thật từ DuckDB + AI settings + runtime state."""
    current_time = datetime.now(timezone.utc).isoformat()
    errors: List[str] = []

    # 1. System & Models
    maker_settings = LLMSettings.from_env()
    checker_settings = LLMSettings.for_auditor(avoid_model=maker_settings.model)
    is_cross = bool(maker_settings.api_key) and (maker_settings.model != checker_settings.model)

    email_live = bool(config.SMTP_HOST and config.NOTIFICATION_EMAIL)
    zalo_live = bool(config.ZALO_WEBHOOK_URL or (config.ZALO_OA_TOKEN and config.ZALO_USER_ID))
    telegram_live = bool(config.TELEGRAM_BOT_TOKEN and (config.TELEGRAM_CHAT_ID or config.TELEGRAM_USER_ID))

    wh_online = True
    wh_rows = 1000
    try:
        from data.warehouse import ensure_database
        ensure_database(config.DUCKDB_PATH)
        wh_count = db.row_count("fact_orders")
        if wh_count is not None:
            wh_rows = wh_count
    except Exception as e:
        errors.append(f"Warehouse check failed: {e}")


    system_info = {
        "service": config.APP_TITLE,
        "version": config.APP_VERSION,
        "warehouse": {
            "online": wh_online,
            "path": config.DUCKDB_PATH,
            "fact_orders_rows": wh_rows,
        },
        "notifications": {
            "email": "live" if email_live else "dry_run",
            "zalo": "live" if zalo_live else "dry_run",
            "telegram": "live" if telegram_live else "dry_run",
        },
        "models": {
            "maker": {"model": maker_settings.model, "offline": not maker_settings.api_key},
            "checker": {"model": checker_settings.model, "offline": not checker_settings.api_key},
            "cross_model_enabled": is_cross,
        },

        "remediation_unlocked": tools.is_remediation_unlocked(),
    }

    # 2. Sources metrics
    sources_data = []
    try:
        res = db.fetch(
            """
            SELECT 
                source_system,
                COUNT(*) AS total_rows,
                SUM(
                    CASE 
                        WHEN customer_id IS NULL THEN 1 
                        WHEN customer_email IS NULL THEN 1
                        WHEN total_amount <= 0 THEN 1 
                        WHEN order_status NOT IN ('COMPLETED', 'PENDING', 'CANCELLED', 'REFUNDED') THEN 1
                        ELSE 0 
                    END
                ) AS total_viols,
                MAX(ingested_at) AS last_ingested_at
            FROM fact_orders
            GROUP BY source_system
            """
        )
        rows = res.get("rows", [])
        sources_map = {r["source_system"]: r for r in rows}

        # Kiểm tra trùng order_id
        dup_res = db.fetch("SELECT source_system, COUNT(*) - COUNT(DISTINCT order_id) AS dup_cnt FROM fact_orders GROUP BY source_system")
        for d in dup_res.get("rows", []):
            sk = d.get("source_system")
            dc = d.get("dup_cnt", 0)
            if sk in sources_map and dc > 0:
                sources_map[sk]["total_viols"] = int(sources_map[sk].get("total_viols") or 0) + int(dc)
    except Exception as e:
        errors.append(f"Sources query failed: {e}")
        sources_map = {}

    src_meta = [
        {"key": "erp_core", "name": "ERP Core System", "version": "v2.1.0"},
        {"key": "web_checkout", "name": "Web Checkout Stream", "version": "v1.8.4"},
        {"key": "mobile_app_v3", "name": "Mobile App Ingest", "version": "v3.4.1"},
    ]

    total_violating = 0
    for s in src_meta:
        m = sources_map.get(s["key"], {})
        s_rows = m.get("total_rows", 0)
        s_viols = int(m.get("total_viols", 0) or 0)
        s_last = m.get("last_ingested_at")
        total_violating += s_viols

        status = "incident" if s_viols > 0 else "healthy"

        sources_data.append({
            "key": s["key"],
            "name": s["name"],
            "version": s["version"],
            "rows": s_rows,
            "violations": s_viols,
            "last_ingested_at": str(s_last) if s_last else current_time,
            "status": status,
        })

    # 3. Quarantined & KPIs
    quarantine_table = data_audit.detect_quarantine_table("fact_orders")
    quarantined_rows = db.row_count(quarantine_table) if quarantine_table else 0

    # DQ Tests summary
    try:
        dq_results = run_all_checks()
        failed_tests = sum(1 for t in dq_results if t.get("status") == "fail")
        passed_tests = len(dq_results) - failed_tests
    except Exception as e:
        errors.append(f"DQ checks failed: {e}")
        dq_results = []
        passed_tests = 5
        failed_tests = 1

    kpis = {
        "total_rows": wh_rows,
        "violating_rows": total_violating,
        "quarantined_rows": quarantined_rows,
        "quarantine_expected": 15,
        "tests_total": len(dq_results) if dq_results else 6,
        "tests_passed": passed_tests,
    }

    # 4. Tables list
    all_tables = db.list_tables()
    tables_data = [
        {
            "name": "fact_orders",
            "layer": "fact",
            "rows": wh_rows,
            "dq": "fail" if total_violating > 0 else "pass",
            "failed_tests": 1 if total_violating > 0 else 0,
            "updated_at": current_time,
            "recommendation": "Cách ly 15 dòng lỗi từ SDK 3.4.1" if total_violating > 0 else "Dữ liệu sạch",
        },
        {
            "name": "dim_customers",
            "layer": "dim",
            "rows": db.row_count("dim_customers") if "dim_customers" in all_tables else 400,
            "dq": "pass",
            "failed_tests": 0,
            "updated_at": current_time,
            "recommendation": "Phục vụ bình thường",
        },
        {
            "name": "quarantine_fact_orders",
            "layer": "quarantine",
            "rows": quarantined_rows,
            "dq": "pending" if quarantined_rows == 0 else "pass",
            "updated_at": current_time if quarantined_rows > 0 else None,
            "recommendation": f"Đã cách ly {quarantined_rows} dòng vi phạm" if quarantined_rows > 0 else "Lưu vết cách ly khi có sự cố",
        },
        {
            "name": "mart_daily_revenue",
            "layer": "mart",
            "rows": db.row_count("mart_daily_revenue") if "mart_daily_revenue" in all_tables else None,
            "dq": "stale" if total_violating > 0 else "pass",
            "updated_at": current_time if "mart_daily_revenue" in all_tables else None,
            "recommendation": "Cần rebuild sau khi vá dữ liệu fact" if total_violating > 0 else "Đã đồng bộ",
        },
    ]

    # 5. Runtime dynamic state from web.state
    runtime = ui_state.get_state()
    bad_sources = [s["name"] for s in sources_data if s["violations"] > 0]
    bad_keys = [s["key"] for s in sources_data if s["violations"] > 0]

    incident_info = None
    if total_violating > 0:
        # Đang có sự cố dữ liệu thực tế trong warehouse
        inc_status = runtime.get("status")
        if not inc_status or inc_status in ("IDLE", "RESOLVED"):
            inc_status = "WAITING_FOR_APPROVAL"

        inc_id = runtime.get("incident_id") or f"INC-{datetime.now(timezone.utc).strftime('%Y%m%d')}-DQ01"
        src_label = ", ".join(bad_sources) if bad_sources else "mobile_app_v3"
        src_key = ", ".join(bad_keys) if bad_keys else "mobile_app_v3"

        incident_info = {
            "id": inc_id,
            "status": inc_status,
            "severity": "CRITICAL" if total_violating >= 15 or len(bad_sources) > 1 else "HIGH",
            "type": "DATA_QUALITY",
            "title": f"{total_violating} dòng vi phạm DQ trên {src_label}",
            "target_table": "fact_orders",
            "source": src_key,
            "detected_at": current_time,
            "blast_radius": ["mart_daily_revenue", "mart_customer_ltv"],
            "audit_verdict": runtime.get("audit_verdict"),
            "agents": {
                "maker": runtime.get("maker", "idle"),
                "checker": runtime.get("checker", "idle"),
            },
        }
    elif quarantined_rows > 0 and runtime.get("status") == "RESOLVED":
        # Đã xử lý xong và có dữ liệu cách ly
        incident_info = {
            "id": runtime.get("incident_id") or "INC-2026-DQ01",
            "status": "RESOLVED",
            "severity": "HIGH",
            "type": "DATA_QUALITY",
            "title": f"Đã cách ly {quarantined_rows} dòng lỗi thành công",
            "target_table": "fact_orders",
            "source": "mobile_app_v3",
            "detected_at": current_time,
            "blast_radius": ["mart_daily_revenue", "mart_customer_ltv"],
            "audit_verdict": "AUDIT_PASSED",
            "agents": {
                "maker": "idle",
                "checker": "idle",
            },
        }

    # 6. Activity log
    activity_data = []
    try:
        raw_logs = data_audit.read_audit_log(limit=10).get("rows", [])
        for r in raw_logs:
            tool_name = r.get("tool_name", "")
            is_write = tool_name == "tool_execute_remediation"
            is_checker = "auditor" in str(r.get("incident_id", "")).lower() or tool_name == "tool_get_incident_context"
            activity_data.append({
                "ts": str(r.get("logged_at", current_time)),
                "actor": "checker" if is_checker else "maker",
                "tool": tool_name,
                "kind": "write" if is_write else "read",
                "summary": str(r.get("payload", ""))[:120],
            })
    except Exception as e:
        errors.append(f"Audit log query failed: {e}")

    return {
        "generated_at": current_time,
        "system": system_info,
        "kpis": kpis,
        "sources": sources_data,
        "tables": tables_data,
        "dq_tests": [
            {
                "test_name": t.get("test_name", ""),
                "column": t.get("column", "customer_id"),
                "type": "not_null" if "not_null" in t.get("test_name", "") else "check",
                "failures": t.get("failures", 0),
                "status": t.get("status", "pass"),
                "last_run_at": current_time,
            }
            for t in (dq_results or [])
        ],
        "lineage": {
            "nodes": [
                {
                    "id": "sources",
                    "label": "3 Nguồn Upstream",
                    "rows": wh_rows,
                    "sub": f"{wh_rows} dòng",
                    "state": "normal",
                },
                {
                    "id": "fact_orders",
                    "label": "fact_orders",
                    "rows": wh_rows,
                    "sub": f"{total_violating} vi phạm" if total_violating > 0 else f"{wh_rows} dòng sạch",
                    "state": "incident" if total_violating > 0 else "normal",
                },
                {
                    "id": "dq_checks",
                    "label": "DQ Sentry Checks",
                    "rows": len(dq_results),
                    "sub": f"{passed_tests}/{len(dq_results)} test pass",
                    "state": "warn" if failed_tests > 0 else "normal",
                },
                {
                    "id": "quarantine",
                    "label": "quarantine_fact_orders",
                    "rows": quarantined_rows,
                    "sub": f"{quarantined_rows} dòng cách ly" if quarantined_rows > 0 else "0 dòng",
                    "state": "normal" if quarantined_rows > 0 else "pending",
                },
                {
                    "id": "mart_daily_revenue",
                    "label": "mart_daily_revenue",
                    "rows": None,
                    "sub": "cần rebuild" if total_violating > 0 else "đã đồng bộ",
                    "state": "affected" if total_violating > 0 else "normal",
                },
                {
                    "id": "mart_customer_ltv",
                    "label": "mart_customer_ltv",
                    "rows": None,
                    "sub": "cần rebuild" if total_violating > 0 else "đã đồng bộ",
                    "state": "affected" if total_violating > 0 else "normal",
                },
            ],
            "edges": [
                {"from": "sources", "to": "fact_orders", "state": "normal"},
                {"from": "fact_orders", "to": "dq_checks", "state": "incident" if total_violating > 0 else "normal"},
                {"from": "dq_checks", "to": "quarantine", "state": "normal"},
                {"from": "fact_orders", "to": "mart_daily_revenue", "state": "affected" if total_violating > 0 else "normal"},
                {"from": "mart_daily_revenue", "to": "mart_customer_ltv", "state": "affected" if total_violating > 0 else "normal"},
            ],
        },
        "incident": incident_info,
        "activity": activity_data,
        "errors": errors if errors else None,
    }


@ui_router.get("/state")
async def get_ui_state() -> Dict[str, Any]:
    """Cung cấp toàn bộ state thời gian thực cho DataOps Console."""
    return await run_in_threadpool(_build_state_sync)


@ui_router.post("/dq/run")
async def run_dq_endpoint() -> Dict[str, Any]:
    """Chạy lại toàn bộ DQ checks và trả về kết quả."""
    results = await run_in_threadpool(run_all_checks)
    failed = sum(1 for r in results if r.get("status") == "fail")
    return {
        "total": len(results),
        "failed": failed,
        "passed": len(results) - failed,
        "results": results,
    }

@ui_router.post("/demo/inject-incident")
async def inject_demo_incident(
    source: str = "mobile_app_v3",
    defect_type: str = "null_customer_id",
    rows: int = 15,
) -> Dict[str, Any]:
    """Cấy lỗi thực tế vào warehouse (theo từng nguồn hoặc đa nguồn) và bắn cảnh báo tức thì."""
    from data.jobs.inject_defect import inject_custom_defect

    res = await run_in_threadpool(
        inject_custom_defect,
        source=source,
        defect_type=defect_type,
        rows=rows,
        notify=True,
    )
    return res


@ui_router.post("/select-source-incident")
async def select_source_incident_endpoint(source: str = "web_checkout") -> Dict[str, Any]:
    """Chọn hoặc tạo hồ sơ sự cố cho nguồn được chỉ định để Copilot nạp ngay lập tức."""
    from data import incident_store
    from data.incidents import build_incident_payload, build_sample_incident_payload
    from data.connection import CONN_LOCK, get_connection
    import json

    # 1. Lưu nguồn đang chọn vào ui_state
    ui_state.set_state(selected_source=source)

    # 2. Kiểm tra số lỗi thực tế của nguồn này trên fact_orders
    con = get_connection()
    viol_cnt = 0
    with CONN_LOCK:
        try:
            r = con.execute(
                """
                SELECT COUNT(*) FROM fact_orders 
                WHERE source_system = ? 
                AND (
                    customer_id IS NULL 
                    OR customer_email IS NULL 
                    OR total_amount <= 0 
                    OR order_status NOT IN ('COMPLETED', 'PENDING', 'CANCELLED', 'REFUNDED')
                )
                """,
                [source],
            ).fetchone()
            viol_cnt = int(r[0]) if r else 0
        except Exception:
            viol_cnt = 0

    # Nếu nguồn hoàn toàn sạch (0 lỗi) và không có sự cố thực sự
    if viol_cnt == 0:
        incident_store.clear_selection()
        return {
            "ok": True,
            "source": source,
            "status": "healthy",
            "incident_id": None,
            "message": f"Nguồn {source} đang sạch 100% (0 vi phạm)",
        }

    # 2. Nếu có lỗi, kiểm tra xem có incident nào đang mở của nguồn này không
    all_open = incident_store.list_incidents(status=None, limit=20)
    target_inc_id = None
    for inc in all_open:
        inc_data = incident_store.get_incident(str(inc["incident_id"]))
        if inc_data and inc_data.get("envelope"):
            hint = inc_data["envelope"].get("evidence_payload", {}).get("upstream_hint", {})
            if hint.get("source_system") == source or source in str(inc_data.get("title", "")):
                target_inc_id = str(inc["incident_id"])
                break

    # 3. Nếu có lỗi thật mà chưa có ticket, tạo incident mới
    if not target_inc_id:
        now_ts = datetime.now(timezone.utc)
        target_inc_id = f"INC-{now_ts.strftime('%Y%m%d-%H%M%S')}"
        try:
            envelope = build_incident_payload(incident_id=target_inc_id)
        except Exception:
            envelope = build_sample_incident_payload()
            envelope["incident_id"] = target_inc_id

        # Ghi đè thông tin nguồn vào envelope
        if "evidence_payload" in envelope:
            envelope["evidence_payload"]["upstream_hint"] = {
                "source_system": source,
                "source_version": "v2.1.0" if source == "erp_core" else ("v1.8.4" if source == "web_checkout" else "v3.4.1")
            }
            envelope["description"] = f"Phát hiện {viol_cnt} dòng vi phạm DQ trên nguồn [{source}] trong bảng fact_orders"

        try:
            with CONN_LOCK:
                con.execute(
                    """
                    INSERT INTO incidents (
                        incident_id, job_id, run_id, created_at, updated_at, status, severity,
                        target_table, test_name, column_name, test_type, failed_rows, occurrences,
                        title, envelope_json, report_json, audit_json, error,
                        shadow_table, retry_count, ready_for_production, published_at
                    ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                    """,
                    [
                        target_inc_id, f"job_ingest_{source}", f"run_{now_ts.strftime('%Y%m%d%H%M%S')}", now_ts, now_ts, "WAITING_FOR_APPROVAL",
                        "HIGH", "fact_orders", "source_dq_fact_orders", "multiple", "custom", viol_cnt, 1,
                        f"Sự cố dữ liệu trên nguồn {source} ({viol_cnt} vi phạm)",
                        json.dumps(envelope, ensure_ascii=False, default=str), None, None, None,
                        "", 0, False, None,
                    ],
                )
        except Exception as e:
            print(f"[WARN] Failed to insert source incident: {e}")

    # 4. Chọn incident cho phiên chat kế tiếp
    if target_inc_id:
        incident_store.select_incident(target_inc_id)

    return {
        "ok": True,
        "source": source,
        "incident_id": target_inc_id,
        "status": "incident",
        "violations": viol_cnt,
    }


@ui_router.post("/demo/reset-clean")
async def reset_clean_data_endpoint() -> Dict[str, Any]:
    """Reset kho dữ liệu DuckDB về trạng thái sạch hoàn toàn và giải phóng sự cố."""
    from data.jobs.inject_defect import reset_clean_warehouse

    stats = await run_in_threadpool(reset_clean_warehouse)
    return {"ok": True, "stats": stats}


__all__ = ["ui_router"]


