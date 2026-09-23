/**
 * render.js — Render toàn bộ state lên DOM (hàm thuần, không mutate dữ liệu)
 */

import { esc, formatNumber, formatRelativeTime, formatTime } from './format.js';
import { renderLineageSvg } from './lineage.js';
import { renderSourceTabs } from './copilot.js';

export function render(state) {
  if (!state) return;

  renderTopbar(state);
  renderNotifications(state);
  renderHero(state);
  renderKpis(state.kpis);
  renderSources(state.sources);
  renderSourceTabs(state.sources);
  renderSquadAndGuardrails(state.system);
  renderLineage(state.lineage);
  renderTables(state.tables);
  renderIncidentsTab(state);
  renderDqTests(state.dq_tests);
  renderActivity(state.activity);

  const chip = document.getElementById('dockContextChip');
  if (chip && !chip.innerHTML.includes('📍 Ngữ cảnh:')) {
    if (state.incident) {
      const srcName = state.incident.source || 'web_checkout';
      chip.innerHTML = `📍 Ngữ cảnh: <strong style="color:#a5b4fc;font-weight:700;">${srcName}</strong> · <span style="font-family:'JetBrains Mono',monospace;color:var(--text,#f8fafc);font-weight:600;">${state.incident.id || 'INC-2026-DQ01'}</span>`;
    }
  }
}

function renderTopbar(state) {
  const chipsEl = document.getElementById('topbarSystemChips');
  if (!chipsEl) return;

  const whRows = state.system?.warehouse?.fact_orders_rows ?? state.kpis?.total_rows ?? 0;
  const isCross = state.system?.models?.cross_model_enabled;
  const notifEmail = state.system?.notifications?.email === 'live';
  const notifZalo = state.system?.notifications?.zalo === 'live';
  const notifTele = state.system?.notifications?.telegram === 'live';
  const notifLabel = (notifEmail || notifZalo || notifTele) ? 'Live' : 'dry-run';
  const notifClass = (notifEmail || notifZalo || notifTele) ? '' : 'warn';

  chipsEl.innerHTML = `
    <div class="chip-sys" title="${esc(state.system?.warehouse?.path)}">
      <span class="status-dot dot-healthy"></span>
      <span>Warehouse: <strong>${formatNumber(whRows)} dòng</strong></span>
    </div>
    <div class="chip-sys ${notifClass}" title="Email: ${notifEmail ? 'Live' : 'Mock'} | Zalo: ${notifZalo ? 'Live' : 'Mock'} | Tele: ${notifTele ? 'Live' : 'Mock'}">
      <span>Notify: <strong>${notifLabel}</strong></span>
    </div>
    <div class="chip-sys ${isCross ? '' : 'warn'}" title="Maker: ${esc(state.system?.models?.maker?.model)} | Checker: ${esc(state.system?.models?.checker?.model)}">
      <span>Cross-model: <strong>${isCross ? 'Bật' : 'Tắt'}</strong></span>
    </div>
  `;
}

