// Groups & ledgers: the chart of accounts as a tree (main groups › your groups › ledgers) with totals on every group.
import React, { useMemo, useState } from "react";
import { api, can } from "../lib/api";
import { fyStart, inr, today } from "../lib/format";
import { Breakdown, color, Icon } from "../components/charts";
import { Btn, Card, Field, Modal, run, toast, useLoad } from "../components/ui";

type Led = { id: number; name: string; balance: string; is_active: boolean; system: boolean; party_type?: string };
export type GNode = { id: number; name: string; nature: string; system: boolean; fixed: boolean; parent_id: number | null; groups: GNode[]; ledgers: Led[]; total: string; ledger_count: number };

const drcr = (v: any) => { const n = Number(v || 0); return n === 0 ? "–" : `${inr(Math.abs(n))} ${n > 0 ? "Dr" : "Cr"}`; };

function walk(nodes: GNode[], fn: (g: GNode, path: string[]) => void, path: string[] = []) {
  nodes.forEach((g) => { fn(g, [...path, g.name]); walk(g.groups, fn, [...path, g.name]); });
}
const topOf = (byId: Record<number, GNode>, g: GNode): GNode => (g.parent_id && byId[g.parent_id] ? topOf(byId, byId[g.parent_id]) : g);

export function GroupTree({ onLedger }: { onLedger: (l: { id: number; name: string }) => void }) {
  const [mode, setMode] = useState<"balance" | "movement">("balance");
  const tree = useLoad<GNode[]>(`/api/account-groups/tree${mode === "movement" ? `?start=${fyStart()}&on=${today()}` : ""}`);
  const [open, setOpen] = useState<Record<number, boolean>>({});
  const [q, setQ] = useState("");
  const [sel, setSel] = useState<number | null>(null);
  const [dlg, setDlg] = useState<any>(null);
  const nodes = tree.data || [];
  React.useEffect(() => {  // main groups start expanded, as in the approved design
    if (tree.data && !Object.keys(open).length) setOpen(Object.fromEntries(tree.data.map((g) => [g.id, true])));
  }, [tree.data]);
  const { byId, paths } = useMemo(() => {
    const byId: Record<number, GNode> = {}; const paths: Record<number, string> = {};
    walk(nodes, (g, p) => { byId[g.id] = g; paths[g.id] = p.join(" › "); });
    return { byId, paths };
  }, [tree.data]);
  const query = q.trim().toLowerCase();
  const matches = (g: GNode): boolean => !query || g.name.toLowerCase().includes(query) || g.ledgers.some((l) => l.name.toLowerCase().includes(query)) || g.groups.some(matches);
  const expandAll = (v: boolean) => { const o: Record<number, boolean> = {}; Object.keys(byId).forEach((k) => (o[Number(k)] = v)); setOpen(o); };
  const reload = () => tree.reload();
  const selected = sel ? byId[sel] : null;

  const rows: React.ReactNode[] = [];
  const emit = (g: GNode, depth: number) => {
    if (!matches(g)) return;
    const isOpen = query ? true : !!open[g.id];
    rows.push(<div key={`g${g.id}`} className={`gt-row grp d${Math.min(depth, 3)} ${sel === g.id ? "sel" : ""}`} onClick={() => setSel(g.id)}>
      <span className="gt-name" style={{ paddingLeft: depth * 24 }}>
        <button type="button" className={`chev ${isOpen ? "on" : ""}`} aria-label={`${isOpen ? "Collapse" : "Expand"} ${g.name}`} onClick={(e) => { e.stopPropagation(); setOpen({ ...open, [g.id]: !isOpen }); }}><Icon name="chevron" size={14} /></button>
        <Icon name="folder" size={17} className={depth === 0 ? "gt-main" : "gt-sub"} />
        <b>{g.name}</b>
        {depth === 0 ? <span className="badge">Main group</span> : !g.system ? <span className="badge info">Your group</span> : null}
      </span>
      <span className="gt-count">{g.ledger_count}</span>
      <span className="gt-amt">{drcr(g.total)}</span>
    </div>);
    if (!isOpen) return;
    g.groups.forEach((c) => emit(c, depth + 1));
    g.ledgers.filter((l) => !query || l.name.toLowerCase().includes(query) || g.name.toLowerCase().includes(query)).forEach((l) => rows.push(
      <div key={`l${l.id}`} className="gt-row" onClick={() => onLedger(l)}>
        <span className="gt-name" style={{ paddingLeft: depth * 24 + 30 }}><Icon name="book" size={15} className="gt-led" /><span className={l.is_active ? "" : "muted"}>{l.name}</span></span>
        <span className="gt-count" />
        <span className="gt-amt led">{drcr(l.balance)}</span>
      </div>));
  };
  nodes.forEach((g) => emit(g, 0));

  const parts = selected ? [...selected.groups.map((c) => ({ label: c.name, value: Math.abs(Number(c.total)) })), ...selected.ledgers.map((l) => ({ label: l.name, value: Math.abs(Number(l.balance)) }))].filter((x) => x.value > 0).sort((a, b) => b.value - a.value) : [];
  const top = parts.slice(0, 6).map((p, i) => ({ ...p, color: color(i) }));
  if (parts.length > 6) top.push({ label: `${parts.length - 6} more`, value: parts.slice(6).reduce((a, p) => a + p.value, 0), color: "var(--c7)" });
  const writable = can("accounts:write");

  return <>
    <div className="toolbar">
      <input className="search" type="search" placeholder="Search a group or ledger – e.g. salary" value={q} onChange={(e) => setQ(e.target.value)} />
      <div className="seg-inline">
        <button type="button" className={mode === "balance" ? "on" : ""} onClick={() => setMode("balance")}>Balances today</button>
        <button type="button" className={mode === "movement" ? "on" : ""} onClick={() => setMode("movement")}>This year's movement</button>
      </div>
      <div className="grow" />
      <Btn small onClick={() => expandAll(true)}>Expand all</Btn><Btn small onClick={() => expandAll(false)}>Collapse all</Btn>
      {writable && <Btn onClick={() => setDlg({ kind: "new", parent_id: selected && !selected.fixed ? selected.id : null, ledger_ids: [] })}>+ Group</Btn>}
      {writable && <Btn kind="primary" onClick={() => setDlg({ kind: "ledger", group_id: selected && !selected.fixed ? selected.id : null })}>+ Ledger</Btn>}
    </div>
    <div className="gt-wrap">
      <div className="gt-table">
        <div className="gt-row head"><span>Group / ledger</span><span className="gt-count">Ledgers</span><span className="gt-amt">{mode === "balance" ? "Balance" : "Movement"}</span></div>
        <div className="gt-body">{tree.loading && !tree.data ? <div className="loading">Loading…</div> : rows.length ? rows : <div className="empty-box">Nothing matches “{q}”</div>}</div>
      </div>
      <div className="gt-side">
        {selected ? <Card>
          <div className="stat-h" style={{ marginBottom: 8 }}><span className="stat-ic"><Icon name="folder" /></span><span><b>{selected.name}</b><br /><small className="muted">{selected.parent_id ? `Group under ${byId[selected.parent_id]?.name}` : `Main group · ${selected.nature}`}</small></span></div>
          <div className="stat-v">{drcr(selected.total)}</div>
          <div className="muted small" style={{ margin: "4px 0 10px" }}>{selected.ledger_count} ledger(s) · {mode === "balance" ? "balance today" : "this financial year"}</div>
          {top.length > 0 && <Breakdown items={top} fmt={(v) => inr(v)} />}
          {writable && <div className="row gap wrap" style={{ marginTop: 12 }}>
            {!selected.fixed && <Btn small onClick={() => setDlg({ kind: "new", parent_id: selected.id, ledger_ids: [] })}>+ Sub-group</Btn>}
            {!selected.fixed && <Btn small onClick={() => setDlg({ kind: "move", group: selected, ledger_ids: [] })}>Move ledgers here</Btn>}
            {!selected.fixed && <Btn small onClick={() => setDlg({ kind: "ledger", group_id: selected.id })}>+ Ledger here</Btn>}
            {!selected.system && <Btn small onClick={() => setDlg({ kind: "rename", group: selected, name: selected.name, parent_id: selected.parent_id })}>Rename / move</Btn>}
            {!selected.system && <Btn small kind="danger" onClick={async () => { if (confirm(`Delete group “${selected.name}”?`) && await run(() => api.del(`/api/account-groups/${selected.id}`), "Group deleted")) { setSel(null); reload(); } }}>Delete</Btn>}
          </div>}
          {selected.fixed && <p className="muted small" style={{ marginTop: 10 }}>The system reads this group by name (receivables, payables, cash &amp; bank), so it has no sub-groups and its ledgers stay here.</p>}
        </Card> : <Card title="How grouping works"><ul className="small" style={{ paddingLeft: 18, margin: 0, lineHeight: 1.6 }}>
          <li>Main groups (Indirect Expenses, Current Assets…) are fixed, as in Tally.</li>
          <li>Create your own groups inside them – any depth.</li>
          <li>Every group shows the total of everything under it.</li>
          <li>Move a ledger to another group any time; its past entries move with it.</li>
          <li>Groups print the same way in Trial balance, P&amp;L and Balance sheet (Summary or Detailed).</li>
          <li>Click a group for details, a ledger for its statement.</li>
        </ul></Card>}
      </div>
    </div>
    {dlg?.kind === "new" && <GroupDialog nodes={nodes} byId={byId} paths={paths} init={dlg} onClose={() => setDlg(null)} onDone={(id) => { setDlg(null); setOpen({ ...open, [id]: true, ...(dlg.parent_id ? { [dlg.parent_id]: true } : {}) }); setSel(id); reload(); }} />}
    {dlg?.kind === "move" && <GroupDialog nodes={nodes} byId={byId} paths={paths} init={{ ...dlg, parent_id: dlg.group.id }} moveOnly onClose={() => setDlg(null)} onDone={() => { setDlg(null); setOpen({ ...open, [dlg.group.id]: true }); reload(); }} />}
    {dlg?.kind === "rename" && <Modal title={`Group – ${dlg.group.name}`} onClose={() => setDlg(null)} footer={<Btn kind="primary" onClick={async () => { if (await run(() => api.put(`/api/account-groups/${dlg.group.id}`, { name: dlg.name, parent_id: dlg.parent_id }), "Group saved")) { setDlg(null); reload(); } }}>Save</Btn>}>
      <Field label="Group name"><input value={dlg.name} onChange={(e) => setDlg({ ...dlg, name: e.target.value })} /></Field>
      <Field label="Under"><select value={dlg.parent_id || ""} onChange={(e) => setDlg({ ...dlg, parent_id: Number(e.target.value) })}>{Object.values(byId).filter((g) => !g.fixed && g.id !== dlg.group.id && topOf(byId, g).nature === topOf(byId, dlg.group).nature && !paths[g.id].startsWith(paths[dlg.group.id] + " › ")).sort((a, b) => paths[a.id].localeCompare(paths[b.id])).map((g) => <option key={g.id} value={g.id}>{paths[g.id]}</option>)}</select></Field>
    </Modal>}
    {dlg?.kind === "ledger" && <NewLedger byId={byId} paths={paths} groupId={dlg.group_id} onClose={() => setDlg(null)} onDone={() => { setDlg(null); reload(); }} />}
  </>;
}

