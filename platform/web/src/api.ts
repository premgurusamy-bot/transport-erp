// Thin, typed API client. All data goes through the FastAPI backend; the browser never talks to the database.
export type ApiError = { code: string; message: string; details?: any; status: number };

const TOKEN_KEY = "grl.token";
let token: string | null = (() => {
  try { return sessionStorage.getItem(TOKEN_KEY); } catch { return null; }
})();

export function setToken(t: string | null) {
  token = t;
  try { t ? sessionStorage.setItem(TOKEN_KEY, t) : sessionStorage.removeItem(TOKEN_KEY); } catch { /* private mode */ }
}
export const getToken = () => token;

export async function api<T = any>(path: string, opts: { method?: string; body?: any; form?: FormData; app?: string } = {}): Promise<T> {
  const headers: Record<string, string> = { "X-GRL-App": opts.app || "web" };
  if (token) headers.Authorization = `Bearer ${token}`;
  let body: BodyInit | undefined;
  if (opts.form) body = opts.form;
  else if (opts.body !== undefined) { headers["Content-Type"] = "application/json"; body = JSON.stringify(opts.body); }
  const res = await fetch(`/api/v1${path}`, { method: opts.method || (body ? "POST" : "GET"), headers, body });
  const ct = res.headers.get("content-type") || "";
  const data = ct.includes("json") ? await res.json() : await res.blob();
  if (!res.ok) {
    if (res.status === 401 && token) { setToken(null); window.dispatchEvent(new Event("grl:logout")); }
    const e = (data as any)?.error || {};
    throw { code: e.code || "error", message: e.message || res.statusText, details: e.details, status: res.status } as ApiError;
  }
  return data as T;
}

export const get = <T = any>(p: string) => api<T>(p);
export const post = <T = any>(p: string, body?: any) => api<T>(p, { method: "POST", body: body ?? {} });
export const patch = <T = any>(p: string, body: any) => api<T>(p, { method: "PATCH", body });
export const put = <T = any>(p: string, body: any) => api<T>(p, { method: "PUT", body });

// ---- Offline queue (Driver web app): events captured offline are replayed idempotently via /sync/events
const QKEY = "grl.offline.queue";
export type QueuedEvent = { client_event_id: string; device_id: string; event_type: string; payload: any; occurred_at: string; source: string };
export function queueOffline(event_type: string, payload: any) {
  const q: QueuedEvent[] = readQueue();
  q.push({ client_event_id: crypto.randomUUID(), device_id: deviceId(), event_type, payload, occurred_at: new Date().toISOString(), source: "app_offline" });
  try { localStorage.setItem(QKEY, JSON.stringify(q)); } catch { /* storage unavailable */ }
}
export function readQueue(): QueuedEvent[] {
  try { return JSON.parse(localStorage.getItem(QKEY) || "[]"); } catch { return []; }
}
export async function flushQueue(): Promise<{ applied: number; rejected: number }> {
  const q = readQueue();
  if (!q.length) return { applied: 0, rejected: 0 };
  const r = await post<{ results: { client_event_id: string; status: string }[] }>("/sync/events", { events: q });
  const done = new Set(r.results.map((x) => x.client_event_id));
  try { localStorage.setItem(QKEY, JSON.stringify(q.filter((x) => !done.has(x.client_event_id)))); } catch { /* ignore */ }
  return { applied: r.results.filter((x) => x.status !== "rejected").length, rejected: r.results.filter((x) => x.status === "rejected").length };
}
function deviceId() {
  try {
    let d = localStorage.getItem("grl.device");
    if (!d) { d = crypto.randomUUID(); localStorage.setItem("grl.device", d); }
    return d;
  } catch { return "web"; }
}