function renderNotifications(state) {
  const notifBadge = document.getElementById('notifBadge');
  const notifHeaderCount = document.getElementById('notifHeaderCount');
  const notifList = document.getElementById('notifList');
  const tabBadge = document.getElementById('tabIncidentsBadge');
  if (!notifList) return;

  const inc = state.incident;
  const dqFails = (state.dq_tests || []).filter(t => t.status === 'fail');
  const notifEmail = state.system?.notifications?.email === 'live';
  const notifZalo = state.system?.notifications?.zalo === 'live';
  const notifTele = state.system?.notifications?.telegram === 'live';

  const items = [];

  if (inc) {
    items.push({
      type: 'high',
      title: `<span class="chip-sev sev-high" style="font-size: 9px; padding: 1px 4px;">HIGH</span> ${esc(inc.id)} · ${esc(inc.title || 'Sự cố dữ liệu')}`,
      body: `Bảng: <code>${esc(inc.target_table || 'fact_orders')}</code> · Nguồn: <code>${esc(inc.source || 'mobile_app_v3')}</code> · Blast: ${esc((inc.blast_radius || []).join(', '))}`,
      time: 'Vừa xong',
      channels: [
        { name: 'Email', active: notifEmail, mode: notifEmail ? 'Live' : 'Dry-run' },
        { name: 'Zalo', active: notifZalo, mode: notifZalo ? 'Live' : 'Dry-run' }
      ],
      actions: [
        { label: 'Mở Copilot duyệt →', primary: true, fn: `window.openCopilotWithContext?.('${esc(inc.source || 'mobile_app_v3')}')` },
        { label: 'Xem sự cố', primary: false, fn: `window.switchToTab?.('tabIncidents')` }
      ]
    });
  }

  if (dqFails.length > 0) {
    dqFails.forEach(t => {
      items.push({
        type: 'warn',
        title: `<span class="chip-sev sev-med" style="font-size: 9px; padding: 1px 4px;">DQ</span> ${esc(t.test_name)} không đạt`,
        body: `Cột <code>${esc(t.column)}</code> vi phạm ${formatNumber(t.failures)} dòng trong ${esc(t.test_name)}.`,
        time: formatRelativeTime(t.last_run_at),
        channels: [],
        actions: [
          { label: 'Xem DQ tests', primary: false, fn: `window.switchToTab?.('tabDq')` }
        ]
      });
    });
  }

  // System status notification item
  items.push({
    type: 'info',
    title: 'Hệ thống Maker · Checker v2.0',
    body: `Maker (${esc(state.system?.models?.maker?.model || 'LLM')}) · Checker (${esc(state.system?.models?.checker?.model || 'LLM')}) · Cross-model: ${state.system?.models?.cross_model_enabled ? 'Bật' : 'Tắt'}`,
    time: '24/7',
    channels: [],
    actions: []
  });

  const unreadCount = (inc ? 1 : 0) + dqFails.length;

  if (notifBadge) {
    notifBadge.textContent = unreadCount > 0 ? unreadCount : '';
    notifBadge.style.display = unreadCount > 0 ? 'flex' : 'none';
  }
  if (tabBadge) {
    tabBadge.textContent = unreadCount > 0 ? unreadCount : '0';
    tabBadge.style.display = unreadCount > 0 ? 'inline-block' : 'none';
  }
  if (notifHeaderCount) {
    notifHeaderCount.textContent = unreadCount > 0 ? `${unreadCount} cảnh báo` : '0 cảnh báo';
    notifHeaderCount.style.background = unreadCount > 0 ? 'var(--danger-weak)' : 'var(--surface-3)';
    notifHeaderCount.style.color = unreadCount > 0 ? 'var(--danger)' : 'var(--text-muted)';
  }

  notifList.innerHTML = items.map(item => `
    <div class="notif-item notif-${item.type}">
      <div class="notif-item-top">
        <span class="notif-item-title">${item.title}</span>
        <span class="type-mono-sm text-subtle" style="font-size: 10px;">${item.time}</span>
      </div>
      <div class="notif-item-body">${item.body}</div>
      ${(item.channels.length > 0 || item.actions.length > 0) ? `
        <div class="notif-item-footer">
          <div class="notif-channels">
            ${item.channels.map(c => `
              <span class="chip-channel ${c.active ? 'active' : ''}" title="${c.name}: ${c.mode}">
                ${c.name}: ${c.mode}
              </span>
            `).join('')}
          </div>
          <div class="notif-item-actions">
            ${item.actions.map(act => `
              <button class="btn-notif-action ${act.primary ? 'btn-notif-primary' : ''}" onclick="${act.fn}">
                ${act.label}
              </button>
            `).join('')}
          </div>
        </div>
      ` : ''}
    </div>
  `).join('');
}