/** New group (with ledgers to move in) – or, with moveOnly, move ledgers into an existing group. */
function GroupDialog({ nodes, byId, paths, init, moveOnly, onClose, onDone }: { nodes: GNode[]; byId: Record<number, GNode>; paths: Record<number, string>; init: any; moveOnly?: boolean; onClose: () => void; onDone: (id: number) => void }) {
  const [f, setF] = useState<any>({ name: "", ...init });
  const [q, setQ] = useState("");
  const parent = f.parent_id ? byId[f.parent_id] : null;
  const nature = parent ? topOf(byId, parent).nature : null;
  const all: { id: number; name: string; group: GNode; balance: string }[] = [];
  walk(nodes, (g) => g.ledgers.forEach((l) => all.push({ id: l.id, name: l.name, group: g, balance: l.balance })));
  const why = (l: (typeof all)[0]) => (!parent ? "choose a group first" : l.group.id === parent.id ? "already in this group" : l.group.fixed ? `${l.group.name} ledgers stay in that group` : topOf(byId, l.group).nature !== nature ? `${topOf(byId, l.group).nature.toLowerCase()} – can't move to an ${String(nature).toLowerCase()} group` : "");
  const list = all.filter((l) => !q || l.name.toLowerCase().includes(q.toLowerCase())).sort((a, b) => (why(a) ? 1 : 0) - (why(b) ? 1 : 0) || a.name.localeCompare(b.name)).slice(0, 60);
  const ids: number[] = f.ledger_ids || [];
  const toggle = (id: number) => setF({ ...f, ledger_ids: ids.includes(id) ? ids.filter((x) => x !== id) : [...ids, id] });
  const chosen = all.filter((l) => ids.includes(l.id));
  const total = chosen.reduce((a, l) => a + Number(l.balance || 0), 0);
  const save = async () => {
    const r: any = moveOnly ? await run(() => api.post(`/api/account-groups/${f.parent_id}/ledgers`, { ledger_ids: ids }), `${ids.length} ledger(s) moved`)
      : await run(() => api.post("/api/account-groups", { name: f.name, parent_id: f.parent_id, ledger_ids: ids }), `Group created${ids.length ? `, ${ids.length} ledger(s) moved` : ""}`);
    if (r) onDone(moveOnly ? f.parent_id : r.id);
  };
  return <Modal wide title={moveOnly ? `Move ledgers into “${parent?.name}”` : "New group"} onClose={onClose} footer={<><Btn onClick={onClose}>Cancel</Btn><Btn kind="primary" disabled={moveOnly ? !ids.length : !(f.name.trim().length >= 2 && f.parent_id)} onClick={save}>{moveOnly ? `Move ${ids.length} ledger(s)` : ids.length ? `Create group & move ${ids.length} ledger(s)` : "Create group"}</Btn></>}>
    {!moveOnly && <div className="form-grid">
      <Field label="Group name" required><input autoFocus value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} placeholder="e.g. Salaries" /></Field>
      <Field label="Under" required help={nature ? `Type is taken from the main group: ${nature}${["Income", "Expense"].includes(nature) ? " – shown in Profit & Loss" : " – shown in the Balance sheet"}.` : undefined}>
        <select value={f.parent_id || ""} onChange={(e) => setF({ ...f, parent_id: Number(e.target.value) || null, ledger_ids: [] })}><option value="">— choose —</option>{Object.values(byId).filter((g) => !g.fixed).sort((a, b) => paths[a.id].localeCompare(paths[b.id])).map((g) => <option key={g.id} value={g.id}>{paths[g.id]}</option>)}</select>
      </Field>
    </div>}
    <Field label={moveOnly ? "Ledgers to move" : "Move these ledgers into the new group (optional)"}><input type="search" placeholder="Find ledgers – e.g. salary" value={q} onChange={(e) => setQ(e.target.value)} /></Field>
    <div className="pick-list">{list.map((l) => { const w = why(l); return <label key={l.id} className={`pick ${ids.includes(l.id) ? "on" : ""} ${w ? "off" : ""}`}>
      <input type="checkbox" disabled={!!w} checked={ids.includes(l.id)} onChange={() => toggle(l.id)} />
      <span className="grow">{l.name}</span><small className={w && !w.startsWith("already") && w !== "choose a group first" ? "warn-t" : "muted"}>{w || `now in ${l.group.name}`}</small>
    </label>; })}{!list.length && <div className="empty-box">No ledgers match</div>}</div>
    {ids.length > 0 && <div className="calc"><b>Preview</b><div style={{ marginTop: 4 }}>{paths[f.parent_id] || ""}{!moveOnly && f.name ? ` › ${f.name}` : ""} – {ids.length} ledger(s) · {drcr(total)}</div><div className="muted small">{chosen.map((l) => l.name).join(" · ")}</div><div className="muted small">Their past entries move with them – reports for earlier months show the new grouping too.</div></div>}
  </Modal>;
}

