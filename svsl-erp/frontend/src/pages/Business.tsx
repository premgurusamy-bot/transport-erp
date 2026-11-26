import React, { useEffect, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { api, can, qs } from "../lib/api";
import { dt, inr, monthStart, today } from "../lib/format";
import ResourcePage, { ListSummary } from "../components/ResourcePage";
import { Badge, Btn, Card, Field, Kpi, Modal, Page, RefSelect, Table, Tabs, download, run, toast, useLoad, useLookup } from "../components/ui";

// ------------------------------------------------------------------ warehouse
function Scanner({ onCode }: { onCode: (c: string) => void }) {
  const video = useRef<HTMLVideoElement>(null);
  const [on, setOn] = useState(false);
  const supported = typeof (window as any).BarcodeDetector !== "undefined";
  useEffect(() => {
    if (!on) return;
    let stream: MediaStream | null = null, stop = false;
    const det = new (window as any).BarcodeDetector({ formats: ["qr_code", "code_128", "ean_13", "code_39"] });
    navigator.mediaDevices.getUserMedia({ video: { facingMode: "environment" } }).then((s) => {
      stream = s;
      if (video.current) { video.current.srcObject = s; video.current.play(); }
      const tick = async () => {
        if (stop || !video.current) return;
        try { const r = await det.detect(video.current); if (r[0]) { onCode(r[0].rawValue); setOn(false); return; } } catch { /* frame not ready */ }
        requestAnimationFrame(tick);
      };
      tick();
    }).catch((e) => { toast.err("Camera not available: " + e.message); setOn(false); });
    return () => { stop = true; stream?.getTracks().forEach((t) => t.stop()); };
  }, [on]);
  return <div>
    {supported ? <Btn small onClick={() => setOn(!on)}>{on ? "Stop camera" : "Scan with camera"}</Btn> : <small className="muted">Camera scanning is not supported in this browser – use a USB/Bluetooth scanner or type the code.</small>}
    {on && <video ref={video} className="scanner" muted playsInline />}
  </div>;
}

function StockDocForm({ onDone, onClose }: { onDone: () => void; onClose: () => void }) {
  const items = useLookup("items");
  const [f, setF] = useState<any>({ doc_type: "Inward", doc_date: today(), lines: [{ item_id: null, qty: "", batch_no: "", packages: "" }] });
  const [code, setCode] = useState("");
  const scan = async (c: string) => {
    const r: any = await run(() => api.get(`/api/warehouse/scan/${encodeURIComponent(c)}`));
    if (r?.type === "item") setF((x: any) => ({ ...x, lines: [...x.lines.filter((l: any) => l.item_id), { item_id: r.item.id, qty: 1, batch_no: r.batch_no || "", packages: "" }] }));
    else if (r?.type === "lr") setF((x: any) => ({ ...x, consignment_id: r.id }));
    setCode("");
  };
  const line = (i: number, k: string, v: any) => setF({ ...f, lines: f.lines.map((x: any, j: number) => (j === i ? { ...x, [k]: v } : x)) });
  return <Modal wide title="Stock document" onClose={onClose} footer={<Btn kind="primary" onClick={async () => { if (await run(() => api.post("/api/warehouse/docs", { ...f, lines: f.lines.filter((l: any) => l.item_id) }), "Posted")) onDone(); }}>Post</Btn>}>
    <div className="form-grid">
      <Field label="Type"><select value={f.doc_type} onChange={(e) => setF({ ...f, doc_type: e.target.value })}>{["Inward", "Outward", "Transfer", "Damage", "Shortage", "Adjustment", "Count"].map((x) => <option key={x}>{x}</option>)}</select></Field>
      <Field label="Date"><input type="date" value={f.doc_date} onChange={(e) => setF({ ...f, doc_date: e.target.value })} /></Field>
      <Field label="Godown"><RefSelect refName="warehouses" value={f.warehouse_id} onChange={(v) => setF({ ...f, warehouse_id: v })} /></Field>
      {f.doc_type === "Transfer" && <Field label="To godown"><RefSelect refName="warehouses" value={f.to_warehouse_id} onChange={(v) => setF({ ...f, to_warehouse_id: v })} /></Field>}
      <Field label="Customer (stock owner)"><RefSelect refName="customers" value={f.customer_id} onChange={(v) => setF({ ...f, customer_id: v })} /></Field>
      <Field label="Vehicle no"><input value={f.vehicle_no || ""} onChange={(e) => setF({ ...f, vehicle_no: e.target.value.toUpperCase() })} /></Field>
      <Field label="Party document no"><input value={f.party_doc_no || ""} onChange={(e) => setF({ ...f, party_doc_no: e.target.value })} /></Field>
      <Field label="Loaded / unloaded by"><input value={f.loaded_by || ""} onChange={(e) => setF({ ...f, loaded_by: e.target.value })} /></Field>
      <Field label="Remarks" wide><input value={f.remarks || ""} onChange={(e) => setF({ ...f, remarks: e.target.value })} /></Field>
    </div>
    <div className="row gap"><input placeholder="Scan / type barcode then Enter" value={code} onChange={(e) => setCode(e.target.value)} onKeyDown={(e) => e.key === "Enter" && code && scan(code)} /><Scanner onCode={scan} /></div>
    {f.doc_type === "Count" && <p className="muted small">Enter the physically counted quantity; the difference is posted as an adjustment.</p>}
    {f.lines.map((l: any, i: number) => <div className="row gap" key={i}>
      <select className="grow" value={l.item_id || ""} onChange={(e) => line(i, "item_id", Number(e.target.value))}><option value="">— item —</option>{items.map((it) => <option key={it.id} value={it.id}>{it.label}</option>)}</select>
      <input type="number" placeholder={f.doc_type === "Count" ? "Counted qty" : "Qty"} style={{ width: 100 }} value={l.qty} onChange={(e) => line(i, "qty", e.target.value)} />
      <input placeholder="Batch" style={{ width: 110 }} value={l.batch_no} onChange={(e) => line(i, "batch_no", e.target.value)} />
      <input type="number" placeholder="Pkgs" style={{ width: 80 }} value={l.packages} onChange={(e) => line(i, "packages", e.target.value)} />
      {f.doc_type === "Adjustment" && <select value={l.direction || "out"} onChange={(e) => line(i, "direction", e.target.value)}><option value="in">Add</option><option value="out">Reduce</option></select>}
      <button className="x" onClick={() => setF({ ...f, lines: f.lines.filter((_: any, j: number) => j !== i) })}>×</button>
    </div>)}
    <Btn small onClick={() => setF({ ...f, lines: [...f.lines, { item_id: null, qty: "", batch_no: "", packages: "" }] })}>+ Line</Btn>
  </Modal>;
}

export function Warehouse() {
  const [tab, setTab] = useState("Stock");
  const [wh, setWh] = useState<number | null>(null);
  const [cust, setCust] = useState<number | null>(null);
  const stock = useLoad<any[]>(tab === "Stock" ? `/api/warehouse/stock${qs({ warehouse_id: wh, customer_id: cust })}` : null);
  const docs = useLoad<any[]>(tab === "Documents" ? `/api/warehouse/docs${qs({ warehouse_id: wh })}` : null);
  const [form, setForm] = useState(false);
  const [lbl, setLbl] = useState<any>(null);
  return <Page title="Warehouse" actions={can("warehouse:write") && <Btn kind="primary" onClick={() => setForm(true)}>+ Inward / outward</Btn>}>
    <ListSummary name="stock_docs" icon="warehouse" />
    <div className="toolbar"><RefSelect refName="warehouses" value={wh} onChange={setWh} placeholder="All godowns" /><RefSelect refName="customers" value={cust} onChange={setCust} placeholder="All owners" /></div>
    <Tabs tabs={["Stock", "Documents", "Labels"]} value={tab} onChange={setTab} />
    {tab === "Stock" && <Table cols={[{ key: "warehouse", label: "Godown" }, { key: "sku", label: "SKU" }, { key: "item", label: "Item" }, { key: "batch_no", label: "Batch" }, { key: "customer_id", label: "Owner", type: "ref", ref: "customers" }, { key: "qty_in", label: "In", type: "number" }, { key: "qty_out", label: "Out", type: "number" }, { key: "balance", label: "Balance", type: "number" }]} rows={stock.data || []} />}
    {tab === "Documents" && <Table cols={[{ key: "doc_no", label: "Doc" }, { key: "doc_date", label: "Date", type: "date" }, { key: "doc_type", label: "Type", type: "badge" }, { key: "warehouse", label: "Godown" }, { key: "vehicle_no", label: "Vehicle" }, { key: "lines", label: "Items", render: (d) => d.lines.map((l: any) => `${l.item} ${l.batch_no ? "[" + l.batch_no + "]" : ""} ${Number(l.in) || ""}${Number(l.out) ? "-" + l.out : ""}`).join("; ") }, { key: "remarks", label: "Remarks" }]} rows={docs.data || []} />}
    {tab === "Labels" && <Card title="Print QR labels">
      <div className="row gap"><RefSelect refName="items" value={lbl?.item_id} onChange={(v) => setLbl({ ...lbl, item_id: v })} /><input placeholder="Batch" value={lbl?.batch_no || ""} onChange={(e) => setLbl({ ...lbl, batch_no: e.target.value })} /><input type="number" placeholder="Copies" value={lbl?.copies || 1} onChange={(e) => setLbl({ ...lbl, copies: e.target.value })} />
        <Btn disabled={!lbl?.item_id} onClick={() => download(`/api/warehouse/labels${qs(lbl)}`)}>Print labels</Btn></div>
    </Card>}
    {form && <StockDocForm onClose={() => setForm(false)} onDone={() => { setForm(false); stock.reload(); docs.reload(); }} />}
  </Page>;
}

export function WarehouseMasters() {
  const [tab, setTab] = useState("Godowns");
  return <Page title="Godowns & items">
    <Tabs tabs={["Godowns", "Items", "Rental rate cards"]} value={tab} onChange={setTab} />
    {tab === "Godowns" && <ResourcePage embedded name="warehouses" columns={["code", "name", "branch_id", "area_sqft", "capacity_pallets", "incharge"]} />}
    {tab === "Items" && <ResourcePage embedded name="items" columns={["sku", "name", "hsn", "uom", "customer_id", "batch_tracked", "barcode"]} />}
    {tab === "Rental rate cards" && <ResourcePage embedded name="warehouse_rate_cards" columns={["customer_id", "warehouse_id", "storage_basis", "storage_rate", "handling_in_rate", "handling_out_rate", "min_monthly", "effective_from", "effective_to"]} />}
  </Page>;
}

// ------------------------------------------------------------------ purchase
export function Purchase() {
  const [tab, setTab] = useState("Vendor bills");
  const bills = useLoad<any[]>(tab === "Vendor bills" ? "/api/vendor-bills" : null);
  const pos = useLoad<any[]>(tab === "Purchase orders" ? "/api/purchase-orders" : null);
  const grns = useLoad<any[]>(tab === "Goods receipts" ? "/api/goods-receipts" : null);
  const [bill, setBill] = useState<any>(null);
  const [po, setPo] = useState<any>(null);
  const [rcv, setRcv] = useState<any>(null);
  const [pay, setPay] = useState<any>(null);
  const cats = ["Diesel / Fuel", "Spare Parts", "Tyres", "Batteries", "Workshop / Repairs", "Vehicle Dealer", "Insurance", "Office", "Vehicle Owner (Attached)", "Transporter", "Other"];
  return <Page title="Purchase & vendor bills" actions={can("purchase:write") && <>
    <ListSummary name="vendor_bills" icon="cart" />
    <Btn onClick={() => setPo({ po_date: today(), lines: [{ description: "", qty: 1, uom: "NOS", rate: "", gst_rate: 18 }] })}>+ Purchase order</Btn>
    <Btn kind="primary" onClick={() => setBill({ bill_date: today(), lines: [{ description: "", amount: "", gst_rate: 18 }], itc_eligible: true })}>+ Vendor bill</Btn>
    {can("accounts:write") && <Btn onClick={() => setPay({ date: today(), mode: "Bank" })}>Pay vendor</Btn>}</>}>
    <Tabs tabs={["Vendor bills", "Purchase orders", "Goods receipts"]} value={tab} onChange={setTab} />
    {tab === "Vendor bills" && <Table cols={[{ key: "entry_no", label: "Entry" }, { key: "bill_no", label: "Bill no" }, { key: "bill_date", label: "Date", type: "date" }, { key: "vendor", label: "Vendor" }, { key: "category", label: "Category" }, { key: "taxable_value", label: "Taxable", type: "money" }, { key: "total", label: "Total", type: "money" }, { key: "balance", label: "Balance", type: "money" }, { key: "due_date", label: "Due", type: "date" }, { key: "status", label: "Status", type: "badge" },
      { key: "x", label: "", render: (b) => b.status === "Unpaid" && can("accounts:cancel") ? <Btn small kind="ghost" onClick={async () => { const r = prompt("Reason for cancelling this bill?"); if (r && await run(() => api.post(`/api/vendor-bills/${b.id}/cancel`, { reason: r }), "Cancelled")) bills.reload(); }}>Cancel</Btn> : null }]} rows={bills.data || []} />}
    {tab === "Purchase orders" && <Table cols={[{ key: "po_no", label: "PO" }, { key: "po_date", label: "Date", type: "date" }, { key: "vendor", label: "Vendor" }, { key: "category", label: "Category" }, { key: "total", label: "Total", type: "money" }, { key: "status", label: "Status", type: "badge" },
      { key: "x", label: "", render: (p) => ["Open", "Partly Received"].includes(p.status) && can("purchase:write") ? <Btn small onClick={() => setRcv({ po: p, grn_date: today(), lines: p.lines.map((l: any, i: number) => ({ po_line: i, qty: "" })) })}>Receive</Btn> : null }]} rows={pos.data || []} />}
    {tab === "Goods receipts" && <Table cols={[{ key: "grn_no", label: "GRN" }, { key: "grn_date", label: "Date", type: "date" }, { key: "po_id", label: "PO id" }, { key: "challan_no", label: "Challan" }, { key: "lines", label: "Items", render: (g) => g.lines.map((l: any) => `${l.description} × ${l.qty}`).join("; ") }]} rows={grns.data || []} />}
    {bill && <Modal wide title="Vendor bill" onClose={() => setBill(null)} footer={<Btn kind="primary" onClick={async () => { if (await run(() => api.post("/api/vendor-bills", bill), "Bill posted")) { setBill(null); bills.reload(); } }}>Post bill</Btn>}>
      <div className="form-grid">
        <Field label="Vendor"><RefSelect refName="vendors" value={bill.vendor_id} onChange={(v) => setBill({ ...bill, vendor_id: v })} /></Field>
        <Field label="Bill no"><input value={bill.bill_no || ""} onChange={(e) => setBill({ ...bill, bill_no: e.target.value })} /></Field>
        <Field label="Bill date"><input type="date" value={bill.bill_date} onChange={(e) => setBill({ ...bill, bill_date: e.target.value })} /></Field>
        <Field label="Category"><select value={bill.category || ""} onChange={(e) => setBill({ ...bill, category: e.target.value })}><option value="">Vendor's category</option>{cats.map((c) => <option key={c}>{c}</option>)}</select></Field>
        <Field label="Vehicle (cost centre)"><RefSelect refName="vehicles" value={bill.vehicle_id} onChange={(v) => setBill({ ...bill, vehicle_id: v })} /></Field>
        <Field label="Against PO"><input type="number" value={bill.po_id || ""} onChange={(e) => setBill({ ...bill, po_id: e.target.value })} /></Field>
        <Field label="Reverse charge (RCM)"><input type="checkbox" checked={!!bill.is_rcm} onChange={(e) => setBill({ ...bill, is_rcm: e.target.checked })} /></Field>
        <Field label="Input tax credit eligible"><input type="checkbox" checked={!!bill.itc_eligible} onChange={(e) => setBill({ ...bill, itc_eligible: e.target.checked })} /></Field>
        <Field label="TDS deducted ₹"><input type="number" value={bill.tds_amount || ""} onChange={(e) => setBill({ ...bill, tds_amount: e.target.value })} /></Field>
      </div>
      {bill.lines.map((l: any, i: number) => <div className="row gap" key={i}>
        <input className="grow" placeholder="Description" value={l.description} onChange={(e) => setBill({ ...bill, lines: bill.lines.map((x: any, j: number) => (j === i ? { ...x, description: e.target.value } : x)) })} />
        <input type="number" placeholder="Taxable ₹" style={{ width: 130 }} value={l.amount} onChange={(e) => setBill({ ...bill, lines: bill.lines.map((x: any, j: number) => (j === i ? { ...x, amount: e.target.value } : x)) })} />
        <select value={l.gst_rate} onChange={(e) => setBill({ ...bill, lines: bill.lines.map((x: any, j: number) => (j === i ? { ...x, gst_rate: e.target.value } : x)) })}>{[0, 5, 12, 18, 28, 40].map((r) => <option key={r} value={r}>{r}%</option>)}</select>
      </div>)}
      <Btn small onClick={() => setBill({ ...bill, lines: [...bill.lines, { description: "", amount: "", gst_rate: 18 }] })}>+ Line</Btn>
    </Modal>}
    {po && <Modal wide title="Purchase order" onClose={() => setPo(null)} footer={<Btn kind="primary" onClick={async () => { if (await run(() => api.post("/api/purchase-orders", po), "PO created")) { setPo(null); pos.reload(); } }}>Create PO</Btn>}>
      <div className="form-grid"><Field label="Vendor"><RefSelect refName="vendors" value={po.vendor_id} onChange={(v) => setPo({ ...po, vendor_id: v })} /></Field><Field label="Date"><input type="date" value={po.po_date} onChange={(e) => setPo({ ...po, po_date: e.target.value })} /></Field><Field label="Expected"><input type="date" value={po.expected_date || ""} onChange={(e) => setPo({ ...po, expected_date: e.target.value })} /></Field><Field label="Vehicle"><RefSelect refName="vehicles" value={po.vehicle_id} onChange={(v) => setPo({ ...po, vehicle_id: v })} /></Field></div>
      {po.lines.map((l: any, i: number) => <div className="row gap" key={i}>{["description", "qty", "uom", "rate", "gst_rate"].map((k) => <input key={k} placeholder={k} className={k === "description" ? "grow" : ""} type={["qty", "rate", "gst_rate"].includes(k) ? "number" : "text"} value={l[k]} onChange={(e) => setPo({ ...po, lines: po.lines.map((x: any, j: number) => (j === i ? { ...x, [k]: e.target.value } : x)) })} />)}</div>)}
      <Btn small onClick={() => setPo({ ...po, lines: [...po.lines, { description: "", qty: 1, uom: "NOS", rate: "", gst_rate: 18 }] })}>+ Line</Btn>
    </Modal>}
    {rcv && <Modal title={`Receive ${rcv.po.po_no}`} onClose={() => setRcv(null)} footer={<Btn kind="primary" onClick={async () => { if (await run(() => api.post(`/api/purchase-orders/${rcv.po.id}/receive`, rcv), "Goods received")) { setRcv(null); pos.reload(); } }}>Save GRN</Btn>}>
      <Field label="Date"><input type="date" value={rcv.grn_date} onChange={(e) => setRcv({ ...rcv, grn_date: e.target.value })} /></Field>
      <Field label="Challan no"><input value={rcv.challan_no || ""} onChange={(e) => setRcv({ ...rcv, challan_no: e.target.value })} /></Field>
      {rcv.po.lines.map((l: any, i: number) => <div className="row gap" key={i}><span className="grow">{l.description} (ordered {l.qty}, received {l.received_qty || 0})</span><input type="number" style={{ width: 100 }} value={rcv.lines[i].qty} onChange={(e) => setRcv({ ...rcv, lines: rcv.lines.map((x: any, j: number) => (j === i ? { ...x, qty: e.target.value } : x)) })} /></div>)}
    </Modal>}
    {pay && <Modal title="Vendor payment" onClose={() => setPay(null)} footer={<Btn kind="primary" onClick={async () => { if (await run(() => api.post("/api/vendor-payments", pay), "Payment posted")) { setPay(null); bills.reload(); } }}>Pay</Btn>}>
      <Field label="Vendor"><RefSelect refName="vendors" value={pay.vendor_id} onChange={(v) => setPay({ ...pay, vendor_id: v })} /></Field>
      <Field label="Amount ₹"><input type="number" value={pay.amount || ""} onChange={(e) => setPay({ ...pay, amount: e.target.value })} /></Field>
      <Field label="Date"><input type="date" value={pay.date} onChange={(e) => setPay({ ...pay, date: e.target.value })} /></Field>
      <Field label="Mode"><select value={pay.mode} onChange={(e) => setPay({ ...pay, mode: e.target.value })}><option>Bank</option><option>Cash</option></select></Field>
      <Field label="Cheque / UTR"><input value={pay.instrument_no || ""} onChange={(e) => setPay({ ...pay, instrument_no: e.target.value })} /></Field>
      <p className="muted small">The payment is allocated to the oldest unpaid bills first.</p>
    </Modal>}
  </Page>;
}

// ------------------------------------------------------------------ HR
export function Employees() {
  const [tab, setTab] = useState("Employees");
  return <Page title="Employees">
    <Tabs tabs={["Employees", "Departments", "Leave requests", "Leave types", "Salary advances"]} value={tab} onChange={setTab} />
    {tab === "Employees" && <ResourcePage embedded name="employees" columns={["code", "name", "department_id", "designation", "branch_id", "mobile", "joining_date", "status", "basic"]} />}
    {tab === "Departments" && <ResourcePage embedded name="departments" columns={["name", "is_active"]} />}
    {tab === "Leave requests" && <ResourcePage embedded name="leave_requests" columns={["person_type", "person_id", "leave_type_id", "from_date", "to_date", "days", "status"]} defaults={{ person_type: "employee", status: "Pending" }} />}
    {tab === "Leave types" && <ResourcePage embedded name="leave_types" columns={["name", "days_per_year", "paid"]} />}
    {tab === "Salary advances" && <ResourcePage embedded name="salary_advances" columns={["advance_date", "employee_id", "amount", "monthly_recovery", "recovered", "mode"]} defaults={{ advance_date: today(), mode: "Cash" }} />}
  </Page>;
}

export function Attendance() {
  const [ptype, setPtype] = useState("employee");
  const [day, setDay] = useState(today());
  const { data, setData } = useLoad<any[]>(`/api/attendance?person_type=${ptype}&on=${day}`);
  const statuses = ["Present", "Absent", "Half Day", "Leave", "On Trip", "Week Off", "Holiday"];
  return <Page title="Attendance" actions={can("hr:write") && <Btn kind="primary" onClick={() => run(() => api.post("/api/attendance", { person_type: ptype, date: day, rows: data }), "Attendance saved")}>Save</Btn>}>
    <div className="toolbar"><select value={ptype} onChange={(e) => setPtype(e.target.value)}><option value="employee">Employees</option><option value="driver">Drivers</option></select><input type="date" value={day} onChange={(e) => setDay(e.target.value)} />
      <Btn small onClick={() => setData((data || []).map((r) => ({ ...r, status: r.status || "Present" })))}>Mark unmarked as present</Btn></div>
    <Table cols={[{ key: "code", label: "Code" }, { key: "name", label: "Name" },
      { key: "status", label: "Status", render: (r) => <select value={r.status || ""} onChange={(e) => setData((data || []).map((x) => (x.id === r.id ? { ...x, status: e.target.value } : x)))}><option value="">—</option>{statuses.map((s) => <option key={s}>{s}</option>)}</select> },
      { key: "in_time", label: "In", render: (r) => <input type="time" value={r.in_time || ""} onChange={(e) => setData((data || []).map((x) => (x.id === r.id ? { ...x, in_time: e.target.value } : x)))} /> },
      { key: "out_time", label: "Out", render: (r) => <input type="time" value={r.out_time || ""} onChange={(e) => setData((data || []).map((x) => (x.id === r.id ? { ...x, out_time: e.target.value } : x)))} /> },
      { key: "remarks", label: "Remarks", render: (r) => <input value={r.remarks || ""} onChange={(e) => setData((data || []).map((x) => (x.id === r.id ? { ...x, remarks: e.target.value } : x)))} /> }]} rows={data || []} />
  </Page>;
}

export function Payroll() {
  const [month, setMonth] = useState(today().slice(0, 7));
  const { data, reload, setData } = useLoad<any>(`/api/payroll/${month}`);
  const run_ = data?.run;
  return <Page title="Payroll" actions={<>
    <input type="month" value={month} onChange={(e) => setMonth(e.target.value)} />
    {can("payroll:write") && run_?.status !== "Posted" && <Btn onClick={async () => { const r = await run(() => api.post(`/api/payroll/${month}/compute`), "Payroll computed"); if (r) setData(r); }}>Compute</Btn>}
    {can("payroll:write") && run_?.status === "Draft" && <Btn kind="primary" onClick={async () => { if (confirm("Post payroll to accounts? It cannot be recomputed after posting.")) { const r = await run(() => api.post(`/api/payroll/${month}/post`), "Payroll posted"); if (r) setData(r); } }}>Post to accounts</Btn>}
    {run_ && <Btn onClick={() => download(`/api/reports/payroll_register?month=${month}&format=xlsx`)}>Register (Excel)</Btn>}</>}>
    {run_ && <div className="kpis small"><Kpi label="Status" value={<Badge v={run_.status} />} /><Kpi label="Gross" value={inr(run_.total_gross)} /><Kpi label="Deductions" value={inr(run_.total_deductions)} /><Kpi label="Net pay" value={inr(run_.total_net)} /><Kpi label="Employer EPF" value={inr(run_.employer_pf)} /><Kpi label="Employer ESI" value={inr(run_.employer_esi)} /></div>}
    <Table cols={[{ key: "name", label: "Name" }, { key: "person_type", label: "Type" }, { key: "paid_days", label: "Paid days", type: "number" }, { key: "gross", label: "Gross", type: "money" }, { key: "pf_employee", label: "EPF", type: "money" }, { key: "esi_employee", label: "ESI", type: "money" }, { key: "professional_tax", label: "PT", type: "money" }, { key: "tds", label: "TDS", type: "money" }, { key: "advance_recovery", label: "Advance", type: "money" }, { key: "net_pay", label: "Net", type: "money" },
      { key: "x", label: "", render: (s) => <Btn small kind="ghost" onClick={() => download(`/api/payslips/${s.id}/pdf`)}>Payslip</Btn> }]} rows={data?.slips || []} empty="Compute payroll for this month" />
    <p className="muted small">EPF, ESI and professional tax rates/ceilings are configured in Settings → Payroll. Verify them against current notifications before posting.</p>
  </Page>;
}

// ------------------------------------------------------------------ compliance & documents
export function Compliance() {
  const [tab, setTab] = useState("Dashboard");
  const dash = useLoad<any>(tab === "Dashboard" ? "/api/compliance/dashboard" : null);
  const tasks = useLoad<any[]>(tab === "Calendar" ? "/api/compliance/tasks" : null);
  const [ed, setEd] = useState<any>(null);
  const [regs, setRegs] = useState<any>(null);
  const uploadProof = async (file: File) => {
    const fd = new FormData(); fd.append("file", file); fd.append("title", `${ed.name} ${ed.period} acknowledgement`); fd.append("doc_type", "Statutory Return"); fd.append("entity_type", "compliance"); fd.append("entity_id", String(ed.id));
    const d: any = await run(() => api.form("/api/documents/upload", fd), "Proof uploaded");
    if (d) setEd({ ...ed, document_id: d.id });
  };
  const T = (rows: any[]) => <Table cols={[{ key: "due_date", label: "Due", type: "date" }, { key: "name", label: "Requirement" }, { key: "category", label: "Category" }, { key: "period", label: "Period" }, { key: "status", label: "Status", type: "badge" }, { key: "arn", label: "ARN / ack" }, { key: "overdue", label: "", render: (r) => r.overdue ? <span className="badge bad">Overdue</span> : "" }]} rows={rows} onRow={can("compliance:write") ? (r) => setEd({ ...r }) : undefined} />;
  return <Page title="Compliance" actions={can("compliance:write") && <Btn onClick={async () => { const fy = prompt("Financial year (e.g. 2026-27)"); if (fy) { const r: any = await run(() => api.post("/api/compliance/generate", { fy })); if (r) toast.ok(`${r.created} due dates created`); } }}>Generate calendar</Btn>}>
    <div className="warn-box">Due dates are defaults – verify against the latest notifications and extensions. A filing is marked complete only when you record the ARN/acknowledgement from the government portal and upload the proof.</div>
    <Tabs tabs={["Dashboard", "Calendar", "Requirements", "Statutory registers"]} value={tab} onChange={setTab} />
    {tab === "Dashboard" && dash.data && <>
      <div className="kpis small"><Kpi label="Overdue" value={dash.data.overdue.length} tone={dash.data.overdue.length ? "bad" : "good"} /><Kpi label="Due in 30 days" value={dash.data.due_30.length} /><Kpi label="Awaiting acknowledgement" value={dash.data.awaiting_ack.length} /><Kpi label="Licence / permit / insurance alerts" value={dash.data.document_alerts.length} /></div>
      <Card title="Overdue">{T(dash.data.overdue)}</Card><Card title="Due in the next 30 days">{T(dash.data.due_30)}</Card>
      <Card title="Vehicle & driver documents"><Table dense cols={[{ key: "severity", label: "", type: "badge" }, { key: "title", label: "Alert" }, { key: "body", label: "" }]} rows={dash.data.document_alerts} /></Card>
    </>}
    {tab === "Calendar" && T(tasks.data || [])}
    {tab === "Requirements" && <ResourcePage embedded name="compliance_rules" columns={["code", "name", "category", "frequency", "due_day", "due_month_offset", "applicable", "authority"]} />}
    {tab === "Statutory registers" && <ResourcePage embedded name="statutory_registers" columns={["name", "act", "description"]} rowActions={(r) => <Btn small onClick={async () => setRegs({ reg: r, entries: await api.get(`/api/registers/${r.id}/entries`), new: { entry_date: today(), data: {} } })}>Entries</Btn>} />}
    {ed && <Modal title={`${ed.name} – ${ed.period}`} onClose={() => setEd(null)} footer={<Btn kind="primary" onClick={async () => { if (await run(() => api.put(`/api/compliance/tasks/${ed.id}`, ed), "Saved")) { setEd(null); tasks.reload(); dash.reload(); } }}>Save</Btn>}>
      <p className="muted">Due {dt(ed.due_date)} · {ed.authority}</p>
      <Field label="Status"><select value={ed.status} onChange={(e) => setEd({ ...ed, status: e.target.value })}>{["Pending", "In Preparation", "Filed - Awaiting Ack", "Acknowledged", "Not Applicable"].map((s) => <option key={s}>{s}</option>)}</select></Field>
      <Field label="ARN / acknowledgement / challan ref (from portal)"><input value={ed.arn || ""} onChange={(e) => setEd({ ...ed, arn: e.target.value })} /></Field>
      <Field label="Filed on"><input type="date" value={ed.filed_on || ""} onChange={(e) => setEd({ ...ed, filed_on: e.target.value })} /></Field>
      <Field label="Amount paid ₹"><input type="number" value={ed.amount_paid || ""} onChange={(e) => setEd({ ...ed, amount_paid: e.target.value })} /></Field>
      <Field label="Acknowledgement proof">{ed.document_id ? <span>Uploaded (doc #{ed.document_id})</span> : <input type="file" onChange={(e) => e.target.files?.[0] && uploadProof(e.target.files[0])} />}</Field>
      <Field label="Remarks"><textarea value={ed.remarks || ""} onChange={(e) => setEd({ ...ed, remarks: e.target.value })} /></Field>
    </Modal>}
    {regs && <Modal wide title={regs.reg.name} onClose={() => setRegs(null)}>
      <Table dense cols={[{ key: "entry_date", label: "Date", type: "date" }, ...(regs.reg.columns || []).map((c: string) => ({ key: c, label: c, render: (r: any) => r.data?.[c] }))]} rows={regs.entries} />
      {can("compliance:write") && <div className="row gap wrap"><input type="date" value={regs.new.entry_date} onChange={(e) => setRegs({ ...regs, new: { ...regs.new, entry_date: e.target.value } })} />
        {(regs.reg.columns || []).map((c: string) => <input key={c} placeholder={c} value={regs.new.data[c] || ""} onChange={(e) => setRegs({ ...regs, new: { ...regs.new, data: { ...regs.new.data, [c]: e.target.value } } })} />)}
        <Btn onClick={async () => { if (await run(() => api.post(`/api/registers/${regs.reg.id}/entries`, regs.new), "Added")) setRegs({ ...regs, entries: await api.get(`/api/registers/${regs.reg.id}/entries`), new: { entry_date: today(), data: {} } }); }}>Add</Btn></div>}
    </Modal>}
  </Page>;
}

export function Documents() {
  const [sp] = useSearchParams();
  const [up, setUp] = useState<any>(null);
  const [vers, setVers] = useState<any>(null);
  const [k, setK] = useState(0);
  const DOC_TYPES = ["GST Certificate", "PAN", "RC Book", "Insurance", "Fitness Certificate", "National Permit", "State Permit", "Pollution Certificate", "Road Tax", "Driving Licence", "Aadhaar", "Customer Agreement", "Vendor Agreement", "LR", "POD", "Invoice", "E-way Bill", "Purchase Bill", "Receipt", "Photo", "Employee Document", "Statutory Return", "Other"];
  const filters: any = {};
  if (sp.get("entity_type")) filters.entity_type = sp.get("entity_type");
  if (sp.get("entity_id")) filters.entity_id = sp.get("entity_id");
  const send = async () => {
    const fd = new FormData();
    Object.entries(up).forEach(([key, v]: any) => v !== undefined && v !== null && v !== "" && fd.append(key, v));
    if (await run(() => api.form("/api/documents/upload", fd), "Uploaded")) { setUp(null); setK(k + 1); }
  };
  return <Page title="Documents" actions={can("documents:write") && <Btn kind="primary" onClick={() => setUp({ doc_type: "Other", ...filters })}>+ Upload</Btn>}>
    <ResourcePage key={k} embedded name="documents" filters={{ ...filters, is_deleted: false }} columns={["title", "doc_type", "entity_type", "entity_id", "doc_number", "expiry_date", "current_version"]}
      rowActions={(r) => <><Btn small onClick={() => download(`/api/documents/${r.id}/download`)}>Open</Btn><Btn small kind="ghost" onClick={async () => setVers({ doc: r, list: await api.get(`/api/documents/${r.id}/versions`) })}>Versions</Btn>
        {can("documents:write") && <label className="btn sm ghost">New version<input hidden type="file" onChange={async (e) => { const f = e.target.files?.[0]; if (!f) return; const fd = new FormData(); fd.append("file", f); fd.append("document_id", String(r.id)); if (await run(() => api.form("/api/documents/upload", fd), "New version uploaded")) setK(k + 1); }} /></label>}</>} />
    {up && <Modal title="Upload document" onClose={() => setUp(null)} footer={<Btn kind="primary" disabled={!up.file} onClick={send}>Upload</Btn>}>
      <div className="form-grid">
        <Field label="File"><input type="file" accept="image/*,application/pdf,.xlsx,.xls,.doc,.docx,.csv" capture="environment" onChange={(e) => setUp({ ...up, file: e.target.files?.[0] })} /></Field>
        <Field label="Title"><input value={up.title || ""} onChange={(e) => setUp({ ...up, title: e.target.value })} /></Field>
        <Field label="Type"><select value={up.doc_type} onChange={(e) => setUp({ ...up, doc_type: e.target.value })}>{DOC_TYPES.map((d) => <option key={d}>{d}</option>)}</select></Field>
        <Field label="Linked to"><select value={up.entity_type || ""} onChange={(e) => setUp({ ...up, entity_type: e.target.value, entity_id: "" })}><option value="">—</option>{["company", "vehicle", "driver", "customer", "vendor", "employee"].map((x) => <option key={x}>{x}</option>)}</select></Field>
        {up.entity_type && up.entity_type !== "company" && <Field label="Record"><RefSelect refName={{ vehicle: "vehicles", driver: "drivers", customer: "customers", vendor: "vendors", employee: "employees" }[up.entity_type as string] as string} value={up.entity_id ? Number(up.entity_id) : null} onChange={(v) => setUp({ ...up, entity_id: v })} /></Field>}
        <Field label="Document number"><input value={up.doc_number || ""} onChange={(e) => setUp({ ...up, doc_number: e.target.value })} /></Field>
        <Field label="Issue date"><input type="date" value={up.issue_date || ""} onChange={(e) => setUp({ ...up, issue_date: e.target.value })} /></Field>
        <Field label="Expiry date (alerts)"><input type="date" value={up.expiry_date || ""} onChange={(e) => setUp({ ...up, expiry_date: e.target.value })} /></Field>
      </div>
    </Modal>}
    {vers && <Modal title={`Versions – ${vers.doc.title}`} onClose={() => setVers(null)}>
      <Table dense cols={[{ key: "version", label: "Ver" }, { key: "file_name", label: "File" }, { key: "size_bytes", label: "Bytes", type: "number" }, { key: "uploaded_at", label: "Uploaded", type: "datetime" }, { key: "sha256", label: "SHA-256", render: (v) => <span className="mono tiny">{v.sha256.slice(0, 16)}…</span> }]} rows={vers.list} onRow={(v) => download(`/api/documents/${vers.doc.id}/download?version=${v.version}`)} />
    </Modal>}
  </Page>;
}

export { monthStart };
