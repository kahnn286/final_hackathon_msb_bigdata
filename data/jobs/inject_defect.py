"""
Job: inject_defect — Bộ công cụ cấy lỗi chủ động phục vụ Demo & Test Data SRE
=============================================================================

Hỗ trợ cấy lỗi vào từng nguồn riêng lẻ hoặc nhiều nguồn cùng lúc:
  1. mobile_app_v3 : Lỗi NULL customer_id (SDK 3.4.1 đổi mapping)
  2. web_checkout  : Lỗi Amount âm / Invalid status
  3. erp_core      : Lỗi Duplicate order_id / Schema mismatch
  4. all           : Cấy lỗi đồng thời cả 3 nguồn (Multi-source failure)

Usage CLI:
    python -m data.jobs.inject_defect --source mobile_app_v3 --rows 15
    python -m data.jobs.inject_defect --source web_checkout --rows 10
    python -m data.jobs.inject_defect --source all
    python -m data.jobs.inject_defect --reset   # Trả warehouse về sạch
"""

from __future__ import annotations

import argparse
import random
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Dict, List

from data.connection import CONN_LOCK, get_connection, row_count, scalar
from data.warehouse import (
    BATCH_DATE,
    BATCH_TS,
    PAYMENT_METHODS,
    PRODUCT_SKUS,
    bootstrap,
)
from web.notifications import NotificationHub


def inject_custom_defect(
    source: str = "mobile_app_v3",
    defect_type: str = "null_customer_id",
    rows: int = 15,
    notify: bool = True,
) -> Dict[str, Any]:
    """
    Cấy lỗi dữ liệu thực tế vào DuckDB fact_orders theo từng nguồn hoặc đa nguồn.
    """
    con = get_connection()
    max_order_id = int(scalar("SELECT COALESCE(MAX(order_id), 100000) FROM fact_orders") or 100000)
    rng = random.Random()
    now_ts = datetime.now(timezone.utc)

    sources_to_inject = [source] if source != "all" else ["mobile_app_v3", "web_checkout", "erp_core"]
    injected_details: List[Dict[str, Any]] = []
    total_added = 0

    for src in sources_to_inject:
        payload: List[tuple[Any, ...]] = []
        src_rows = rows if source != "all" else max(5, rows // 3)

        for offset in range(src_rows):
            order_id = max_order_id + total_added + 1
            total_added += 1
            cust_no = rng.randint(1, 300)
            qty = rng.randint(1, 4)
            unit_price = Decimal(str(rng.choice([199000, 349000, 599000, 1290000])))

            # Mặc định sạch
            c_cust_id = f"CUST-{cust_no:05d}"
            c_email = f"khachhang{cust_no:05d}@example.com"
            c_amount = (unit_price * qty).quantize(Decimal("0.01"))
            c_status = "COMPLETED"
            c_version = "v3.4.1" if src == "mobile_app_v3" else ("v1.8.4" if src == "web_checkout" else "v2.1.0")

            # Cấy lỗi chuẩn xác theo từng nguồn được chọn
            if src == "mobile_app_v3":
                c_cust_id = None
                c_email = None
            elif src == "web_checkout":
                c_amount = Decimal("-150000.00")
                c_status = "UNKNOWN_ERROR"
            elif src == "erp_core":
                c_cust_id = None
                c_status = "FAILED_PAYMENT_SYNC"
            elif defect_type == "null_customer_id":
                c_cust_id = None
                c_email = None
            elif defect_type == "negative_amount":
                c_amount = Decimal("-150000.00")
                c_status = "UNKNOWN_ERROR"
            else:
                c_cust_id = None
                c_email = None

            payload.append((
                order_id,
                BATCH_DATE,
                c_cust_id,
                c_email,
                rng.choice(PRODUCT_SKUS),
                qty,
                unit_price,
                c_amount,
                "VND",
                c_status,
                rng.choice(PAYMENT_METHODS),
                src,
                c_version,
                now_ts + timedelta(seconds=offset * 5),
            ))

        with CONN_LOCK:
            con.executemany(
                "INSERT INTO fact_orders VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                payload,
            )

        injected_details.append({
            "source": src,
            "rows_injected": len(payload),
            "defect_type": defect_type if source != "all" else f"auto_{src}",
        })

    # Cập nhật kết quả DQ checks ngay lập tức vào database
    from data.dq import run_all_checks
    dq_res = run_all_checks()

    # Cập nhật state runtime & tạo hồ sơ Incident trong incident_store
    import json
    from data import incident_store
    from data.incidents import build_incident_payload
    from web import state as ui_state

    inc_id = f"INC-{now_ts.strftime('%Y%m%d-%H%M%S')}"
    desc = f"Phát hiện sự cố DQ trên nguồn [{', '.join(sources_to_inject)}]: {total_added} dòng dữ liệu lỗi trong fact_orders"

    # Tìm test đang fail
    failed_test_name = "source_not_null_warehouse_fact_orders_customer_id"
    for r in dq_res:
        if r.get("status") == "fail":
            failed_test_name = r.get("check_name") or failed_test_name
            break

    try:
        envelope = build_incident_payload(test_name=failed_test_name, incident_id=inc_id)
    except Exception:
        envelope = {
            "incident_id": inc_id,
            "incident_type": "DATA_QUALITY",
            "target_table": "main.fact_orders",
            "source": ", ".join(sources_to_inject),
            "description": desc,
            "evidence_payload": {
                "source_system": sources_to_inject[0] if sources_to_inject else "erp_core",
                "failures": total_added,
            },
        }

    # Lưu vào bảng incidents và chọn làm active incident cho Copilot
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
                    inc_id, f"job_ingest_{sources_to_inject[0]}", f"run_{now_ts.strftime('%Y%m%d%H%M%S')}", now_ts, now_ts, "WAITING_FOR_APPROVAL",
                    "CRITICAL" if len(sources_to_inject) > 1 else "HIGH",
                    "fact_orders", failed_test_name, "customer_id", "not_null", total_added, 1, desc,
                    json.dumps(envelope, ensure_ascii=False, default=str), None, None, None,
                    "", 0, False, None,
                ],
            )
        incident_store.select_incident(inc_id)
    except Exception as e:
        print(f"[WARN] Failed to insert incident to store: {e}")

    ui_state.set_state(
        status="WAITING_FOR_APPROVAL",
        maker="idle",
        incident_id=inc_id,
        stage="investigate",
    )

    notif_res = None
    if notify:
        notif_res = NotificationHub.notify_incident(
            incident_id=inc_id,
            incident_type="MULTI_SOURCE_DQ" if len(sources_to_inject) > 1 else "DATA_QUALITY",
            target_table="fact_orders",
            source_system=", ".join(sources_to_inject),
            severity="CRITICAL" if len(sources_to_inject) > 1 else "HIGH",
            description=desc,
        )

    return {
        "ok": True,
        "incident_id": inc_id,
        "total_injected_rows": total_added,
        "sources": injected_details,
        "notification": notif_res,
    }


