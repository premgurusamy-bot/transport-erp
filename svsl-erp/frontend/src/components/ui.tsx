import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api, ApiError, openFile } from "../lib/api";
import { dt, inr, label as niceLabel, num } from "../lib/format";
import { t } from "../lib/i18n";

// ------------------------------------------------------------------ toast
type ToastMsg = { id: number; text: string; kind: "ok" | "err" | "info" };
let pushToast: (m: Omit<ToastMsg, "id">) => void = () => {};
export const toast = {
  ok: (text: string) => pushToast({ text, kind: "ok" }),
  err: (e: any) => pushToast({ text: e instanceof ApiError || e instanceof Error ? e.message : String(e), kind: "err" }),
  info: (text: string) => pushToast({ text, kind: "info" }),
};
export function Toasts() {
  const [items, setItems] = useState<ToastMsg[]>([]);
  useEffect(() => {
    pushToast = (m) => {
      const id = Date.now() + Math.random();
      setItems((x) => [...x, { ...m, id }]);
      setTimeout(() => setItems((x) => x.filter((i) => i.id !== id)), m.kind === "err" ? 7000 : 3500);
    };
  }, []);
  return <div className="toasts" role="status">{items.map((i) => <div key={i.id} className={`toast ${i.kind}`} onClick={() => setItems((x) => x.filter((y) => y.id !== i.id))}>{i.text}</div>)}</div>;
}

// ------------------------------------------------------------------ hooks
export function useLoad<T = any>(url: string | null, deps: any[] = []): { data: T | null; loading: boolean; error: string | null; reload: () => void; setData: (d: T) => void } {
  const [data, setData] = useState<T | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [tick, setTick] = useState(0);
  useEffect(() => {
    if (!url) return;
    let live = true;
    setLoading(true);
    setError(null);
    api.get(url).then((d) => live && setData(d)).catch((e) => live && setError(e.message)).finally(() => live && setLoading(false));
    return () => { live = false; };
  }, [url, tick, ...deps]);
  return { data, loading, error, reload: useCallback(() => setTick((x) => x + 1), []), setData };
}

export async function run<T>(fn: () => Promise<T>, okMsg?: string): Promise<T | undefined> {
  try {
    const r = await fn();
    if (okMsg) toast.ok(okMsg);
    return r;
  } catch (e) {
    toast.err(e);
    return undefined;
  }
}

export const download = (url: string, name?: string) => openFile(url, name).catch(toast.err);

// ------------------------------------------------------------------ primitives
export function Btn({ kind = "default", small, ...p }: React.ButtonHTMLAttributes<HTMLButtonElement> & { kind?: "primary" | "danger" | "default" | "ghost"; small?: boolean }) {
  const [busy, setBusy] = useState(false);
  const onClick = p.onClick;
  return <button {...p} disabled={p.disabled || busy} className={`btn ${kind} ${small ? "sm" : ""} ${p.className || ""}`}
    onClick={onClick ? async (e) => { const r: any = onClick(e); if (r && typeof r.then === "function") { setBusy(true); try { await r; } finally { setBusy(false); } } } : undefined} />;
}

export function Card({ title, actions, children, className }: { title?: React.ReactNode; actions?: React.ReactNode; children: React.ReactNode; className?: string }) {
  return <section className={`card ${className || ""}`}>{(title || actions) && <header className="card-h"><h3>{title}</h3><div className="row gap">{actions}</div></header>}<div className="card-b">{children}</div></section>;
}

export function Page({ title, actions, children }: { title: string; actions?: React.ReactNode; children: React.ReactNode }) {
  useEffect(() => { document.title = `${title} – SVL ERP`; }, [title]);
  return <div className="page"><div className="page-h"><h1>{t(title)}</h1><div className="row gap wrap">{actions}</div></div>{children}</div>;
}

