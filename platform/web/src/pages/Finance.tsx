import { useState } from "react";
import { Route, Routes } from "react-router-dom";
import { api, get, post } from "../api";
import { useAuth } from "../auth";
import { enumOpts, opts, useLookup } from "../components/Resource";
import { Badge, Btn, Card, d, ErrorBox, Form, inr, Modal, Table, toast, useData } from "../components/ui";
import { SubNav } from "./ErpApp";

const today = () => new Date().toISOString().slice(0, 10);
const fyStart = () => { const n = new Date(); const y = n.getMonth() >= 3 ? n.getFullYear() : n.getFullYear() - 1; return `${y}-04-01`; };

export default function Finance() {
  return (
    <div className="stack">
      <SubNav items={[{ to: "/erp/finance", label: "Invoices" }, { to: "/erp/finance/receipts", label: "Receipts" }, { to: "/erp/finance/expenses", label: "Expenses" },
        { to: "/erp/finance/settlements", label: "Settlements & payments" }, { to: "/erp/finance/bank", label: "Bank reconciliation" },
        { to: "/erp/finance/collections", label: "Collections" }, { to: "/erp/finance/reports", label: "Reports" }, { to: "/erp/finance/cash", label: "Cash flow & budget" },
        { to: "/erp/finance/tally", label: "Tally / migration" }]} />
      <Routes>
        <Route index element={<Invoices />} />
        <Route path="receipts" element={<Receipts />} />
        <Route path="expenses" element={<Expenses />} />
        <Route path="settlements" element={<Settlements />} />
        <Route path="bank" element={<Bank />} />
        <Route path="collections" element={<Collections />} />
        <Route path="reports" element={<Reports />} />
        <Route path="cash" element={<Cash />} />
        <Route path="tally" element={<Tally />} />
      </Routes>
    </div>
  );
}

function Invoices() {
  const { can } = useAuth();
  const inv = useData(() => get("/finance/invoices"), []);
  const unb = useData(() => (can("invoice.write") ? get("/finance/unbilled") : Promise.resolve([])), []);
  const [sel, setSel] = useState<string[]>([]);
  const [err, setErr] = useState<any>(null);
  const lk = useLookup();
  const custName = (id: string) => lk.data?.customers.find((c: any) => c.id === id)?.label || id;
  const [print, setPrint] = useState<any>(null);
  return (
    <div className="stack">
      {can("invoice.write") && <Card title="Ready to bill (POD verified)" note="Invoices generate only from verified milestones; the same booking cannot be billed twice.">
        <ErrorBox error={err} />
        <Table rows={unb.data} cols={[{ key: "s", label: "", render: (r: any) => <input type="checkbox" checked={sel.includes(r.booking_id)} onChange={() => setSel((s) => s.includes(r.booking_id) ? s.filter((x) => x !== r.booking_id) : [...s, r.booking_id])} /> },
          { key: "code", label: "Booking" }, { key: "customer_id", label: "Customer", render: (r: any) => custName(r.customer_id) }, { key: "freight", label: "Freight", money: true },
          { key: "gst_mode", label: "GST" }, { key: "pod_verified_at", label: "POD verified", date: true }]} empty="Nothing waiting to be billed" />
        <Btn disabled={!sel.length} onClick={async () => {
          setErr(null);
          const first = unb.data!.find((x: any) => x.booking_id === sel[0]);
          try { const i = await post("/finance/invoices", { customer_id: first.customer_id, booking_ids: sel }); toast(`Invoice ${i.number} issued`); setSel([]); unb.reload(); inv.reload(); } catch (e) { setErr(e); }
        }}>Generate invoice</Btn>
      </Card>}
      <Card title="Invoices">
        <Table rows={inv.data} cols={[{ key: "number", label: "Invoice" }, { key: "customer_name", label: "Customer" }, { key: "invoice_date", label: "Date", render: (r: any) => d(r.invoice_date) },
          { key: "due_date", label: "Due", render: (r: any) => d(r.due_date) }, { key: "taxable_value", label: "Taxable", money: true },
          { key: "gst", label: "GST", render: (r: any) => inr(Number(r.cgst) + Number(r.sgst) + Number(r.igst)) }, { key: "total", label: "Total", money: true },
          { key: "balance", label: "Balance", money: true }, { key: "gst_mode", label: "Mode" }, { key: "status", label: "Status", badge: true }, { key: "irn_status", label: "IRN", badge: true },
          { key: "p", label: "", render: (r: any) => <Btn kind="ghost" onClick={() => setPrint(r)}>Print</Btn> }]} />
      </Card>
      {print && <Modal title={`Invoice ${print.number}`} onClose={() => setPrint(null)}><PrintInvoice inv={print} /></Modal>}
    </div>
  );
}