function renderHero(state) {
  const heroEl = document.getElementById('incidentHero');
  if (!heroEl) return;

  const inc = state.incident;
  if (!inc) {
    heroEl.className = 'hero-card hero-healthy';
    heroEl.innerHTML = `
      <div class="hero-head">
        <div>
          <div class="hero-meta">
            <span class="status-pill status-healthy"><span class="status-dot dot-healthy"></span> Hoàn toàn bình thường</span>
          </div>
          <div class="hero-title">Tất cả nguồn dữ liệu sạch và hoạt động ổn định</div>
          <div class="hero-sub">Không có sự cố nào đang mở · DQ tests gần nhất: ${state.kpis?.tests_passed ?? 6}/${state.kpis?.tests_total ?? 6} pass</div>
        </div>
        <div class="hero-actions">
          <button class="btn-primary" onclick="window.triggerDqRun?.()">
            <svg class="icon"><use href="/static/dashboard/icons.svg#icon-refresh-cw"></use></svg>
            <span>Chạy lại DQ tests</span>
          </button>
        </div>
      </div>
    `;
    return;
  }

  const status = inc.status || 'WAITING_FOR_APPROVAL';
  const statusMap = {
    'INVESTIGATING': { cls: 'hero-investigating', pill: 'Đang điều tra', pillCls: 'status-investigating', cta: 'Xem tiến trình' },
    'WAITING_FOR_APPROVAL': { cls: 'hero-incident', pill: 'Có sự cố · chờ duyệt', pillCls: 'status-incident', cta: 'Xem báo cáo & duyệt' },
    'EXECUTING': { cls: 'hero-investigating', pill: 'Đang vá dữ liệu', pillCls: 'status-investigating', cta: 'Xem tiến trình' },
    'AUDITING': { cls: 'hero-auditing', pill: 'Checker đang nghiệm thu', pillCls: 'status-investigating', cta: 'Xem nghiệm thu' },
    'RESOLVED': { cls: 'hero-resolved', pill: 'Đã xử lý · đã nghiệm thu', pillCls: 'status-resolved', cta: 'Xem biên bản' },
    'REJECTED': { cls: 'hero-card', pill: 'Đã từ chối', pillCls: 'status-sleep', cta: 'Yêu cầu phương án khác' },
    'FAILED': { cls: 'hero-incident', pill: 'Thất bại', pillCls: 'status-incident', cta: 'Thử lại' },
  };

  const st = statusMap[status] || statusMap['WAITING_FOR_APPROVAL'];
  heroEl.className = `hero-card ${st.cls}`;

  const stepperHtml = renderStepper(status, inc.audit_verdict);

  heroEl.innerHTML = `
    <div class="hero-head">
      <div>
        <div class="hero-meta">
          <span class="chip-sev sev-high">${esc(inc.severity || 'HIGH')}</span>
          <span class="status-pill ${st.pillCls}">
            <span class="status-dot dot-${st.pillCls.replace('status-', '')}"></span>
            ${st.pill}
          </span>
          <span class="type-mono-sm text-muted">${esc(inc.id)}</span>
        </div>
        <div class="hero-title">${esc(inc.title || '15 dòng customer_id NULL trong fact_orders')}</div>
        <div class="hero-sub">
          <strong>${esc(inc.target_table)}</strong> · nguồn <code>${esc(inc.source)}</code> · phát hiện ${formatRelativeTime(inc.detected_at)} · Blast radius: <strong>${(inc.blast_radius || []).join(', ')}</strong>
        </div>
      </div>
      <div class="hero-actions">
        <button class="btn-primary" onclick="window.openCopilotWithContext?.('${esc(inc.source)}')">
          <svg class="icon"><use href="/static/dashboard/icons.svg#icon-search-check"></use></svg>
          <span>${st.cta}</span>
        </button>
      </div>
    </div>
    ${stepperHtml}
  `;
}