export function Kpi({ label, value, sub, tone, onClick }: { label: string; value: React.ReactNode; sub?: React.ReactNode; tone?: "good" | "bad" | "warn"; onClick?: () => void }) {
  return <div className={`kpi ${tone || ""} ${onClick ? "click" : ""}`} onClick={onClick}><div className="kpi-l">{t(label)}</div><div className="kpi-v">{value}</div>{sub && <div className="kpi-s">{sub}</div>}</div>;
}

const STATUS_TONE: Record<string, string> = {
  Available: "good", Active: "good", Paid: "good", Verified: "good", Acknowledged: "good", Closed: "muted", Settled: "good", Delivered: "good", "POD Received": "good", "POD Collected": "good", Completed: "good", Posted: "good", Generated: "good", Adjusted: "good", Approved: "good", sent: "good", Matched: "good",
  "On Trip": "info", "In Transit": "info", Dispatched: "info", Loading: "info", Loaded: "info", Billed: "info", Issued: "info", "Partly Paid": "warn", Open: "warn", Pending: "warn", Requested: "warn", Draft: "muted", "Filed - Awaiting Ack": "info",
  Maintenance: "warn", Breakdown: "bad", Cancelled: "bad", Failed: "bad", Corrupted: "bad", Rejected: "bad", Inactive: "muted", Sold: "muted", Superseded: "muted", Reversal: "muted", critical: "bad", warning: "warn", info: "info", failed: "bad", not_configured: "muted",
};
export function Badge({ v }: { v: any }) {
  if (v === null || v === undefined || v === "") return null;
  if (typeof v === "boolean") return <span className={`badge ${v ? "good" : "muted"}`}>{v ? "Yes" : "No"}</span>;
  return <span className={`badge ${STATUS_TONE[String(v)] || ""}`}>{String(v)}</span>;
}

export function Modal({ title, onClose, children, wide, footer }: { title: string; onClose: () => void; children: React.ReactNode; wide?: boolean; footer?: React.ReactNode }) {
  useEffect(() => {
    const h = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", h);
    return () => window.removeEventListener("keydown", h);
  }, [onClose]);
  return <div className="modal-bg" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
    <div className={`modal ${wide ? "wide" : ""}`} role="dialog" aria-label={title}>
      <header className="modal-h"><h3>{title}</h3><button className="x" onClick={onClose} aria-label="Close">×</button></header>
      <div className="modal-b">{children}</div>
      {footer && <footer className="modal-f">{footer}</footer>}
    </div>
  </div>;
}

export function ReasonModal({ title, label = "Reason", onSubmit, onClose, extra }: { title: string; label?: string; onSubmit: (reason: string, extra: Record<string, string>) => Promise<any>; onClose: () => void; extra?: string[] }) {
  const [reason, setReason] = useState("");
  const [vals, setVals] = useState<Record<string, string>>({});
  return <Modal title={title} onClose={onClose} footer={<><Btn onClick={onClose}>{t("Cancel")}</Btn><Btn kind="danger" disabled={reason.trim().length < 3} onClick={async () => { const r = await onSubmit(reason, vals); if (r !== undefined) onClose(); }}>Confirm</Btn></>}>
    {(extra || []).map((e) => <Field key={e} label={e}><input value={vals[e] || ""} onChange={(ev) => setVals({ ...vals, [e]: ev.target.value })} /></Field>)}
    <Field label={label}><textarea rows={3} value={reason} onChange={(e) => setReason(e.target.value)} autoFocus /></Field>
  </Modal>;
}

export function Field({ label, children, help, wide, required }: { label: string; children: React.ReactNode; help?: string; wide?: boolean; required?: boolean }) {
  return <label className={`field ${wide ? "wide" : ""}`}><span className="field-l">{label}{required && <b className="req">*</b>}</span>{children}{help && <small className="help">{help}</small>}</label>;
}

// lookup cache for reference selects
const lookupCache: Record<string, Promise<any[]>> = {};
export function invalidateLookup(ref: string) { delete lookupCache[ref]; }
export function useLookup(ref: string | null) {
  const [items, setItems] = useState<any[]>([]);
  useEffect(() => {
    if (!ref) return;
    const url = ref.startsWith("/") ? ref : `/api/r/${ref}?lookup=1`;
    lookupCache[url] = lookupCache[url] || api.get(url).catch(() => []);
    lookupCache[url].then(setItems);
  }, [ref]);
  return items;
}