export function PrintInvoice({ inv }: { inv: any }) {
  const co = useData(() => get("/public/company"), []);
  return (
    <div className="print-doc">
      <div className="row between"><div><h2>{co.data?.name || "G ROAD LINES"}</h2><div className="small">{co.data?.address}</div></div>
        <div><h3>TAX INVOICE</h3><div>{inv.number}</div><div className="small">Date {d(inv.invoice_date)} · Due {d(inv.due_date)}</div></div></div>
      <p><b>Bill to:</b> {inv.customer_name} · Place of supply {inv.place_of_supply || "—"}</p>
      <Table rows={inv.lines.filter((l: any) => l.active)} cols={[{ key: "lr_number", label: "LR" }, { key: "description", label: "Description" },
        { key: "is_pass_through", label: "Reimbursement", render: (l: any) => (l.is_pass_through ? "Yes" : "") }, { key: "amount", label: "Amount", money: true }]} />
      <dl className="dl"><dt>Taxable value</dt><dd>{inr(inv.taxable_value)}</dd><dt>CGST / SGST / IGST</dt><dd>{inr(inv.cgst)} / {inr(inv.sgst)} / {inr(inv.igst)}</dd>
        <dt>Reimbursements</dt><dd>{inr(inv.pass_through)}</dd><dt><b>Total</b></dt><dd><b>{inr(inv.total)}</b></dd></dl>
      <p className="small">{inv.tax_rule_snapshot?.note} {inv.irn ? `IRN: ${inv.irn} (${inv.irn_status})` : ""}</p>
      <Btn onClick={() => window.print()}>Print</Btn>
    </div>
  );
}

function Receipts() {
  const { can } = useAuth();
  const lk = useLookup();
  const { data, reload } = useData(() => get("/finance/receipts"), []);
  const banks = useData(() => get("/masters/company-bank-accounts"), []);
  const [adding, setAdding] = useState(false);
  return (
    <Card title="Customer receipts" note="Receipts stay UNCONFIRMED until matched to the bank statement (cash is confirmed on counting)."
          actions={can("accounts.post") && <Btn onClick={() => setAdding(true)}>+ Receipt</Btn>}>
      <Table rows={data} cols={[{ key: "number", label: "Receipt" }, { key: "receipt_date", label: "Date", render: (r: any) => d(r.receipt_date) }, { key: "amount", label: "Amount", money: true },
        { key: "tds_amount", label: "TDS", money: true }, { key: "mode", label: "Mode" }, { key: "reference", label: "Reference" }, { key: "unallocated", label: "Unallocated", money: true },
        { key: "status", label: "Status", badge: true }]} />
      {adding && <Modal title="Record receipt" onClose={() => setAdding(false)}>
        <Form fields={[{ name: "customer_id", label: "Customer", type: "select", options: opts(lk.data?.customers), required: true },
          { name: "amount", label: "Amount ₹", type: "number", required: true }, { name: "tds_amount", label: "TDS deducted ₹", type: "number" },
          { name: "mode", label: "Mode", type: "select", options: enumOpts("neft", "rtgs", "imps", "upi", "cheque", "cash"), required: true },
          { name: "reference", label: "UTR / cheque no." }, { name: "receipt_date", label: "Date", type: "date", required: true },
          { name: "company_bank_id", label: "Bank", type: "select", options: (banks.data || []).map((b: any) => ({ value: b.id, label: b.name })) },
          { name: "is_advance", label: "Advance against booking", type: "checkbox" }, { name: "remittance_note", label: "Remittance advice", type: "textarea" }]}
          initial={{ receipt_date: today(), mode: "neft" }} onSubmit={async (v) => { await post("/finance/receipts", v); toast("Recorded"); setAdding(false); reload(); }} />
      </Modal>}
    </Card>
  );
}

