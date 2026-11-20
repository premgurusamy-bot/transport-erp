import React, { useState } from "react";
import { api, can, qs } from "../lib/api";
import { dt, fyStart, inr, today } from "../lib/format";
import ResourcePage from "../components/ResourcePage";
import { Badge, Btn, Card, Field, Kpi, Modal, Page, Pager, ReasonModal, Search, Table, Tabs, download, run, toast, useLoad } from "../components/ui";

export function Vouchers() {
  const [q, setQ] = useState("");
  const [type, setType] = useState("");
  const [offset, setOffset] = useState(0);
  const [view, setView] = useState<number | null>(null);
  const [creating, setCreating] = useState(false);
  const list = useLoad<any>(`/api/vouchers${qs({ q, type, offset, limit: 50 })}`);
  return <Page title="Vouchers" actions={can("accounts:write") && <Btn kind="primary" onClick={() => setCreating(true)}>+ Voucher</Btn>}>
    <div className="toolbar"><Search value={q} onChange={setQ} placeholder="Voucher no / narration / reference" />
      <select value={type} onChange={(e) => setType(e.target.value)}><option value="">All types</option>{["Journal", "Payment", "Receipt", "Contra", "Purchase", "Sales", "Debit Note", "Credit Note"].map((t) => <option key={t}>{t}</option>)}</select></div>
    <Table cols={[{ key: "voucher_date", label: "Date", type: "date" }, { key: "voucher_no", label: "No" }, { key: "voucher_type", label: "Type" }, { key: "narration", label: "Narration" }, { key: "reference", label: "Ref" }, { key: "total", label: "Amount", type: "money" }, { key: "status", label: "Status", type: "badge" }]} rows={list.data?.items || []} onRow={(r) => setView(r.id)} />
    <Pager total={list.data?.total || 0} limit={50} offset={offset} onChange={setOffset} />
    {view && <VoucherView id={view} onClose={() => { setView(null); list.reload(); }} />}
    {creating && <VoucherForm onClose={() => setCreating(false)} onDone={() => { setCreating(false); list.reload(); }} />}
  </Page>;
}

function VoucherView({ id, onClose }: { id: number; onClose: () => void }) {
  const { data: v, reload } = useLoad<any>(`/api/vouchers/${id}`);
  const [cancel, setCancel] = useState(false);
  if (!v) return null;
  return <Modal wide title={`${v.voucher_type} ${v.voucher_no}`} onClose={onClose} footer={<>{v.status === "Posted" && can("accounts:cancel") && <Btn kind="danger" onClick={() => setCancel(true)}>Cancel (reverse)</Btn>}<Btn onClick={onClose}>Close</Btn></>}>
    <div className="kv">{[["Date", dt(v.voucher_date)], ["Status", <Badge v={v.status} />], ["Narration", v.narration], ["Reference", v.reference], ["Source", v.source_type], ["Cancel reason", v.cancel_reason]].filter(([, x]) => x).map(([k, x]) => <div key={k as string}><span>{k}</span><b>{x}</b></div>)}</div>
    <Table dense cols={[{ key: "ledger", label: "Ledger" }, { key: "debit", label: "Debit", type: "money" }, { key: "credit", label: "Credit", type: "money" }, { key: "narration", label: "Note" }, { key: "reconciled_on", label: "Bank reco", type: "date" }]} rows={v.entries} />
    {cancel && <ReasonModal title="Reverse voucher" onClose={() => setCancel(false)} onSubmit={async (reason) => { const r = await run(() => api.post(`/api/vouchers/${id}/cancel`, { reason }), "Reversal posted"); reload(); return r; }} />}
  </Modal>;
}