export function RefSelect({ refName, value, onChange, placeholder, disabled, filter }: { refName: string; value: any; onChange: (v: any) => void; placeholder?: string; disabled?: boolean; filter?: (i: any) => boolean }) {
  const items = useLookup(refName);
  const list = filter ? items.filter(filter) : items;
  return <select value={value ?? ""} disabled={disabled} onChange={(e) => onChange(e.target.value ? Number(e.target.value) : null)}>
    <option value="">{placeholder || "— select —"}</option>
    {list.map((i) => <option key={i.id} value={i.id}>{i.label}</option>)}
  </select>;
}

export function RefLabel({ refName, id }: { refName: string; id: any }) {
  const items = useLookup(id ? refName : null);
  if (!id) return null;
  return <>{items.find((i) => i.id === id)?.label ?? `#${id}`}</>;
}

// ------------------------------------------------------------------ table
export type Col = { key: string; label: string; type?: "money" | "number" | "date" | "datetime" | "badge" | "bool" | "ref" | "text"; ref?: string; render?: (row: any) => React.ReactNode; align?: string };

export function cell(row: any, c: Col): React.ReactNode {
  if (c.render) return c.render(row);
  const v = row[c.key];
  switch (c.type) {
    case "money": return inr(v);
    case "number": return num(v);
    case "date": case "datetime": return dt(v);
    case "badge": return <Badge v={v} />;
    case "bool": return v ? "✔" : "";
    case "ref": return <RefLabel refName={c.ref!} id={v} />;
    default: return v === null || v === undefined ? "" : typeof v === "object" ? JSON.stringify(v) : String(v);
  }
}

export function Table({ cols, rows, onRow, empty = "No records", totals, dense }: { cols: Col[]; rows: any[]; onRow?: (r: any) => void; empty?: string; totals?: Record<string, any>; dense?: boolean }) {
  return <div className="table-wrap"><table className={`tbl ${dense ? "dense" : ""}`}>
    <thead><tr>{cols.map((c) => <th key={c.key} className={c.type === "money" || c.type === "number" ? "r" : ""}>{c.label}</th>)}</tr></thead>
    <tbody>
      {rows.length === 0 && <tr><td colSpan={cols.length} className="empty">{empty}</td></tr>}
      {rows.map((r, i) => <tr key={r.id ?? i} onClick={onRow ? () => onRow(r) : undefined} className={onRow ? "click" : ""}>
        {cols.map((c) => <td key={c.key} className={c.type === "money" || c.type === "number" ? "r" : ""}>{cell(r, c)}</td>)}
      </tr>)}
    </tbody>
    {totals && <tfoot><tr>{cols.map((c, i) => <td key={c.key} className={c.type === "money" || c.type === "number" ? "r" : ""}>{c.key in totals ? cell(totals, c) : i === 0 ? "Total" : ""}</td>)}</tr></tfoot>}
  </table></div>;
}

export function Tabs({ tabs, value, onChange }: { tabs: string[]; value: string; onChange: (v: string) => void }) {
  return <div className="tabs" role="tablist">{tabs.map((x) => <button key={x} role="tab" aria-selected={x === value} className={x === value ? "on" : ""} onClick={() => onChange(x)}>{x}</button>)}</div>;
}

export function Search({ value, onChange, placeholder }: { value: string; onChange: (v: string) => void; placeholder?: string }) {
  const [v, setV] = useState(value);
  const timer = useRef<any>();
  return <input className="search" type="search" placeholder={placeholder || t("Search") + "…"} value={v} onChange={(e) => { setV(e.target.value); clearTimeout(timer.current); timer.current = setTimeout(() => onChange(e.target.value), 300); }} />;
}