function NewLedger({ byId, paths, groupId, onClose, onDone }: { byId: Record<number, GNode>; paths: Record<number, string>; groupId: number | null; onClose: () => void; onDone: () => void }) {
  const [f, setF] = useState<any>({ name: "", group_id: groupId, opening_balance: "", opening_type: "Dr" });
  return <Modal title="New ledger" onClose={onClose} footer={<Btn kind="primary" disabled={!f.name.trim() || !f.group_id} onClick={async () => { if (await run(() => api.post("/api/r/ledgers", { ...f, opening_balance: f.opening_balance || 0 }), "Ledger created")) onDone(); }}>Create ledger</Btn>}>
    <Field label="Ledger name" required><input autoFocus value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} placeholder="e.g. Prem Salary" /></Field>
    <Field label="Group" required><select value={f.group_id || ""} onChange={(e) => setF({ ...f, group_id: Number(e.target.value) || null })}><option value="">— choose —</option>{Object.values(byId).filter((g) => !g.fixed).sort((a, b) => paths[a.id].localeCompare(paths[b.id])).map((g) => <option key={g.id} value={g.id}>{paths[g.id]}</option>)}</select></Field>
    <div className="form-grid"><Field label="Opening balance ₹"><input type="number" value={f.opening_balance} onChange={(e) => setF({ ...f, opening_balance: e.target.value })} /></Field>
      <Field label="Dr / Cr"><select value={f.opening_type} onChange={(e) => setF({ ...f, opening_type: e.target.value })}><option>Dr</option><option>Cr</option></select></Field></div>
    <p className="muted small">Customers, vendors, banks and drivers get their ledgers automatically when you add them.</p>
  </Modal>;
}

