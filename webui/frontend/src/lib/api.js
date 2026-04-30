// Thin wrapper around fetch() that handles JSON encoding/decoding,
// surfaces FastAPI-style error payloads with human-readable messages,
// and retries idempotent (GET) calls on transient 5xx failures.

const BASE = '';  // same origin -> proxied by Vite to :8000

// ----- Error formatting --------------------------------------------------
//
// FastAPI returns errors in three main shapes:
//   1. { "detail": "string" }                  -- HTTPException(status, "msg")
//   2. { "detail": [{loc, msg, type}, ...] }   -- Pydantic validation
//   3. { "error": "string" }                   -- our @app.exception_handler
// Plus the network layer can fail (TypeError) without a response body.
//
// `formatApiError(payload, status, statusText)` returns a user-friendly
// string. Used both internally by `request()` and exported so that
// pages/services can format errors thrown by their own fetch logic if
// they wrap it.

export function formatApiError(payload, status, statusText) {
  if (payload == null) return `${status || ''} ${statusText || ''}`.trim();
  if (typeof payload === 'string') return payload;
  // Validation errors: array of { loc:[...], msg, type }
  if (Array.isArray(payload?.detail)) {
    const lines = payload.detail.map((e) => {
      const where = Array.isArray(e.loc) ? e.loc.join('.') : (e.loc || '');
      const msg = e.msg || e.type || 'errore';
      return where ? `${where}: ${msg}` : msg;
    });
    return lines.join('; ');
  }
  if (typeof payload?.detail === 'string') return payload.detail;
  if (typeof payload?.error === 'string') return payload.error;
  // Last resort: stringify but trim very long blobs
  try {
    const s = JSON.stringify(payload);
    return s.length > 240 ? s.slice(0, 240) + '...' : s;
  } catch {
    return `${status || ''} ${statusText || ''}`.trim();
  }
}

// ----- Retry helper ------------------------------------------------------
//
// Exponential backoff for transient 5xx and network errors on GET only.
// POST/PUT/DELETE are NOT retried by default to avoid double-mutations
// (the caller can opt-in via `opts.retry = true`).

function isRetryable(method, errOrResp) {
  if (method !== 'GET' && method !== 'HEAD') return false;
  // Network-level failure (fetch threw)
  if (errOrResp instanceof Error) return true;
  // Server-side failure
  if (errOrResp && typeof errOrResp.status === 'number') {
    return errOrResp.status >= 500 && errOrResp.status < 600;
  }
  return false;
}

async function doFetch(path, opts) {
  const headers = { 'Content-Type': 'application/json',
                    ...(opts.headers || {}) };
  return await fetch(BASE + path, { ...opts, headers });
}

async function sleep(ms) {
  return new Promise((r) => setTimeout(r, ms));
}

async function request(path, opts = {}) {
  const method = (opts.method || 'GET').toUpperCase();
  const allowRetry = opts.retry !== false &&
                      (opts.retry === true || method === 'GET' || method === 'HEAD');
  const maxAttempts = allowRetry ? 3 : 1;

  let lastErr = null;
  for (let attempt = 1; attempt <= maxAttempts; attempt++) {
    let res;
    try {
      res = await doFetch(path, opts);
    } catch (netErr) {
      // Network failure (offline, DNS, etc.)
      lastErr = netErr;
      if (attempt < maxAttempts && isRetryable(method, netErr)) {
        await sleep(200 * Math.pow(2, attempt - 1));
        continue;
      }
      const err = new Error(
        netErr?.message ||
        'Connessione al server fallita. Verifica che il backend sia attivo.');
      err.status = 0;
      err.networkError = true;
      throw err;
    }
    if (res.ok) {
      if (res.status === 204) return null;
      const ct = res.headers.get('content-type') || '';
      if (ct.includes('application/json')) return await res.json();
      return await res.blob();
    }
    // Non-OK response: try to parse a body and decide whether to retry
    let body = null;
    try { body = await res.json(); } catch { /* non-JSON body */ }
    if (attempt < maxAttempts && isRetryable(method, res)) {
      lastErr = res;
      await sleep(200 * Math.pow(2, attempt - 1));
      continue;
    }
    const msg = formatApiError(body, res.status, res.statusText);
    const err = new Error(msg);
    err.status = res.status;
    err.body = body;
    throw err;
  }
  // Should not reach here, but be defensive.
  const err = new Error(lastErr?.message || 'Richiesta fallita.');
  err.status = lastErr?.status ?? 0;
  throw err;
}

export const api = {
  get:  (p, opts) => request(p, { method: 'GET',  ...(opts || {}) }),
  post: (p, body, opts) => request(p,
    { method: 'POST', body: body == null ? null : JSON.stringify(body),
      ...(opts || {}) }),
  put:  (p, body, opts) => request(p,
    { method: 'PUT',  body: body == null ? null : JSON.stringify(body),
      ...(opts || {}) }),
  del:  (p, opts) => request(p, { method: 'DELETE', ...(opts || {}) }),
  raw:  request
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