function renderStepper(status, auditVerdict) {
  const steps = [
    { key: 'detect', label: 'Phát hiện', actor: 'dbt alert' },
    { key: 'investigate', label: 'Điều tra', actor: 'Maker' },
    { key: 'approve', label: 'Chờ duyệt', actor: 'Con người', isHuman: true },
    { key: 'remediate', label: 'Vá', actor: 'Maker' },
    { key: 'audit', label: 'Nghiệm thu', actor: 'Checker', isChecker: true },
    { key: 'done', label: 'Hoàn tất', actor: 'SRE Ops' },
  ];

  // Derive step states
  let activeIndex = 2; // WAITING_FOR_APPROVAL by default
  let isError = false;

  if (status === 'INVESTIGATING') activeIndex = 1;
  else if (status === 'WAITING_FOR_APPROVAL') activeIndex = 2;
  else if (status === 'EXECUTING') activeIndex = 3;
  else if (status === 'AUDITING') activeIndex = 4;
  else if (status === 'RESOLVED') activeIndex = auditVerdict === 'AUDIT_FAILED' ? 4 : 5;
  else if (status === 'REJECTED') { activeIndex = 2; isError = true; }
  else if (status === 'FAILED') { activeIndex = 3; isError = true; }

  let html = '<div class="stepper-wrap"><div class="stepper">';
  steps.forEach((s, idx) => {
    let stateClass = '';
    if (idx < activeIndex || (status === 'RESOLVED' && idx === 5 && auditVerdict !== 'AUDIT_FAILED')) {
      stateClass = 'step-done';
    } else if (idx === activeIndex) {
      stateClass = isError ? 'step-error' : 'step-active';
      if (s.isHuman) stateClass += ' step-human';
      if (s.isChecker) stateClass += ' step-checker';
    }

    let iconHtml = `${idx + 1}`;
    if (stateClass.includes('step-done')) {
      iconHtml = '<svg class="icon icon-14"><use href="/static/dashboard/icons.svg#icon-circle-check"></use></svg>';
    } else if (stateClass.includes('step-error')) {
      iconHtml = '<svg class="icon icon-14"><use href="/static/dashboard/icons.svg#icon-x"></use></svg>';
    }

    html += `
      <div class="step-item ${stateClass}">
        <div class="step-circle">${iconHtml}</div>
        <div>
          <span class="step-label">${esc(s.label)}</span>
          <span class="step-actor">${esc(s.actor)}</span>
        </div>
      </div>
    `;
    if (idx < steps.length - 1) {
      html += '<div class="step-divider"></div>';
    }
  });
  html += '</div></div>';
  return html;
}

function renderKpis(kpis) {
  if (!kpis) return;

  const totalEl = document.getElementById('kpiTotalRows');
  if (totalEl) totalEl.textContent = formatNumber(kpis.total_rows);

  const violEl = document.getElementById('kpiViolatingRows');
  const violSubEl = document.getElementById('kpiViolatingSub');
  if (violEl) {
    violEl.textContent = formatNumber(kpis.violating_rows);
    violEl.className = `kpi-value ${kpis.violating_rows > 0 ? 'text-danger' : 'text-ok'}`;
  }
  if (violSubEl) {
    violSubEl.textContent = kpis.violating_rows > 0 ? 'not_null_customer_id' : '0 lỗi vi phạm';
  }

  const quarEl = document.getElementById('kpiQuarantined');
  const quarSubEl = document.getElementById('kpiQuarantinedSub');
  if (quarEl) {
    quarEl.textContent = `${formatNumber(kpis.quarantined_rows)} dòng`;
  }
  if (quarSubEl) {
    quarSubEl.textContent = kpis.quarantined_rows > 0 ? 'đã cách ly an toàn' : 'chờ cách ly khi có sự cố';
  }

  const dqEl = document.getElementById('kpiDqTests');
  const dqSubEl = document.getElementById('kpiDqSub');
  if (dqEl) {
    dqEl.textContent = `${kpis.tests_passed} / ${kpis.tests_total}`;
  }
  if (dqSubEl) {
    const failed = (kpis.tests_total || 6) - (kpis.tests_passed || 0);
    dqSubEl.textContent = failed > 0 ? `${failed} test không đạt` : 'tất cả test đều đạt';
  }
}


