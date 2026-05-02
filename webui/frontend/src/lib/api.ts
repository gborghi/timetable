// Thin wrapper around fetch() that handles JSON encoding/decoding,
// surfaces FastAPI-style error payloads with human-readable messages,
// and retries idempotent (GET) calls on transient 5xx failures.

import type { ApiErrorResponse } from "./types";

const BASE = ""; // same origin -> proxied by Vite to :8000

// ----- Error formatting --------------------------------------------------

/**
 * FastAPI returns errors in three main shapes:
 *   1. { "detail": "string" }                   -- HTTPException(status, "msg")
 *   2. { "detail": [{loc, msg, type}, ...] }    -- Pydantic validation
 *   3. { "error": "string" }                    -- legacy custom handler
 *   4. canonical ErrorResponse (Section 2.3 P2) -- {detail, code, errors[], hint}
 * Plus the network layer can fail (TypeError) without a response body.
 */
export function formatApiError(
  payload: unknown,
  status?: number,
  statusText?: string,
): string {
  if (payload == null) return `${status ?? ""} ${statusText ?? ""}`.trim();
  if (typeof payload === "string") return payload;
  const p = payload as Partial<ApiErrorResponse> & {
    detail?: unknown;
    error?: unknown;
  };
  // Validation errors: array of { loc, msg, type }
  if (Array.isArray(p.detail)) {
    const lines = (p.detail as Array<{ loc?: unknown; msg?: string; type?: string }>)
      .map((e) => {
        const where = Array.isArray(e.loc)
          ? (e.loc as unknown[]).join(".")
          : ((e.loc as string) || "");
        const msg = e.msg || e.type || "errore";
        return where ? `${where}: ${msg}` : msg;
      });
    return lines.join("; ");
  }
  if (typeof p.detail === "string") return p.detail;
  if (typeof p.error === "string") return p.error;
  // Last resort: stringify but trim very long blobs
  try {
    const s = JSON.stringify(payload);
    return s.length > 240 ? s.slice(0, 240) + "..." : s;
  } catch {
    return `${status ?? ""} ${statusText ?? ""}`.trim();
  }
}

// ----- Retry helper ------------------------------------------------------

type Method = "GET" | "POST" | "PUT" | "PATCH" | "DELETE" | "HEAD";

interface RequestOpts extends Omit<RequestInit, "method" | "headers"> {
  method?: Method;
  retry?: boolean;
  headers?: Record<string, string>;
}

export interface ApiError extends Error {
  status: number;
  body?: unknown;
  networkError?: boolean;
}

function isRetryable(method: Method, errOrResp: Response | Error | null): boolean {
  if (method !== "GET" && method !== "HEAD") return false;
  if (errOrResp instanceof Error) return true;
  if (errOrResp && typeof (errOrResp as Response).status === "number") {
    const s = (errOrResp as Response).status;
    return s >= 500 && s < 600;
  }
  return false;
}

async function doFetch(path: string, opts: RequestOpts): Promise<Response> {
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...(opts.headers || {}),
  };
  const init: RequestInit = { ...(opts as RequestInit), headers };
  return await fetch(BASE + path, init);
}

function sleep(ms: number): Promise<void> {
  return new Promise((r) => setTimeout(r, ms));
}

async function request<T = unknown>(
  path: string,
  opts: RequestOpts = {},
): Promise<T> {
  const method: Method = ((opts.method as Method) || "GET").toUpperCase() as Method;
  const allowRetry =
    opts.retry !== false &&
    (opts.retry === true || method === "GET" || method === "HEAD");
  const maxAttempts = allowRetry ? 3 : 1;

  let lastErr: Response | Error | null = null;
  for (let attempt = 1; attempt <= maxAttempts; attempt++) {
    let res: Response;
    try {
      res = await doFetch(path, opts);
    } catch (netErr) {
      lastErr = netErr as Error;
      if (attempt < maxAttempts && isRetryable(method, lastErr)) {
        await sleep(200 * Math.pow(2, attempt - 1));
        continue;
      }
      const err: ApiError = Object.assign(
        new Error(
          (netErr as Error)?.message ||
            "Connessione al server fallita. Verifica che il backend sia attivo.",
        ),
        { status: 0, networkError: true },
      ) as ApiError;
      throw err;
    }
    if (res.ok) {
      if (res.status === 204) return null as T;
      const ct = res.headers.get("content-type") || "";
      if (ct.includes("application/json")) return (await res.json()) as T;
      return (await res.blob()) as unknown as T;
    }
    let body: unknown = null;
    try {
      body = await res.json();
    } catch {
      /* non-JSON body */
    }
    if (attempt < maxAttempts && isRetryable(method, res)) {
      lastErr = res;
      await sleep(200 * Math.pow(2, attempt - 1));
      continue;
    }
    const msg = formatApiError(body, res.status, res.statusText);
    const err: ApiError = Object.assign(new Error(msg), {
      status: res.status,
      body,
    }) as ApiError;
    throw err;
  }
  const err: ApiError = Object.assign(
    new Error((lastErr as Error)?.message || "Richiesta fallita."),
    { status: (lastErr as Response | null)?.status ?? 0 },
  ) as ApiError;
  throw err;
}