export function Pager({ total, limit, offset, onChange }: { total: number; limit: number; offset: number; onChange: (o: number) => void }) {
  if (total <= limit) return <div className="muted small">{total} record(s)</div>;
  return <div className="row gap center small"><Btn small disabled={offset === 0} onClick={() => onChange(Math.max(0, offset - limit))}>‹ Prev</Btn>
    <span>{offset + 1}–{Math.min(total, offset + limit)} of {total}</span>
    <Btn small disabled={offset + limit >= total} onClick={() => onChange(offset + limit)}>Next ›</Btn></div>;
}

// ------------------------------------------------------------------ metadata-driven form
export type Meta = { name: string; title: string; label: string; fields: any[]; can_create: boolean; can_update: boolean; can_delete: boolean; soft_delete: boolean };

export function FieldInput({ f, value, onChange }: { f: any; value: any; onChange: (v: any) => void }) {
  const ro = f.readonly;
  if (f.ref) return <RefSelect refName={f.ref} value={value} onChange={onChange} disabled={ro} />;
  if (f.options) return <select value={value ?? ""} disabled={ro} onChange={(e) => onChange(e.target.value)}><option value="">—</option>{f.options.filter((o: string) => o !== "").map((o: string) => <option key={o} value={o}>{niceLabel(o)}</option>)}</select>;
  switch (f.type) {
    case "bool": return <input type="checkbox" checked={!!value} disabled={ro} onChange={(e) => onChange(e.target.checked)} />;
    case "date": return <input type="date" value={value ?? ""} disabled={ro} onChange={(e) => onChange(e.target.value)} />;
    case "datetime": return <input type="datetime-local" value={value ? String(value).slice(0, 16) : ""} disabled={ro} onChange={(e) => onChange(e.target.value)} />;
    case "int": case "number": return <input type="number" step="any" value={value ?? ""} disabled={ro} onChange={(e) => onChange(e.target.value)} />;
    case "text": return <textarea rows={2} value={value ?? ""} disabled={ro} onChange={(e) => onChange(e.target.value)} />;
    case "json": return <textarea rows={3} className="mono" value={typeof value === "string" ? value : value ? JSON.stringify(value, null, 1) : ""} disabled={ro} onChange={(e) => { try { onChange(JSON.parse(e.target.value)); } catch { onChange(e.target.value); } }} />;
    default: return <input type={f.secret ? "password" : "text"} autoComplete="off" maxLength={f.max_length || undefined} value={value ?? ""} disabled={ro} placeholder={f.secret && value ? "unchanged" : ""}
      onChange={(e) => onChange(["gstin", "pan", "ifsc", "vehicle_no"].includes(f.validator) ? e.target.value.toUpperCase() : e.target.value)} />;
  }
}

export function MetaForm({ meta, value, onChange, only }: { meta: Meta; value: any; onChange: (v: any) => void; only?: string[] }) {
  const fields = meta.fields.filter((f) => !f.hidden && (!only || only.includes(f.name)));
  const groups = useMemo(() => {
    const g: Record<string, any[]> = {};
    fields.forEach((f) => { (g[f.group || "Details"] = g[f.group || "Details"] || []).push(f); });
    return g;
  }, [meta, only]);
  const keys = Object.keys(groups);
  const [tab, setTab] = useState(keys[0]);
  const shown = keys.length > 1 ? groups[tab] || [] : fields;
  return <div>
    {keys.length > 1 && <Tabs tabs={keys} value={tab} onChange={setTab} />}
    <div className="form-grid">
      {shown.map((f) => <Field key={f.name} label={f.label} help={f.help} required={f.required} wide={f.type === "text" || f.type === "json"}>
        <FieldInput f={f} value={value[f.name]} onChange={(v) => onChange({ ...value, [f.name]: v })} />
      </Field>)}
    </div>
  </div>;
}

export function Empty({ children }: { children: React.ReactNode }) { return <div className="empty-box">{children}</div>; }
export function Loading() { return <div className="loading">Loading…</div>; }
export function ErrorBox({ error }: { error: string | null }) { return error ? <div className="error-box">{error}</div> : null; }
