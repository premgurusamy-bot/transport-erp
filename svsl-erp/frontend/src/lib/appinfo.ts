// Installation facts every screen may need: first-run state, the customer's company name (from Settings → Company,
// never built into the app) and the licence state.
import { useEffect, useState } from "react";
import { api, auth } from "./api";

export type AppInfo = { setup_needed: boolean; setup_allowed_here: boolean; company: string; has_logo: boolean };
export type Licence = {
  state: "trial" | "active" | "grace" | "expired" | "trial_expired" | "clock_error"; read_only: boolean; message: string; days_left: number | null;
  install_id?: string; licensed_to: string | null; licence_id: string | null; plan: string | null; plan_label: string | null; valid_from: string | null;
  valid_until: string | null; max_users: number; trial_days: number; trial_ends?: string; first_seen: string; key_error: string | null; grace_days: number;
};

const EMPTY: AppInfo = { setup_needed: false, setup_allowed_here: false, company: "", has_logo: false };
let infoP: Promise<AppInfo> | null = null;
export function loadAppInfo(fresh = false): Promise<AppInfo> {
  if (!infoP || fresh) infoP = fetch("/api/setup/status").then((r) => (r.ok ? r.json() : EMPTY)).catch(() => { infoP = null; return EMPTY; });
  return infoP;
}
export function useAppInfo(): AppInfo | null {
  const [v, setV] = useState<AppInfo | null>(null);
  useEffect(() => { let live = true; loadAppInfo().then((x) => live && setV(x)); return () => { live = false; }; }, []);
  return v;
}

const listeners = new Set<(l: Licence | null) => void>();
let licP: Promise<Licence | null> | null = null;
export function loadLicence(fresh = false): Promise<Licence | null> {
  if (!auth.token) return Promise.resolve(null);
  if (!licP || fresh) licP = api.get("/api/licence").catch(() => { licP = null; return null; });
  if (fresh) licP.then((l) => listeners.forEach((f) => f(l)));
  return licP;
}
if (typeof window !== "undefined") window.addEventListener("aprime:licence", () => { loadLicence(true); });

export function useLicence(): Licence | null {
  const [v, setV] = useState<Licence | null>(null);
  useEffect(() => {
    let live = true;
    loadLicence().then((x) => live && setV(x));
    const f = (l: Licence | null) => live && setV(l);
    listeners.add(f);
    return () => { live = false; listeners.delete(f); };
  }, []);
  return v;
}
