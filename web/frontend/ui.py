"""
web/frontend/ui.py — Chainlit app (Human-in-the-loop)
=====================================================

Đây là **target của `mount_chainlit`** (xem `web/server.py`). File này chỉ điều phối
luồng hội thoại; phần render markdown/nút nằm ở `rendering.py`.

Luồng Maker–Checker trên UI:

    on_chat_start        nạp incident -> Agent 1 điều tra (stream từng tool call)
                         -> báo cáo + [✅ Duyệt] / [❌ Từ chối]
    action "approve"     Agent 1 vá + verify -> HỎI engineer: có recheck không?
    action "audit"       engineer chọn "có" -> Agent 2 nghiệm thu độc lập
                         (cũng dùng để chạy lại nghiệm thu bất cứ lúc nào)
    action "skip_audit"  engineer chọn "không" -> đóng incident luôn, ghi vết vào audit log
    action "reject"      không thực thi gì, hỏi lý do -> Agent 1 re-plan
    on_message           engineer chất vấn; câu hỏi về nghiệm thu -> Agent 2, còn lại -> Agent 1

Có HAI điểm human-in-the-loop:
    1. Trước khi GHI dữ liệu   -> approve / reject
    2. Sau khi ghi xong        -> recheck (Agent 2) / chốt luôn
Điểm thứ hai để engineer tự cân đối: lỗi đơn giản thì chốt cho nhanh, lỗi phức tạp thì
trả thêm thời gian + token để có biên bản nghiệm thu độc lập.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any, Callable, Dict, List, Optional

import chainlit as cl
from fastapi.concurrency import run_in_threadpool

import config
from ai import tools, worker
from ai.agent import DataReliabilityAgent
from ai.auditor import DataAuditorAgent, run_audit_headless
from ai.llm import LLMSettings, ToolEvent
from ai.schemas import (
    MAX_REPLAN_ATTEMPTS,
    AgentReport,
    AuditReport,
    IncidentInput,
    IncidentStatus,
)
from data import audit as data_audit
from data import incident_store
from data.incidents import build_sample_incident_payload
from data.warehouse import ensure_database
from web import state as ui_state
from web.notifications import NotificationHub
from web.frontend.rendering import (
    AUTHOR_ALERT,
    AUTHOR_AUDITOR,
    AUTHOR_ENGINEER,
    AUTHOR_SRE,
    AUTHOR_SYSTEM,
    approval_actions,
    audit_actions,
    healthy_action_chips,
    markdown_table,
    multi_source_actions,
    publish_actions,
    recheck_decision_actions,
    render_compact_incident_alert,
    render_healthy_landing_card,
    render_multi_source_matrix,
    render_notification_bar,
    render_raw_data_boxes,
    render_tool_step,
    triage_actions,
    warehouse_snapshot,
    welcome_message,
)

# ---------------------------------------------------------------------------
# 1. Chạy hành động blocking của agent + stream tool call lên UI
# ---------------------------------------------------------------------------


async def run_agent_with_live_steps(agent: Any, blocking_call: Callable[[], Any]) -> Any:
    """
    Chạy một hành động blocking của agent trong threadpool, đồng thời stream các tool
    call lên UI ngay khi chúng xảy ra.

    Cơ chế: callback `on_tool_event` (chạy trong worker thread) đẩy event vào
    `asyncio.Queue` qua `loop.call_soon_threadsafe`; coroutine `_pump` (chạy trên event
    loop) mới là nơi gọi API Chainlit. Nhờ vậy không gọi Chainlit từ thread khác.
    """
    loop = asyncio.get_running_loop()
    queue: asyncio.Queue = asyncio.Queue()
    sentinel = object()

    def on_event(event: ToolEvent) -> None:
        loop.call_soon_threadsafe(queue.put_nowait, event)

    async def _pump() -> None:
        while True:
            item = await queue.get()
            if item is sentinel:
                return
            try:
                await render_tool_step(item)  # type: ignore[arg-type]
            except Exception:  # noqa: BLE001 - lỗi render không được làm hỏng agent run
                pass

    previous_cb = agent.on_tool_event
    agent.on_tool_event = on_event
    pump_task = asyncio.create_task(_pump())
    try:
        return await cl.make_async(blocking_call)()
    finally:
        agent.on_tool_event = previous_cb
        queue.put_nowait(sentinel)
        await pump_task


# ---------------------------------------------------------------------------
# 2. Gửi báo cáo lên UI
# ---------------------------------------------------------------------------


async def send_agent_report(report: AgentReport, agent: DataReliabilityAgent) -> None:
    """Báo cáo của Agent 1 + JSON contract + 2 nút duyệt."""
    await cl.Message(
        content=report.to_markdown(),
        author=AUTHOR_SRE,
        actions=approval_actions(),
        elements=[
            cl.Text(
                name=f"{report.incident_id}-report.json",
                content=report.to_json(),
                display="side",
                language="json",
            )
        ],
    ).send()
    cl.user_session.set("report", report)
    cl.user_session.set("agent", agent)


async def send_audit_report(audit: AuditReport) -> None:
    """Biên bản nghiệm thu của Agent 2."""
    await cl.Message(
        content=audit.to_markdown(),
        author=AUTHOR_AUDITOR,
        elements=[
            cl.Text(
                name=f"{audit.audit_id}-audit.json",
                content=audit.to_json(),
                display="side",
                language="json",
            )
        ],
    ).send()
    cl.user_session.set("audit_report", audit)


# ---------------------------------------------------------------------------
# 3. Agent 2 — nghiệm thu độc lập
# ---------------------------------------------------------------------------


async def run_independent_audit(trigger: str = "auto") -> Optional[AuditReport]:
    """
    Chạy **Agent 2 (Data Auditor)** nghiệm thu độc lập.

    Agent 2 được khởi tạo MỚI, có `messages` riêng, chỉ được cấp tool đọc, và chạy
    bằng model khác Agent 1 (nếu cấu hình cross-model) — nó không thừa hưởng gì từ hội
    thoại của Agent 1 ngoài bản báo cáo (gắn nhãn "lời khai cần kiểm chứng").
    """
    incident: Optional[IncidentInput] = cl.user_session.get("incident")
    report: Optional[AgentReport] = cl.user_session.get("report")
    maker_agent: Optional[DataReliabilityAgent] = cl.user_session.get("agent")
    maker_model = maker_agent.settings.model if maker_agent else "?"
    maker_usage = maker_agent.usage.describe() if maker_agent else "n/a"

    auditor: Optional[DataAuditorAgent] = cl.user_session.get("auditor")
    if auditor is None:
        # Truyền model của Maker vào để Checker tự bốc model KHÁC trong pool
        auditor = DataAuditorAgent(settings=LLMSettings.for_auditor(avoid_model=maker_model))
        cl.user_session.set("auditor", auditor)

    cross_model = (not auditor.is_offline) and auditor.settings.model != maker_model
    if auditor.is_offline:
        brain = (
            "🟡 Brain của em: **OFFLINE** (chưa cấu hình `DRA_API_KEY`) — số liệu DuckDB "
            "vẫn là số liệu thật, lấy từ engine checks ạ"
        )
    else:
        brain = f"🧠 Brain của em: `{auditor.settings.model}`"
        brain += (
            f" — **khác model của anh SRE Agent** (`{maker_model}`) 🔀 nên em có góc nhìn "
            "độc lập, không bị mù cùng một chỗ với anh ấy ạ"
            if cross_model
            else f" (trùng model với anh SRE Agent `{maker_model}` ⚠️)"
        )

    intro = (
        "🕵️‍♀️ Em là **Data Auditor** (Agent 2) đây ạ! Em vào nghiệm thu **độc lập** phần "
        "anh SRE Agent vừa làm nhé.\n\n"
        f"{brain}\n\n"
        "🔒 Quyền của em: **chỉ đọc** DuckDB. Em **không dùng lại con số nào** trong báo "
        "cáo của anh ấy — em tự lấy baseline trước-khi-vá từ DuckDB rồi tự viết SQL kiểm "
        "3 việc: 🧼 dữ liệu còn bẩn không, 🧊 có xoá oan mất dòng nào không, "
        "🧮 tổng số dòng có bảo toàn không."
    )
    if trigger == "manual":
        intro += "\n\n_(Anh vừa bấm nút nghiệm thu lại — em chạy lại từ đầu ạ 🙆‍♀️)_"

    thinking = cl.Message(author=AUTHOR_AUDITOR, content=intro)
    await thinking.send()

    ui_state.set_state(status="AUDITING", checker="working")
    try:
        audit: AuditReport = await run_agent_with_live_steps(
            auditor, lambda: auditor.audit(incident=incident, remediation_report=report)
        )
    except Exception as exc:  # noqa: BLE001
        ui_state.set_state(status="FAILED", checker="idle")
        await cl.Message(
            author=AUTHOR_AUDITOR, content=f"😢 Em nghiệm thu bị lỗi giữa đường ạ: `{exc}`"
        ).send()
        return None

    await send_audit_report(audit)

    ok = audit.verdict == "AUDIT_PASSED"
    ui_state.set_state(
        status="RESOLVED" if ok else "AUDIT_FAILED",
        checker="idle",
        audit_verdict=audit.verdict,
    )
    mismatch = any(c.verified_by_engine is False for c in audit.checks)
    tail = [
        f"### {'🎖️' if ok else '🛑'} Maker–Checker: "
        f"{'NGHIỆM THU ĐẠT' if ok else 'NGHIỆM THU KHÔNG ĐẠT'}",
        "",
        f"- 👷‍♀️ **Maker** (Agent 1) · `{maker_model}`: đã vá dữ liệu và tự verify.",
        f"- 🕵️‍♀️ **Checker** (Agent 2) · `{audit.auditor_model or auditor.settings.model}`: "
        f"tự chạy **{len(auditor.executed_queries())} câu SQL** độc lập, đạt "
        f"**{audit.passed_count}/{len(audit.checks)}** hạng mục.",
        "",
        f"💰 **Chi phí token** · Maker: {maker_usage} · Checker: {auditor.usage.describe()}",
    ]
    if cross_model:
        tail.append(
            "- 🔀 **Cross-model checking**: hai vai chạy bằng hai model khác nhau, nên lỗi "
            "của model này khó lọt qua model kia."
        )
    if mismatch:
        tail.append(
            "- 🚨 **Có hạng mục LLM khai khác số liệu máy đo** → hệ thống đã lấy kết quả "
            "đo bằng Python và tự hạ verdict. Anh xem mục có dấu ⚠️ nhé."
        )
    if not ok:
        tail.append(
            "- 💡 Anh cân nhắc rollback theo `rollback_hint` trong báo cáo của Agent 1, "
            "hoặc escalate cho on-call theo `oncall_escalation`."
        )
    await cl.Message(author=AUTHOR_SYSTEM, content="\n".join(tail), actions=audit_actions()).send()
    return audit


# ---------------------------------------------------------------------------
# 4. CHAINLIT HANDLERS & MULTI-SOURCE MONITORING
# ---------------------------------------------------------------------------


def scan_all_sources_status() -> List[Dict[str, Any]]:
    """Quét đo đếm toàn diện số dòng và vi phạm của 3 nguồn dữ liệu trên fact_orders."""
    src_meta = [
        {"key": "web_checkout", "name": "Web Checkout Stream", "version": "v1.8.4"},
        {"key": "mobile_app_v3", "name": "Mobile App Ingest", "version": "v3.4.1"},
        {"key": "erp_core", "name": "ERP Core System", "version": "v2.1.0"},
    ]
    sources_map: Dict[str, Dict[str, Any]] = {}
    try:
        from data import connection as db_conn
        res = db_conn.fetch(
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
        sources_map = {str(r.get("source_system")): r for r in rows if r.get("source_system")}

        dup_res = db_conn.fetch(
            "SELECT source_system, COUNT(*) - COUNT(DISTINCT order_id) AS dup_cnt FROM fact_orders GROUP BY source_system"
        )
        for d in dup_res.get("rows", []):
            sk = str(d.get("source_system"))
            dc = int(d.get("dup_cnt") or 0)
            if sk in sources_map and dc > 0:
                sources_map[sk]["total_viols"] = int(sources_map[sk].get("total_viols") or 0) + dc
    except Exception:
        sources_map = {}

    sources_data: List[Dict[str, Any]] = []
    for s in src_meta:
        m = sources_map.get(s["key"], {})
        s_rows = int(m.get("total_rows", 0) or 0)
        s_viols = int(m.get("total_viols", 0) or 0)
        sources_data.append({
            "key": s["key"],
            "name": s["name"],
            "version": s["version"],
            "total_rows": s_rows,
            "total_viols": s_viols,
            "status": "incident" if s_viols > 0 else "healthy",
        })
    return sources_data


def _resolve_incident_for_source(source_key: str) -> tuple[Optional[Dict[str, Any]], Optional[AgentReport], str]:
    """Tìm hoặc tạo incident envelope nhắm vào nguồn dữ liệu cụ thể (chỉ khi có lỗi thật)."""
    sources_data = scan_all_sources_status()
    src_info = next((s for s in sources_data if s.get("key") == source_key), None)
    if not src_info or src_info.get("total_viols", 0) == 0:
        return None, None, "clean"

    all_open = incident_store.list_incidents(status="WAITING_FOR_APPROVAL", limit=10) + \
               incident_store.list_incidents(status="DETECTED", limit=10)
    for inc in all_open:
        row = incident_store.get_incident(str(inc.get("incident_id", "")))
        if row and row.get("envelope"):
            env = row["envelope"]
            hint_src = str((env.get("evidence_payload") or {}).get("upstream_hint", {}).get("source_system", ""))
            if source_key in hint_src or source_key in str(env.get("description", "")):
                report = None
                if row.get("report"):
                    try:
                        report = AgentReport.model_validate(row["report"])
                    except Exception:
                        report = None
                return env, report, f"sự cố `{row['incident_id']}` nguồn `{source_key}`"

    try:
        from data.incidents import build_incident_payload
        env = build_incident_payload()
        if "evidence_payload" in env and isinstance(env["evidence_payload"], dict):
            env["evidence_payload"]["upstream_hint"] = {
                "source_system": source_key,
                "source_version": "v3.4.1" if "mobile" in source_key else "v1.8.4",
            }
        return env, None, f"phát hiện {src_info.get('total_viols', 0)} dòng lỗi trên nguồn `{source_key}`"
    except Exception:
        return None, None, "clean"


def _resolve_incident(target_source: Optional[str] = None) -> tuple[Optional[Dict[str, Any]], Optional[AgentReport], str]:
    """
    Chọn incident cho phiên chat này (chạy trong threadpool vì có truy vấn DuckDB).
    Chỉ trả về incident khi THỰC SỰ có vi phạm DQ trên DuckDB.
    """
    # 1. Kiểm tra tình trạng thực tế của DuckDB
    sources_data = scan_all_sources_status()
    total_viols = sum(s.get("total_viols", 0) for s in sources_data)
    if total_viols == 0:
        # Kho dữ liệu hoàn toàn sạch 100% -> tuyệt đối không nạp incident cũ
        incident_store.clear_selection()
        try:
            con = tools.get_connection()
            con.execute("UPDATE incidents SET status = 'RESOLVED', updated_at = CURRENT_TIMESTAMP WHERE status IN ('DETECTED', 'INVESTIGATING', 'WAITING_FOR_APPROVAL', 'WAITING_SHADOW_APPROVAL')")
        except Exception:
            pass
        return None, None, "clean"

    # Nếu có chỉ định target_source cụ thể (từ tab đang chọn)
    if target_source:
        src_info = next((s for s in sources_data if s.get("key") == target_source), None)
        if src_info and src_info.get("total_viols", 0) == 0:
            return None, None, "clean"
        return _resolve_incident_for_source(target_source)

    # 2. Nếu thực sự có vi phạm, kiểm tra incident được chọn hoặc mở
    incident_id = incident_store.selected_incident_id()
    row = incident_store.get_incident(incident_id) if incident_id else None

    if row is None:
        waiting = incident_store.list_incidents(status="WAITING_FOR_APPROVAL", limit=1)
        if waiting:
            row = incident_store.get_incident(str(waiting[0]["incident_id"]))
        else:
            detected = incident_store.list_incidents(status="DETECTED", limit=1)
            if detected:
                row = incident_store.get_incident(str(detected[0]["incident_id"]))

    if row is not None and row.get("envelope"):
        incident_store.clear_selection()
        report: Optional[AgentReport] = None
        if row.get("report"):
            try:
                report = AgentReport.model_validate(row["report"])
            except Exception:
                report = None
        note = (
            f"sự cố `{row['incident_id']}` từ job `{row['job_id']}`"
            + (" · dùng lại báo cáo worker nền đã điều tra" if report else " · chưa có báo cáo")
        )
        return row["envelope"], report, note

    # Nếu không có incident record lưu sẵn, lấy nguồn có nhiều vi phạm nhất để tạo envelope
    dirty = [s for s in sources_data if s.get("total_viols", 0) > 0]
    dirtiest = sorted(dirty, key=lambda s: s.get("total_viols", 0), reverse=True)[0]
    return _resolve_incident_for_source(dirtiest["key"])


@cl.on_chat_start
async def on_chat_start() -> None:
    """
    Khởi động phiên trực:
    - Nếu hệ thống sạch: Hiện Landing Card trực chiến theo đúng NGUỒN ĐANG CHỌN, KHÔNG chạy vá giả.
    - Nếu có sự cố: Hiện 1 thẻ Alert duy nhất và bắt đầu điều tra.
    """
    await run_in_threadpool(ensure_database, config.DUCKDB_PATH)

    # 1. Xác định tab nguồn đang chọn (từ referer URL query param `src`, hoặc state)
    active_source = "web_checkout"
    try:
        session = getattr(cl.context, "session", None)
        headers = getattr(session, "headers", {}) or {}
        referer = headers.get("referer", "") or getattr(session, "http_referer", "") or ""
        if "src=" in referer:
            from urllib.parse import parse_qs, urlparse
            qs = parse_qs(urlparse(referer).query)
            if "src" in qs and qs["src"]:
                active_source = qs["src"][0]
        else:
            st = ui_state.get_state()
            if st.get("selected_source"):
                active_source = st["selected_source"]
    except Exception:
        pass

    agent = DataReliabilityAgent()
    checker_settings = LLMSettings.for_auditor(avoid_model=agent.settings.model)

    sources_data = await run_in_threadpool(scan_all_sources_status)
    payload, preloaded_report, source_note = await run_in_threadpool(_resolve_incident, active_source)

    # --- TRƯỜNG HỢP 1: DỮ LIỆU SẠCH (HEALTHY MODE) ---
    if payload is None or source_note == "clean":
        ui_state.set_state(status="RESOLVED", maker="idle", checker="idle")
        cl.user_session.set("agent", agent)
        cl.user_session.set("incident", None)
        cl.user_session.set("report", None)
        cl.user_session.set("auditor", None)
        cl.user_session.set("audit_report", None)
        cl.user_session.set("published", False)
        cl.user_session.set("ready_for_production", False)

        welcome_text = render_healthy_landing_card(
            source_key=active_source,
            sources_data=sources_data,
            maker_model=agent.settings.model,
            checker_model=checker_settings.model,
        )
        await cl.Message(
            author=AUTHOR_SYSTEM,
            content=welcome_text,
            actions=healthy_action_chips(active_source),
        ).send()
        return

    # --- TRƯỜNG HỢP 2: CÓ SỰ CỐ THẬT (INCIDENT MODE) ---
    incident = IncidentInput(**payload)
    evidence = getattr(incident, "evidence_payload", {}) or {}
    source_sys = str(evidence.get("source_system", "web_checkout") if isinstance(evidence, dict) else "web_checkout")
    await _start_investigation_flow(incident, source_sys, preloaded_report=preloaded_report, source_note=source_note)


async def _start_investigation_flow(
    incident: IncidentInput,
    source_sys: str,
    preloaded_report: Optional[AgentReport] = None,
    source_note: str = "",
) -> None:
    """Bắt đầu luồng điều tra sự cố thực tế với Agent 1 và hiển thị thẻ sự cố."""
    agent: Optional[DataReliabilityAgent] = cl.user_session.get("agent")
    if agent is None:
        agent = DataReliabilityAgent()
        cl.user_session.set("agent", agent)

    severity_val = str(getattr(incident, "severity", None) or "HIGH")
    alert_card = render_compact_incident_alert(
        incident_id=incident.incident_id,
        incident_type=str(incident.incident_type),
        target_table=incident.target_table,
        source_sys=source_sys,
        severity=severity_val,
        description=incident.description,
        source_note=source_note,
    )

    payload_dict = incident.model_dump()
    await cl.Message(
        author=AUTHOR_ALERT,
        content=alert_card,
        elements=[
            cl.Text(
                name="incident_payload.json",
                content=json.dumps(payload_dict, ensure_ascii=False, indent=2, default=str),
                display="side",
                language="json",
            )
        ],
    ).send()

    agent.load_incident(incident)
    ui_state.set_state(
        incident_id=incident.incident_id,
        status="INVESTIGATING",
        maker="working",
        audit_verdict=None,
    )
    cl.user_session.set("agent", agent)
    cl.user_session.set("incident", incident)
    cl.user_session.set("auditor", None)
    cl.user_session.set("audit_report", None)
    cl.user_session.set("awaiting_reject_reason", False)
    cl.user_session.set("awaiting_recheck_decision", False)
    cl.user_session.set("audit_skipped", False)
    cl.user_session.set("resolved", False)

    if preloaded_report is not None:
        agent.report = preloaded_report
        agent.status = preloaded_report.status
        cl.user_session.set("agent", agent)
        ui_state.set_state(status="WAITING_FOR_APPROVAL", maker="idle")
        await send_agent_report(preloaded_report, agent)
        return

    thinking = cl.Message(
        author=AUTHOR_SRE,
        content=f"🔍 Em nhận ca sự cố `{incident.incident_id}` nguồn `{source_sys}` rồi ạ! Đang điều tra trên DuckDB…",
    )
    await thinking.send()

    try:
        report: AgentReport = await run_agent_with_live_steps(agent, agent.investigate)
    except Exception as exc:  # noqa: BLE001
        ui_state.set_state(status="FAILED", maker="idle", checker="idle")
        thinking.content = f"❌ Em gặp lỗi khi điều tra: `{exc}`"
        await thinking.update()
        return

    ui_state.set_state(status="WAITING_FOR_APPROVAL", maker="idle")
    thinking.content = (
        f"✅ Em điều tra xong rồi ạ — **{len(agent.tool_events)} lần gọi tool** "
        f"({len(agent.executed_queries())} câu SQL trên DuckDB) 📊\n\n"
        f"💰 Chi phí: {agent.usage.describe()}"
    )
    await thinking.update()
    await send_agent_report(report, agent)


# Từ khoá để định tuyến câu hỏi sang Agent 2 thay vì Agent 1
_AUDITOR_KEYWORDS = (
    "audit", "auditor", "nghiệm thu", "nghiem thu", "kiểm toán", "kiem toan",
    "checker", "agent 2", "agent2", "biên bản", "bien ban", "chứng nhận",
    "chung nhan", "mất dữ liệu", "mat du lieu", "xoá oan", "xoa oan", "bảo toàn",
    "bao toan", "row count",
)


def route_to_auditor(question: str) -> bool:
    """Câu hỏi về nghiệm thu thì để Agent 2 trả lời, còn lại là việc của Agent 1."""
    low = question.lower()
    return any(keyword in low for keyword in _AUDITOR_KEYWORDS)


@cl.on_message
async def on_message(message: cl.Message) -> None:
    """
    Engineer chat tự do: "tại sao lại lỗi?", "show thử 5 dòng dữ liệu",
    "có mất dữ liệu không?"… Cả hai agent đều dùng tool DuckDB để trả lời bằng số
    liệu thật; Agent 2 vẫn chỉ được đọc.
    """
    agent: Optional[DataReliabilityAgent] = cl.user_session.get("agent")
    if agent is None:
        await cl.Message(
            author=AUTHOR_SYSTEM,
            content="Chưa có phiên điều tra nào ạ. Anh bấm **New Chat** để nạp incident mới nhé 🙏",
        ).send()
        return

    question = (message.content or "").strip()
    if not question:
        return

    # --- Engineer vừa bấm [Từ chối] -> tin nhắn này là lý do -> re-plan ---
    if cl.user_session.get("awaiting_reject_reason"):
        cl.user_session.set("awaiting_reject_reason", False)
        thinking = cl.Message(
            author=AUTHOR_SRE,
            content="🔁 Em ghi nhận rồi ạ. Em điều tra lại và lập phương án mới ngay…",
        )
        await thinking.send()
        try:
            await run_agent_with_live_steps(agent, lambda: agent.reject(question))
            new_report: AgentReport = await run_agent_with_live_steps(
                agent, lambda: agent.replan(question)
            )
        except Exception as exc:  # noqa: BLE001
            thinking.content = f"❌ Em chưa lập lại được kế hoạch ạ: `{exc}`"
            await thinking.update()
            return
        thinking.content = "✅ Em có phương án remediation mới rồi, anh xem lại giúp em nhé 🙆‍♀️"
        await thinking.update()
        await send_agent_report(new_report, agent)
        return

    # --- Định tuyến sang Agent 2 nếu là câu hỏi về nghiệm thu ---
    auditor: Optional[DataAuditorAgent] = cl.user_session.get("auditor")
    if auditor is not None and route_to_auditor(question):
        thinking = cl.Message(
            author=AUTHOR_AUDITOR, content="🔬 Em kiểm tra lại trên DuckDB rồi trả lời anh ngay…"
        )
        await thinking.send()
        try:
            answer = await run_agent_with_live_steps(auditor, lambda: auditor.ask(question))
        except Exception as exc:  # noqa: BLE001
            thinking.content = f"❌ Em bị lỗi khi tra cứu ạ: `{exc}`"
            await thinking.update()
            return
        thinking.content = answer or "_(Agent 2 không trả về nội dung)_"
        await thinking.update()
        return

    # --- Chất vấn Agent 1 ---
    thinking = cl.Message(author=AUTHOR_SRE, content="💭 Em đang tra cứu trên DuckDB ạ…")
    await thinking.send()
    try:
        answer = await run_agent_with_live_steps(agent, lambda: agent.ask(question))
    except Exception as exc:  # noqa: BLE001
        thinking.content = f"❌ Em bị lỗi khi xử lý câu hỏi ạ: `{exc}`"
        await thinking.update()
        return

    thinking.content = answer or "_(Agent không trả về nội dung)_"
    await thinking.update()

    if cl.user_session.get("report") is None:
        return
    if cl.user_session.get("awaiting_recheck_decision"):
        # Agent 1 đã vá xong nhưng engineer chưa chọn recheck hay chốt luôn
        await cl.Message(
            author=AUTHOR_SYSTEM,
            content="Anh chốt giúp em: có cần **recheck độc lập** không ạ? 🤔",
            actions=recheck_decision_actions(allow_skip=bool(cl.user_session.get("resolved"))),
        ).send()
    elif cl.user_session.get("resolved"):
        nudge = (
            "Ca này **chưa qua nghiệm thu độc lập** — anh muốn em cho Agent 2 soi lại không ạ? 🕵️‍♀️"
            if cl.user_session.get("audit_skipped")
            else "Anh muốn em cho Agent 2 nghiệm thu lại lần nữa không ạ? 🕵️‍♀️"
        )
        await cl.Message(author=AUTHOR_SYSTEM, content=nudge, actions=audit_actions()).send()
    else:
        await cl.Message(
            author=AUTHOR_SYSTEM,
            content="Anh duyệt để em thực thi remediation, hoặc hỏi em thêm gì cũng được ạ 🙆‍♀️",
            actions=approval_actions(),
        ).send()


@cl.action_callback("approve")
async def on_approve(action: cl.Action) -> None:
    """
    [🧪 Duyệt chạy thử trên Staging] — **BƯỚC 1** của Two-Phase Human-in-the-loop.

    Chạy script vá trên `shadow_<table>` rồi cho Agent 2 nghiệm thu ngay trên bảng bóng
    đó. Bảng production không bị chạm ở bước này, nên đây là nút an toàn: sai thì chỉ
    cần xoá bảng bóng.

    Nút Publish (bước 2) chỉ xuất hiện khi Agent 2 cấp chứng nhận.
    """
    await action.remove()

    agent: Optional[DataReliabilityAgent] = cl.user_session.get("agent")
    report: Optional[AgentReport] = cl.user_session.get("report")
    if agent is None or report is None:
        await cl.Message(author=AUTHOR_SYSTEM, content="Không tìm thấy báo cáo để duyệt.").send()
        return
    if cl.user_session.get("published"):
        await cl.Message(
            author=AUTHOR_SYSTEM, content="Sự cố này đã publish xong, không cần duyệt lại ạ."
        ).send()
        return

    plan = report.remediation
    await cl.Message(
        author=AUTHOR_ENGINEER,
        content=(
            f"🧪 **APPROVED BƯỚC 1** — chạy thử `{plan.action_type.value}` cho "
            f"`{report.incident_id}` trên bảng bóng `{plan.shadow_table_name}`."
        ),
    ).send()

    thinking = cl.Message(
        author=AUTHOR_SRE,
        content=(
            f"⚙️ Em dựng bảng bóng `{plan.shadow_table_name}` và chạy script vá **trên đó** "
            f"ạ. Bảng thật `{plan.target_production_table}` em không chạm vào đâu 🛡️"
        ),
    )
    await thinking.send()

    ui_state.set_state(status="EXECUTING", maker="working")
    try:
        result: Dict[str, Any] = await run_agent_with_live_steps(
            agent, lambda: agent.approve_shadow(narrate=False)
        )
    except Exception as exc:  # noqa: BLE001
        ui_state.set_state(status="FAILED", maker="idle")
        thinking.content = f"❌ Chạy trên staging thất bại ạ: `{exc}`"
        await thinking.update()
        return

    execution = result.get("execution", {}) or {}
    staged = bool(result.get("ok"))
    try:
        incident_store.set_status(
            report.incident_id,
            "STAGING_VERIFYING" if staged else "AUDIT_FAILED_TRIAGE",
            shadow_table=result.get("shadow_table") or plan.shadow_table_name,
            error=None if staged else str(result.get("error"))[:900],
        )
    except Exception as exc:
        print(f"[on_approve] ⚠️  Warning set_status STAGING_VERIFYING: {exc}")

    if not staged:
        error_detail = str(result.get("error"))[:300]
        thinking.content = (
            f"❌ Không chạy được trên staging ạ: `{error_detail}`\n\n"
            f"🛡️ Nhưng bảng thật `{plan.target_production_table}` **vẫn nguyên vẹn 100%** nên "
            "mình chưa mất gì cả."
        )
        await thinking.update()
        cl.user_session.set("triage", True)

        # Thông báo tại chỗ, không xui người dùng đi tìm dashboard
        fail_text = (
            f"### 🚨 REMEDIATION FAILED — Staging (Data Safe)\n\n"
            f"**Nguyên nhân:** `{error_detail}`\n\n"
            f"🛡️ Bảng production chưa bị thay đổi (Data Safe 100%).\n"
            f"Vui lòng chọn hướng xử lý cứu hộ ngay bên dưới:"
        )

        # Gắn 3 nút hành động trực tiếp vào khung chat Chainlit
        actions = [
            cl.Action(
                name="replan_agent",
                value=report.incident_id,
                payload={"decision": "replan"},
                label=f"🤖 Cho Agent 1 Re-plan ({agent.retry_count}/{MAX_REPLAN_ATTEMPTS})",
            ),
            cl.Action(
                name="action_manual_sql",
                value=report.incident_id,
                payload={"decision": "manual_sql"},
                label="✏️ Sửa SQL Thủ Công",
            ),
            cl.Action(
                name="cancel_shadow",
                value=report.incident_id,
                payload={"decision": "cancel"},
                label="🛑 Huỷ Bỏ & Dọn Staging",
            ),
        ]
        await cl.Message(author=AUTHOR_SYSTEM, content=fail_text, actions=actions).send()
        return

    thinking.content = (
        f"✅ Đã chạy **{execution.get('statements_executed', 0)}** câu lệnh trên bảng bóng "
        f"`{execution.get('shadow_table')}`:\n"
        f"- 🧪 Bảng bóng: **{execution.get('rows_shadow')}** dòng · "
        f"**{execution.get('violations_after')}** vi phạm\n"
        f"- 🗂️ Bảng thật: **{execution.get('rows_prod_before')}** dòng · "
        f"**{execution.get('violations_before')}** vi phạm (chưa bị chạm — đúng thiết kế)"
    )
    await thinking.update()

    # ---- Agent 2 nghiệm thu NGAY trên bảng bóng --------------------------
    # Ở kiến trúc WAP, nghiệm thu không còn là lựa chọn tuỳ ý: nó là **cổng** mở nút
    # Publish. Bỏ qua nghiệm thu thì không có đường nào lên production cả.
    shadow_tbl = str(execution.get("shadow_table") or plan.shadow_table_name or "")
    maker_model = agent.settings.model if agent else "?"
    auditor: Optional[DataAuditorAgent] = cl.user_session.get("auditor")
    if auditor is None:
        auditor = DataAuditorAgent(settings=LLMSettings.for_auditor(avoid_model=maker_model))
        cl.user_session.set("auditor", auditor)

    auditor_msg = cl.Message(
        author=AUTHOR_AUDITOR,
        content=f"🕵️‍♀️ Em là **Data Auditor** (Agent 2) — em đang soi bảng bóng `{shadow_tbl}` trên DuckDB…",
    )
    await auditor_msg.send()

    audit: Optional[AuditReport] = None
    try:
        audit = await asyncio.wait_for(
            run_agent_with_live_steps(
                auditor,
                lambda: auditor.audit(
                    incident=agent.incident,
                    remediation_report=report,
                    shadow_table=shadow_tbl,
                ),
            ),
            timeout=20.0,
        )
    except Exception as exc:  # noqa: BLE001
        # Fallback nếu LLM của Agent 2 lỗi / timeout -> dùng trực tiếp engine checks (Python thuần)
        try:
            auditor.load_case(agent.incident, report, shadow_table=shadow_tbl)
            engine_checks = auditor.run_engine_checks()
            is_passed = all(c.passed for c in engine_checks if c.severity == "BLOCKING")
            err_label = "Timeout 20s" if isinstance(exc, asyncio.TimeoutError) else str(exc)[:80]
            audit = AuditReport(
                audit_id=auditor.audit_id,
                audited_incident_id=report.incident_id,
                target_table=report.target_table,
                quarantine_table=auditor.quarantine_table or "",
                verdict="AUDIT_PASSED" if is_passed else "AUDIT_FAILED",
                checks=engine_checks,
                certification_summary=(
                    f"⚡ Agent 2 ({err_label}) — hệ thống tự động nghiệm thu siêu tốc "
                    "bằng Engine Checks (Python thuần trực tiếp trên DuckDB) ạ."
                ),
                recommended_action="PUBLISH" if is_passed else "INVESTIGATE",
                auditor_notes=f"Nghiệm thu trực tiếp qua DuckDB engine: {err_label}",
                shadow_table=shadow_tbl,
                auditor_model="fast-duckdb-engine",
            )
            audit = AuditReport.model_validate(audit.model_dump())
            auditor.report = audit
        except Exception as fallback_exc:  # noqa: BLE001
            await cl.Message(
                author=AUTHOR_AUDITOR,
                content=f"❌ Nghiệm thu thất bại: `{fallback_exc}`",
            ).send()
            return

    if audit is None:
        await cl.Message(
            author=AUTHOR_AUDITOR,
            content="❌ Không nhận được báo cáo nghiệm thu từ Agent 2.",
        ).send()
        return

    cl.user_session.set("audit_report", audit)
    ready = bool(audit.is_ready_for_production)
    audit_report = json.loads(audit.to_json())

    try:
        incident_store.set_status(
            report.incident_id,
            "READY_FOR_PRODUCTION" if ready else "AUDIT_FAILED_TRIAGE",
            audit_json=json.dumps(audit_report, ensure_ascii=False, default=str),
            ready_for_production=ready,
            error="" if ready else str(
                (audit.failed_details or {}).get("error_message") or ""
            )[:900],
        )
    except Exception as exc:
        print(f"[on_approve] ⚠️  Warning set_status READY_FOR_PRODUCTION: {exc}")

    passed_count = sum(1 for c in audit.checks if c.passed)
    total_checks = len(audit.checks)
    auditor_msg.content = (
        f"{'🎖️' if ready else '🛑'} **{audit.verdict}** — "
        f"{passed_count}/{total_checks} hạng mục đạt trên bảng bóng."
    )
    await auditor_msg.update()

    diff = auditor.shadow_diff or {}
    await cl.Message(
        author=AUTHOR_AUDITOR,
        content=(
            "### 🔬 Đối chiếu trước khi Publish\n\n"
            "| Chỉ số | Bảng thật (hiện tại) | Bảng bóng (sau vá) |\n"
            "| --- | --- | --- |\n"
            f"| Số dòng vi phạm | {diff.get('violations_prod')} | "
            f"**{diff.get('violations_shadow')}** |\n"
            f"| Tổng số dòng | {diff.get('rows_prod')} | {diff.get('rows_shadow')} |\n"
            f"| Dòng đã cách ly | — | {diff.get('rows_quarantine', diff.get('rows_removed'))} |\n"
            f"| Schema khớp | — | {'✅ khớp' if diff.get('schema_match') else '❌ lệch'} |\n"
        ),
        elements=[
            cl.Text(
                name="audit_on_shadow.json",
                content=json.dumps(
                    {
                        "mode": auditor.mode,
                        "audit_report": audit_report,
                        "shadow_table": auditor.shadow_table,
                        "shadow_diff": auditor.shadow_diff,
                        "is_ready_for_production": audit.is_ready_for_production,
                        "failed_details": audit.failed_details,
                    },
                    ensure_ascii=False,
                    indent=2,
                    default=str,
                ),
                display="side",
                language="json",
            )
        ],
    ).send()

    if ready:
        cl.user_session.set("ready_for_production", True)
        await cl.Message(
            author=AUTHOR_SYSTEM,
            content=(
                f"### 🚀 SẴN SÀNG PUBLISH — `{report.incident_id}`\n"
                f"Agent 2 đã nghiệm thu **ĐẠT** trên bảng bóng. Bảng thật "
                f"`{plan.target_production_table}` hiện vẫn còn "
                f"**{diff.get('violations_prod')}** dòng vi phạm.\n\n"
                "Bấm nút dưới để **atomic swap** bảng bóng thành bảng thật (một transaction, "
                "không có cửa sổ nào consumer đọc được bảng nửa vời) 👇"
            ),
            actions=publish_actions(),
        ).send()
    else:
        cl.user_session.set("triage", True)
        failed = audit_payload.get("failed_details") or {}
        await cl.Message(
            author=AUTHOR_SYSTEM,
            content=(
                f"### 🛑 AUDIT FAILED — cổng Publish vẫn đóng\n"
                f"`{str(failed.get('error_message'))[:400]}`\n\n"
                f"🛡️ Bảng production **nguyên vẹn 100%** — mọi lệnh vá chỉ chạy trên bảng bóng.\n\n"
                "Anh chọn một trong ba hướng cứu hộ 👇"
            ),
            actions=triage_actions(
                can_replan=agent.retry_count < MAX_REPLAN_ATTEMPTS,
                retry_count=agent.retry_count,
            ),
        ).send()


@cl.action_callback("publish_prod")
async def on_publish_prod(action: cl.Action) -> None:
    """[🚀 Publish to Production] — **BƯỚC 2**: atomic swap sang bảng thật."""
    await action.remove()

    agent: Optional[DataReliabilityAgent] = cl.user_session.get("agent")
    report: Optional[AgentReport] = cl.user_session.get("report")
    if agent is None or report is None:
        await cl.Message(author=AUTHOR_SYSTEM, content="Không tìm thấy phiên xử lý.").send()
        return
    if not cl.user_session.get("ready_for_production"):
        # Cửa này đóng cả ở đây, không chỉ ở chỗ ẩn nút: nút có thể còn sót trên màn hình
        # cũ sau khi trạng thái đã đổi.
        await cl.Message(
            author=AUTHOR_SYSTEM,
            content="⛔ Chưa có chứng nhận của Agent 2 nên em không publish được ạ.",
        ).send()
        return

    plan = report.remediation
    await cl.Message(
        author=AUTHOR_ENGINEER,
        content=f"🚀 **PUBLISH** `{plan.shadow_table_name}` → `{plan.target_production_table}`.",
    ).send()

    thinking = cl.Message(author=AUTHOR_SRE, content="⚙️ Em tráo bảng trong một transaction ạ…")
    await thinking.send()

    tools.grant_phase(report.incident_id, phase=tools.PHASE_PUBLISH)
    try:
        result = await run_in_threadpool(
            tools.tool_atomic_publish_to_prod,
            plan.shadow_table_name,
            plan.target_production_table,
            report.incident_id,
            False,
        )
    finally:
        tools.revoke_phase(report.incident_id, phase=tools.PHASE_PUBLISH)

    if not result.get("ok"):
        thinking.content = f"❌ Publish thất bại, đã ROLLBACK ạ: `{result.get('error')}`"
        await thinking.update()
        incident_store.set_status(
            report.incident_id, "AUDIT_FAILED_TRIAGE", error=str(result.get("error"))[:900]
        )
        return

    thinking.content = (
        f"🎉 Đã publish xong ạ! `{result.get('prod_table')}`: "
        f"**{result.get('rows_prod_before')}** → **{result.get('rows_prod_after')}** dòng."
    )
    await thinking.update()

    cl.user_session.set("published", True)
    incident_store.set_status(
        report.incident_id, "PUBLISHED_RESOLVED", ready_for_production=True
    )
    ui_state.set_state(status="RESOLVED", maker="idle", checker="idle")

    snapshot = await run_in_threadpool(warehouse_snapshot, plan.target_production_table)
    if snapshot:
        await cl.Message(
            author=AUTHOR_SYSTEM,
            content="### 📊 Trạng thái warehouse sau Publish\n" + snapshot,
        ).send()

    await cl.Message(
        author=AUTHOR_SRE,
        content=(
            f"### ✅ `{report.incident_id}` → **PUBLISHED_RESOLVED**\n"
            f"- 🗂️ Bảng thật đã nhận dữ liệu sạch từ bảng bóng\n"
            f"- 🧊 Dữ liệu bẩn vẫn nằm trong `quarantine_*` để backfill sau\n"
            f"- 💰 Chi phí phiên này: {agent.usage.describe()}\n\n"
            "**Việc cần làm tiếp:** dựng lại các mart hạ nguồn bằng "
            "`dbt run --select <model>` — em cố tình không tự viết SQL rebuild vì để dbt "
            "biên dịch theo lineage thật thì không bị sai tên cột ạ 💚"
        ),
    ).send()

    # ---- TỰ ĐỘNG QUÉT LẠI TOÀN BỘ 3 NGUỒN (Post-Publish Multi-Source Re-scan) ----
    sources_data = await run_in_threadpool(scan_all_sources_status)
    matrix_md = render_multi_source_matrix(sources_data)
    await cl.Message(
        author=AUTHOR_SYSTEM,
        content=(
            "### 📡 Báo Cáo Quét Lại Toàn Bộ 3 Nguồn Dữ Liệu (Post-Publish Multi-Source Re-scan)\n\n"
            f"{matrix_md}"
        ),
    ).send()

    dirty_sources = [s for s in sources_data if s.get("total_viols", 0) > 0]
    if not dirty_sources:
        await cl.Message(
            author=AUTHOR_SRE,
            content=(
                "🎉 **HỆ THỐNG HOÀN TOÀN ỔN ĐỊNH**: Tất cả các nguồn dữ liệu "
                "(`web_checkout`, `mobile_app_v3`, `erp_core`) đều đã **SẠCH 100% (Zero DQ Violations)**! "
                "Mart hạ nguồn sẵn sàng để dbt rebuild."
            ),
        ).send()
    else:
        dirty_labels = [f"`{s['key']}` ({s['total_viols']} vi phạm)" for s in dirty_sources]
        await cl.Message(
            author=AUTHOR_ALERT,
            content=(
                f"⚠️ **Phát hiện sự cố còn tồn tại trên nguồn:** {', '.join(dirty_labels)}.\n\n"
                "Anh bấm nút bên dưới để em chuyển sang khoanh vùng và xử lý ngay nguồn tiếp theo nhé 👇"
            ),
            actions=multi_source_actions(sources_data),
        ).send()


@cl.action_callback("investigate_source")
@cl.action_callback("switch_source")
async def on_investigate_source(action: cl.Action) -> None:
    """Chuyển phiên làm việc của AI sang điều tra nguồn dữ liệu được chọn."""
    await action.remove()
    source_key = str(action.payload.get("source") or action.value or "mobile_app_v3")

    await cl.Message(
        author=AUTHOR_ENGINEER,
        content=f"🔍 **Yêu cầu Agent 1 chuyển sang điều tra nguồn dữ liệu:** `{source_key}`.",
    ).send()

    # Nạp incident của source này
    payload, preloaded_report, source_note = await run_in_threadpool(_resolve_incident_for_source, source_key)
    incident = IncidentInput(**payload)

    severity_val = str(getattr(incident, "severity", None) or "HIGH")
    evidence = getattr(incident, "evidence_payload", {}) or {}
    source_sys = str(evidence.get("source_system", source_key) if isinstance(evidence, dict) else source_key)

    notif_bar = render_notification_bar(
        incident_id=incident.incident_id,
        target_table=incident.target_table,
        source_system=source_sys,
        severity=severity_val,
    )

    await cl.Message(
        author=AUTHOR_ALERT,
        content=(
            f"### 🚨 Chuyển sang Sự Cố: `{incident.incident_id}` (Nguồn `{source_key}`)\n"
            f"- **Loại:** `{incident.incident_type}`\n"
            f"- **Bảng:** `{incident.target_table}`\n"
            f"- **Nguồn alert:** `{incident.source}`\n"
            f"- **Nạp từ:** {source_note}\n\n"
            f"{incident.description}\n\n"
            f"{notif_bar}"
        ),
    ).send()

    agent = DataReliabilityAgent()
    agent.load_incident(incident)
    ui_state.set_state(
        incident_id=incident.incident_id,
        status="INVESTIGATING",
        maker="working",
        audit_verdict=None,
    )
    cl.user_session.set("agent", agent)
    cl.user_session.set("incident", incident)
    cl.user_session.set("auditor", None)
    cl.user_session.set("audit_report", None)
    cl.user_session.set("published", False)
    cl.user_session.set("ready_for_production", False)

    thinking = cl.Message(
        author=AUTHOR_SRE,
        content=f"🔍 Em nhận lệnh chuyển sang nguồn `{source_key}` rồi ạ! Đang điều tra trên DuckDB…",
    )
    await thinking.send()

    try:
        report: AgentReport = await run_agent_with_live_steps(agent, agent.investigate)
    except Exception as exc:  # noqa: BLE001
        ui_state.set_state(status="FAILED", maker="idle", checker="idle")
        thinking.content = f"❌ Em gặp lỗi khi điều tra nguồn `{source_key}` ạ: `{exc}`"
        await thinking.update()
        return

    ui_state.set_state(status="WAITING_FOR_APPROVAL", maker="idle")
    thinking.content = (
        f"✅ Em điều tra xong nguồn `{source_key}` rồi ạ — **{len(agent.tool_events)} lần gọi tool** "
        f"({len(agent.executed_queries())} câu SQL trên DuckDB) 📊\n\n"
        f"💰 Chi phí: {agent.usage.describe()}"
    )
    await thinking.update()
    await send_agent_report(report, agent)


@cl.action_callback("cancel_shadow")
@cl.action_callback("action_cancel_shadow")
async def on_cancel_shadow(action: cl.Action) -> None:
    """[🛑 Huỷ bỏ & Xoá Staging] — dọn bảng bóng, đóng sự cố ở CANCELLED."""
    await action.remove()

    agent: Optional[DataReliabilityAgent] = cl.user_session.get("agent")
    report: Optional[AgentReport] = cl.user_session.get("report")
    if agent is None or report is None:
        await cl.Message(author=AUTHOR_SYSTEM, content="Không tìm thấy phiên xử lý.").send()
        return

    result = await run_in_threadpool(agent.cancel_shadow, "engineer huỷ trên Chainlit")
    incident_store.set_status(report.incident_id, "CANCELLED", error="Engineer huỷ phương án")
    cl.user_session.set("triage", False)
    await cl.Message(
        author=AUTHOR_SRE,
        content=result.get("summary") or "🗑️ Đã dọn bảng bóng ạ.",
    ).send()


@cl.action_callback("action_manual_sql")
async def on_action_manual_sql(action: cl.Action) -> None:
    """[✏️ Sửa SQL Thủ Công] — hướng dẫn engineer nhập SQL hoặc mở SQL Studio."""
    await action.remove()
    await cl.Message(
        author=AUTHOR_SYSTEM,
        content=(
            "✏️ **Sửa SQL thủ công**:\n"
            "- Anh có thể nhập trực tiếp câu lệnh SQL vào khung chat này (bắt đầu bằng `SQL:` hoặc paste code block SQL).\n"
            "- Hoặc chuyển sang tab **Remediation Matrix** / **SQL Studio** trên Dashboard để chỉnh sửa và chạy trực tiếp trên Staging."
        ),
    ).send()


@cl.action_callback("replan_agent")
@cl.action_callback("action_replan")
async def on_replan_agent(action: cl.Action) -> None:
    """[🤖 Cho Agent 1 Re-plan] — Bounded Reflection Loop, tối đa 1 lượt."""
    await action.remove()

    agent: Optional[DataReliabilityAgent] = cl.user_session.get("agent")
    report: Optional[AgentReport] = cl.user_session.get("report")
    if agent is None or report is None:
        await cl.Message(author=AUTHOR_SYSTEM, content="Không tìm thấy phiên xử lý.").send()
        return

    row = await run_in_threadpool(incident_store.get_incident, report.incident_id)
    failed_details = ((row or {}).get("audit") or {}).get("failed_details") or {
        "error_message": str((row or {}).get("error") or "")
    }

    thinking = cl.Message(
        author=AUTHOR_SRE,
        content="🔁 Em đọc lại lỗi của chị Auditor, soi `DESCRIBE` bảng rồi viết script v2 ạ…",
    )
    await thinking.send()

    result = await run_agent_with_live_steps(
        agent, lambda: agent.replan_with_feedback(failed_details, agent.retry_count)
    )
    thinking.content = result.get("summary") or "_(không có tổng kết)_"
    await thinking.update()

    if not result.get("allowed"):
        await cl.Message(
            author=AUTHOR_SYSTEM,
            content=(
                "⛔ Hết lượt re-plan. Anh sửa SQL tay ở **SQL Studio** trên dashboard (`/`), "
                "hoặc escalate cho on-call theo runbook nhé."
            ),
        ).send()
        return

    new_report = AgentReport.model_validate(result.get("report") or {})
    cl.user_session.set("report", new_report)
    incident_store.set_status(
        report.incident_id,
        result.get("status") or "WAITING_SHADOW_APPROVAL",
        report_json=new_report.model_dump_json(),
        retry_count=result.get("retry_count"),
        ready_for_production=False,
    )
    await cl.Message(author=AUTHOR_SRE, content=new_report.to_markdown()).send()
    if new_report.remediation.is_stageable:
        await cl.Message(
            author=AUTHOR_SYSTEM,
            content="Anh xem plan v2 rồi duyệt chạy thử lại giúp em nhé 🙆‍♀️",
            actions=approval_actions(),
        ).send()


@cl.action_callback("reject")
async def on_reject(action: cl.Action) -> None:
    """[❌ Từ chối] — không thực thi gì, hỏi lý do rồi để Agent 1 re-plan."""
    await action.remove()

    agent: Optional[DataReliabilityAgent] = cl.user_session.get("agent")
    if agent is None:
        await cl.Message(author=AUTHOR_SYSTEM, content="Không tìm thấy phiên điều tra.").send()
        return

    report: Optional[AgentReport] = cl.user_session.get("report")
    if report is not None:
        tools.lock_remediation(report.incident_id)
    agent.status = IncidentStatus.REJECTED
    cl.user_session.set("awaiting_reject_reason", True)
    ui_state.set_state(status="REJECTED", maker="idle")

    await cl.Message(
        author=AUTHOR_ENGINEER,
        content="❌ **REJECTED** — chưa thực thi bất kỳ thay đổi nào trên DuckDB.",
    ).send()
    await cl.Message(
        author=AUTHOR_SRE,
        content=(
            "🙇‍♀️ Dạ em hiểu rồi. Anh cho em biết **lý do từ chối** hoặc ràng buộc anh muốn nhé "
            "(ví dụ: *“không được xoá dòng nào, chỉ được đánh dấu”*, *“phải giữ nguyên doanh thu "
            "ngày 15/09”*, *“chờ team Mobile fix rồi backfill”*). Em sẽ điều tra lại và đề xuất "
            "phương án khác ngay ạ 💪"
        ),
    ).send()


@cl.action_callback("audit")
async def on_audit(action: cl.Action) -> None:
    """
    [🕵️‍♀️ Recheck / Nghiệm thu độc lập] — engineer CHỌN cho Agent 2 vào kiểm.

    Dùng cho cả 2 tình huống:
      - ngay sau khi Agent 1 vá xong (trả lời "có recheck"),
      - hoặc chạy lại bất cứ lúc nào sau đó.
    """
    await action.remove()
    if cl.user_session.get("agent") is None:
        await cl.Message(author=AUTHOR_SYSTEM, content="Chưa có ca nào để nghiệm thu ạ 🙏").send()
        return

    first_time = bool(cl.user_session.get("awaiting_recheck_decision"))
    cl.user_session.set("awaiting_recheck_decision", False)
    cl.user_session.set("audit_skipped", False)

    report: Optional[AgentReport] = cl.user_session.get("report")
    await run_in_threadpool(
        data_audit.log_tool_call,
        "human_decision",
        "REQUEST_RECHECK",
        f"incident={report.incident_id if report else '?'}",
        "ok",
        "Engineer yêu cầu Agent 2 nghiệm thu độc lập",
    )
    await cl.Message(
        author=AUTHOR_ENGINEER,
        content="🕵️‍♀️ **YÊU CẦU RECHECK** — cho Agent 2 nghiệm thu độc lập.",
    ).send()
    await run_independent_audit(trigger="auto" if first_time else "manual")


@cl.action_callback("skip_audit")
async def on_skip_audit(action: cl.Action) -> None:
    """
    [⚡ Không cần, chốt luôn] — đóng incident mà KHÔNG chạy Agent 2.

    Dùng khi engineer đã biết rõ lỗi đơn giản, không cần tốn thêm thời gian/token cho
    vòng nghiệm thu độc lập. Quyết định này được ghi vào `agent_audit_log` để sau này
    truy được: ca nào đã bỏ qua Checker và ai bỏ qua.
    """
    await action.remove()

    report: Optional[AgentReport] = cl.user_session.get("report")
    if report is None:
        await cl.Message(author=AUTHOR_SYSTEM, content="Chưa có ca nào để chốt ạ 🙏").send()
        return

    cl.user_session.set("awaiting_recheck_decision", False)
    cl.user_session.set("audit_skipped", True)
    cl.user_session.set("resolved", True)

    await run_in_threadpool(
        data_audit.log_tool_call,
        "human_decision",
        "SKIP_RECHECK",
        f"incident={report.incident_id}",
        "ok",
        "Engineer chốt luôn, bỏ qua nghiệm thu độc lập của Agent 2",
    )

    await cl.Message(
        author=AUTHOR_ENGINEER,
        content="⚡ **CHỐT LUÔN** — bỏ qua bước recheck của Agent 2.",
    ).send()

    agent: Optional[DataReliabilityAgent] = cl.user_session.get("agent")
    usage = agent.usage.describe() if agent else "n/a"
    snapshot = await run_in_threadpool(warehouse_snapshot, report.target_table)

    await cl.Message(
        author=AUTHOR_SYSTEM,
        content=(
            f"### ✅ Incident `{report.incident_id}` → **RESOLVED** (không recheck)\n"
            f"- 🛠️ Hành động: `{report.remediation.action_type.value}`\n"
            f"- 🧾 Agent 1 tự verify: vi phạm về **0**\n"
            f"- 💰 Tổng chi phí: {usage} _(tiết kiệm được cả lượt Agent 2)_\n"
            + (f"\n{snapshot}\n" if snapshot else "")
            + "\n⚠️ **Lưu ý cho hồ sơ:** ca này **chưa qua nghiệm thu độc lập**, nên bằng "
            "chứng duy nhất là lời tự verify của Agent 1. Quyết định bỏ qua đã được ghi vào "
            "`agent_audit_log` (`human_decision` / `SKIP_RECHECK`) để audit sau này truy được.\n\n"
            "Đổi ý thì anh bấm nút dưới đây, em cho Agent 2 vào soi lại bất cứ lúc nào ạ 🙆‍♀️"
        ),
        actions=audit_actions(),
    ).send()


@cl.action_callback("action_scan_dq")
async def on_action_scan_dq(action: cl.Action) -> None:
    """[🔍 Quét lại toàn diện DQ] — quét kiểm tra trực tiếp trên DuckDB cả 3 nguồn."""
    await action.remove()
    sources_status = await run_in_threadpool(scan_all_sources_status)
    matrix_md = render_multi_source_matrix(sources_status)
    total_viols = sum(s.get("viol_cnt", 0) for s in sources_status)

    if total_viols == 0:
        await cl.Message(
            author=AUTHOR_SYSTEM,
            content=f"### 🔍 Kết Quả Quét Data Quality Toàn Diện\n\n{matrix_md}\n\n🟢 **Tất cả các nguồn dữ liệu đều hoàn toàn sạch (0 vi phạm)!**",
            actions=healthy_action_chips(),
        ).send()
    else:
        await cl.Message(
            author=AUTHOR_SYSTEM,
            content=f"### 🚨 Phát Hiện Lỗi Dữ Liệu Khi Quét DQ!\n\n{matrix_md}\n\nĐang tự động khởi tạo luồng SRE điều tra...",
        ).send()
        payload, preloaded_report, source_note = await run_in_threadpool(_resolve_incident)
        if payload:
            incident = IncidentInput(**payload)
            evidence = getattr(incident, "evidence_payload", {}) or {}
            source_sys = str(evidence.get("source_system", "web_checkout") if isinstance(evidence, dict) else "web_checkout")
            cl.user_session.set("incident_id", incident.incident_id)
            await _start_investigation_flow(incident, source_sys, preloaded_report=preloaded_report, source_note=source_note)


@cl.action_callback("action_data_profile")
async def on_action_data_profile(action: cl.Action) -> None:
    """[📊 Xem Data Profile] — xem số liệu thực tế trên DuckDB."""
    await action.remove()

    def _get_profile() -> tuple[Any, List[Any]]:
        con = tools.get_connection()
        row = con.execute("""
            SELECT 
                COUNT(*) as total_rows,
                COUNT(DISTINCT source_system) as sources_count,
                MIN(order_date) as min_ts,
                MAX(order_date) as max_ts,
                COALESCE(SUM(total_amount), 0) as total_revenue,
                COUNT(CASE WHEN order_status = 'COMPLETED' THEN 1 END) as completed_cnt
            FROM fact_orders
        """).fetchone()
        src_rows = con.execute("""
            SELECT 
                source_system, 
                COUNT(*) as cnt, 
                COUNT(CASE WHEN customer_id IS NULL THEN 1 END) as null_cust, 
                COUNT(CASE WHEN total_amount < 0 THEN 1 END) as neg_amt
            FROM fact_orders
            GROUP BY source_system
            ORDER BY source_system
        """).fetchall()
        return row, src_rows

    row, src_rows = await run_in_threadpool(_get_profile)
    profile_md = (
        f"### 📊 Data Profile Snapshot — `main.fact_orders`\n\n"
        f"- 📦 **Tổng số bản ghi**: `{row[0]:,}` dòng\n"
        f"- 🌐 **Số nguồn active**: `{row[1]}` nguồn\n"
        f"- 📅 **Khoảng thời gian**: `{row[2]}` → `{row[3]}`\n"
        f"- 💵 **Tổng doanh thu ghi nhận**: `${row[4]:,.2f}`\n"
        f"- ✅ **Đơn hoàn thành**: `{row[5]:,}` đơn\n\n"
        f"**Phân bổ chi tiết theo từng nguồn:**\n\n"
        f"| Nguồn dữ liệu | Tổng số dòng | Lỗi NULL customer | Lỗi Amount âm |\n"
        f"| :--- | :--- | :--- | :--- |"
    )
    for src in src_rows:
        profile_md += f"\n| `{src[0]}` | {src[1]:,} | {src[2]} | {src[3]} |"

    await cl.Message(
        author=AUTHOR_SYSTEM,
        content=profile_md,
        actions=healthy_action_chips(),
    ).send()


@cl.action_callback("action_inject_defect")
async def on_action_inject_defect(action: cl.Action) -> None:
    """[⚡ Cấy Lỗi Mẫu Để Thử Nghiệm] — chủ động sinh lỗi dữ liệu thực tế."""
    await action.remove()
    target_source = (action.payload or {}).get("source") or "mobile_app_v3"
    if target_source in ("auto", "all"):
        target_source = "mobile_app_v3"

    defect_type = (
        "null_customer_id"
        if target_source == "mobile_app_v3"
        else ("negative_amount" if target_source == "web_checkout" else "duplicate_order")
    )

    thinking = cl.Message(
        author=AUTHOR_SYSTEM,
        content=f"⚡ Đang cấy 15 dòng lỗi mẫu (`{defect_type}`) vào nguồn `{target_source}` để thử nghiệm...",
    )
    await thinking.send()

    from data.jobs.inject_defect import inject_custom_defect
    res = await run_in_threadpool(
        inject_custom_defect,
        source=target_source,
        defect_type=defect_type,
        rows=15,
        notify=True,
    )

    thinking.content = (
        f"🚨 **Đã cấy thành công {res.get('total_injected_rows', 15)} dòng lỗi vào nguồn `{target_source}`!**\n\n"
        f"Hệ thống phát hiện vi phạm và đang khởi tạo luồng SRE điều tra tự động..."
    )
    await thinking.update()

    payload, preloaded_report, source_note = await run_in_threadpool(_resolve_incident_for_source, target_source)
    if payload:
        incident = IncidentInput(**payload)
        evidence = getattr(incident, "evidence_payload", {}) or {}
        source_sys = str(evidence.get("source_system", target_source) if isinstance(evidence, dict) else target_source)
        cl.user_session.set("incident_id", incident.incident_id)
        await _start_investigation_flow(incident, source_sys, preloaded_report=preloaded_report, source_note=source_note)


@cl.action_callback("switch_source")
async def on_switch_source(action: cl.Action) -> None:
    """[📱 Chuyển Nguồn] — Xem trạng thái hoặc sự cố riêng biệt của từng nguồn."""
    await action.remove()
    source_key = (action.payload or {}).get("source") or action.value or "web_checkout"

    payload, preloaded_report, source_note = await run_in_threadpool(_resolve_incident_for_source, source_key)
    if source_note == "clean" or payload is None:
        sources_data = await run_in_threadpool(scan_all_sources_status)
        agent: Optional[DataReliabilityAgent] = cl.user_session.get("agent")
        maker_model = agent.settings.model if agent else "?"
        checker_settings = LLMSettings.for_auditor(avoid_model=maker_model)

        welcome_text = render_healthy_landing_card(
            source_key=source_key,
            sources_data=sources_data,
            maker_model=maker_model,
            checker_model=checker_settings.model,
        )
        await cl.Message(
            author=AUTHOR_SYSTEM,
            content=welcome_text,
            actions=healthy_action_chips(source_key),
        ).send()
        return

    incident = IncidentInput(**payload)
    evidence = getattr(incident, "evidence_payload", {}) or {}
    source_sys = str(evidence.get("source_system", source_key) if isinstance(evidence, dict) else source_key)
    cl.user_session.set("incident_id", incident.incident_id)
    await _start_investigation_flow(incident, source_sys, preloaded_report=preloaded_report, source_note=source_note)