function renderSources(sources) {
  const container = document.getElementById('sourcesGrid');
  if (!container || !sources) return;

  const total = sources.reduce((acc, s) => acc + (s.rows || 0), 0) || 1;
  const iconMap = {
    'erp_core': 'icon-database',
    'web_checkout': 'icon-shopping-cart',
    'mobile_app_v3': 'icon-smartphone',
  };

  container.innerHTML = sources.map(s => {
    const isIncident = s.status === 'incident' || (s.violations || 0) > 0;
    const ratio = Math.round(((s.rows || 0) / total) * 100);
    const iconId = iconMap[s.key] || 'icon-database';
    const desc = isIncident 
      ? `Phát hiện ${formatNumber(s.violations)} dòng vi phạm DQ trong fact_orders.` 
      : `Luồng giao dịch đồng bộ định kỳ bình thường.`;

    const defectType = s.key === 'mobile_app_v3' 
      ? 'null_customer_id' 
      : (s.key === 'web_checkout' ? 'negative_amount' : 'duplicate_order');

    return `
      <div class="source-card ${isIncident ? 'source-incident' : ''}">
        <div>
          <div class="source-card-head">
            <div class="source-name-wrap">
              <svg class="icon"><use href="/static/dashboard/icons.svg#${iconId}"></use></svg>
              <span class="source-name">${esc(s.name)}</span>
              <span class="source-version">${esc(s.version)}</span>
            </div>
            <span class="status-pill status-${isIncident ? 'incident' : 'healthy'}">
              <span class="status-dot dot-${isIncident ? 'incident' : 'healthy'}"></span>
              ${isIncident ? `Có sự cố (${s.violations} lỗi)` : 'Bình thường'}
            </span>
          </div>
          <div class="source-desc">${desc}</div>
        </div>

        <div>
          <div class="source-stats">
            <div>
              <div class="stat-col-label">Tổng dòng</div>
              <div class="stat-col-val">${formatNumber(s.rows)}</div>
              <div class="source-ratio-bar"><div class="source-ratio-fill" style="width: ${ratio}%;"></div></div>
            </div>
            <div>
              <div class="stat-col-label">Vi phạm DQ</div>
              <div class="stat-col-val ${s.violations > 0 ? 'text-danger' : 'text-ok'}">${formatNumber(s.violations)}</div>
            </div>
            <div>
              <div class="stat-col-label">Đồng bộ</div>
              <div class="stat-col-val" style="font-size: 11px;">${formatRelativeTime(s.last_ingested_at)}</div>
            </div>
          </div>
          <div class="source-card-footer" style="display: flex; justify-content: space-between; align-items: center; margin-top: 10px; padding-top: 8px; border-top: 1px solid var(--border-subtle);">
            <button class="btn-source-inject" onclick="event.stopPropagation(); window.injectDefect('${s.key}', '${defectType}')" title="Chủ động cấy lỗi vào nguồn này để test">
              ⚡ Cấy lỗi nguồn này
            </button>
            <button class="btn-text text-accent" style="font-size: 11px; font-weight: 600;" onclick="window.openCopilotWithContext?.('${esc(s.key)}')">
              Mở Copilot →
            </button>
          </div>
        </div>
      </div>
    `;
  }).join('');
}

