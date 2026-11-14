// Shared design system: buttons, cards, tables, schema forms, badges, error display and data hooks.
import React, { useCallback, useEffect, useState } from "react";
import { ApiError } from "../api";

export const inr = (v: any) =>
  v === null || v === undefined || v === "" ? "—" : "₹ " + Number(v).toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
export const dt = (v: any) =>
  v ? new Date(v).toLocaleString("en-IN", { timeZone: "Asia/Kolkata", day: "2-digit", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit" }) : "—";
export const d = (v: any) => (v ? new Date(v).toLocaleDateString("en-IN", { timeZone: "Asia/Kolkata", day: "2-digit", month: "short", year: "numeric" }) : "—");

export function useData<T = any>(load: () => Promise<T>, deps: any[] = []) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [loading, setLoading] = useState(true);
  const reload = useCallback(() => {
    setLoading(true);
    load().then((x) => { setData(x); setError(null); }).catch(setError).finally(() => setLoading(false));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);
  useEffect(reload, [reload]);
  return { data, error, loading, reload, setData };
}

export function Btn(p: React.ButtonHTMLAttributes<HTMLButtonElement> & { kind?: "primary" | "danger" | "ghost" }) {
  const { kind = "primary", className, ...rest } = p;
  return <button {...rest} className={`btn btn-${kind} ${className || ""}`} />;
}

export function Card(p: { title?: React.ReactNode; actions?: React.ReactNode; children: React.ReactNode; note?: React.ReactNode }) {
  return (
    <section className="card">
      {(p.title || p.actions) && (
        <header className="card-h"><h3>{p.title}</h3><div className="row gap">{p.actions}</div></header>
      )}
      {p.note && <p className="muted small">{p.note}</p>}
      <div>{p.children}</div>
    </section>
  );
}

const TONES: Record<string, string> = {
  ok: "green", approved: "green", active: "green", verified: "green", paid: "green", closed: "grey", delivered: "green", live: "green",
  pod_verified: "green", confirmed: "blue", matched: "green", completed: "green", applied: "green", sent: "blue", published: "green",
  pending: "amber", pending_approval: "amber", submitted: "amber", warning: "amber", suggested: "amber", planned: "blue", in_transit: "blue",
  dispatched: "blue", draft: "grey", stale: "amber", live_failover: "amber", unconfirmed: "amber", needs_review: "amber", on_hold: "red",
  blocked: "red", rejected: "red", failed: "red", cancelled: "grey", critical: "red", high: "red", medium: "amber", low: "grey",
  unmatched: "red", unavailable: "red", MOCK: "amber", SANDBOX: "amber", LIVE: "green", overdue: "red", open: "amber", unverified: "amber",
};
export function Badge({ v }: { v: any }) {
  const s = String(v ?? "—");
  return <span className={`badge b-${TONES[s] || "grey"}`}>{s.replace(/_/g, " ")}</span>;
}

export function ErrorBox({ error }: { error: ApiError | null }) {
  if (!error) return null;
  const details = Array.isArray(error.details) ? error.details : null;
  return (
    <div className="alert alert-red" role="alert">
      <strong>{error.message}</strong>
      {details && (
        <ul>{details.map((x: any, i: number) => <li key={i}>{x.message || x.field ? `${x.field ? x.field + ": " : ""}${x.message}` : JSON.stringify(x)}</li>)}</ul>
      )}
    </div>
  );
}

export type Col<T = any> = { key: string; label: string; render?: (row: T) => React.ReactNode; money?: boolean; date?: boolean; badge?: boolean };
export function Table<T = any>({ rows, cols, onRow, empty = "No records" }: { rows: T[] | null | undefined; cols: Col<T>[]; onRow?: (r: T) => void; empty?: string }) {
  if (!rows) return <p className="muted">Loading…</p>;
  if (!rows.length) return <p className="muted">{empty}</p>;
  return (
    <div className="table-wrap">
      <table>
        <thead><tr>{cols.map((c) => <th key={c.key}>{c.label}</th>)}</tr></thead>
        <tbody>
          {rows.map((r: any, i) => (
            <tr key={r.id || i} onClick={onRow ? () => onRow(r) : undefined} className={onRow ? "clickable" : ""}>
              {cols.map((c) => (
                <td key={c.key} className={c.money ? "num" : ""}>
                  {c.render ? c.render(r) : c.money ? inr(r[c.key]) : c.date ? dt(r[c.key]) : c.badge ? <Badge v={r[c.key]} /> : fmt(r[c.key])}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
const fmt = (v: any) => (v === null || v === undefined ? "—" : typeof v === "object" ? JSON.stringify(v) : typeof v === "boolean" ? (v ? "Yes" : "No") : String(v));

export type Field = {
  name: string; label: string; type?: "text" | "number" | "date" | "datetime-local" | "select" | "checkbox" | "textarea" | "email" | "tel" | "password";
  options?: { value: string; label: string }[]; required?: boolean; help?: string; step?: string;
};
export function Form({ fields, initial = {}, onSubmit, submitLabel = "Save", busy }: {
  fields: Field[]; initial?: Record<string, any>; onSubmit: (v: Record<string, any>) => Promise<any> | void; submitLabel?: string; busy?: boolean;
}) {
  const [v, setV] = useState<Record<string, any>>(initial);
  const [err, setErr] = useState<ApiError | null>(null);
  const [saving, setSaving] = useState(false);
  const set = (k: string, val: any) => setV((o) => ({ ...o, [k]: val }));
  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setSaving(true);
    setErr(null);
    const out: Record<string, any> = {};
    for (const f of fields) {
      let x = v[f.name];
      if (x === "" || x === undefined) continue;
      if (f.type === "number") x = Number(x);
      if (f.type === "datetime-local" && x) x = new Date(x).toISOString();
      out[f.name] = x;
    }
    try { await onSubmit(out); } catch (ex: any) { setErr(ex); } finally { setSaving(false); }
  };
  return (
    <form onSubmit={submit} className="form">
      <ErrorBox error={err} />
      <div className="grid-form">
        {fields.map((f) => (
          <label key={f.name} className={f.type === "textarea" ? "span2" : ""}>
            <span>{f.label}{f.required && " *"}</span>
            {f.type === "select" ? (
              <select value={v[f.name] ?? ""} required={f.required} onChange={(e) => set(f.name, e.target.value)}>
                <option value="">— select —</option>
                {f.options?.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
              </select>
            ) : f.type === "checkbox" ? (
              <input type="checkbox" checked={!!v[f.name]} onChange={(e) => set(f.name, e.target.checked)} />
            ) : f.type === "textarea" ? (
              <textarea value={v[f.name] ?? ""} required={f.required} onChange={(e) => set(f.name, e.target.value)} rows={3} />
            ) : (
              <input type={f.type || "text"} step={f.step || (f.type === "number" ? "any" : undefined)} value={v[f.name] ?? ""} required={f.required}
                     onChange={(e) => set(f.name, e.target.value)} />
            )}
            {f.help && <small className="muted">{f.help}</small>}
          </label>
        ))}
      </div>
      <Btn type="submit" disabled={saving || busy}>{saving ? "Saving…" : submitLabel}</Btn>
    </form>
  );
}

export function Modal({ title, onClose, children }: { title: string; onClose: () => void; children: React.ReactNode }) {
  useEffect(() => {
    const k = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", k);
    return () => window.removeEventListener("keydown", k);
  }, [onClose]);
  return (
    <div className="modal-bg" onClick={onClose}>
      <div className="modal" role="dialog" aria-label={title} onClick={(e) => e.stopPropagation()}>
        <header className="card-h"><h3>{title}</h3><Btn kind="ghost" onClick={onClose} aria-label="Close">✕</Btn></header>
        {children}
      </div>
    </div>
  );
}

let toastFn: (m: string, tone?: string) => void = () => {};
export const toast = (m: string, tone = "green") => toastFn(m, tone);
export function Toaster() {
  const [items, setItems] = useState<{ id: number; m: string; tone: string }[]>([]);
  toastFn = (m, tone = "green") => {
    const id = Date.now() + Math.random();
    setItems((x) => [...x, { id, m, tone }]);
    setTimeout(() => setItems((x) => x.filter((i) => i.id !== id)), 4500);
  };
  return <div className="toaster">{items.map((i) => <div key={i.id} className={`alert alert-${i.tone}`}>{i.m}</div>)}</div>;
}

export function Checks({ checks }: { checks: { check: string; ok: boolean; severity: string; message: string }[] }) {
  return (
    <ul className="checks">
      {checks.map((c, i) => (
        <li key={i} className={c.ok ? "ok" : c.severity === "warning" ? "warn" : "fail"}>
          <span>{c.ok ? "✔" : c.severity === "warning" ? "!" : "✖"}</span> <b>{c.check.replace(/_/g, " ")}</b> — {c.message}
          {!c.ok && c.severity !== "warning" && <em className="muted"> ({c.severity === "commercial" ? "authorised override possible" : "mandatory"})</em>}
        </li>
      ))}
    </ul>
  );
}

export function Kpi({ label, value, source, basis }: { label: string; value: any; source?: string; basis?: string }) {
  return (
    <div className="kpi">
      <div className="kpi-l">{label}</div>
      <div className="kpi-v">{value ?? "—"}</div>
      {(source || basis) && <div className="kpi-s">{basis && <Badge v={basis} />} {source}</div>}
    </div>
  );
}
