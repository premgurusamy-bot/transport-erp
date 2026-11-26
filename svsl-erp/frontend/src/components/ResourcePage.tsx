import React, { useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { api, qs } from "../lib/api";
import { t } from "../lib/i18n";
import { Btn, cell, Col, ErrorBox, Meta, MetaForm, Modal, Page, Pager, Search, STATUS_TONE, Table, invalidateLookup, run, useLoad } from "./ui";
import { Breakdown, color, Icon, short, StatCard } from "./charts";
import { iconOf } from "../lib/nav";
import { FilterBar, FilterSpec, useUrlFilters } from "./filters";

const TONE_COLOR: Record<string, string> = { good: "var(--c3)", bad: "var(--bad)", warn: "var(--c2)", info: "var(--c1)", muted: "var(--c7)" };

/** Summary cards shown above every list: total, active, added in 30 days and a breakdown by status/type. */
export function ListSummary({ name, icon, reloadKey }: { name: string; icon?: string; reloadKey?: any }) {
  const { data: s } = useLoad<any>(`/api/r/${name}/summary`, [reloadKey]);
  if (!s) return <div className="summary"><div className="skeleton" style={{ height: 96 }} /><div className="skeleton" style={{ height: 96 }} /><div className="skeleton wide" style={{ height: 96 }} /></div>;
  const hasAmount = s.by?.counts.some((c: any) => c.amount !== undefined);
  let used = 0;
  const items = (s.by?.counts || []).map((c: any) => {
    const tone = STATUS_TONE[c.label];
    return { label: c.label, value: c.count, color: tone ? TONE_COLOR[tone] : color(used++), sub: hasAmount && Number(c.amount) ? short(c.amount) : undefined };
  });
  return <div className="summary">
    <StatCard icon={icon || iconOf(window.location.pathname) || "file"} label="Total records" value={s.total.toLocaleString("en-IN")} foot={s.active !== undefined ? <>{s.active.toLocaleString("en-IN")} active · {(s.total - s.active).toLocaleString("en-IN")} inactive</> : null} />
    {s.added_30d !== undefined && <StatCard icon="calendar" label="Added in 30 days" value={s.added_30d.toLocaleString("en-IN")} tone="info" foot={s.total ? <>{Math.round((100 * s.added_30d) / s.total)}% of all records</> : null} />}
    {s.by && items.length > 0 && <div className="stat wide"><div className="stat-h"><span className="stat-ic"><Icon name="pie" /></span><span>By {s.by.label.toLowerCase()}</span></div><Breakdown items={items} /></div>}
  </div>;
}

type Props = {
  name: string;
  title?: string;
  columns: string[];
  filters?: Record<string, any>;
  rowActions?: (row: any, reload: () => void) => React.ReactNode;
  detail?: (row: any, reload: () => void) => React.ReactNode;
  headerActions?: (reload: () => void) => React.ReactNode;
  defaults?: Record<string, any>;
  embedded?: boolean;
  summary?: boolean;
};

function colFor(meta: Meta, key: string): Col {
  const f = meta.fields.find((x) => x.name === key);
  if (!f) return { key, label: key };
  const type = f.ref ? "ref" : f.type === "number" && /amount|value|rate|limit|salary|freight|cost|emi|₹/i.test(f.label) ? "money" : f.type === "number" || f.type === "int" ? "number" : f.type === "date" ? "date" : f.type === "datetime" ? "datetime" : f.type === "bool" ? "bool" : key === "status" ? "badge" : "text";
  return { key, label: f.label, type: type as any, ref: f.ref };
}

const REF_FILTERS = ["vehicles", "drivers", "customers", "vendors", "routes", "warehouses", "employees", "ledgers", "items"];
const OPTION_FILTERS = ["status", "stage", "kind", "category", "doc_type", "vehicle_type", "ownership", "employment_status", "party_type", "purpose", "mode", "shift", "frequency"];

/** Filters offered on a list: up to three vehicle / driver / customer … fields, a status-type field and a date range. */
function autoFilters(m: Meta | null, fixed: Record<string, any>): FilterSpec[] {
  if (!m) return [];
  const usable = m.fields.filter((f: any) => !f.hidden && !(f.name in fixed));
  const refs = usable.filter((f: any) => f.ref && REF_FILTERS.includes(f.ref)).sort((a: any, b: any) => REF_FILTERS.indexOf(a.ref) - REF_FILTERS.indexOf(b.ref)).slice(0, 3)
    .map((f: any) => ({ key: f.name, label: f.label, ref: f.ref }));
  const opt = OPTION_FILTERS.map((n) => usable.find((f: any) => f.name === n && f.options)).find(Boolean) as any;
  const out: FilterSpec[] = [...refs];
  if (opt) out.push({ key: opt.name, label: opt.label, type: "select", options: opt.options.filter((o: string) => o !== "") });
  if ((m as any).date_field) out.push({ key: "from", label: "From", type: "date" }, { key: "to", label: "To", type: "date" });
  return out;
}

export default function ResourcePage({ name, title, columns, filters = {}, rowActions, detail, headerActions, defaults = {}, embedded, summary = true }: Props) {
  const meta = useLoad<Meta>(`/api/r/${name}/meta`);
  const [q, setQ] = useState("");
  const [offset, setOffset] = useState(0);
  const [showInactive, setShowInactive] = useState(false);
  const limit = 50;
  const hasActive = meta.data?.fields.some((f) => f.name === "is_active");
  const specs = useMemo(() => autoFilters(meta.data, filters), [meta.data, JSON.stringify(filters)]);
  const [fv, setF, clearF] = useUrlFilters(specs);
  const list = useLoad<{ items: any[]; total: number }>(meta.data ? `/api/r/${name}${qs({ q, limit, offset, ...fv, ...filters, ...(hasActive && !showInactive ? { is_active: true } : {}) })}` : null, [JSON.stringify(filters)]);
  const [sp, setSp] = useSearchParams();
  const openParam = sp.get("open");
  const [editing, setEditing] = useState<any | null>(null);
  const [viewing, setViewing] = useState<any | null>(null);
  useEffect(() => setOffset(0), [q, JSON.stringify(fv)]);
  useEffect(() => {  // ?open=<list>.<id> (e.g. from the search box) opens that record
    const [which, id] = (openParam || "").split(".");
    if (which !== name || !id) return;
    api.get(`/api/r/${name}/${id}`).then(setViewing).catch(() => {});
  }, [openParam, name]);
  const closeView = () => {
    setViewing(null);
    if (openParam?.startsWith(name + ".")) { const next = new URLSearchParams(sp); next.delete("open"); setSp(next, { replace: true }); }
  };
  if (meta.error) return <ErrorBox error={meta.error} />;
  if (!meta.data) return null;
  const m = meta.data;
  const cols: Col[] = columns.map((c) => colFor(m, c));
  if (rowActions) cols.push({ key: "_a", label: "", render: (r) => <div className="row gap" onClick={(e) => e.stopPropagation()}>{rowActions(r, list.reload)}</div> });

  const save = async () => {
    const isNew = !editing.id;
    const r = await run(() => (isNew ? api.post(`/api/r/${name}`, editing) : api.put(`/api/r/${name}/${editing.id}`, editing)), isNew ? "Created" : "Saved");
    if (r) { invalidateLookup(`/api/r/${name}?lookup=1`); setEditing(null); list.reload(); if (viewing) setViewing(r); }
  };
  const remove = async (row: any) => {
    if (!confirm(m.soft_delete ? "Deactivate this record? History is kept." : "Delete this record?")) return;
    const r = await run(() => api.del(`/api/r/${name}/${row.id}`), m.soft_delete ? "Deactivated" : "Deleted");
    if (r) { invalidateLookup(`/api/r/${name}?lookup=1`); setViewing(null); list.reload(); }
  };

  const body = <>
    {summary && <ListSummary name={name} reloadKey={list.data?.total} />}
    {specs.length > 0 && <FilterBar specs={specs} values={fv} set={setF} clear={clearF} />}
    <div className="toolbar">
      <Search value={q} onChange={setQ} />
      {hasActive && <label className="row gap small"><input type="checkbox" checked={showInactive} onChange={(e) => setShowInactive(e.target.checked)} /> show inactive</label>}
      <div className="grow" />
      {headerActions?.(list.reload)}
      {m.can_create && <Btn kind="primary" onClick={() => setEditing({ ...defaults, ...filters })}>+ {t("New")}</Btn>}
    </div>
    <ErrorBox error={list.error} />
    <Table cols={cols} rows={list.data?.items || []} onRow={(r) => (detail ? setViewing(r) : m.can_update ? setEditing(r) : setViewing(r))} />
    <Pager total={list.data?.total || 0} limit={limit} offset={offset} onChange={setOffset} />
    {editing && <Modal wide title={`${editing.id ? t("Edit") : t("New")} – ${title || m.title}`} onClose={() => setEditing(null)}
      footer={<><Btn onClick={() => setEditing(null)}>{t("Cancel")}</Btn><Btn kind="primary" onClick={save}>{t("Save")}</Btn></>}>
      <MetaForm meta={m} value={editing} onChange={setEditing} />
    </Modal>}
    {viewing && !editing && <Modal wide title={String(viewing[m.label] ?? title ?? m.title)} onClose={closeView}
      footer={<>{m.can_delete && (viewing.is_active !== false) && <Btn kind="danger" onClick={() => remove(viewing)}>{m.soft_delete ? "Deactivate" : "Delete"}</Btn>}{m.can_update && <Btn kind="primary" onClick={() => setEditing(viewing)}>{t("Edit")}</Btn>}<Btn onClick={closeView}>{t("Close")}</Btn></>}>
      {detail ? detail(viewing, () => { list.reload(); api.get(`/api/r/${name}/${viewing.id}`).then(setViewing).catch(() => {}); }) : null}
      <div className="kv">{m.fields.filter((f) => !f.hidden && viewing[f.name] !== null && viewing[f.name] !== "" && viewing[f.name] !== undefined).map((f) => <div key={f.name}><span>{f.label}</span><b>{cell(viewing, colFor(m, f.name))}</b></div>)}</div>
    </Modal>}
  </>;
  return embedded ? body : <Page title={title || m.title}>{body}</Page>;
}