function renderSquadAndGuardrails(sys) {
  const container = document.getElementById('squadGuardrailsPanel');
  if (!container || !sys) return;

  const makerModel = sys.models?.maker?.model || 'gpt-4o';
  const checkerModel = sys.models?.checker?.model || 'claude-3-5-sonnet';
  const isUnlocked = sys.remediation_unlocked;
  const isCross = sys.models?.cross_model_enabled;

  container.innerHTML = `
    <div class="squad-list">
      <div class="squad-member">
        <div class="member-avatar avatar-maker">M</div>
        <div class="member-info">
          <div class="member-title-row">
            <span>Maker · Agent 1 (Data SRE)</span>
            <span class="member-model">${esc(makerModel)}</span>
          </div>
          <div class="member-desc">đọc + ghi (chỉ sau khi anh duyệt)</div>
        </div>
      </div>

      <div class="squad-member">
        <div class="member-avatar avatar-checker">C</div>
        <div class="member-info">
          <div class="member-title-row">
            <span>Checker · Agent 2 (Auditor)</span>
            <span class="member-model">${esc(checkerModel)}</span>
          </div>
          <div class="member-desc">chỉ đọc · nghiệm thu độc lập</div>
        </div>
      </div>
    </div>

    <div class="guardrails-list">
      <div class="guardrail-row">
        <div class="guardrail-title">
          <svg class="icon"><use href="/static/dashboard/icons.svg#${isUnlocked ? 'icon-lock-open' : 'icon-lock'}"></use></svg>
          <span>Ghi dữ liệu</span>
        </div>
        <span class="guardrail-status ${isUnlocked ? 'text-warn' : 'text-muted'}">${isUnlocked ? 'Đã mở cho lần vá này' : 'Đang khoá — chờ anh duyệt'}</span>
      </div>

      <div class="guardrail-row">
        <div class="guardrail-title">
          <svg class="icon"><use href="/static/dashboard/icons.svg#icon-lock"></use></svg>
          <span>Checker chỉ đọc</span>
        </div>
        <span class="guardrail-status text-muted">Không có tool ghi</span>
      </div>

      <div class="guardrail-row">
        <div class="guardrail-title">
          <svg class="icon"><use href="/static/dashboard/icons.svg#icon-shield-check"></use></svg>
          <span>Cross-model</span>
        </div>
        <span class="guardrail-status ${isCross ? 'text-ok' : 'text-warn'}">${isCross ? 'Bật · Maker ≠ Checker' : 'Tắt · cùng điểm mù'}</span>
      </div>

      <div class="guardrail-row">
        <div class="guardrail-title">
          <svg class="icon"><use href="/static/dashboard/icons.svg#icon-circle-check"></use></svg>
          <span>Đối chiếu bằng Python</span>
        </div>
        <span class="guardrail-status text-ok">Máy thắng khi lệch LLM</span>
      </div>
    </div>
  `;
}

function renderLineage(lineage) {
  const el = document.getElementById('lineageSvgContainer');
  if (el) {
    renderLineageSvg(el, lineage);
  }
}

function renderTables(tables) {
  const tbody = document.getElementById('tablesTableBody');
  if (!tbody || !tables) return;

  tbody.innerHTML = tables.map(t => `
    <tr>
      <td>
        <span class="badge-layer">${esc((t.layer || '').toUpperCase())}</span>
        <code>${esc(t.name)}</code>
      </td>
      <td class="num">${formatNumber(t.rows)}</td>
      <td>
        <span class="status-pill status-${t.dq === 'pass' ? 'healthy' : (t.dq === 'fail' ? 'incident' : 'sleep')}">
          ${t.dq === 'pass' ? 'Đạt (0 lỗi)' : (t.dq === 'fail' ? `Không đạt (${t.failed_tests || 1} lỗi)` : (t.dq === 'stale' ? 'Cần rebuild' : 'Chờ'))}
        </span>
      </td>
      <td>${formatRelativeTime(t.updated_at)}</td>
      <td class="text-muted" style="font-size: 12px;">${esc(t.recommendation || '—')}</td>
    </tr>
  `).join('');
}