function Expenses() {
  const { can } = useAuth();
  const [status, setStatus] = useState("submitted");
  const { data, reload } = useData(() => get(`/finance/expenses?status=${status}`), [status]);
  const [adding, setAdding] = useState(false);
  const decide = async (r: any, approve: boolean) => {
    const note = approve ? (r.duplicate_of ? prompt("Possible duplicate - explain") : "") : prompt("Rejection reason");
    if (!approve && !note) return;
    try { await post(`/finance/expenses/${r.id}/decide`, { approve, note }); toast(approve ? "Approved & posted" : "Rejected"); reload(); } catch (e: any) { toast(e.message, "red"); }
  };
  return (
    <Card title="Expenses" note="OCR values are suggestions only. You cannot approve your own expense." actions={<>
      <select value={status} onChange={(e) => setStatus(e.target.value)}>{["submitted", "posted", "rejected"].map((s) => <option key={s}>{s}</option>)}</select>
      {can("accounts.post") && <Btn onClick={() => setAdding(true)}>+ Expense</Btn>}</>}>
      <Table rows={data} cols={[{ key: "code", label: "Ref" }, { key: "expense_date", label: "Date", render: (r: any) => d(r.expense_date) }, { key: "category", label: "Category" },
        { key: "amount", label: "Amount", money: true }, { key: "vendor_name", label: "Vendor" }, { key: "paid_by", label: "Paid by" }, { key: "source", label: "Source" },
        { key: "duplicate_of", label: "Dup?", render: (r: any) => (r.duplicate_of ? <Badge v="warning" /> : "") },
        { key: "ocr", label: "OCR", render: (r: any) => (r.ocr ? <span className="small">{r.ocr.label}: {r.ocr.amount}</span> : "") }, { key: "status", label: "Status", badge: true },
        { key: "a", label: "", render: (r: any) => can("accounts.approve") && r.status === "submitted" && <div className="row gap"><Btn onClick={() => decide(r, true)}>Approve</Btn><Btn kind="danger" onClick={() => decide(r, false)}>Reject</Btn></div> }]} />
      {adding && <Modal title="New expense" onClose={() => setAdding(false)}>
        <Form fields={[{ name: "category", label: "Category", type: "select", required: true, options: enumOpts("fuel", "toll", "repair", "hamali", "loading", "crane", "parking", "permit", "allowance", "insurance", "compliance", "godown", "overhead", "tyre", "marketing", "other") },
          { name: "expense_date", label: "Date", type: "date", required: true }, { name: "amount", label: "Amount ₹ (excl. GST)", type: "number", required: true },
          { name: "tax_amount", label: "GST ₹", type: "number" }, { name: "vendor_name", label: "Vendor" }, { name: "bill_number", label: "Bill no." },
          { name: "paid_by", label: "Paid by", type: "select", options: enumOpts("company", "driver_cash", "driver_advance", "vendor_credit") },
          { name: "payment_mode", label: "Mode", type: "select", options: enumOpts("cash", "upi", "neft", "card") }, { name: "rebillable", label: "Pass-through to customer", type: "checkbox" }]}
          initial={{ expense_date: today(), paid_by: "company" }} onSubmit={async (v) => { const r = await post("/finance/expenses", v); toast(r.possible_duplicate ? `Saved - possible duplicate of ${r.possible_duplicate}` : "Saved"); setAdding(false); reload(); }} />
      </Modal>}
    </Card>
  );
}

