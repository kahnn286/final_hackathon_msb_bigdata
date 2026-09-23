/**
 * main.js — Điểm khởi động của DataOps Console
 */

import { fetchState, runDqChecks } from './api.js';
import { render } from './render.js';
import { initCopilotDock } from './copilot.js';

let currentState = null;

async function refreshData() {
  const btn = document.getElementById('btnRefresh');
  if (btn) btn.style.opacity = '0.5';
  try {
    const state = await fetchState();
    currentState = state;
    render(state);
  } catch (err) {
    console.error('Failed to load state:', err);
  } finally {
    if (btn) btn.style.opacity = '1';
  }
}

export function switchToTab(tabId) {
  const tabs = document.querySelectorAll('.tab-btn');
  const panels = document.querySelectorAll('.tab-content-panel');

  tabs.forEach(t => {
    const isTarget = t.getAttribute('data-target') === tabId;
    t.setAttribute('aria-selected', isTarget ? 'true' : 'false');
  });

  panels.forEach(p => {
    p.style.display = (p.id === tabId) ? 'block' : 'none';
  });

  // Scroll to tabs container if needed
  const container = document.querySelector('.tabs-container');
  if (container) {
    container.scrollIntoView({ behavior: 'smooth', block: 'start' });
  }
}
window.switchToTab = switchToTab;

function initTabs() {
  const tabs = document.querySelectorAll('.tab-btn');
  tabs.forEach(tab => {
    tab.addEventListener('click', () => {
      const targetId = tab.getAttribute('data-target');
      if (targetId) switchToTab(targetId);
    });
  });
}

function initNotifications() {
  const btn = document.getElementById('btnNotification');
  const dropdown = document.getElementById('notificationDropdown');
  const btnViewAll = document.getElementById('btnViewAllIncidents');

  if (!btn || !dropdown) return;

  function toggleDropdown(e) {
    e?.stopPropagation();
    const isOpen = dropdown.style.display === 'block';
    dropdown.style.display = isOpen ? 'none' : 'block';
    btn.setAttribute('aria-expanded', !isOpen);
  }

  function closeDropdown() {
    dropdown.style.display = 'none';
    btn.setAttribute('aria-expanded', 'false');
  }

  btn.addEventListener('click', toggleDropdown);

  btnViewAll?.addEventListener('click', () => {
    closeDropdown();
    switchToTab('tabIncidents');
  });

  function showToast(msg, type = 'info') {
    const oldToast = document.querySelector('.dash-toast');
    if (oldToast) oldToast.remove();

    const toast = document.createElement('div');
    toast.className = 'dash-toast';
    const borderCol = type === 'danger' ? '#F87171' : (type === 'success' ? '#34D399' : '#38BDF8');
    toast.style.borderColor = borderCol;
    toast.innerHTML = `<span>${msg}</span>`;
    document.body.appendChild(toast);
    setTimeout(() => toast.remove(), 4000);
  }

  window.injectDefect = async function(source, defectType) {
    showToast(`⚡ Đang cấy lỗi vào nguồn [${source}]...`, 'info');
    try {
      const resp = await fetch(`/ui/demo/inject-incident?source=${encodeURIComponent(source)}&defect_type=${encodeURIComponent(defectType || 'auto')}`, {
        method: 'POST',
      });
      const data = await resp.json();
      if (data.ok) {
        showToast(`🚨 Đã cấy ${data.total_injected_rows || 15} dòng lỗi vào [${source}]! Telegram đã nhận alert.`, 'danger');
        await refreshData();
        // Tự động chuyển Copilot sang nguồn vừa có lỗi để AI điều tra ngay lập tức
        const targetSrc = (source === 'all' || source === 'auto') ? 'web_checkout' : source;
        if (window.openCopilotWithContext) {
          window.openCopilotWithContext(targetSrc);
        }
      } else {
        showToast(`❌ Không thể cấy lỗi: ${data.error || 'Lỗi server'}`, 'danger');
      }
    } catch (err) {
      console.error('Lỗi khi cấy lỗi:', err);
      showToast(`❌ Lỗi kết nối: ${err.message}`, 'danger');
    }
  };

  window.resetCleanData = async function() {
    showToast(`🧹 Đang khôi phục kho dữ liệu sạch...`, 'info');
    try {
      const resp = await fetch('/ui/demo/reset-clean', { method: 'POST' });
      const data = await resp.json();
      if (data.ok) {
        showToast(`✅ Đã reset kho dữ liệu sạch 100%!`, 'success');
        await refreshData();
        if (window.openCopilotWithContext) {
          window.openCopilotWithContext('web_checkout');
        }
      }
    } catch (err) {
      console.error('Lỗi khi reset:', err);
      showToast(`❌ Lỗi kết nối: ${err.message}`, 'danger');
    }
  };

  window.refreshData = refreshData;

  // Close when clicking outside
  document.addEventListener('click', (e) => {
    if (!dropdown.contains(e.target) && !btn.contains(e.target)) {
      closeDropdown();
    }
  });

  // Close on Escape
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && dropdown.style.display === 'block') {
      closeDropdown();
    }
  });
}