def reset_clean_warehouse() -> Dict[str, Any]:
    """Khôi phục kho dữ liệu DuckDB về trạng thái 100% sạch (0 lỗi, 6/6 test pass)."""
    import os
    import duckdb
    import config
    from data.connection import close_connection, get_connection
    from data.warehouse import (
        DDL_STATEMENTS,
        MART_SQL,
        SEED,
        _gen_customers,
        _gen_orders,
    )
    from data.dq import run_all_checks
    from web import state as ui_state

    path = config.DUCKDB_PATH
    close_connection()
    if os.path.exists(path):
        try:
            os.remove(path)
        except Exception:
            pass

    rng = random.Random(SEED)
    customers = _gen_customers(rng)
    orders = _gen_orders(rng)  # 100% clean orders (KHÔNG gọi _inject_defects)

    con = duckdb.connect(path)
    try:
        for ddl in DDL_STATEMENTS:
            con.execute(ddl)
        from data.incident_store import INCIDENT_DDL
        for ddl in INCIDENT_DDL:
            try:
                con.execute(ddl)
            except Exception:
                pass
        from data.wap import _DDL as WAP_DDL
        for ddl in WAP_DDL:
            try:
                con.execute(ddl)
            except Exception:
                pass

        con.execute("DROP TABLE IF EXISTS quarantine_fact_orders")
        con.execute("DROP TABLE IF EXISTS shadow_fact_orders")
        try:
            con.execute("UPDATE incidents SET status = 'RESOLVED', updated_at = CURRENT_TIMESTAMP WHERE status IN ('DETECTED', 'INVESTIGATING', 'WAITING_FOR_APPROVAL', 'WAITING_SHADOW_APPROVAL')")
        except Exception:
            pass
        con.executemany("INSERT INTO dim_customers VALUES (?, ?, ?, ?, ?)", customers)
        con.executemany(
            "INSERT INTO fact_orders VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [tuple(r) for r in orders],
        )
        for sql in MART_SQL.values():
            con.execute(sql)
        row_cnt = con.execute("SELECT COUNT(*) FROM fact_orders").fetchone()[0]
    finally:
        con.close()

    # Khởi tạo lại connection & chạy lại DQ checks
    get_connection()
    dq_results = run_all_checks()

    # Reset UI State về IDLE sạch
    ui_state.set_state(
        status="IDLE",
        maker="idle",
        checker="idle",
        incident_id=None,
        stage="idle",
    )

    return {
        "fact_orders_rows": row_cnt,
        "dq_results": dq_results,
        "clean": True,
    }



def main() -> int:
    parser = argparse.ArgumentParser(description="Chủ động cấy lỗi phục vụ Demo")
    parser.add_argument("--source", choices=["mobile_app_v3", "web_checkout", "erp_core", "all"], default="mobile_app_v3")
    parser.add_argument("--type", default="null_customer_id", choices=["null_customer_id", "negative_amount", "duplicate_order"])
    parser.add_argument("--rows", type=int, default=15)
    parser.add_argument("--no-notify", action="store_true")
    parser.add_argument("--reset", action="store_true", help="Reset kho dữ liệu về trạng thái sạch")
    args = parser.parse_args()

    if args.reset:
        print("🔄 Đang reset kho dữ liệu về trạng thái sạch...")
        stats = reset_clean_warehouse()
        print(f"✅ Reset thành công: {stats['fact_orders_rows']} dòng fact_orders sạch.")
        return 0

    print(f"⚡ Đang cấy lỗi vào nguồn [{args.source}] ({args.rows} dòng)...")
    res = inject_custom_defect(
        source=args.source,
        defect_type=args.type,
        rows=args.rows,
        notify=not args.no_notify,
    )
    print("=" * 60)
    print(f"✅ Cấy lỗi thành công! Incident ID: {res['incident_id']}")
    print(f"  Tổng dòng lỗi: {res['total_injected_rows']}")
    print(f"  Nguồn ảnh hưởng: {[s['source'] for s in res['sources']]}")
    if res.get("notification"):
        print("  📢 Đã phát thông báo đa kênh qua Telegram Bot!")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
