// Thin wrapper around fetch() that handles JSON encoding/decoding and
// surfaces FastAPI-style error payloads.

const BASE = '';  // same origin -> proxied by Vite to :8000

async function request(path, opts = {}) {
  const headers = { 'Content-Type': 'application/json', ...(opts.headers || {}) };
  const res = await fetch(BASE + path, { ...opts, headers });
  if (!res.ok) {
    let msg = `${res.status} ${res.statusText}`;
    try {
      const j = await res.json();
      if (j && j.detail) msg = typeof j.detail === 'string' ? j.detail : JSON.stringify(j.detail);
      else if (j && j.error) msg = j.error;
    } catch { /* keep msg */ }
    const err = new Error(msg);
    err.status = res.status;
    throw err;
  }
  if (res.status === 204) return null;
  const ct = res.headers.get('content-type') || '';
  if (ct.includes('application/json')) return await res.json();
  return await res.blob();
}

export const api = {
  get: (p) => request(p, { method: 'GET' }),
  post: (p, body) => request(p, { method: 'POST', body: body == null ? null : JSON.stringify(body) }),
  put: (p, body) => request(p, { method: 'PUT', body: body == null ? null : JSON.stringify(body) }),
  del: (p) => request(p, { method: 'DELETE' }),
  raw: request
};

export function downloadUrl(path) {
  return BASE + path;
}

// Subscribe to SSE for a run; returns an unsubscriber
export function streamRun(runId, { onLog, onStatus, onEnd, onError }) {
  const url = `/api/optimize/runs/${runId}/stream`;
  const es = new EventSource(url);
  if (onLog) es.addEventListener('log', (e) => onLog(e.data));
  if (onStatus) es.addEventListener('status', (e) => {
    try { onStatus(JSON.parse(e.data)); } catch { /* */ }
  });
  if (onEnd) es.addEventListener('end', (e) => { onEnd(e.data); es.close(); });
  if (onError) es.addEventListener('error', (e) => onError(e));
  return () => es.close();
}