function VoucherForm({ onClose, onDone }: { onClose: () => void; onDone: () => void }) {
  const ledgers = useLoad<any[]>("/api/ledgers/balances");
  const [f, setF] = useState<any>({ voucher_type: "Journal", voucher_date: today(), narration: "", reference: "", lines: [{ ledger_id: "", debit: "", credit: "" }, { ledger_id: "", debit: "", credit: "" }] });
  const dr = f.lines.reduce((a: number, l: any) => a + Number(l.debit || 0), 0), cr = f.lines.reduce((a: number, l: any) => a + Number(l.credit || 0), 0);
  const line = (i: number, k: string, v: any) => setF({ ...f, lines: f.lines.map((x: any, j: number) => (j === i ? { ...x, [k]: v } : x)) });
  return <Modal wide title="New voucher" onClose={onClose} footer={<><span className={dr === cr && dr > 0 ? "good" : "bad"}>Dr {inr(dr)} · Cr {inr(cr)}</span><Btn kind="primary" disabled={dr !== cr || dr === 0} onClick={async () => { if (await run(() => api.post("/api/vouchers", f), "Voucher posted")) onDone(); }}>Post</Btn></>}>
    <div className="form-grid">
      <Field label="Type"><select value={f.voucher_type} onChange={(e) => setF({ ...f, voucher_type: e.target.value })}>{["Journal", "Payment", "Receipt", "Contra"].map((t) => <option key={t}>{t}</option>)}</select></Field>
      <Field label="Date"><input type="date" value={f.voucher_date} onChange={(e) => setF({ ...f, voucher_date: e.target.value })} /></Field>
      <Field label="Reference"><input value={f.reference} onChange={(e) => setF({ ...f, reference: e.target.value })} /></Field>
      <Field label="Narration" wide><input value={f.narration} onChange={(e) => setF({ ...f, narration: e.target.value })} /></Field>
    </div>
    {f.lines.map((l: any, i: number) => <div key={i} className="row gap">
      <select className="grow" value={l.ledger_id} onChange={(e) => line(i, "ledger_id", e.target.value)}><option value="">— ledger —</option>{(ledgers.data || []).filter((x) => x.is_active).map((x) => <option key={x.id} value={x.id}>{x.name} ({x.group})</option>)}</select>
      <input type="number" placeholder="Debit" style={{ width: 130 }} value={l.debit} onChange={(e) => line(i, "debit", e.target.value)} />
      <input type="number" placeholder="Credit" style={{ width: 130 }} value={l.credit} onChange={(e) => line(i, "credit", e.target.value)} />
      <button className="x" onClick={() => setF({ ...f, lines: f.lines.filter((_: any, j: number) => j !== i) })}>×</button></div>)}
    <Btn small onClick={() => setF({ ...f, lines: [...f.lines, { ledger_id: "", debit: "", credit: "" }] })}>+ Line</Btn>
  </Modal>;
}

export function Ledgers() {
  const [tab, setTab] = useState("Balances");
  const bal = useLoad<any[]>(tab === "Balances" ? "/api/ledgers/balances" : null);
  const [q, setQ] = useState("");
  const [stmt, setStmt] = useState<any>(null);
  return <Page title="Ledgers">
    <Tabs tabs={["Balances", "Manage ledgers"]} value={tab} onChange={setTab} />
    {tab === "Balances" ? <>
      <div className="toolbar"><Search value={q} onChange={setQ} /></div>
      <Table dense cols={[{ key: "group", label: "Group" }, { key: "name", label: "Ledger" }, { key: "nature", label: "Nature" }, { key: "balance", label: "Balance (Dr +)", type: "money" }]} rows={(bal.data || []).filter((l) => !q || l.name.toLowerCase().includes(q.toLowerCase()))} onRow={(l) => setStmt(l)} />
    </> : <ResourcePage embedded name="ledgers" columns={["name", "code", "group_id", "party_type", "opening_balance", "opening_type", "gstin"]} />}
    {stmt && <LedgerStatement ledger={stmt} onClose={() => setStmt(null)} />}
  </Page>;
}

function LedgerStatement({ ledger, onClose }: { ledger: any; onClose: () => void }) {
  const [p, setP] = useState({ start: fyStart(), end: today() });
  const { data } = useLoad<any>(`/api/reports/ledger${qs({ ...p, ledger_id: ledger.id })}`);
  return <Modal wide title={`Ledger – ${ledger.name}`} onClose={onClose} footer={<><Btn onClick={() => download(`/api/reports/ledger${qs({ ...p, ledger_id: ledger.id, format: "pdf" })}`)}>PDF</Btn><Btn onClick={() => download(`/api/reports/ledger${qs({ ...p, ledger_id: ledger.id, format: "xlsx" })}`)}>Excel</Btn></>}>
    <div className="row gap"><Field label="From"><input type="date" value={p.start} onChange={(e) => setP({ ...p, start: e.target.value })} /></Field><Field label="To"><input type="date" value={p.end} onChange={(e) => setP({ ...p, end: e.target.value })} /></Field></div>
    {data && <Table dense cols={data.columns} rows={data.rows} totals={data.totals} />}
  </Modal>;
}

