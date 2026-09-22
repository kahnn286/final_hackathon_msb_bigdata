/**
 * lineage.js — Dựng SVG lineage diagram với các node và đường cong động theo state
 */

export function renderLineageSvg(containerEl, lineageData) {
  if (!containerEl) return;

  const rawNodes = lineageData?.nodes || [];
  const rawEdges = lineageData?.edges || [];

  // Base coordinates mapping for node layout
  const layout = {
    sources: { x: 30, y: 70, w: 130, h: 44, label: '3 Nguồn Upstream', sub: '1,000 dòng', state: 'normal' },
    fact_orders: { x: 220, y: 70, w: 140, h: 44, label: 'fact_orders', sub: '1,000 dòng', state: 'normal' },
    dq_checks: { x: 420, y: 30, w: 140, h: 44, label: 'DQ Sentry Checks', sub: '6/6 test pass', state: 'normal' },
    quarantine: { x: 620, y: 30, w: 160, h: 44, label: 'quarantine_fact_orders', sub: '0 dòng', state: 'pending' },
    mart_daily_revenue: { x: 420, y: 110, w: 150, h: 44, label: 'mart_daily_revenue', sub: 'đã đồng bộ', state: 'normal' },
    mart_customer_ltv: { x: 620, y: 110, w: 150, h: 44, label: 'mart_customer_ltv', sub: 'đã đồng bộ', state: 'normal' },
  };

  // Merge dynamic backend data into layout
  rawNodes.forEach(n => {
    if (layout[n.id]) {
      if (n.label) layout[n.id].label = n.label;
      if (n.sub) layout[n.id].sub = n.sub;
      if (n.state) layout[n.id].state = n.state;
    }
  });

  const colorMap = {
    normal: { bg: '#11171F', border: '#232D3A', title: '#E6EBF2', sub: '#7D8A9C', stroke: '#2E3A4A', marker: 'arrow-normal' },
    incident: { bg: '#1F1722', border: '#F87171', title: '#FCA5A5', sub: '#F87171', stroke: '#F87171', marker: 'arrow-incident' },
    warn: { bg: '#1E1B13', border: '#FBBF24', title: '#FDE68A', sub: '#FBBF24', stroke: '#FBBF24', marker: 'arrow-warn' },
    affected: { bg: '#1E1B13', border: '#FBBF24', title: '#FDE68A', sub: '#FBBF24', stroke: '#FBBF24', marker: 'arrow-warn' },
    pending: { bg: '#0D1117', border: '#1E293B', title: '#94A3B8', sub: '#64748B', stroke: '#1E293B', marker: 'arrow-normal' },
  };

  let svgHtml = `
  <svg class="lineage-svg" viewBox="0 0 800 180" xmlns="http://www.w3.org/2000/svg">
    <defs>
      <marker id="arrow-normal" viewBox="0 0 10 10" refX="6" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
        <path d="M 0 1.5 L 8 5 L 0 8.5 z" fill="#2E3A4A"/>
      </marker>
      <marker id="arrow-incident" viewBox="0 0 10 10" refX="6" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
        <path d="M 0 1.5 L 8 5 L 0 8.5 z" fill="#F87171"/>
      </marker>
      <marker id="arrow-warn" viewBox="0 0 10 10" refX="6" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
        <path d="M 0 1.5 L 8 5 L 0 8.5 z" fill="#FBBF24"/>
      </marker>
    </defs>
  `;

  // Draw connecting curved paths based on dynamic edges
  const defaultEdges = [
    { from: 'sources', to: 'fact_orders', state: 'normal' },
    { from: 'fact_orders', to: 'dq_checks', state: layout.fact_orders.state === 'incident' ? 'incident' : 'normal' },
    { from: 'dq_checks', to: 'quarantine', state: 'normal' },
    { from: 'fact_orders', to: 'mart_daily_revenue', state: layout.mart_daily_revenue.state },
    { from: 'mart_daily_revenue', to: 'mart_customer_ltv', state: layout.mart_customer_ltv.state },
  ];

  const edgesToDraw = rawEdges.length > 0 ? rawEdges : defaultEdges;

  edgesToDraw.forEach(p => {
    const s = layout[p.from];
    const t = layout[p.to];
    if (!s || !t) return;
    const edgeState = p.state || 'normal';
    const c = colorMap[edgeState] || colorMap.normal;

    const sx = s.x + s.w;
    const sy = s.y + s.h / 2;
    const tx = t.x;
    const ty = t.y + t.h / 2;
    const mx = (sx + tx) / 2;
    svgHtml += `<path d="M ${sx} ${sy} C ${mx} ${sy}, ${mx} ${ty}, ${tx} ${ty}" fill="none" stroke="${c.stroke}" stroke-width="1.75" marker-end="url(#${c.marker})"/>`;
  });

  // Draw node boxes
  Object.keys(layout).forEach(key => {
    const n = layout[key];
    const c = colorMap[n.state] || colorMap.normal;

    svgHtml += `
    <g class="lineage-node">
      <rect x="${n.x}" y="${n.y}" width="${n.w}" height="${n.h}" rx="8" fill="${c.bg}" stroke="${c.border}" stroke-width="1.5"/>
      <text x="${n.x + 12}" y="${n.y + 18}" font-family="'Plus Jakarta Sans', sans-serif" font-size="11" font-weight="600" fill="${c.title}">${n.label}</text>
      <text x="${n.x + 12}" y="${n.y + 34}" font-family="'JetBrains Mono', monospace" font-size="10" fill="${c.sub}">${n.sub}</text>
    </g>
    `;
  });

  svgHtml += `</svg>`;
  containerEl.innerHTML = svgHtml;
}