function Settlements() {
  const { can } = useAuth();
  const st = useData(() => get("/finance/settlements"), []);
  const pays = useData(() => get("/finance/payments"), []);
  const act = async (fn: () => Promise<any>, m: string) => { try { await fn(); toast(m); st.reload(); pays.reload(); } catch (e: any) { toast(e.message, "red"); } };
  const [mk, setMk] = useState<"" | "owner" | "driver">("");
  return (
    <div className="stack">
      <Card title="Settlements" note="Driver/owner/vendor settlements are rule-based, maker-checker approved, with no unapproved deductions."
            actions={can("settlement.prepare") && <><Btn kind="ghost" onClick={() => setMk("owner")}>+ Owner settlement</Btn><Btn kind="ghost" onClick={() => setMk("driver")}>+ Driver settlement</Btn></>}>
        {mk && <NewSettlement kind={mk} onClose={() => { setMk(""); st.reload(); }} />}
        <Table rows={st.data} cols={[{ key: "code", label: "Ref" }, { key: "party_type", label: "Party" }, { key: "gross", label: "Gross", money: true },
          { key: "advances", label: "Advances", money: true }, { key: "tds", label: "TDS", money: true }, { key: "net_payable", label: "Net", money: true },
          { key: "paid", label: "Paid", money: true }, { key: "status", label: "Status", badge: true },
          { key: "a", label: "", render: (r: any) => <div className="row gap">
            {can("settlement.prepare") && r.status === "draft" && <Btn kind="ghost" onClick={() => act(() => post(`/finance/settlements/${r.id}/submit`), "Submitted for approval")}>Submit</Btn>}
            {can("payment.prepare") && ["approved", "part_paid"].includes(r.status) && <Btn kind="ghost" onClick={() => act(() => post("/finance/payments", {
              payee_type: r.party_type, payee_id: r.party_id, amount: (Number(r.net_payable) - Number(r.paid)).toFixed(2), purpose: `Settlement ${r.code}`, settlement_id: r.id }), "Payment prepared - needs approval")}>Prepare payment</Btn>}
          </div> }]} />
      </Card>
      <Card title="Payments" note="Never autonomous. Prepared → approved by another user → executed (bank portal UTR or MOCK bank API).">
        <Table rows={pays.data} cols={[{ key: "code", label: "Ref" }, { key: "payee_name", label: "Payee" }, { key: "amount", label: "Amount", money: true }, { key: "purpose", label: "Purpose" },
          { key: "status", label: "Status", badge: true }, { key: "executed_via", label: "Via" }, { key: "bank_reference", label: "UTR" },
          { key: "x", label: "", render: (r: any) => can("payment.approve") && r.status === "approved" && <Btn onClick={() => {
            const utr = prompt("UTR from bank portal (leave blank to use MOCK bank API)");
            act(() => post(`/finance/payments/${r.id}/execute`, utr ? { via: "manual_bank_portal", bank_reference: utr } : { via: "bank_api" }), "Executed");
          }}>Execute</Btn> }]} />
      </Card>
    </div>
  );
}

function NewSettlement({ kind, onClose }: { kind: "owner" | "driver"; onClose: () => void }) {
  const lk = useLookup();
  const drivers = useData(() => (kind === "driver" ? get("/drivers") : Promise.resolve([])), [kind]);
  const trips = useData(() => (kind === "owner" ? get("/trips?status=closed") : Promise.resolve([])), [kind]);
  const [party, setParty] = useState("");
  const earnings = useData(() => (kind === "driver" && party ? get(`/drivers/${party}/remuneration`) : Promise.resolve(null)), [party]);
  const [sel, setSel] = useState<string[]>([]);
  const [err, setErr] = useState<any>(null);
  const rows = kind === "owner" ? (trips.data || []).filter((t: any) => t.owner_id === party) : (earnings.data?.earnings || []).filter((e: any) => e.status === "approved" && !e.settlement_id);
  return (
    <Modal title={`New ${kind} settlement`} onClose={onClose}>
      <ErrorBox error={err} />
      <select value={party} onChange={(e) => { setParty(e.target.value); setSel([]); }}>
        <option value="">Select {kind}…</option>
        {(kind === "owner" ? lk.data?.owners || [] : (drivers.data || []).map((d: any) => ({ id: d.id, label: `${d.code} ${d.name}` }))).map((o: any) => <option key={o.id} value={o.id}>{o.label}</option>)}
      </select>
      <Table rows={rows} cols={[{ key: "s", label: "", render: (r: any) => <input type="checkbox" checked={sel.includes(r.id)} onChange={() => setSel((x) => x.includes(r.id) ? x.filter((y) => y !== r.id) : [...x, r.id])} /> },
        ...(kind === "owner" ? [{ key: "code", label: "Trip" }, { key: "owner_hire_amount", label: "Hire", money: true }, { key: "owner_advance", label: "Advance", money: true }]
          : [{ key: "created_at", label: "Date", date: true }, { key: "gross", label: "Earning", money: true }])]} empty={party ? "Nothing ready to settle (trips must be closed / earnings approved)" : "Choose a party"} />
      <Btn disabled={!sel.length} onClick={async () => {
        try { await post(`/finance/settlements/${kind}`, kind === "owner" ? { owner_id: party, trip_ids: sel } : { driver_id: party, earning_ids: sel }); toast("Draft settlement created"); onClose(); } catch (e) { setErr(e); }
      }}>Create draft settlement</Btn>
    </Modal>
  );
}