/** Payroll setting card: salary to each person's own ledger (approved design, screen 4). */
export function SalaryPosting({ value, onChange }: { value: any; onChange: (v: any) => void }) {
  const groups = useLoad<any[]>("/api/account-groups");
  const mode = value.salary_posting || "per_person";
  const opts = (groups.data || []).filter((g) => !g.fixed && ["Expense"].includes(g.nature));
  return <Card title="Salary posting">
    <label className={`radio-card ${mode === "per_person" ? "on" : ""}`}><input type="radio" checked={mode === "per_person"} onChange={() => onChange({ ...value, salary_posting: "per_person" })} />
      <span><b>One ledger per employee</b> <span className="badge info">recommended</span><br /><small className="muted">"Prem Salary", "Meena Salary"… are created automatically under the groups below, so you see each person's salary cost for the year.</small></span></label>
    <label className={`radio-card ${mode === "single" ? "on" : ""}`}><input type="radio" checked={mode === "single"} onChange={() => onChange({ ...value, salary_posting: "single" })} />
      <span><b>One ledger for everyone</b><br /><small className="muted">All salaries go to "Salaries &amp; Wages".</small></span></label>
    {mode === "per_person" && <div className="form-grid" style={{ marginTop: 10 }}>
      <Field label="Office staff salaries go to group" help="Created under Indirect Expenses if it doesn't exist."><input list="exp-groups" value={value.staff_salary_group || ""} onChange={(e) => onChange({ ...value, staff_salary_group: e.target.value })} /></Field>
      <Field label="Driver salaries go to group" help="Created under Direct Expenses if it doesn't exist."><input list="exp-groups" value={value.driver_salary_group || ""} onChange={(e) => onChange({ ...value, driver_salary_group: e.target.value })} /></Field>
      <Field label="Ledger name format"><select value={value.salary_ledger_format || "{name} Salary"} onChange={(e) => onChange({ ...value, salary_ledger_format: e.target.value })}><option value="{name} Salary">{"{name} Salary – e.g. Prem Salary"}</option><option value="Salary – {name} ({code})">{"Salary – {name} ({code})"}</option></select></Field>
      <Field label="Existing employees & drivers"><Btn onClick={async () => { const r: any = await run(() => api.post("/api/payroll/salary-ledgers")); if (r) toast.ok(`${r.created} salary ledger(s) created (${r.total} in all)`); }}>Create their ledgers now</Btn></Field>
      <datalist id="exp-groups">{opts.map((g) => <option key={g.id} value={g.name}>{g.path}</option>)}</datalist>
    </div>}
    <p className="muted small" style={{ marginTop: 8 }}>Payslips, statutory deductions and Salary Payable work as before – only the expense side is split by person. Remember to Save.</p>
  </Card>;
}
