import React, { useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { api, can, qs } from "../lib/api";
import { dt, fyStart, inr, today } from "../lib/format";
import ResourcePage, { ListSummary } from "../components/ResourcePage";
import { Bars, change, Donut, short, StatCard } from "../components/charts";
import { Badge, Btn, Card, Field, Kpi, Modal, Page, Pager, ReasonModal, RefSelect, Search, Table, Tabs, download, run, toast, useLoad } from "../components/ui";

export function Vouchers() {
  const [q, setQ] = useState("");
  const [type, setType] = useState("");
  const [offset, setOffset] = useState(0);
  const [view, setView] = useState<number | null>(null);
  const [sp, setSp] = useSearchParams();
  const [creating, setCreating] = useState<string | false>(sp.get("new") || false);
  const list = useLoad<any>(`/api/vouchers${qs({ q, type, offset, limit: 50 })}`);
  return <Page title="Vouchers" actions={can("accounts:write") && <Btn kind="primary" onClick={() => setCreating("Journal")}>+ Voucher</Btn>}>
    <ListSummary name="vouchers" icon="book" />
    <div className="toolbar"><Search value={q} onChange={setQ} placeholder="Voucher no / narration / reference" />
      <select value={type} onChange={(e) => setType(e.target.value)}><option value="">All types</option>{["Journal", "Payment", "Receipt", "Contra", "Purchase", "Sales", "Debit Note", "Credit Note"].map((t) => <option key={t}>{t}</option>)}</select></div>
    <Table cols={[{ key: "voucher_date", label: "Date", type: "date" }, { key: "voucher_no", label: "No" }, { key: "voucher_type", label: "Type" }, { key: "narration", label: "Narration" }, { key: "reference", label: "Ref" }, { key: "total", label: "Amount", type: "money" }, { key: "status", label: "Status", type: "badge" }]} rows={list.data?.items || []} onRow={(r) => setView(r.id)} />
    <Pager total={list.data?.total || 0} limit={50} offset={offset} onChange={setOffset} />
    {view && <VoucherView id={view} onClose={() => { setView(null); list.reload(); }} />}
    {creating && <VoucherForm initialType={creating} onClose={() => { setCreating(false); setSp({}); }} onDone={() => { setCreating(false); setSp({}); list.reload(); }} />}
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

function VoucherForm({ onClose, onDone, initialType = "Journal" }: { onClose: () => void; onDone: () => void; initialType?: string }) {
  const ledgers = useLoad<any[]>("/api/ledgers/balances");
  const [f, setF] = useState<any>({ voucher_type: ["Journal", "Payment", "Receipt", "Contra"].includes(initialType) ? initialType : "Journal", voucher_date: today(), narration: "", reference: "", lines: [{ ledger_id: "", debit: "", credit: "" }, { ledger_id: "", debit: "", credit: "" }] });
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


const AGE_COLORS = ["var(--c6)", "var(--c3)", "var(--c4)", "var(--c1)", "var(--bad)"];

export function AccountsHome() {
  const nav = useNavigate();
  const { data: d } = useLoad<any>("/api/accounts/summary");
  const tiles: [string, string, string][] = [
    ["Trial balance", "trial_balance", "All ledger balances, debit = credit"], ["Profit & loss", "profit_loss", "Income, expenses, gross & net profit"], ["Balance sheet", "balance_sheet", "Assets, liabilities & capital"],
    ["Cash flow", "cash_flow", "Operating / investing / financing"], ["Day book", "day_book", "Every voucher by date"], ["Cash book", "cash_book", "Cash in hand"], ["Bank book", "bank_book", "All bank accounts"],
    ["General ledger", "ledger", "Any ledger statement"], ["Customer outstanding", "customer_outstanding", "Ageing 0-30/31-60/61-90/90+"], ["Supplier outstanding", "supplier_outstanding", "What you owe vendors"],
    ["Sales register", "sales_register", "Invoices & notes with GST"], ["Purchase register", "purchase_register", "Vendor bills with GST"], ["GST summary", "gst_summary", "For GSTR-1 / GSTR-3B preparation"],
  ];
  return <Page title="Accounts" actions={can("accounts:write") && <div className="row gap wrap">
    <Btn kind="primary" onClick={() => nav("/receipts")}>+ Receipt from customer</Btn>
    <Btn onClick={() => nav("/vendor-payments")}>+ Payment to vendor</Btn>
    <Btn onClick={() => nav("/vouchers?new=Payment")}>+ Expense payment</Btn>
    <Btn onClick={() => nav("/vouchers?new=Journal")}>+ Journal</Btn>
    <Btn onClick={() => nav("/vouchers?new=Contra")}>+ Contra (cash ↔ bank)</Btn></div>}>
    {!d && <div className="kpis four">{[0, 1, 2, 3].map((i) => <div key={i} className="skeleton" style={{ height: 118 }} />)}</div>}
    {d && <>
      <div className="kpis four">
        <StatCard icon="file" label="Bills raised (sales)" value={short(d.compare.billing.this)} delta={change(d.compare.billing.this, d.compare.billing.last)} deltaText="vs last month" foot={!Number(d.compare.billing.last) ? "this month" : null} onClick={() => nav("/invoices")} />
        <StatCard icon="cart" label="Bills received (purchase)" value={short(d.compare.purchases.this)} tone="warn" delta={change(d.compare.purchases.this, d.compare.purchases.last)} goodWhen="down" deltaText="vs last month" foot={!Number(d.compare.purchases.last) ? "this month" : null} onClick={() => nav("/purchase")} />
        <StatCard icon="rupee" label="Payments received" value={short(d.compare.receipts.this)} tone="good" delta={change(d.compare.receipts.this, d.compare.receipts.last)} deltaText="vs last month" foot={!Number(d.compare.receipts.last) ? "this month" : null} onClick={() => nav("/receipts")} />
        <StatCard icon="bank" label="Payments made" value={short(d.compare.payments.this)} tone="info" delta={change(d.compare.payments.this, d.compare.payments.last)} goodWhen="down" deltaText="vs last month" foot={!Number(d.compare.payments.last) ? "this month" : null} onClick={() => nav("/vendor-payments")} />
      </div>
      <div className="grid2">
        <Card title="Accounts receivable ageing" actions={<a className="small" onClick={() => nav("/reports?r=customer_outstanding")}>Details</a>}>
          <Donut center={short(d.receivables)} centerSub="receivable" fmt={(v) => inr(v)} data={d.ar_ageing.map((b: any, i: number) => ({ label: b.bucket === "Not due" ? "Not due" : `${b.bucket} days`, value: Number(b.amount), color: AGE_COLORS[i] }))} onSlice={() => nav("/reports?r=customer_bills")} />
        </Card>
        <Card title="Accounts payable ageing" actions={<a className="small" onClick={() => nav("/reports?r=supplier_outstanding")}>Details</a>}>
          <Donut center={short(d.payables)} centerSub="payable" fmt={(v) => inr(v)} data={d.ap_ageing.map((b: any, i: number) => ({ label: b.bucket === "Not due" ? "Not due" : `${b.bucket} days`, value: Number(b.amount), color: AGE_COLORS[i] }))} onSlice={() => nav("/reports?r=supplier_bills")} />
        </Card>
      </div>
      <div className="grid2">
        <Card title="Profit and loss" actions={<span className="muted small">financial year from {dt(d.fy.start)}</span>}>
          <Bars legend={false} labels={["Income", "Expenses", "Net profit / loss"]} series={[{ name: "This year", values: [Number(d.fy.income), -Number(d.fy.expenses), Number(d.fy.net_profit)], colors: ["var(--c4)", "var(--c1)", Number(d.fy.net_profit) >= 0 ? "var(--c3)" : "var(--bad)"] }]} />
          <div className="legend"><span><i className="sw" style={{ background: "var(--c4)" }} />Income {inr(d.fy.income)}</span><span><i className="sw" style={{ background: "var(--c1)" }} />Expenses {inr(d.fy.expenses)}</span><span className={Number(d.fy.net_profit) >= 0 ? "good" : "bad"}>Net {inr(d.fy.net_profit)}</span></div>
        </Card>
        <Card title="Month by month" actions={<span className="muted small">this financial year</span>}>
          <Bars labels={d.fy.trend.map((m: any) => m.month)} series={[{ name: "Income", values: d.fy.trend.map((m: any) => Number(m.income)) }, { name: "Expenses", values: d.fy.trend.map((m: any) => Number(m.expenses)), color: "var(--c4)" }, { name: "Net", values: d.fy.trend.map((m: any) => Number(m.net)), color: "var(--c3)" }]} />
        </Card>
      </div>
      <div className="kpis">
        <Kpi label="Cash in hand" value={inr(d.cash_total)} onClick={() => nav("/reports?r=cash_book")} />
        <Kpi label="Bank balance" value={inr(d.bank_total)} sub={`${d.banks.length} account(s)`} onClick={() => nav("/bank")} />
        <Kpi label="Receivables" value={inr(d.receivables)} sub={`${d.overdue_invoices} invoice(s) overdue`} tone={d.overdue_invoices ? "warn" : undefined} onClick={() => nav("/reports?r=customer_outstanding")} />
        <Kpi label="Payables" value={inr(d.payables)} onClick={() => nav("/reports?r=supplier_outstanding")} />
        <Kpi label="Net profit this month" value={inr(d.month.net_profit)} tone={Number(d.month.net_profit) >= 0 ? "good" : "bad"} sub={`Income ${short(d.month.income)} · Expenses ${short(d.month.expenses)}`} />
        <Kpi label="GST payable (output − input)" value={inr(d.taxes.gst_net_payable)} sub={Number(d.taxes.rcm) ? `RCM ${inr(d.taxes.rcm)}` : ""} onClick={() => nav("/reports?r=gst_summary")} />
        <Kpi label="TDS payable" value={inr(d.taxes.tds_payable)} />
        <Kpi label="EPF / ESI / PT payable" value={inr(d.taxes.pf_esi_pt)} />
        <Kpi label="Books" value={d.books_balanced ? "Balanced" : "Check opening balances"} tone={d.books_balanced ? "good" : "bad"} onClick={() => nav("/reports?r=trial_balance")} />
      </div>
      <div className="grid2">
        <Card title="Financial statements & books"><div className="tiles">{tiles.map(([t, k, s]) => <a key={k} className="tile" onClick={() => nav(`/reports?r=${k}`)}><b>{t}</b><small>{s}</small></a>)}</div></Card>
        <Card title="Recent vouchers" actions={<Btn small onClick={() => nav("/vouchers")}>All vouchers</Btn>}>
          <Table dense cols={[{ key: "date", label: "Date", type: "date" }, { key: "no", label: "No" }, { key: "type", label: "Type" }, { key: "narration", label: "Narration" }, { key: "total", label: "Amount", type: "money" }, { key: "status", label: "", type: "badge" }]} rows={d.recent} onRow={() => nav("/vouchers")} />
        </Card>
      </div>
      <Card title="Cash & bank"><Table dense cols={[{ key: "name", label: "Account" }, { key: "balance", label: "Balance", type: "money" }]} rows={[...d.cash, ...d.banks]} /></Card>
      <Card title="Setting up / moving from another system">
        <div className="row gap wrap">
          <Btn onClick={() => nav("/import?target=opening_balances")}>Import opening balances from Excel</Btn>
          <Btn onClick={() => nav("/import?target=ledgers")}>Import ledgers from Excel</Btn>
          <Btn onClick={() => nav("/import?target=vouchers")}>Import vouchers from Excel</Btn>
          <Btn onClick={() => nav("/tally")}>Tally export / import</Btn>
          <Btn onClick={() => nav("/ledgers")}>Ledgers & groups</Btn>
        </div>
      </Card>
    </>}
  </Page>;
}

export function VendorPayments() {
  const [f, setF] = useState<any>({ date: today(), mode: "Bank" });
  const bills = useLoad<any[]>(f.vendor_id ? `/api/vendor-bills?vendor_id=${f.vendor_id}&status=Unpaid,Partly%20Paid` : null);
  const banks = useLoad<any[]>("/api/ledgers/balances");
  const [manual, setManual] = useState(false);
  const [alloc, setAlloc] = useState<Record<number, string>>({});
  const total = Object.values(alloc).reduce((a, v) => a + Number(v || 0), 0);
  return <Page title="Payments to vendors">
    <Card title="Vendor payment">
      <div className="form-grid">
        <Field label="Vendor"><RefSelect refName="vendors" value={f.vendor_id} onChange={(v) => { setF({ ...f, vendor_id: v }); setAlloc({}); }} /></Field>
        <Field label="Date"><input type="date" value={f.date} onChange={(e) => setF({ ...f, date: e.target.value })} /></Field>
        <Field label="Paid by"><select value={f.mode} onChange={(e) => setF({ ...f, mode: e.target.value })}><option>Bank</option><option>Cash</option></select></Field>
        {f.mode === "Bank" && <Field label="Bank account"><select value={f.bank_ledger_id || ""} onChange={(e) => setF({ ...f, bank_ledger_id: Number(e.target.value) })}><option value="">—</option>{(banks.data || []).filter((l) => l.group === "Bank Accounts").map((l) => <option key={l.id} value={l.id}>{l.name}</option>)}</select></Field>}
        <Field label="Amount ₹"><input type="number" value={manual ? total || "" : f.amount || ""} disabled={manual} onChange={(e) => setF({ ...f, amount: e.target.value })} /></Field>
        <Field label="Cheque / UTR"><input value={f.instrument_no || ""} onChange={(e) => setF({ ...f, instrument_no: e.target.value })} /></Field>
        <Field label="Narration" wide><input value={f.narration || ""} onChange={(e) => setF({ ...f, narration: e.target.value })} /></Field>
      </div>
      <label className="row gap small"><input type="checkbox" checked={manual} onChange={(e) => setManual(e.target.checked)} /> Pay specific bills (otherwise oldest bills first)</label>
      {f.vendor_id && <Table dense cols={[{ key: "entry_no", label: "Entry" }, { key: "bill_no", label: "Bill" }, { key: "bill_date", label: "Date", type: "date" }, { key: "due_date", label: "Due", type: "date" }, { key: "total", label: "Total", type: "money" }, { key: "balance", label: "Balance", type: "money" },
        ...(manual ? [{ key: "pay", label: "Pay ₹", render: (b: any) => <input type="number" style={{ width: 120 }} value={alloc[b.id] || ""} onChange={(e) => setAlloc({ ...alloc, [b.id]: e.target.value })} /> }] : [])]} rows={bills.data || []} empty="No unpaid bills" />}
      {can("accounts:write") && <Btn kind="primary" onClick={async () => {
        const body: any = { ...f };
        if (manual) { body.amount = total; body.allocations = Object.entries(alloc).filter(([, v]) => Number(v) > 0).map(([id, v]) => ({ vendor_bill_id: Number(id), amount: v })); }
        if (await run(() => api.post("/api/vendor-payments", body), "Payment posted")) { setAlloc({}); setF({ date: today(), mode: f.mode, vendor_id: f.vendor_id, bank_ledger_id: f.bank_ledger_id }); bills.reload(); }
      }}>Post payment</Btn>}
    </Card>
  </Page>;
}
