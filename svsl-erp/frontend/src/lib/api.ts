// REST client: bearer token in localStorage, JSON helpers, authenticated file download/open.
const TOKEN_KEY = "svsl_token";
const USER_KEY = "svsl_user";

export type User = {
  id: number; username: string; full_name: string; role: string; permissions: string[];
  customer_id: number | null; driver_id: number | null; language: string; totp_enabled: boolean; must_change_password: boolean;
};

function safeGet(k: string): string | null { try { return localStorage.getItem(k); } catch { return null; } }
function safeSet(k: string, v: string | null) { try { v === null ? localStorage.removeItem(k) : localStorage.setItem(k, v); } catch { /* storage unavailable */ } }

export const auth = {
  get token() { return safeGet(TOKEN_KEY); },
  get user(): User | null { const u = safeGet(USER_KEY); return u ? JSON.parse(u) : null; },
  save(token: string, user: User) { safeSet(TOKEN_KEY, token); safeSet(USER_KEY, JSON.stringify(user)); },
  setUser(user: User) { safeSet(USER_KEY, JSON.stringify(user)); },
  clear() { safeSet(TOKEN_KEY, null); safeSet(USER_KEY, null); },
};

export function can(perm: string): boolean {
  const p = auth.user?.permissions || [];
  if (p.includes("*") || p.includes(perm)) return true;
  return perm.endsWith(":read") && p.includes(perm.replace(":read", ":write"));
}

export class ApiError extends Error { status: number; constructor(msg: string, status: number) { super(msg); this.status = status; } }

async function request(method: string, url: string, body?: any, isForm = false): Promise<any> {
  const headers: Record<string, string> = {};
  if (auth.token) headers.Authorization = `Bearer ${auth.token}`;
  if (body !== undefined && !isForm) headers["Content-Type"] = "application/json";
  const res = await fetch(url, { method, headers, body: body === undefined ? undefined : isForm ? body : JSON.stringify(body) });
  if (res.status === 401 && !url.endsWith("/auth/login")) {
    auth.clear();
    if (!location.pathname.startsWith("/login")) location.href = "/login";
  }
  const ct = res.headers.get("content-type") || "";
  const data = ct.includes("application/json") ? await res.json() : await res.blob();
  if (!res.ok) throw new ApiError((data && data.detail) || `Request failed (${res.status})`, res.status);
  return data;
}

export const api = {
  get: (url: string) => request("GET", url),
  post: (url: string, body: any = {}) => request("POST", url, body),
  put: (url: string, body: any = {}) => request("PUT", url, body),
  del: (url: string) => request("DELETE", url),
  form: (url: string, form: FormData) => request("POST", url, form, true),
};

export function qs(params: Record<string, any>): string {
  const p = new URLSearchParams();
  Object.entries(params).forEach(([k, v]) => { if (v !== undefined && v !== null && v !== "") p.set(k, String(v)); });
  const s = p.toString();
  return s ? "?" + s : "";
}

/** Fetch a protected file and open it in a new tab (PDF) or save it (xlsx/csv/zip). */
export async function openFile(url: string, filename?: string) {
  if (/SVSLApp-Android/.test(navigator.userAgent)) {
    // Android WebView cannot save blobs: get a 2-minute link and let the phone's download manager fetch it.
    const r = await request("POST", "/api/auth/download-link", { path: url });
    location.href = r.url;
    return;
  }
  const res = await fetch(url, { headers: auth.token ? { Authorization: `Bearer ${auth.token}` } : {} });
  if (!res.ok) {
    let msg = `Download failed (${res.status})`;
    try { msg = (await res.json()).detail || msg; } catch { /* not json */ }
    throw new ApiError(msg, res.status);
  }
  const blob = await res.blob();
  const href = URL.createObjectURL(blob);
  const cd = res.headers.get("content-disposition") || "";
  const name = filename || (cd.match(/filename="?([^"]+)"?/) || [])[1] || "download";
  if (blob.type === "application/pdf" || blob.type.startsWith("image/")) {
    const w = window.open(href, "_blank");
    if (!w) { const a = document.createElement("a"); a.href = href; a.download = name; a.click(); }
  } else {
    const a = document.createElement("a"); a.href = href; a.download = name; document.body.appendChild(a); a.click(); a.remove();
  }
  setTimeout(() => URL.revokeObjectURL(href), 60000);
}
