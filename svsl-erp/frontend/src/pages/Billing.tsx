import React, { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { openExternal } from "../lib/native";
import { api, can, qs } from "../lib/api";
import { dt, inr, monthStart, today } from "../lib/format";
import { Badge, Btn, Card, Field, Modal, Page, Pager, ReasonModal, RefSelect, Search, Table, download, run, toast, useLoad, useLookup } from "../components/ui";
import { ListSummary } from "../components/ResourcePage";

const DOC_TYPES: Record<string, string> = { tax_invoice: "Tax invoice", proforma: "Proforma invoice", debit_note: "Debit note", credit_note: "Credit note", bill_of_supply: "Bill of supply", advance_receipt: "Advance receipt voucher" };
const BASES: Record<string, string> = { lr: "LR-wise", consolidated: "Consolidated (many LRs)", trip: "Trip-wise", monthly_contract: "Monthly contract", warehouse: "Warehouse storage & handling", manual: "Manual lines" };

function NewInvoice({ onDone, onClose, preset }: { onDone: (i: any) => void; onClose: () => void; preset?: any }) {
  const [f, setF] = useState<any>({ doc_type: "tax_invoice", basis: "consolidated", invoice_date: today(), lr_ids: [], trip_ids: [], lines: [{ description: "", quantity: 1, rate: "", amount: "" }], period_from: monthStart(), period_to: today(), ...preset });
  const lrs = useLoad<any>(f.customer_id && ["lr", "consolidated"].includes(f.basis) ? `/api/lr?customer_id=${f.customer_id}&unbilled=1&limit=500` : null);
  const trips = useLoad<any>(f.customer_id && f.basis === "trip" ? `/api/trips?customer_id=${f.customer_id}&stage=Closed,POD%20Collected,Delivered&limit=500` : null);
  const contracts = useLoad<any>(f.customer_id && f.basis === "monthly_contract" ? `/api/r/rate_contracts?customer_id=${f.customer_id}&basis=monthly_fixed` : null);
  const refs = useLoad<any>(f.customer_id && ["debit_note", "credit_note"].includes(f.doc_type) ? `/api/invoices?customer_id=${f.customer_id}&doc_type=tax_invoice&limit=500` : null);
  const treatments = useLookup("gst_treatments");
  const [preview, setPreview] = useState<any[] | null>(null);
  const isNote = ["debit_note", "credit_note"].includes(f.doc_type);
  const basis = isNote ? "manual" : f.basis;
  useEffect(() => {
    if (basis === "warehouse" && f.customer_id) api.post("/api/invoices/preview-warehouse", f).then(setPreview).catch((e) => { setPreview(null); toast.err(e); });
  }, [basis, f.customer_id, f.period_from, f.period_to]);
  const toggle = (k: string, id: number) => setF({ ...f, [k]: f[k].includes(id) ? f[k].filter((x: number) => x !== id) : [...f[k], id] });
  const submit = async () => {
    const payload: any = { ...f, basis };
    if (basis !== "manual") delete payload.lines;
    const r = await run(() => api.post("/api/invoices", payload), "Document created");
    if (r) onDone(r);
  };
  const unbilled = (lrs.data?.items || []).filter((l: any) => l.status !== "Cancelled");
  const selTotal = unbilled.filter((l: any) => f.lr_ids.includes(l.id)).reduce((a: number, l: any) => a + Number(l.total_freight), 0);
  return <Modal wide title="New invoice / note" onClose={onClose} footer={<><Btn onClick={onClose}>Cancel</Btn><Btn kind="primary" onClick={submit}>Create</Btn></>}>
    <div className="form-grid">
      <Field label="Document"><select value={f.doc_type} onChange={(e) => setF({ ...f, doc_type: e.target.value })}>{Object.entries(DOC_TYPES).filter(([k]) => k !== "credit_note" || can("invoices:cancel")).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select></Field>
      <Field label="Customer" required><RefSelect refName="customers" value={f.customer_id} onChange={(v) => setF({ ...f, customer_id: v, lr_ids: [], trip_ids: [] })} /></Field>
      <Field label="Date"><input type="date" value={f.invoice_date} onChange={(e) => setF({ ...f, invoice_date: e.target.value })} /></Field>
      {!isNote && <Field label="Billing basis"><select value={f.basis} onChange={(e) => setF({ ...f, basis: e.target.value })}>{Object.entries(BASES).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select></Field>}
      {!isNote && <Field label="GST treatment (blank = contract / customer default)"><select value={f.gst_treatment_id || ""} onChange={(e) => setF({ ...f, gst_treatment_id: e.target.value ? Number(e.target.value) : null })}><option value="">Default</option>{treatments.map((t) => <option key={t.id} value={t.id}>{t.label}</option>)}</select></Field>}
      <Field label="Place of supply (state code, blank = auto)"><input maxLength={2} value={f.place_of_supply || ""} onChange={(e) => setF({ ...f, place_of_supply: e.target.value })} /></Field>
      <Field label="Customer PO / reference"><input value={f.po_number || ""} onChange={(e) => setF({ ...f, po_number: e.target.value })} /></Field>
      {isNote && <Field label="Against invoice" required><select value={f.reference_invoice_id || ""} onChange={(e) => setF({ ...f, reference_invoice_id: Number(e.target.value) })}><option value="">—</option>{(refs.data?.items || []).filter((i: any) => i.status !== "Cancelled").map((i: any) => <option key={i.id} value={i.id}>{i.invoice_no} · {dt(i.invoice_date)} · {inr(i.total)}</option>)}</select></Field>}
      {isNote && <Field label="Reason" required wide><input value={f.reason || ""} onChange={(e) => setF({ ...f, reason: e.target.value })} /></Field>}
      {["monthly_contract", "warehouse"].includes(basis) && <><Field label="Period from"><input type="date" value={f.period_from} onChange={(e) => setF({ ...f, period_from: e.target.value })} /></Field><Field label="Period to"><input type="date" value={f.period_to} onChange={(e) => setF({ ...f, period_to: e.target.value })} /></Field></>}
      {basis === "monthly_contract" && <Field label="Contract"><select value={f.contract_id || ""} onChange={(e) => setF({ ...f, contract_id: Number(e.target.value) })}><option value="">—</option>{(contracts.data?.items || []).filter((c: any) => c.status === "Active").map((c: any) => <option key={c.id} value={c.id}>{c.contract_no} v{c.version} {c.name}</option>)}</select></Field>}
      <Field label="Notes" wide><input value={f.notes || ""} onChange={(e) => setF({ ...f, notes: e.target.value })} /></Field>
    </div>
    {["lr", "consolidated"].includes(basis) && <Card title={`Unbilled LRs – selected ${f.lr_ids.length}, ${inr(selTotal)}`} actions={<Btn small onClick={() => setF({ ...f, lr_ids: unbilled.map((l: any) => l.id) })}>Select all</Btn>}>
      <Table dense cols={[{ key: "sel", label: "", render: (l) => <input type="checkbox" checked={f.lr_ids.includes(l.id)} onChange={() => toggle("lr_ids", l.id)} /> }, { key: "lr_no", label: "LR" }, { key: "lr_date", label: "Date", type: "date" }, { key: "to_place", label: "To" }, { key: "vehicle_no", label: "Vehicle" }, { key: "status", label: "Status", type: "badge" }, { key: "total_freight", label: "Freight", type: "money" }]} rows={unbilled} empty="No unbilled LRs for this customer" />
    </Card>}
    {basis === "trip" && <Card title="Trips"><Table dense cols={[{ key: "sel", label: "", render: (t) => <input type="checkbox" checked={f.trip_ids.includes(t.id)} onChange={() => toggle("trip_ids", t.id)} /> }, { key: "trip_no", label: "Trip" }, { key: "trip_date", label: "Date", type: "date" }, { key: "to_place", label: "To" }, { key: "vehicle_no", label: "Vehicle" }, { key: "stage", label: "Stage", type: "badge" }]} rows={(trips.data?.items || []).filter((t: any) => !t.billed)} /></Card>}
    {basis === "warehouse" && preview && <Table dense cols={[{ key: "description", label: "Line" }, { key: "amount", label: "Amount", type: "money" }]} rows={preview} />}
    {basis === "manual" && <Card title="Lines" actions={<Btn small onClick={() => setF({ ...f, lines: [...f.lines, { description: "", quantity: 1, rate: "", amount: "" }] })}>+ Line</Btn>}>
      {f.lines.map((l: any, i: number) => <div className="row gap" key={i}>
        <input className="grow" placeholder="Description" value={l.description} onChange={(e) => setF({ ...f, lines: f.lines.map((x: any, j: number) => (j === i ? { ...x, description: e.target.value } : x)) })} />
        <input type="number" placeholder="Qty" style={{ width: 80 }} value={l.quantity} onChange={(e) => setF({ ...f, lines: f.lines.map((x: any, j: number) => (j === i ? { ...x, quantity: e.target.value } : x)) })} />
        <input type="number" placeholder="Rate" style={{ width: 110 }} value={l.rate} onChange={(e) => setF({ ...f, lines: f.lines.map((x: any, j: number) => (j === i ? { ...x, rate: e.target.value, amount: "" } : x)) })} />
        <input type="number" placeholder="Amount" style={{ width: 120 }} value={l.amount} onChange={(e) => setF({ ...f, lines: f.lines.map((x: any, j: number) => (j === i ? { ...x, amount: e.target.value } : x)) })} />
        <button className="x" onClick={() => setF({ ...f, lines: f.lines.filter((_: any, j: number) => j !== i) })}>×</button>
      </div>)}
    </Card>}
  </Modal>;
}

function InvoiceDetail({ id, onClose }: { id: number; onClose: () => void }) {
  const { data: inv, reload } = useLoad<any>(`/api/invoices/${id}`);
  const [m, setM] = useState<string | null>(null);
  const [f, setF] = useState<any>({});
  if (!inv) return null;
  return <Modal wide title={`${DOC_TYPES[inv.doc_type]} ${inv.invoice_no}`} onClose={onClose} footer={<Btn onClick={onClose}>Close</Btn>}>
    <div className="row gap wrap"><Badge v={inv.status} /><Badge v={inv.einvoice_status === "Not Applicable" ? null : inv.einvoice_status} /><div className="grow" />
      <Btn small onClick={() => download(`/api/invoices/${id}/pdf`)}>PDF</Btn>
      <Btn small onClick={async () => { const r: any = await run(() => api.post(`/api/invoices/${id}/share`, { channel: "whatsapp" })); if (r?.url) openExternal(r.url); }}>WhatsApp</Btn>
      <Btn small onClick={async () => { const r: any = await run(() => api.post(`/api/invoices/${id}/share`, { channel: "email" })); if (r) r.status === "sent" ? toast.ok("Emailed") : toast.err(r.error || r.status); }}>Email</Btn>
      {["tax_invoice", "debit_note", "credit_note"].includes(inv.doc_type) && inv.status !== "Cancelled" && <>
        <Btn small onClick={() => download(`/api/invoices/${id}/einvoice-json`, `EINV_${inv.invoice_no.replace(/\//g, "-")}.json`)}>E-invoice JSON</Btn>
        {!inv.irn && can("invoices:write") && <Btn small onClick={() => run(() => api.post(`/api/invoices/${id}/einvoice`), "IRN generated").then(reload)}>Generate IRN (API)</Btn>}
        {!inv.irn && can("invoices:write") && <Btn small onClick={() => { setF({}); setM("irn"); }}>Record IRN from portal</Btn>}
        {inv.irn && inv.einvoice_status === "Generated" && can("invoices:cancel") && <Btn small onClick={() => { setF({}); setM("irncancel"); }}>Record IRN cancellation</Btn>}
      </>}
      {inv.status !== "Cancelled" && can("invoices:cancel") && <Btn small kind="danger" onClick={() => setM("cancel")}>Cancel</Btn>}
    </div>
    <div className="kv">{[["Date", dt(inv.invoice_date)], ["Due", dt(inv.due_date)], ["Billed to", inv.billing_name], ["GSTIN", inv.customer_gstin || "Unregistered"], ["Place of supply", inv.place_of_supply], ["GST", `${inv.gst_treatment_code} · ${inv.charge_mechanism} @ ${inv.gst_rate}%`], ["Taxable", inr(inv.taxable_value)], ["CGST", inr(inv.cgst)], ["SGST", inr(inv.sgst)], ["IGST", inr(inv.igst)], ["RCM tax (payable by recipient)", Number(inv.rcm_tax) ? inr(inv.rcm_tax) : ""], ["Round off", inr(inv.round_off)], ["Total", inr(inv.total)], ["Received", inr(inv.amount_received)], ["Balance", inr(inv.balance)], ["IRN", inv.irn], ["Ack no", inv.ack_no], ["E-invoice error", inv.einvoice_error], ["Reason", inv.reason], ["Cancelled", inv.cancelled_at ? `${dt(inv.cancelled_at)} – ${inv.cancel_reason}` : ""]].filter(([, v]) => v).map(([k, v]) => <div key={k}><span>{k}</span><b>{v}</b></div>)}</div>
    <Table dense cols={[{ key: "line_no", label: "#" }, { key: "description", label: "Description" }, { key: "sac", label: "SAC" }, { key: "quantity", label: "Qty", type: "number" }, { key: "rate", label: "Rate", type: "money" }, { key: "amount", label: "Amount", type: "money" }]} rows={inv.lines} />
    {inv.receipts.length > 0 && <><h4>Receipts / adjustments</h4><Table dense cols={[{ key: "voucher_no", label: "Voucher" }, { key: "amount", label: "Amount", type: "money" }, { key: "tds", label: "TDS", type: "money" }, { key: "reversed", label: "Reversed", type: "bool" }]} rows={inv.receipts} /></>}
    {inv.notes?.length > 0 && <><h4>Debit / credit notes</h4><Table dense cols={[{ key: "invoice_no", label: "No" }, { key: "doc_type", label: "Type" }, { key: "total", label: "Total", type: "money" }, { key: "status", label: "Status", type: "badge" }]} rows={inv.notes} /></>}
    {m === "cancel" && <ReasonModal title={`Cancel ${inv.invoice_no}`} onClose={() => setM(null)} onSubmit={async (reason) => { const r = await run(() => api.post(`/api/invoices/${id}/cancel`, { reason }), "Cancelled – reversal voucher posted"); reload(); return r; }} />}
    {m === "irn" && <Modal title="Record IRN obtained on the IRP portal" onClose={() => setM(null)} footer={<Btn kind="primary" onClick={async () => { if (await run(() => api.post(`/api/invoices/${id}/einvoice/record`, f), "IRN recorded")) { setM(null); reload(); } }}>Save</Btn>}>
      <p className="muted small">Upload the JSON on the IRP portal / offline tool, then paste the IRN, acknowledgement number and signed QR returned by the IRP.</p>
      <Field label="IRN (64 characters)"><input value={f.irn || ""} onChange={(e) => setF({ ...f, irn: e.target.value })} /></Field>
      <Field label="Ack no"><input value={f.ack_no || ""} onChange={(e) => setF({ ...f, ack_no: e.target.value })} /></Field>
      <Field label="Ack date"><input type="datetime-local" value={f.ack_date || ""} onChange={(e) => setF({ ...f, ack_date: e.target.value })} /></Field>
      <Field label="Signed QR code text"><textarea value={f.signed_qr || ""} onChange={(e) => setF({ ...f, signed_qr: e.target.value })} /></Field>
    </Modal>}
    {m === "irncancel" && <Modal title="IRN cancellation" onClose={() => setM(null)} footer={<Btn kind="danger" onClick={async () => { if (await run(() => api.post(`/api/invoices/${id}/einvoice/cancelled`, f), "Recorded")) { setM(null); reload(); } }}>Save</Btn>}>
      <p className="muted small">IRNs can be cancelled on the IRP only within 24 hours. After that, issue a credit note.</p>
      <Field label="IRP cancellation confirmation / date"><input value={f.confirmation || ""} onChange={(e) => setF({ ...f, confirmation: e.target.value })} /></Field>
    </Modal>}
  </Modal>;
}

export default function Invoices() {
  const [sp, setSp] = useSearchParams();
  const [q, setQ] = useState("");
  const [type, setType] = useState("");
  const [status, setStatus] = useState("");
  const [offset, setOffset] = useState(0);
  const [creating, setCreating] = useState(false);
  const list = useLoad<any>(`/api/invoices${qs({ q, doc_type: type, status, offset, limit: 50 })}`);
  return <Page title="Invoices" actions={can("invoices:write") && <Btn kind="primary" onClick={() => setCreating(true)}>+ New invoice / note</Btn>}>
    <ListSummary name="invoices" icon="file" />
    <div className="toolbar"><Search value={q} onChange={setQ} placeholder="Invoice no / customer" />
      <select value={type} onChange={(e) => setType(e.target.value)}><option value="">All documents</option>{Object.entries(DOC_TYPES).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select>
      <select value={status} onChange={(e) => setStatus(e.target.value)}><option value="">All statuses</option>{["Issued", "Partly Paid", "Paid", "Adjusted", "Cancelled"].map((s) => <option key={s}>{s}</option>)}</select></div>
    <Table cols={[{ key: "invoice_no", label: "No" }, { key: "doc_type", label: "Type", render: (r) => DOC_TYPES[r.doc_type] }, { key: "invoice_date", label: "Date", type: "date" }, { key: "billing_name", label: "Customer" }, { key: "charge_mechanism", label: "GST" }, { key: "taxable_value", label: "Taxable", type: "money" }, { key: "total", label: "Total", type: "money" }, { key: "balance", label: "Balance", type: "money" }, { key: "due_date", label: "Due", type: "date" }, { key: "status", label: "Status", type: "badge" }]}
      rows={list.data?.items || []} onRow={(r) => setSp({ id: String(r.id) })} />
    <Pager total={list.data?.total || 0} limit={50} offset={offset} onChange={setOffset} />
    {creating && <NewInvoice onClose={() => setCreating(false)} onDone={(i) => { setCreating(false); list.reload(); setSp({ id: String(i.id) }); }} />}
    {sp.get("id") && <InvoiceDetail id={Number(sp.get("id"))} onClose={() => { setSp({}); list.reload(); }} />}
  </Page>;
}

export function Receipts() {
  const [f, setF] = useState<any>({ date: today(), mode: "Bank", amount: "", tds_amount: "", allocations: [] });
  const open = useLoad<any>(f.customer_id ? `/api/invoices?customer_id=${f.customer_id}&status=Issued,Partly%20Paid&limit=500` : null);
  const banks = useLoad<any[]>("/api/ledgers/balances");
  const [manual, setManual] = useState(false);
  const alloc = (id: number, amount: string) => setF({ ...f, allocations: [...f.allocations.filter((a: any) => a.invoice_id !== id), ...(amount ? [{ invoice_id: id, amount }] : [])] });
  const submit = async () => {
    const payload = { ...f, allocations: manual ? f.allocations : [], auto_allocate: !manual };
    const r: any = await run(() => api.post("/api/receipts", payload), "Receipt posted");
    if (r) { setF({ date: today(), mode: "Bank", amount: "", tds_amount: "", allocations: [], customer_id: f.customer_id }); open.reload(); }
  };
  return <Page title="Receipts">
    <Card title="Customer receipt">
      <div className="form-grid">
        <Field label="Customer"><RefSelect refName="customers" value={f.customer_id} onChange={(v) => setF({ ...f, customer_id: v, allocations: [] })} /></Field>
        <Field label="Date"><input type="date" value={f.date} onChange={(e) => setF({ ...f, date: e.target.value })} /></Field>
        <Field label="Mode"><select value={f.mode} onChange={(e) => setF({ ...f, mode: e.target.value })}><option>Bank</option><option>Cash</option></select></Field>
        {f.mode === "Bank" && <Field label="Bank account"><select value={f.bank_ledger_id || ""} onChange={(e) => setF({ ...f, bank_ledger_id: Number(e.target.value) })}><option value="">—</option>{(banks.data || []).filter((l) => l.group === "Bank Accounts").map((l) => <option key={l.id} value={l.id}>{l.name}</option>)}</select></Field>}
        <Field label="Amount received ₹"><input type="number" value={f.amount} onChange={(e) => setF({ ...f, amount: e.target.value })} /></Field>
        <Field label="TDS deducted by customer ₹"><input type="number" value={f.tds_amount} onChange={(e) => setF({ ...f, tds_amount: e.target.value })} /></Field>
        <Field label="Cheque / UTR no"><input value={f.instrument_no || ""} onChange={(e) => setF({ ...f, instrument_no: e.target.value })} /></Field>
        <Field label="Narration"><input value={f.narration || ""} onChange={(e) => setF({ ...f, narration: e.target.value })} /></Field>
      </div>
      <label className="row gap small"><input type="checkbox" checked={manual} onChange={(e) => setManual(e.target.checked)} /> Allocate to specific bills (otherwise oldest bills first)</label>
      {manual && <Table dense cols={[{ key: "invoice_no", label: "Invoice" }, { key: "invoice_date", label: "Date", type: "date" }, { key: "total", label: "Total", type: "money" }, { key: "balance", label: "Balance", type: "money" }, { key: "a", label: "Allocate ₹", render: (i) => <input type="number" style={{ width: 120 }} value={f.allocations.find((a: any) => a.invoice_id === i.id)?.amount || ""} onChange={(e) => alloc(i.id, e.target.value)} /> }]} rows={open.data?.items || []} />}
      <Btn kind="primary" onClick={submit}>Post receipt</Btn>
    </Card>
    {f.customer_id && <Card title="Open bills"><Table dense cols={[{ key: "invoice_no", label: "Invoice" }, { key: "invoice_date", label: "Date", type: "date" }, { key: "due_date", label: "Due", type: "date" }, { key: "total", label: "Total", type: "money" }, { key: "balance", label: "Balance", type: "money" }, { key: "status", label: "Status", type: "badge" }]} rows={open.data?.items || []} /></Card>}
  </Page>;
}
