/**
 * api.js — Giao tiếp với backend API (/ui/state)
 */

export async function fetchState() {
  try {
    const res = await fetch('/ui/state', { cache: 'no-cache' });
    if (res.ok) {
      return await res.json();
    }
  } catch (err) {
    console.warn('Backend /ui/state not ready yet, falling back to mock-state.json');
  }

  // Fallback Phase 1 to mock state
  const mockRes = await fetch('/static/dashboard/mock-state.json', { cache: 'no-cache' });
  return await mockRes.json();
}

export async function runDqChecks() {
  const res = await fetch('/ui/dq/run', { method: 'POST' });
  if (res.ok) {
    return await res.json();
  }
  throw new Error('Không thể chạy DQ checks');
}