function renderIncidentsTab(state) {
  const tbody = document.getElementById('incidentsTableBody');
  if (!tbody) return;

  const inc = state.incident;
  if (!inc) {
    tbody.innerHTML = `
      <tr>
        <td colspan="8" style="padding: 32px 16px; text-align: center; color: var(--text-muted);">
          <div style="display: flex; flex-direction: column; align-items: center; gap: 8px;">
            <svg class="icon icon-24 text-ok"><use href="/static/dashboard/icons.svg#icon-circle-check"></use></svg>
            <div style="font-weight: 600; color: var(--text);">Không có sự cố nào đang mở</div>
            <div style="font-size: 12px;">Tất cả các nguồn dữ liệu và pipeline đang vận hành bình thường.</div>
          </div>
        </td>
      </tr>
    `;
    return;
  }

  const notifEmail = state.system?.notifications?.email === 'live';
  const notifZalo = state.system?.notifications?.zalo === 'live';
  const notifTele = state.system?.notifications?.telegram === 'live';
  const blast = (inc.blast_radius || []).join(', ') || '—';

  const status = inc.status || 'WAITING_FOR_APPROVAL';
  const statusMap = {
    'INVESTIGATING': 'Đang điều tra (Maker)',
    'WAITING_FOR_APPROVAL': 'Chờ duyệt phê duyệt',
    'EXECUTING': 'Đang vá dữ liệu',
    'AUDITING': 'Đang nghiệm thu (Checker)',
    'RESOLVED': 'Đã xử lý & nghiệm thu',
    'REJECTED': 'Đã từ chối',
    'FAILED': 'Thất bại',
  };
  const stText = statusMap[status] || status;

  tbody.innerHTML = `
    <tr>
      <td><code>${esc(inc.id)}</code></td>
      <td><span class="chip-sev sev-${(inc.severity || 'HIGH').toLowerCase() === 'critical' ? 'crit' : 'high'}">${esc(inc.severity || 'HIGH')}</span></td>
      <td>
        <div style="font-weight: 600;">${esc(inc.title || 'Vi phạm chất lượng dữ liệu')}</div>
        <div class="text-muted" style="font-size: 11px;">Nguồn: <code>${esc(inc.source || 'mobile_app_v3')}</code></div>
      </td>
      <td>
        <code>${esc(inc.target_table || 'fact_orders')}</code>
        <div class="text-subtle" style="font-size: 10px;">Ảnh hưởng: ${esc(blast)}</div>
      </td>
      <td>
        <div class="notif-channels">
          <span class="chip-channel ${notifTele ? 'active' : ''}">Tele: ${notifTele ? 'Live' : 'Mock'}</span>
          <span class="chip-channel ${notifEmail ? 'active' : ''}">Email: ${notifEmail ? 'Live' : 'Dry-run'}</span>
          <span class="chip-channel ${notifZalo ? 'active' : ''}">Zalo: ${notifZalo ? 'Live' : 'Dry-run'}</span>
        </div>
      </td>
      <td>
        <span class="status-pill status-${status === 'RESOLVED' ? 'healthy' : (status === 'REJECTED' ? 'sleep' : 'incident')}">
          ${stText}
        </span>
      </td>
      <td class="type-mono-sm text-subtle">${formatRelativeTime(inc.detected_at)}</td>
      <td class="num">
        <button class="btn-notif-action btn-notif-primary" onclick="window.openCopilotWithContext?.('${esc(inc.source || 'mobile_app_v3')}')">
          Mở Copilot
        </button>
      </td>
    </tr>
  `;
}

function renderDqTests(tests) {
  const tbody = document.getElementById('dqTestsTableBody');
  if (!tbody || !tests) return;

  tbody.innerHTML = tests.map(t => `
    <tr>
      <td><code>${esc(t.test_name)}</code></td>
      <td><code>${esc(t.column)}</code></td>
      <td><span class="chip-version">${esc(t.type)}</span></td>
      <td class="num ${t.failures > 0 ? 'text-danger' : 'text-ok'}"><strong>${formatNumber(t.failures)}</strong></td>
      <td>
        <span class="status-pill status-${t.status === 'pass' ? 'healthy' : 'incident'}">
          ${t.status === 'pass' ? 'Đạt' : 'Không đạt'}
        </span>
      </td>
      <td>${formatRelativeTime(t.last_run_at)}</td>
    </tr>
  `).join('');
}

function renderActivity(activity) {
  const container = document.getElementById('activityLogList');
  if (!container || !activity) return;

  container.innerHTML = activity.map(a => `
    <div style="display: flex; align-items: center; justify-content: space-between; padding: 10px 0; border-bottom: 1px solid var(--border); font-size: 13px;">
      <div style="display: flex; align-items: center; gap: var(--s2);">
        <span class="type-mono-sm text-subtle">${formatTime(a.ts)}</span>
        <span class="member-avatar ${a.actor === 'checker' ? 'avatar-checker' : 'avatar-maker'}" style="width: 20px; height: 20px; font-size: 10px;">${a.actor === 'checker' ? 'C' : 'M'}</span>
        <span class="badge-layer">${a.kind === 'write' ? 'GHI' : 'ĐỌC'}</span>
        <code>${esc(a.tool)}</code>
        <span class="text-muted">${esc(a.summary)}</span>
      </div>
    </div>
  `).join('');
}