export function BankReco() {
  const banks = useLoad<any[]>("/api/ledgers/balances");
  const bankList = (banks.data || []).filter((l) => l.group === "Bank Accounts");
  const [lid, setLid] = useState<number | null>(null);
  const [on, setOn] = useState(today());
  const reco = useLoad<any>(lid ? `/api/bank/${lid}/reconciliation?on=${on}` : null);
  const [pick, setPick] = useState<any>(null);
  const upload = async (file: File) => {
    const fd = new FormData(); fd.append("file", file);
    const r: any = await run(() => api.form(`/api/bank/${lid}/statement`, fd));
    if (r) { toast.ok(`${r.added} lines imported, ${r.auto_matched} matched automatically`); r.errors?.slice(0, 3).forEach((e: string) => toast.err(e)); reco.reload(); }
  };
  const d = reco.data;
  return <Page title="Bank reconciliation">
    <div className="toolbar">
      <select value={lid || ""} onChange={(e) => setLid(Number(e.target.value))}><option value="">— bank account —</option>{bankList.map((b) => <option key={b.id} value={b.id}>{b.name}</option>)}</select>
      <input type="date" value={on} onChange={(e) => setOn(e.target.value)} />
      {lid && can("accounts:write") && <label className="btn">Import bank statement (CSV/Excel)<input hidden type="file" accept=".csv,.xlsx" onChange={(e) => e.target.files?.[0] && upload(e.target.files[0])} /></label>}
    </div>
    {!bankList.length && <div className="warn-box">Add a bank account in Company → Bank accounts first.</div>}
    {d && <>
      <div className="kpis small"><Kpi label="Balance as per books" value={inr(d.book_balance)} /><Kpi label="Deposits not yet credited" value={inr(d.deposits_not_credited)} /><Kpi label="Cheques / payments not presented" value={inr(d.cheques_not_presented)} /><Kpi label="Balance as per bank" value={inr(d.balance_as_per_bank)} /></div>
      <div className="grid2">
        <Card title="Unreconciled book entries"><Table dense cols={[{ key: "date", label: "Date", type: "date" }, { key: "voucher_no", label: "Voucher" }, { key: "narration", label: "Narration" }, { key: "debit", label: "Deposit", type: "money" }, { key: "credit", label: "Withdrawal", type: "money" },
          { key: "x", label: "", render: (e) => can("accounts:write") && <Btn small onClick={() => setPick({ entry: e, date: today() })}>Reconcile</Btn> }]} rows={d.unreconciled_entries} /></Card>
        <Card title="Unmatched statement lines"><Table dense cols={[{ key: "date", label: "Date", type: "date" }, { key: "description", label: "Description" }, { key: "reference", label: "Ref" }, { key: "deposit", label: "Deposit", type: "money" }, { key: "withdrawal", label: "Withdrawal", type: "money" }]} rows={d.unmatched_statement_lines} /></Card>
      </div>
    </>}
    {pick && <Modal title={`Reconcile ${pick.entry.voucher_no}`} onClose={() => setPick(null)} footer={<Btn kind="primary" onClick={async () => { if (await run(() => api.post("/api/bank/reconcile", { entry_id: pick.entry.entry_id, date: pick.date, statement_line_id: pick.line }), "Reconciled")) { setPick(null); reco.reload(); } }}>Save</Btn>}>
      <Field label="Cleared in bank on"><input type="date" value={pick.date} onChange={(e) => setPick({ ...pick, date: e.target.value })} /></Field>
      <Field label="Match statement line (optional)"><select value={pick.line || ""} onChange={(e) => setPick({ ...pick, line: e.target.value ? Number(e.target.value) : null })}><option value="">—</option>{d.unmatched_statement_lines.map((l: any) => <option key={l.id} value={l.id}>{dt(l.date)} {l.description} {inr(l.deposit || l.withdrawal)}</option>)}</select></Field>
    </Modal>}
  </Page>;
}

export function Tally() {
  const [p, setP] = useState({ start: fyStart(), end: today() });
  const [res, setRes] = useState<any>(null);
  const [file, setFile] = useState<File | null>(null);
  const imp = async (dry: boolean) => {
    if (!file) return;
    const fd = new FormData(); fd.append("file", file);
    const r = await run(() => api.form(`/api/tally/import?dry_run=${dry}`, fd), dry ? undefined : "Imported");
    if (r) setRes(r);
  };
  return <Page title="Tally export / import">
    <div className="grid2">
      <Card title="Export to Tally (Excel / CSV)">
        <div className="row gap"><Field label="From"><input type="date" value={p.start} onChange={(e) => setP({ ...p, start: e.target.value })} /></Field><Field label="To"><input type="date" value={p.end} onChange={(e) => setP({ ...p, end: e.target.value })} /></Field></div>
        <div className="row gap wrap">
          <Btn onClick={() => download(`/api/tally/vouchers${qs(p)}`)}>Vouchers (.xlsx)</Btn><Btn onClick={() => download(`/api/tally/vouchers${qs({ ...p, fmt: "csv" })}`)}>Vouchers (.csv)</Btn>
          <Btn onClick={() => download("/api/tally/ledgers")}>Ledger masters (.xlsx)</Btn>
        </div>
        <p className="muted small">Layout: Date, Voucher Type, Voucher Number, Ledger Name, Dr/Cr, Amount, Narration, Reference, Cost Centre (vehicle). Map these columns in your Tally Excel-import tool (TDL/utility). Ledger names must exist in Tally.</p>
      </Card>
      {can("accounts:write") && <Card title="Import journal vouchers">
        <input type="file" accept=".csv,.xlsx" onChange={(e) => setFile(e.target.files?.[0] || null)} />
        <div className="row gap"><Btn onClick={() => imp(true)}>Validate</Btn><Btn kind="primary" onClick={() => imp(false)}>Import</Btn></div>
        <p className="muted small">Same layout as the export. Every voucher must balance and every ledger must already exist. The whole file is rejected if any voucher has an error.</p>
        {res && <div><p>{res.valid} of {res.vouchers} vouchers valid{res.posted ? `, ${res.posted} posted` : ""}.</p>{res.errors.map((e: string) => <div key={e} className="error-box">{e}</div>)}</div>}
      </Card>}
    </div>
  </Page>;
}