function Bank() {
  const { can } = useAuth();
  const sum = useData(() => get("/finance/bank/summary"), []);
  const tx = useData(() => get("/finance/bank/transactions?status=unmatched,suggested"), []);
  const banks = useData(() => get("/masters/company-bank-accounts"), []);
  const [file, setFile] = useState<File | null>(null);
  const [bankId, setBankId] = useState("");
  const [err, setErr] = useState<any>(null);
  return (
    <div className="stack">
      <Card title="Daily bank dashboard" note="No live bank connection: statements are imported (CSV). Never store internet-banking passwords/OTPs.">
        <Table rows={sum.data} cols={[{ key: "bank", label: "Account" }, { key: "book_balance", label: "Book balance", money: true },
          { key: "statement_balance", label: "Statement balance", money: true }, { key: "statement_to", label: "Statement to" }, { key: "sync_status", label: "Sync" },
          { key: "unreconciled_count", label: "Unreconciled" }, { key: "oldest_unreconciled_days", label: "Oldest (days)" }]} />
        {can("bank.import") && <div className="row gap">
          <select value={bankId} onChange={(e) => setBankId(e.target.value)}><option value="">Bank account…</option>
            {(banks.data || []).filter((b: any) => !b.is_cash).map((b: any) => <option key={b.id} value={b.id}>{b.name}</option>)}</select>
          <input type="file" accept=".csv,text/csv" onChange={(e) => setFile(e.target.files?.[0] || null)} />
          <Btn disabled={!file || !bankId} onClick={async () => {
            const f = new FormData(); f.append("company_bank_id", bankId); f.append("file", file!); setErr(null);
            try { const r = await api("/finance/bank/import", { form: f }); toast(`Imported ${r.import.rows_new} new rows; auto-confirmed ${r.matching.auto_confirmed}`); sum.reload(); tx.reload(); } catch (e) { setErr(e); }
          }}>Import statement</Btn></div>}
        <ErrorBox error={err} />
      </Card>
      <Card title="Exception queue" note="Unidentified credits are NOT customer payments until Accounts confirms the match.">
        <Table rows={tx.data} cols={[{ key: "txn_date", label: "Date", render: (r: any) => d(r.txn_date) }, { key: "description", label: "Narration" }, { key: "reference", label: "Ref" },
          { key: "credit", label: "Credit", money: true }, { key: "debit", label: "Debit", money: true }, { key: "match_reason", label: "Suggestion" },
          { key: "match_confidence", label: "Conf." }, { key: "status", label: "Status", badge: true },
          { key: "a", label: "", render: (r: any) => can("bank.reconcile") && <div className="row gap">
            {r.status === "suggested" && <Btn kind="ghost" onClick={async () => { try { await post(`/finance/bank/transactions/${r.id}/confirm`, { entity: r.match_entity, ids: r.match_ids }); toast("Matched"); tx.reload(); sum.reload(); } catch (e: any) { toast(e.message, "red"); } }}>Confirm</Btn>}
            <Btn kind="ghost" onClick={async () => { const reason = prompt("Why ignore?"); if (reason) { await post(`/finance/bank/transactions/${r.id}/ignore`, { reason }); tx.reload(); } }}>Ignore</Btn></div> }]} empty="All reconciled" />
      </Card>
    </div>
  );
}

function Collections() {
  const { can } = useAuth();
  const { data, reload } = useData(() => get("/finance/collections"), []);
  const [note, setNote] = useState<any>(null);
  return (
    <Card title="Collections (priority order)" note="Reminders are polite approved templates. AI and staff cannot threaten, write off or change terms here."
          actions={can("collections.write") && <Btn kind="ghost" onClick={async () => { const r = await post("/finance/collections/reminders"); toast(`${r.sent} reminder(s) queued`); }}>Send due reminders</Btn>}>
      <Table rows={data} cols={[{ key: "customer", label: "Customer" }, { key: "outstanding", label: "Outstanding", money: true }, { key: "overdue", label: "Overdue", money: true },
        { key: "oldest_overdue_days", label: "Oldest (days)" }, { key: "disputed", label: "Disputed", money: true },
        { key: "recent_notes", label: "Last note", render: (r: any) => r.recent_notes[0]?.note || "—" },
        { key: "n", label: "", render: (r: any) => can("collections.write") && <Btn kind="ghost" onClick={() => setNote(r)}>Log</Btn> }]} />
      {note && <Modal title={`Follow-up: ${note.customer}`} onClose={() => setNote(null)}>
        <Form fields={[{ name: "kind", label: "Type", type: "select", options: enumOpts("call", "reminder", "promise", "dispute", "short_payment"), required: true },
          { name: "note", label: "Note", type: "textarea", required: true }, { name: "promise_date", label: "Promise date", type: "date" }, { name: "promise_amount", label: "Promise ₹", type: "number" }]}
          initial={{ kind: "call" }} onSubmit={async (v) => { await post("/finance/collections/notes", { customer_id: note.customer_id, ...v }); setNote(null); reload(); }} />
      </Modal>}
    </Card>
  );
}

