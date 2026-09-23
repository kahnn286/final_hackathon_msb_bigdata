/**
 * copilot.js — Điều khiển Copilot dock (mở/đóng, lazy iframe, resize, expand)
 */

let isIframeLoaded = false;

export function initCopilotDock() {
  const dock = document.getElementById('copilotDock');
  const toggleBtn = document.getElementById('btnToggleCopilot');
  const closeBtn = document.getElementById('btnCloseCopilot');
  const expandBtn = document.getElementById('btnExpandCopilot');
  const resizeHandle = document.getElementById('dockResizeHandle');
  const iframe = document.getElementById('copilotIframe');
  const backdrop = document.getElementById('dockBackdrop');

  if (!dock) return;

  function loadIframeIfNeeded() {
    if (!isIframeLoaded && iframe) {
      iframe.src = '/chat/';
      isIframeLoaded = true;
    }
  }

  async function openDock(contextName = null) {
    dock.classList.remove('collapsed');
    toggleBtn?.setAttribute('aria-pressed', 'true');
    if (window.innerWidth < 1280 && backdrop) {
      backdrop.classList.add('active');
    }
    if (contextName) {
      setContextChip(contextName);
      try {
        const resp = await fetch(`/ui/select-source-incident?source=${encodeURIComponent(contextName)}`, {
          method: 'POST',
        });
        const data = await resp.json();
        if (data && data.incident_id) {
          setContextChip(contextName, data.incident_id);
        }
      } catch (err) {
        console.warn('Failed to select incident for source:', err);
      }
      if (iframe) {
        iframe.src = `/chat/?src=${encodeURIComponent(contextName)}&t=${Date.now()}`;
        isIframeLoaded = true;
      }
    } else {
      loadIframeIfNeeded();
    }
  }

  function closeDock() {
    dock.classList.add('collapsed');
    toggleBtn?.setAttribute('aria-pressed', 'false');
    if (backdrop) {
      backdrop.classList.remove('active');
    }
  }

  function toggleDock() {
    if (dock.classList.contains('collapsed')) {
      openDock();
    } else {
      closeDock();
    }
  }

  function toggleExpand() {
    dock.classList.toggle('expanded');
    const isExp = dock.classList.contains('expanded');
    if (expandBtn) {
      expandBtn.innerHTML = isExp 
        ? '<svg class="icon"><use href="/static/dashboard/icons.svg#icon-minimize-2"></use></svg>'
        : '<svg class="icon"><use href="/static/dashboard/icons.svg#icon-maximize-2"></use></svg>';
    }
  }

  toggleBtn?.addEventListener('click', toggleDock);
  closeBtn?.addEventListener('click', closeDock);
  expandBtn?.addEventListener('click', toggleExpand);
  backdrop?.addEventListener('click', closeDock);

  // Resize handling
  let isResizing = false;
  resizeHandle?.addEventListener('mousedown', (e) => {
    isResizing = true;
    resizeHandle.classList.add('active');
    document.body.style.cursor = 'col-resize';
    document.body.style.userSelect = 'none';
  });

  window.addEventListener('mousemove', (e) => {
    if (!isResizing) return;
    const newWidth = window.innerWidth - e.clientX;
    if (newWidth >= 360 && newWidth <= 720) {
      dock.style.width = `${newWidth}px`;
    }
  });

  window.addEventListener('mouseup', () => {
    if (isResizing) {
      isResizing = false;
      resizeHandle?.classList.remove('active');
      document.body.style.cursor = '';
      document.body.style.userSelect = '';
    }
  });

  // Keyboard shortcut: 'C' toggle, 'Esc' close
  window.addEventListener('keydown', (e) => {
    if (['INPUT', 'TEXTAREA', 'SELECT'].includes(document.activeElement?.tagName)) return;
    if (e.key === 'c' || e.key === 'C') {
      e.preventDefault();
      toggleDock();
    } else if (e.key === 'Escape' && !dock.classList.contains('collapsed')) {
      closeDock();
    }
  });

  // Source Tabs handling
  const sourceTabs = document.querySelectorAll('.dock-source-tab');
  sourceTabs.forEach((tab) => {
    tab.addEventListener('click', () => {
      const sourceKey = tab.getAttribute('data-source');
      sourceTabs.forEach((t) => {
        t.classList.remove('active');
        t.setAttribute('aria-selected', 'false');
      });
      tab.classList.add('active');
      tab.setAttribute('aria-selected', 'true');
      if (sourceKey) {
        openDock(sourceKey);
      }
    });
  });

  // Default state according to screen width
  if (window.innerWidth >= 1440) {
    openDock('web_checkout');
  } else {
    closeDock();
  }

  window.openCopilotWithContext = openDock;
}

export function setActiveSourceTab(sourceKey) {
  const sourceTabs = document.querySelectorAll('.dock-source-tab');
  sourceTabs.forEach((tab) => {
    const isTarget = tab.getAttribute('data-source') === sourceKey;
    tab.classList.toggle('active', isTarget);
    tab.setAttribute('aria-selected', isTarget ? 'true' : 'false');
  });
}

export function renderSourceTabs(sources = []) {
  if (!Array.isArray(sources)) return;
  sources.forEach((s) => {
    const key = s.key || s.source_system;
    if (!key) return;
    const badge = document.getElementById(`tabBadge-${key}`);
    if (badge) {
      const viols = s.total_viols || s.violations || 0;
      badge.textContent = viols;
      if (viols > 0) {
        badge.className = 'dock-source-badge badge-warning';
      } else {
        badge.className = 'dock-source-badge badge-neutral';
      }
    }
  });
}

export function setContextChip(name, incId = null) {
  const chip = document.getElementById('dockContextChip');
  if (chip) {
    const idLabel = incId ? ` · <span style="font-family:'JetBrains Mono',monospace;color:var(--text,#f8fafc);font-weight:600;">${incId}</span>` : '';
    chip.innerHTML = `📍 Ngữ cảnh: <strong style="color:#a5b4fc;font-weight:700;">${name}</strong>${idLabel}`;
  }
  setActiveSourceTab(name);
}