function initDebugSwitcher() {
  const urlParams = new URLSearchParams(window.location.search);
  if (urlParams.get('debug') !== '1') return;

  const bar = document.createElement('div');
  bar.style.cssText = `
    position: fixed; bottom: 12px; left: 12px; z-index: 9999;
    background: #161D27; border: 1px solid #334B75; padding: 6px 10px;
    border-radius: 8px; font-size: 11px; display: flex; gap: 6px; align-items: center;
  `;
  bar.innerHTML = `<strong>Debug Status:</strong>`;
  
  const statuses = ['IDLE', 'INVESTIGATING', 'WAITING_FOR_APPROVAL', 'EXECUTING', 'AUDITING', 'RESOLVED', 'REJECTED'];
  statuses.forEach(st => {
    const btn = document.createElement('button');
    btn.textContent = st;
    btn.style.cssText = 'background: #232D3A; color: #fff; padding: 2px 6px; border-radius: 4px; font-size: 10px; cursor: pointer;';
    btn.onclick = () => {
      if (!currentState) return;
      if (st === 'IDLE') {
        currentState.incident = null;
      } else {
        if (!currentState.incident) {
          currentState.incident = { id: 'INC-2026-DQ01', title: '15 dòng customer_id NULL trong fact_orders', source: 'mobile_app_v3', target_table: 'fact_orders' };
        }
        currentState.incident.status = st;
        if (st === 'RESOLVED') currentState.incident.audit_verdict = 'AUDIT_PASSED';
      }
      render(currentState);
    };
    bar.appendChild(btn);
  });
  document.body.appendChild(bar);
}

document.addEventListener('DOMContentLoaded', () => {
  initCopilotDock();
  initTabs();
  initNotifications();
  initDebugSwitcher();

  document.getElementById('btnRefresh')?.addEventListener('click', refreshData);
  window.triggerDqRun = async () => {
    try {
      await runDqChecks();
      await refreshData();
    } catch (e) {
      console.warn(e);
    }
  };

  // Polling loop controller
  let pollTimer = null;
  function startPolling(ms) {
    if (pollTimer) clearInterval(pollTimer);
    if (ms > 0) {
      pollTimer = setInterval(() => {
        if (!document.hidden) {
          refreshData();
        }
      }, ms);
    }
  }

  const scanSelect = document.getElementById('selectScanInterval');
  let currentInterval = parseInt(localStorage.getItem('dra_scan_interval') || '4000', 10);
  if (scanSelect) {
    scanSelect.value = String(currentInterval);
    scanSelect.addEventListener('change', (e) => {
      const ms = parseInt(e.target.value, 10);
      localStorage.setItem('dra_scan_interval', ms);
      startPolling(ms);
      showToast(ms > 0 ? `⏱️ Đã đổi chu kỳ tự quét: ${ms / 1000}s` : `⏸️ Đã tạm dừng tự động quét`, 'info');
    });
  }

  // Initial load
  refreshData();
  startPolling(currentInterval);
});

