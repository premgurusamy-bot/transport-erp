import React, { useEffect, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { openExternal } from "../lib/native";
import { api, can, qs } from "../lib/api";
import { dt, inr, num, today } from "../lib/format";
import { Badge, Btn, Card, Field, Modal, Page, Pager, ReasonModal, RefSelect, Search, Table, Tabs, download, run, toast, useLoad } from "../components/ui";

const EMPTY_ITEM = { description: "", hsn: "", packages: "", package_type: "", quantity: "", uom: "NOS", weight_kg: "", value: "" };

export function LRForm({ initial, onDone, onCancel }: { initial?: any; onDone: (lr: any) => void; onCancel: () => void }) {
  const [f, setF] = useState<any>({ lr_date: today(), load_type: "FTL", payment_terms: "To Be Billed", gst_paid_by: "Consignor", risk: "Owner's Risk", freight_mode: "contract", items: [{ ...EMPTY_ITEM }], delivery_points: [], freight_inputs: {}, ...initial });
  const [calc, setCalc] = useState<any>(null);
  const [calcErr, setCalcErr] = useState("");
  const trips = useLoad<any>(`/api/trips?open=1&limit=200`);
  const set = (k: string, v: any) => setF((x: any) => ({ ...x, [k]: v }));
  const cust = useLoad<any>(f.customer_id ? `/api/r/customers/${f.customer_id}` : null);
  useEffect(() => {
    const c = cust.data;
    if (c && !f.consignor_name) setF((x: any) => ({ ...x, consignor_name: c.legal_name || c.name, consignor_gstin: c.gstin || "", consignor_address: c.billing_address || "", consignor_phone: c.mobile || "" }));
  }, [cust.data]);
  const totals = f.items.reduce((a: any, i: any) => ({ packages: a.packages + Number(i.packages || 0), quantity: a.quantity + Number(i.quantity || 0), weight: a.weight + Number(i.weight_kg || 0), value: a.value + Number(i.value || 0) }), { packages: 0, quantity: 0, weight: 0, value: 0 });
  useEffect(() => {
    if (f.freight_mode !== "contract" || !f.customer_id) { setCalc(null); return; }
    const inputs = { weight_kg: totals.weight, quantity: totals.quantity, km: f.distance_km || 0, is_return: f.is_return, extra_stops: Math.max(0, f.delivery_points.length - 1), ...f.freight_inputs };
    const h = setTimeout(() => api.post("/api/freight/calculate", { customer_id: f.customer_id, route_id: f.route_id, date: f.lr_date, goods: f.items.map((i: any) => i.description).join(" "), inputs })
      .then((r) => { setCalc(r); setCalcErr(""); }).catch((e) => { setCalc(null); setCalcErr(e.message); }), 400);
    return () => clearTimeout(h);
  }, [f.customer_id, f.route_id, f.lr_date, f.freight_mode, f.distance_km, f.is_return, totals.weight, totals.quantity, f.delivery_points.length, JSON.stringify(f.freight_inputs)]);
  const item = (i: number, k: string, v: any) => set("items", f.items.map((x: any, j: number) => (j === i ? { ...x, [k]: v } : x)));
  const point = (i: number, k: string, v: any) => set("delivery_points", f.delivery_points.map((x: any, j: number) => (j === i ? { ...x, [k]: v } : x)));
  const submit = async () => {
    const payload = { ...f, goods_value: f.goods_value || totals.value };
    const r: any = await run(() => api.post("/api/lr", payload));
    if (r) { r.warnings?.forEach((w: string) => toast.info(w)); toast.ok(`LR ${r.lr.lr_no} generated`); onDone(r.lr); }
  };
  const inp = (k: string, type = "text") => <input type={type} value={f[k] ?? ""} onChange={(e) => set(k, type === "checkbox" ? e.target.checked : e.target.value)} />;
  return <div className="lr-form">
    <div className="form-grid">
      <Field label="Customer" required><RefSelect refName="customers" value={f.customer_id} onChange={(v) => setF({ ...f, customer_id: v, consignor_name: "" })} /></Field>
      <Field label="LR date" required>{inp("lr_date", "date")}</Field>
      <Field label="Trip (vehicle & driver come from the trip)"><select value={f.trip_id || ""} onChange={(e) => set("trip_id", e.target.value ? Number(e.target.value) : null)}><option value="">— no trip yet —</option>{(trips.data?.items || []).map((t: any) => <option key={t.id} value={t.id}>{t.trip_no} · {t.vehicle_no || "no vehicle"} · {t.from_place}→{t.to_place}</option>)}</select></Field>
      {!f.trip_id && <><Field label="Vehicle"><RefSelect refName="vehicles" value={f.vehicle_id} onChange={(v) => set("vehicle_id", v)} /></Field><Field label="Driver"><RefSelect refName="drivers" value={f.driver_id} onChange={(v) => set("driver_id", v)} /></Field></>}
      <Field label="Route"><RefSelect refName="routes" value={f.route_id} onChange={(v) => set("route_id", v)} /></Field>
      <Field label="From" required>{inp("from_place")}</Field>
      <Field label="To" required>{inp("to_place")}</Field>
      <Field label="Distance (km)">{inp("distance_km", "number")}</Field>
      <Field label="Load type"><select value={f.load_type} onChange={(e) => set("load_type", e.target.value)}><option>FTL</option><option>PTL</option></select></Field>
      <Field label="Return LR"><input type="checkbox" checked={!!f.is_return} onChange={(e) => set("is_return", e.target.checked)} /></Field>
    </div>
    <div className="grid2">
      <Card title="Consignor"><Field label="Name" required>{inp("consignor_name")}</Field><Field label="GSTIN">{inp("consignor_gstin")}</Field><Field label="Address"><textarea value={f.consignor_address || ""} onChange={(e) => set("consignor_address", e.target.value)} /></Field><Field label="Phone">{inp("consignor_phone")}</Field><Field label="Loading address (if different)"><textarea value={f.loading_address || ""} onChange={(e) => set("loading_address", e.target.value)} /></Field></Card>
      <Card title="Consignee"><Field label="Name" required>{inp("consignee_name")}</Field><Field label="GSTIN">{inp("consignee_gstin")}</Field><Field label="Address"><textarea value={f.consignee_address || ""} onChange={(e) => set("consignee_address", e.target.value)} /></Field><Field label="Phone">{inp("consignee_phone")}</Field><Field label="Delivery address (if different)"><textarea value={f.delivery_address || ""} onChange={(e) => set("delivery_address", e.target.value)} /></Field></Card>
    </div>
    <Card title="Goods" actions={<Btn small onClick={() => set("items", [...f.items, { ...EMPTY_ITEM }])}>+ Line</Btn>}>
      <div className="table-wrap"><table className="tbl dense edit"><thead><tr><th>Description</th><th>HSN</th><th>Pkgs</th><th>Pkg type</th><th>Qty</th><th>Unit</th><th>Weight kg</th><th>Value ₹</th><th /></tr></thead><tbody>
        {f.items.map((it: any, i: number) => <tr key={i}>{["description", "hsn", "packages", "package_type", "quantity", "uom", "weight_kg", "value"].map((k) => <td key={k}><input type={["packages", "quantity", "weight_kg", "value"].includes(k) ? "number" : "text"} value={it[k]} onChange={(e) => item(i, k, e.target.value)} /></td>)}<td><button className="x" onClick={() => set("items", f.items.filter((_: any, j: number) => j !== i))}>×</button></td></tr>)}
      </tbody><tfoot><tr><td>Total</td><td /><td>{totals.packages}</td><td /><td>{num(totals.quantity)}</td><td /><td>{num(totals.weight)}</td><td>{inr(totals.value)}</td><td /></tr></tfoot></table></div>
    </Card>
    <Card title="Multiple delivery points (optional)" actions={<Btn small onClick={() => set("delivery_points", [...f.delivery_points, { consignee_name: "", address: "", contact: "", packages: "" }])}>+ Drop point</Btn>}>
      {f.delivery_points.map((p: any, i: number) => <div className="row gap" key={i}>{["consignee_name", "address", "contact", "packages"].map((k) => <input key={k} placeholder={k.replace("_", " ")} value={p[k]} onChange={(e) => point(i, k, e.target.value)} />)}<button className="x" onClick={() => set("delivery_points", f.delivery_points.filter((_: any, j: number) => j !== i))}>×</button></div>)}
    </Card>
    <div className="grid2">
      <Card title="Documents">
        <div className="form-grid">
          <Field label="Goods value ₹" help="Defaults to total of lines">{inp("goods_value", "number")}</Field>
          <Field label="Customer invoice no">{inp("customer_invoice_no")}</Field>
          <Field label="Invoice date">{inp("customer_invoice_date", "date")}</Field>
          <Field label="E-way bill no (12 digits)">{inp("eway_bill_no")}</Field>
          <Field label="E-way bill valid until">{inp("eway_valid_until", "datetime-local")}</Field>
          <Field label="E-invoice ref">{inp("einvoice_ref")}</Field>
        </div>
      </Card>
      <Card title="Freight">
        <div className="form-grid">
          <Field label="Freight from"><select value={f.freight_mode} onChange={(e) => set("freight_mode", e.target.value)}><option value="contract">Rate contract</option><option value="manual">Manual entry</option></select></Field>
          <Field label="Payment terms"><select value={f.payment_terms} onChange={(e) => set("payment_terms", e.target.value)}><option>To Be Billed</option><option>Paid</option><option>To Pay</option></select></Field>
          <Field label="GST payable by"><select value={f.gst_paid_by} onChange={(e) => set("gst_paid_by", e.target.value)}><option>Consignor</option><option>Consignee</option><option>Transporter</option></select></Field>
          <Field label="Risk"><select value={f.risk} onChange={(e) => set("risk", e.target.value)}><option>Owner's Risk</option><option>Carrier's Risk</option></select></Field>
          {f.freight_mode === "manual" ? <>
            <Field label="Basic freight ₹" required>{inp("basic_freight", "number")}</Field><Field label="Loading ₹">{inp("loading_charges", "number")}</Field><Field label="Unloading ₹">{inp("unloading_charges", "number")}</Field>
            <Field label="Reason for manual rate">{inp("manual_reason")}</Field>
          </> : <>
            {["waiting_hours", "detention_days", "trips", "turns", "loads"].map((k) => <Field key={k} label={k.replace("_", " ")}><input type="number" value={f.freight_inputs[k] ?? ""} onChange={(e) => set("freight_inputs", { ...f.freight_inputs, [k]: e.target.value })} /></Field>)}
          </>}
          <Field label="Other charges ₹">{inp("other_charges", "number")}</Field>
          <Field label="Other charges note">{inp("other_charges_note")}</Field>
          <Field label="Advance received ₹">{inp("advance_freight", "number")}</Field>
        </div>
        {f.freight_mode === "contract" && (calc ? <div className="calc"><div className="muted small">Contract {calc.contract_no} v{calc.contract_version}: {calc.contract_name}</div>{calc.lines.map((l: any, i: number) => <div key={i} className="row between"><span>{l.label}</span><b>{inr(l.amount)}</b></div>)}<div className="row between total"><span>Freight</span><b>{inr(Number(calc.total) + Number(f.other_charges || 0))}</b></div></div> : calcErr && <div className="warn-box">{calcErr}</div>)}
      </Card>
    </div>
    <div className="form-grid">
      <Field label="Remarks" wide><textarea value={f.remarks || ""} onChange={(e) => set("remarks", e.target.value)} /></Field>
      <Field label="Customer authorisation (name / PO / email ref)">{inp("customer_authorization")}</Field>
    </div>
    <div className="row gap end"><Btn onClick={onCancel}>Cancel</Btn><Btn kind="primary" onClick={submit}>Generate LR</Btn></div>
  </div>;
}

export function LRDetail({ id, onClose }: { id: number; onClose: () => void }) {
  const { data: lr, reload } = useLoad<any>(`/api/lr/${id}`);
  const [modal, setModal] = useState<string | null>(null);
  const [form, setForm] = useState<any>({});
  if (!lr) return null;
  const share = async (channel: string) => {
    const r: any = await run(() => api.post(`/api/lr/${id}/share`, { channel, to: form.to }));
    if (r?.url) openExternal(r.url);
    else if (r) r.status === "sent" ? toast.ok("Sent") : toast.err(r.error || r.status);
  };
  const uploadPod = async (file: File) => {
    const fd = new FormData();
    fd.append("file", file); fd.append("title", `POD ${lr.lr_no}`); fd.append("doc_type", "POD"); fd.append("entity_type", "consignment"); fd.append("entity_id", String(lr.id)); fd.append("doc_number", lr.lr_no);
    const d: any = await run(() => api.form("/api/documents/upload", fd));
    if (d && await run(() => api.post(`/api/lr/${id}/pod`, { document_id: d.id }), "POD recorded")) reload();
  };
  return <Modal wide title={`LR ${lr.lr_no}`} onClose={onClose} footer={<Btn onClick={onClose}>Close</Btn>}>
    <div className="row gap wrap">
      <Badge v={lr.status} />{lr.revision > 0 && <span className="badge">Rev {lr.revision}</span>}
      <div className="grow" />
      <Btn small onClick={() => download(`/api/lr/${id}/pdf`)}>PDF (all copies)</Btn>
      <Btn small onClick={() => download(`/api/lr/${id}/pdf?copy=first`)}>PDF single</Btn>
      <Btn small onClick={() => download(`/api/lr/${id}/pdf?fmt=thermal`)}>Thermal 80mm</Btn>
      <Btn small onClick={() => setModal("share")}>Share</Btn>
      {can("lr:write") && lr.status !== "Cancelled" && <>
        <Btn small onClick={() => { setForm({ ewb_no: lr.eway_bill_no || "", vehicle_no: lr.vehicle_no || "" }); setModal("ewb"); }}>E-way bill</Btn>
        {!lr.delivered_at && <Btn small onClick={() => { setForm({}); setModal("deliver"); }}>Mark delivered</Btn>}
        {!lr.pod_received_at && <label className="btn sm">Upload POD<input hidden type="file" accept="image/*,application/pdf" capture="environment" onChange={(e) => e.target.files?.[0] && uploadPod(e.target.files[0])} /></label>}
      </>}
      {can("lr:amend") && !lr.invoice_id && lr.status !== "Cancelled" && <Btn small onClick={() => { setForm({ changes: {}, reason: "", authorized_by: "" }); setModal("amend"); }}>Amend</Btn>}
      {can("lr:cancel") && lr.status !== "Cancelled" && !lr.invoice_id && <Btn small kind="danger" onClick={() => setModal("cancel")}>Cancel LR</Btn>}
    </div>
    <div className="kv">
      {[["Date", dt(lr.lr_date)], ["Customer", lr.customer_name], ["Trip", lr.trip_no], ["Route", `${lr.from_place} → ${lr.to_place}`], ["Vehicle", lr.vehicle_no], ["Driver", `${lr.driver_name || ""} ${lr.driver_mobile || ""}`], ["Consignor", lr.consignor_name], ["Consignee", lr.consignee_name],
        ["Packages / weight", `${lr.packages} / ${num(lr.weight_kg)} kg`], ["Goods value", inr(lr.goods_value)], ["E-way bill", `${lr.eway_bill_no || "-"} ${lr.eway_valid_until ? "valid till " + dt(lr.eway_valid_until) : ""}`], ["Freight basis", lr.freight_basis],
        ["Total freight", inr(lr.total_freight)], ["Advance", inr(lr.advance_freight)], ["Balance", inr(lr.balance_freight)], ["Payment terms", lr.payment_terms], ["Delivered", lr.delivered_at ? `${dt(lr.delivered_at)} to ${lr.receiver_name || ""}` : ""], ["POD", lr.pod_received_at ? dt(lr.pod_received_at) : "Pending"],
        ["Cancelled", lr.cancelled_at ? `${dt(lr.cancelled_at)} – ${lr.cancel_reason}` : ""]].filter(([, v]) => v).map(([k, v]) => <div key={k as string}><span>{k}</span><b>{v}</b></div>)}
    </div>
    <h4>Freight calculation</h4>
    <Table dense cols={[{ key: "label", label: "Line" }, { key: "amount", label: "Amount", type: "money" }]} rows={lr.freight_breakdown?.lines || []} />
    <h4>Goods</h4>
    <Table dense cols={[{ key: "description", label: "Description" }, { key: "hsn", label: "HSN" }, { key: "packages", label: "Pkgs", type: "number" }, { key: "quantity", label: "Qty", type: "number" }, { key: "weight_kg", label: "Kg", type: "number" }, { key: "value", label: "Value", type: "money" }]} rows={lr.items} />
    {lr.delivery_points.length > 0 && <><h4>Delivery points</h4><Table dense cols={[{ key: "sequence", label: "#" }, { key: "consignee_name", label: "Consignee" }, { key: "address", label: "Address" }, { key: "status", label: "Status", type: "badge" }]} rows={lr.delivery_points} /></>}
    {lr.documents.length > 0 && <><h4>Documents</h4><Table dense cols={[{ key: "doc_type", label: "Type" }, { key: "title", label: "Title" }]} rows={lr.documents} onRow={(d) => download(`/api/documents/${d.id}/download`)} /></>}
    {lr.amendments.length > 0 && <><h4>Amendment history</h4><Table dense cols={[{ key: "at", label: "When", type: "datetime" }, { key: "revision", label: "Rev" }, { key: "authorized_by", label: "Authorised by" }, { key: "reason", label: "Reason" }, { key: "after", label: "Changed", render: (a) => Object.keys(a.after || {}).join(", ") }]} rows={lr.amendments} /></>}
    {modal === "cancel" && <ReasonModal title={`Cancel LR ${lr.lr_no}`} onClose={() => setModal(null)} onSubmit={async (reason) => { const r = await run(() => api.post(`/api/lr/${id}/cancel`, { reason }), "LR cancelled"); reload(); return r; }} />}
    {modal === "share" && <Modal title="Share LR" onClose={() => setModal(null)}>
      <Field label="Mobile / email (blank = customer's)"><input value={form.to || ""} onChange={(e) => setForm({ ...form, to: e.target.value })} /></Field>
      <div className="row gap"><Btn onClick={() => share("whatsapp_link")}>WhatsApp (click-to-chat)</Btn><Btn onClick={() => share("whatsapp")}>WhatsApp Business API</Btn><Btn onClick={() => share("email")}>Email PDF</Btn></div>
    </Modal>}
    {modal === "deliver" && <Modal title="Delivery confirmation" onClose={() => setModal(null)} footer={<Btn kind="primary" onClick={async () => { if (await run(() => api.post(`/api/lr/${id}/deliver`, form), "Delivered")) { setModal(null); reload(); } }}>Save</Btn>}>
      <div className="form-grid">{["receiver_name", "receiver_phone", "shortage_qty", "damage_qty"].map((k) => <Field key={k} label={k.replace("_", " ")}><input value={form[k] || ""} onChange={(e) => setForm({ ...form, [k]: e.target.value })} /></Field>)}<Field label="Delivered at"><input type="datetime-local" value={form.at || ""} onChange={(e) => setForm({ ...form, at: e.target.value })} /></Field><Field label="Remarks" wide><textarea value={form.remarks || ""} onChange={(e) => setForm({ ...form, remarks: e.target.value })} /></Field></div>
    </Modal>}
    {modal === "ewb" && <Modal title="E-way bill" onClose={() => setModal(null)} footer={<><Btn onClick={() => download(`/api/lr/${id}/ewaybill-json`, `EWB_${lr.lr_no.replace(/\//g, "-")}.json`)}>Download JSON for portal</Btn><Btn kind="primary" onClick={async () => { if (await run(() => api.post(`/api/lr/${id}/ewaybill`, form), "E-way bill recorded")) { setModal(null); reload(); } }}>Save</Btn></>}>
      <p className="muted small">E-way bills are generated on the government portal (or through an authorised GSP once configured). Record the number here; validity is monitored and alerts are raised before expiry. Changing the vehicle records a Part-B update.</p>
      <div className="form-grid">
        <Field label="E-way bill no"><input value={form.ewb_no || ""} onChange={(e) => setForm({ ...form, ewb_no: e.target.value })} /></Field>
        <Field label="Generated on"><input type="datetime-local" value={form.ewb_date || ""} onChange={(e) => setForm({ ...form, ewb_date: e.target.value })} /></Field>
        <Field label="Valid until (blank = calculate by distance)"><input type="datetime-local" value={form.valid_until || ""} onChange={(e) => setForm({ ...form, valid_until: e.target.value })} /></Field>
        <Field label="Vehicle (Part-B)"><input value={form.vehicle_no || ""} onChange={(e) => setForm({ ...form, vehicle_no: e.target.value.toUpperCase() })} /></Field>
        <Field label="Reason for vehicle change"><input value={form.reason || ""} onChange={(e) => setForm({ ...form, reason: e.target.value })} /></Field>
        <Field label="Validity extended"><input type="checkbox" checked={!!form.extended} onChange={(e) => setForm({ ...form, extended: e.target.checked })} /></Field>
      </div>
    </Modal>}
    {modal === "amend" && <Modal wide title={`Amend LR ${lr.lr_no}`} onClose={() => setModal(null)} footer={<Btn kind="primary" onClick={async () => { if (await run(() => api.post(`/api/lr/${id}/amend`, form), "LR amended")) { setModal(null); reload(); } }}>Save amendment</Btn>}>
      <p className="muted small">Only changed fields are saved. Freight is recalculated. Before/after values are kept in the amendment history.</p>
      <div className="form-grid">
        {["consignee_name", "consignee_address", "to_place", "delivery_address", "customer_invoice_no", "goods_value", "weight_kg", "packages", "quantity", "distance_km", "other_charges", "advance_freight", "remarks"].map((k) => <Field key={k} label={k.replace(/_/g, " ")}><input placeholder={String(lr[k] ?? "")} value={form.changes[k] ?? ""} onChange={(e) => setForm({ ...form, changes: { ...form.changes, [k]: e.target.value } })} /></Field>)}
        <Field label="Vehicle"><RefSelect refName="vehicles" value={form.changes.vehicle_id} onChange={(v) => setForm({ ...form, changes: { ...form.changes, vehicle_id: v } })} /></Field>
        <Field label="Authorised by" required><input value={form.authorized_by} onChange={(e) => setForm({ ...form, authorized_by: e.target.value })} /></Field>
        <Field label="Reason" wide required><textarea value={form.reason} onChange={(e) => setForm({ ...form, reason: e.target.value })} /></Field>
      </div>
    </Modal>}
  </Modal>;
}

export default function LRPage() {
  const [sp, setSp] = useSearchParams();
  const [q, setQ] = useState("");
  const [status, setStatus] = useState("");
  const [offset, setOffset] = useState(0);
  const [creating, setCreating] = useState(sp.get("new") === "1");
  const list = useLoad<any>(`/api/lr${qs({ q, status, offset, limit: 50, trip_id: sp.get("trip_id") })}`);
  const open = sp.get("id");
  return <Page title="LR / Consignments" actions={can("lr:write") && !creating && <Btn kind="primary" onClick={() => setCreating(true)}>+ New LR</Btn>}>
    {creating ? <Card title="New lorry receipt"><LRForm initial={sp.get("trip_id") ? { trip_id: Number(sp.get("trip_id")) } : {}} onCancel={() => setCreating(false)} onDone={(lr) => { setCreating(false); list.reload(); setSp({ id: String(lr.id) }); }} /></Card> : <>
      <div className="toolbar"><Search value={q} onChange={setQ} placeholder="LR no, consignor, consignee, vehicle, e-way bill…" />
        <select value={status} onChange={(e) => setStatus(e.target.value)}><option value="">All statuses</option>{["Booked", "Loaded", "In Transit", "Delivered", "POD Received", "Billed", "Cancelled"].map((s) => <option key={s}>{s}</option>)}</select></div>
      <Table cols={[{ key: "lr_no", label: "LR No" }, { key: "lr_date", label: "Date", type: "date" }, { key: "customer_name", label: "Customer" }, { key: "from_place", label: "From" }, { key: "to_place", label: "To" }, { key: "vehicle_no", label: "Vehicle" }, { key: "packages", label: "Pkgs", type: "number" }, { key: "weight_kg", label: "Kg", type: "number" }, { key: "total_freight", label: "Freight", type: "money" }, { key: "eway_bill_no", label: "EWB" }, { key: "status", label: "Status", type: "badge" }]}
        rows={list.data?.items || []} onRow={(r) => setSp({ id: String(r.id) })} />
      <Pager total={list.data?.total || 0} limit={50} offset={offset} onChange={setOffset} />
    </>}
    {open && <LRDetail id={Number(open)} onClose={() => { setSp({}); list.reload(); }} />}
  </Page>;
}

export { Tabs };