export const api = {
  get: <T = unknown>(p: string, opts?: RequestOpts) =>
    request<T>(p, { method: "GET", ...(opts || {}) }),
  post: <T = unknown>(p: string, body?: unknown, opts?: RequestOpts) =>
    request<T>(p, {
      method: "POST",
      body: body == null ? undefined : JSON.stringify(body),
      ...(opts || {}),
    }),
  put: <T = unknown>(p: string, body?: unknown, opts?: RequestOpts) =>
    request<T>(p, {
      method: "PUT",
      body: body == null ? undefined : JSON.stringify(body),
      ...(opts || {}),
    }),
  del: <T = unknown>(p: string, opts?: RequestOpts) =>
    request<T>(p, { method: "DELETE", ...(opts || {}) }),
  raw: request,
};

export function downloadUrl(path: string): string {
  return BASE + path;
}

// ----- SSE -------------------------------------------------------------

export interface StreamRunHandlers {
  onLog?: (data: string) => void;
  onStatus?: (data: unknown) => void;
  onEnd?: (data: string) => void;
  onError?: (e: Event) => void;
}

/** Wait for a run to reach a terminal state (done | failed). Resolves
 * with the final status payload. Used for chaining steps in the
 * PlaceEventModal pipeline.
 *
 * Implementation: SSE 'end' alone is unreliable on long runs --
 * browsers can close idle EventSource connections (e.g. after ~30s
 * of no traffic), and the 'error' fallback can fire transient blips.
 * We instead authoritatively poll GET /api/optimize/runs/{id} every
 * 2s and resolve when .status is 'done' or 'failed'. SSE is still
 * used for the live log + status pushes; its 'end' just triggers an
 * immediate poll to avoid waiting up to 2s for the next tick.
 */
export function waitForRun(
  runId: number,
  { onLog, onStatus }: {
    onLog?: (line: string) => void;
    onStatus?: (status: { status: string; progress?: number }) => void;
  } = {},
): Promise<{ status: string }> {
  return new Promise((resolve) => {
    let resolved = false;
    let pollTimer: ReturnType<typeof setInterval> | null = null;
    let unsub: (() => void) | null = null;

    function finish(status: string) {
      if (resolved) return;
      resolved = true;
      if (pollTimer) clearInterval(pollTimer);
      try { if (unsub) unsub(); } catch { /* ignore */ }
      resolve({ status });
    }

    async function pollOnce() {
      try {
        const r = await request<{ status: string; progress?: number }>(
          `/api/optimize/runs/${runId}`,
        );
        if (onStatus) onStatus(r);
        if (r.status === 'done' || r.status === 'failed') {
          finish(r.status);
        }
      } catch {
        /* ignore transient poll errors; retry on the next tick */
      }
    }

    unsub = streamRun(runId, {
      onLog: (l) => { if (onLog) onLog(l); },
      onStatus: (s) => {
        if (onStatus) onStatus(s as { status: string; progress?: number });
      },
      onEnd: () => { pollOnce(); },
      // SSE error is non-terminal: ignore it and rely on polling.
      onError: () => { /* swallow */ },
    });

    // Immediate first probe + 2s pulse
    pollOnce();
    pollTimer = setInterval(pollOnce, 2000);
  });
}

/** Subscribe to SSE for a run; returns an unsubscriber. */
export function streamRun(
  runId: number,
  { onLog, onStatus, onEnd, onError }: StreamRunHandlers,
): () => void {
  const url = `/api/optimize/runs/${runId}/stream`;
  const es = new EventSource(url);
  if (onLog) es.addEventListener("log", (e: MessageEvent) => onLog(e.data));
  if (onStatus) {
    es.addEventListener("status", (e: MessageEvent) => {
      try {
        onStatus(JSON.parse(e.data));
      } catch {
        /* ignore malformed status payloads */
      }
    });
  }
  if (onEnd) {
    es.addEventListener("end", (e: MessageEvent) => {
      onEnd(e.data);
      es.close();
    });
  }
  if (onError) es.addEventListener("error", onError);
  return () => es.close();
}