function Reports() {
  const [frm, setFrm] = useState(fyStart());
  const [to, setTo] = useState(today());
  const [rep, setRep] = useState("trial-balance");
  const { data } = useData(() => get(rep === "trial-balance" ? `/finance/reports/trial-balance?as_of=${to}` : rep === "pnl" ? `/finance/reports/pnl?frm=${frm}&to=${to}`
    : rep === "bs" ? `/finance/reports/balance-sheet?as_of=${to}` : rep === "ageing" ? "/finance/reports/ageing" : rep === "gst" ? `/finance/reports/gst?frm=${frm}&to=${to}`
    : `/finance/reports/profitability?frm=${frm}&to=${to}`), [rep, frm, to]);
  const exportable = ["trial-balance", "pnl", "ageing", "gst"].includes(rep);
  const download = async (fmt: string) => {
    const blob = await api(`/finance/reports/export/${rep}?fmt=${fmt}&frm=${frm}&to=${to}`);
    const a = document.createElement("a"); a.href = URL.createObjectURL(blob as Blob); a.download = `GRL_${rep}.${fmt}`; a.click();
  };
  return (
    <Card title="Reports" actions={<>
      <select value={rep} onChange={(e) => setRep(e.target.value)}>
        <option value="trial-balance">Trial balance</option><option value="pnl">Profit & loss</option><option value="bs">Balance sheet</option>
        <option value="ageing">Receivables ageing</option><option value="gst">GST register</option><option value="profit">Profitability (service/vehicle/lane/customer)</option></select>
      <input type="date" value={frm} onChange={(e) => setFrm(e.target.value)} /><input type="date" value={to} onChange={(e) => setTo(e.target.value)} />
      {exportable && <>{["csv", "xlsx", "pdf"].map((f) => <Btn key={f} kind="ghost" onClick={() => download(f)}>{f.toUpperCase()}</Btn>)}</>}</>}>
      {data && <p className="small muted">{data.basis || data.note || ""}</p>}
      {rep === "trial-balance" && data && <><Table rows={data.rows} cols={[{ key: "code", label: "Code" }, { key: "name", label: "Ledger" }, { key: "debit", label: "Debit", money: true }, { key: "credit", label: "Credit", money: true }]} />
        <p>Totals {inr(data.total_debit)} / {inr(data.total_credit)} <Badge v={data.balanced ? "ok" : "failed"} /></p></>}
      {rep === "pnl" && data && <><Table rows={[...data.income.map((x: any) => ({ ...x, t: "Income" })), ...data.expenses.map((x: any) => ({ ...x, t: "Expense" }))]}
        cols={[{ key: "t", label: "Type" }, { key: "name", label: "Ledger" }, { key: "group", label: "Group" }, { key: "amount", label: "Amount", money: true }]} />
        <p>Gross contribution {inr(data.gross_contribution)} · Net profit <b>{inr(data.net_profit)}</b></p></>}
      {rep === "bs" && data && <div className="grid2">{["assets", "liability", "equity"].map((s) => <div key={s}><h4>{s}</h4>
        <Table rows={data.sections[s] || []} cols={[{ key: "name", label: "Ledger" }, { key: "amount", label: "₹", money: true }]} /></div>)}
        <p>Assets {inr(data.total_assets)} = Liabilities + equity {inr(data.total_liabilities_equity)} <Badge v={data.balanced ? "ok" : "failed"} /></p></div>}
      {rep === "ageing" && data && <Table rows={data.rows} cols={[{ key: "party", label: "Customer" }, ...data.buckets.map((b: string) => ({ key: b, label: b, money: true })), { key: "total", label: "Total", money: true }]} />}
      {rep === "gst" && data && <Table rows={data.rows} cols={[{ key: "invoice", label: "Invoice" }, { key: "date", label: "Date" }, { key: "customer", label: "Customer" }, { key: "gstin", label: "GSTIN" },
        { key: "mode", label: "Mode" }, { key: "taxable", label: "Taxable", money: true }, { key: "cgst", label: "CGST", money: true }, { key: "sgst", label: "SGST", money: true }, { key: "igst", label: "IGST", money: true }]} />}
      {rep === "profit" && data && ["by_service", "by_vehicle", "by_lane", "by_customer"].map((k) => <div key={k}><h4>{k.replace("by_", "By ")}</h4>
        <Table rows={data[k]} cols={[{ key: "key", label: "" }, { key: "revenue", label: "Revenue", money: true }, { key: "contribution", label: "Gross contribution", money: true }]} /></div>)}
    </Card>
  );
}

