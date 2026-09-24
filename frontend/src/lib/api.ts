/**
 * API client: fetch wrapper with JWT attach, transparent refresh on 401,
 * offline queueing for writes (spec §40) and honest error surfaces.
 */
const BASE = "/api/v1";

let accessToken: string | null = localStorage.getItem("niecp.access") || null;
let refreshToken: string | null = localStorage.getItem("niecp.refresh") || null;
let onSessionExpired: (() => void) | null = null;

export function setTokens(access: string | null, refresh: string | null) {
  accessToken = access;
  refreshToken = refresh;
  if (access) localStorage.setItem("niecp.access", access);
  else localStorage.removeItem("niecp.access");
  if (refresh) localStorage.setItem("niecp.refresh", refresh);
  else localStorage.removeItem("niecp.refresh");
}

export function getAccessToken() {
  return accessToken;
}

export function setSessionExpiredHandler(fn: () => void) {
  onSessionExpired = fn;
}

export class ApiError extends Error {
  status: number;
  payload: any;
  constructor(status: number, payload: any) {
    super(typeof payload === "object" && payload?.detail ? String(typeof payload.detail === "string" ? payload.detail : payload.detail?.message || JSON.stringify(payload.detail)) : `Request failed (${status})`);
    this.status = status;
    this.payload = payload;
  }
}

// ─────────────────────────────────────────────── offline support ──
const QUEUE_KEY = "niecp.offlineQueue";

function readQueue(): any[] {
  try {
    return JSON.parse(localStorage.getItem(QUEUE_KEY) || "[]");
  } catch {
    return [];
  }
}

function writeQueue(q: any[]) {
  localStorage.setItem(QUEUE_KEY, JSON.stringify(q));
}

export function queueSize(): number {
  return readQueue().length;
}

export function queuedForOffline(method: string, path: string): boolean {
  if (!navigator.onLine) return true;
  return false;
}

export async function flushQueue(): Promise<number> {
  const q = readQueue();
  if (!q.length) return 0;
  let flushed = 0;
  const remaining: any[] = [];
  for (const item of q) {
    try {
      await rawFetch(item.method, item.path, item.body, true);
      flushed += 1;
    } catch {
      remaining.push(item);
    }
  }
  writeQueue(remaining);
  return flushed;
}

export function enqueueOffline(method: string, path: string, body: any) {
  const q = readQueue();
  q.push({ method, path, body, queued_at: new Date().toISOString() });
  writeQueue(q);
  window.dispatchEvent(new CustomEvent("niecp:queue-changed", { detail: queueSize() }));
}

// ─────────────────────────────────────────────────────── fetching ──
async function rawFetch(method: string, path: string, body?: any, isRetry = false): Promise<any> {
  const headers: Record<string, string> = {};
  let payload: any = undefined;
  if (body instanceof FormData) {
    payload = body;
  } else if (body !== undefined) {
    headers["Content-Type"] = "application/json";
    payload = JSON.stringify(body);
  }
  if (accessToken) headers["Authorization"] = `Bearer ${accessToken}`;
  const res = await fetch(BASE + path, { method, headers, body: payload });
  if (res.status === 401 && refreshToken && !isRetry && accessToken) {
    // try a transparent refresh once
    try {
      const r = await fetch(BASE + "/auth/refresh", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ refresh_token: refreshToken }),
      });
      if (r.ok) {
        const data = await r.json();
        setTokens(data.access_token, data.refresh_token);
        return rawFetch(method, path, body, true);
      }
    } catch {
      /* fall through */
    }
    setTokens(null, null);
    onSessionExpired?.();
  }
  if (!res.ok) {
    let parsed: any = null;
    try {
      parsed = await res.json();
    } catch {
      parsed = { detail: res.statusText };
    }
    throw new ApiError(res.status, parsed);
  }
  const ct = res.headers.get("content-type") || "";
  return ct.includes("application/json") ? res.json() : res.text();
}

export async function api<T = any>(method: string, path: string, body?: any, opts: { offlineWrite?: boolean } = {}): Promise<T> {
  if (!navigator.onLine && method !== "GET") {
    if (opts.offlineWrite !== false) enqueueOffline(method, path, body);
    throw new ApiError(0, { detail: "You are offline. Changes will be saved locally and synchronized when the connection returns." });
  }
  if (!navigator.onLine && method === "GET") {
    throw new ApiError(0, { detail: "You are offline. Showing cached information where available." });
  }
  return rawFetch(method, path, body);
}