function Cash() {
  const f = useData(() => get("/finance/reports/cashflow"), []);
  const [period, setPeriod] = useState(today().slice(0, 7));
  const bva = useData(() => get(`/finance/budgets/${period}/vs-actual`), [period]);
  return (
    <div className="stack">
      <Card title="Cash-flow forecast" note={f.data ? `${f.data.label} · confidence ${f.data.confidence} · ${f.data.assumptions.join(" · ")}` : ""}>
        <Table rows={f.data?.weeks} cols={[{ key: "week_start", label: "Week of" }, { key: "inflow", label: "Expected in", money: true }, { key: "outflow", label: "Expected out", money: true },
          { key: "net", label: "Net", money: true }, { key: "cumulative_net", label: "Cumulative", money: true }]} />
      </Card>
      <Card title="Budget vs actual" actions={<input type="month" value={period} onChange={(e) => setPeriod(e.target.value)} />}>
        <Table rows={bva.data?.rows} cols={[{ key: "area", label: "Area" }, { key: "budget", label: "Budget", money: true }, { key: "actual", label: "Actual", money: true }, { key: "variance", label: "Variance", money: true }]} />
      </Card>
    </div>
  );
}

function Tally() {
  const [frm, setFrm] = useState(fyStart());
  const [to, setTo] = useState(today());
  const [file, setFile] = useState<File | null>(null);
  const [res, setRes] = useState<any>(null);
  const batches = useData(() => get("/finance/import-batches"), []);
  return (
    <div className="stack">
      <Card title="Export to Tally (XML)" note="Supported Tally XML import format. Source vouchers and numbers are preserved.">
        <div className="row gap"><input type="date" value={frm} onChange={(e) => setFrm(e.target.value)} /><input type="date" value={to} onChange={(e) => setTo(e.target.value)} />
          <Btn onClick={async () => { const b = await api(`/finance/tally/export?frm=${frm}&to=${to}`); const a = document.createElement("a"); a.href = URL.createObjectURL(b as Blob); a.download = "GRL_Tally.xml"; a.click(); }}>Download XML</Btn></div>
      </Card>
      <Card title="Import from Tally (dry run → approval → commit)" note="Never overwrites Tally. Unmapped ledgers, unbalanced or duplicate vouchers go to the exception list.">
        <div className="row gap"><input type="file" accept=".xml" onChange={(e) => setFile(e.target.files?.[0] || null)} />
          <Btn disabled={!file} onClick={async () => { const f = new FormData(); f.append("file", file!); setRes(await api("/finance/tally/import", { form: f })); batches.reload(); }}>Preview</Btn></div>
        {res && <><p>Batch {res.batch}: {res.valid_vouchers} valid voucher(s)</p><Table rows={res.exceptions} cols={[{ key: "row", label: "#" }, { key: "voucher", label: "Voucher" }, { key: "issue", label: "Issue" }]} empty="No exceptions" /></>}
        <Table rows={batches.data} cols={[{ key: "code", label: "Batch" }, { key: "filename", label: "File" }, { key: "status", label: "Status", badge: true },
          { key: "c", label: "", render: (r: any) => r.status === "previewed" && <Btn kind="ghost" onClick={async () => { try { await post(`/finance/import-batches/${r.id}/commit`); toast("Committed"); batches.reload(); } catch (e: any) { toast(e.message, "red"); } }}>Approve & commit</Btn> }]} />
      </Card>
    </div>
  );
}
