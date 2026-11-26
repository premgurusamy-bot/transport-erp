import React, { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api, auth, qs } from "../lib/api";
import { dt, fyStart, inr, today } from "../lib/format";
import { getLang, setLang, t } from "../lib/i18n";
import { ThemePicker } from "../components/Layout";
import { Badge, Btn, Card, Field, Kpi, Modal, Search, Table, Tabs, download, run, toast, useLoad } from "../components/ui";

function Shell({ title, children }: { title: string; children: React.ReactNode }) {
  const nav = useNavigate();
  const [, force] = useState(0);
  return <div className="portal">
    <header className="top"><img src="/api/company/logo" alt="" className="mini-logo" onError={(e) => ((e.target as HTMLImageElement).style.display = "none")} /><b>{title}</b><div className="grow" />
      <select value={getLang()} onChange={(e) => { setLang(e.target.value); force((x) => x + 1); }}><option value="en">EN</option><option value="ta">த</option></select>
      <ThemePicker />
      <button className="btn ghost sm" onClick={() => nav("/profile")}>{auth.user?.full_name}</button>
      <button className="btn ghost sm" onClick={async () => { await api.post("/api/auth/logout").catch(() => {}); auth.clear(); nav("/login"); }}>{t("Sign out")}</button></header>
    <main className="content">{children}</main>
  </div>;
}

// ------------------------------------------------------------------ customer portal
export function CustomerPortal() {
  const [tab, setTab] = useState("Shipments");
  const sum = useLoad<any>("/api/portal/summary");
  const [q, setQ] = useState("");
  const ships = useLoad<any[]>(tab === "Shipments" ? `/api/portal/shipments${qs({ q })}` : null);
  const invs = useLoad<any[]>(tab === "Invoices" ? "/api/portal/invoices" : null);
  const pays = useLoad<any[]>(tab === "Payments" ? "/api/portal/payments" : null);
  const books = useLoad<any[]>(tab === "Book vehicle" ? "/api/portal/bookings" : null);
  const comps = useLoad<any[]>(tab === "Complaints" ? "/api/portal/complaints" : null);
  const [st, setSt] = useState({ start: fyStart(), end: today() });
  const stmt = useLoad<any>(tab === "Statement" ? `/api/portal/statement${qs(st)}` : null);
  const [bk, setBk] = useState<any>({ required_date: today(), vehicles_required: 1 });
  const [cp, setCp] = useState<any>({});
  const s = sum.data;
  return <Shell title={s?.customer || "Customer portal"}>
    {s && <div className="kpis small"><Kpi label="Outstanding" value={inr(s.outstanding)} /><Kpi label="In transit" value={s.in_transit} /><Kpi label="Delivered (30 days)" value={s.delivered_30d} /><Kpi label="Open bookings" value={s.open_bookings} /></div>}
    <Tabs tabs={["Shipments", "Book vehicle", "Invoices", "Payments", "Statement", "Complaints"]} value={tab} onChange={setTab} />
    {tab === "Shipments" && <><div className="toolbar"><Search value={q} onChange={setQ} placeholder="LR / invoice / consignee" /></div>
      <Table cols={[{ key: "lr_no", label: "LR" }, { key: "lr_date", label: "Date", type: "date" }, { key: "to", label: "To" }, { key: "consignee", label: "Consignee" }, { key: "vehicle_no", label: "Vehicle" }, { key: "status", label: "Status", type: "badge" }, { key: "expected_delivery_at", label: "Expected", type: "datetime" }, { key: "delivered_at", label: "Delivered", type: "datetime" },
        { key: "x", label: "", render: (l) => <div className="row gap"><Btn small onClick={() => download(`/api/portal/lr/${l.id}/pdf`)}>LR</Btn>{l.pod_available && <Btn small onClick={() => download(`/api/portal/lr/${l.id}/pod`)}>POD</Btn>}</div> }]} rows={ships.data || []} /></>}
    {tab === "Book vehicle" && <div className="grid2">
      <Card title="Request transport">
        <Field label="Pickup / loading address"><textarea value={bk.pickup_address || ""} onChange={(e) => setBk({ ...bk, pickup_address: e.target.value })} /></Field>
        <Field label="Delivery address"><textarea value={bk.drop_address || ""} onChange={(e) => setBk({ ...bk, drop_address: e.target.value })} /></Field>
        <div className="form-grid">
          <Field label="Vehicle required on"><input type="date" min={today()} value={bk.required_date} onChange={(e) => setBk({ ...bk, required_date: e.target.value })} /></Field>
          <Field label="Vehicle type"><select value={bk.vehicle_type || ""} onChange={(e) => setBk({ ...bk, vehicle_type: e.target.value })}><option value="">Any</option>{["Trailer (40 ft)", "Trailer (32 ft)", "Container (20 ft)", "Container (32 ft)", "Open Body Truck", "Closed Body Truck", "Multi-Axle Truck", "LCV / Tempo", "Car Carrier"].map((v) => <option key={v}>{v}</option>)}</select></Field>
          <Field label="No. of vehicles"><input type="number" min={1} value={bk.vehicles_required} onChange={(e) => setBk({ ...bk, vehicles_required: e.target.value })} /></Field>
          <Field label="Goods"><input value={bk.goods_description || ""} onChange={(e) => setBk({ ...bk, goods_description: e.target.value })} /></Field>
          <Field label="Approx. weight (kg)"><input type="number" value={bk.weight_kg || ""} onChange={(e) => setBk({ ...bk, weight_kg: e.target.value })} /></Field>
          <Field label="Contact at site"><input value={bk.contact_person || ""} onChange={(e) => setBk({ ...bk, contact_person: e.target.value })} /></Field>
          <Field label="Contact phone"><input value={bk.contact_phone || ""} onChange={(e) => setBk({ ...bk, contact_phone: e.target.value })} /></Field>
        </div>
        <Field label="Remarks"><textarea value={bk.remarks || ""} onChange={(e) => setBk({ ...bk, remarks: e.target.value })} /></Field>
        <Btn kind="primary" onClick={async () => { const r: any = await run(() => api.post("/api/portal/bookings", bk)); if (r) { toast.ok(`Booking ${r.booking_no} sent`); setBk({ required_date: today(), vehicles_required: 1 }); books.reload(); } }}>Submit request</Btn>
      </Card>
      <Card title="My bookings"><Table dense cols={[{ key: "booking_no", label: "No" }, { key: "required_date", label: "Required", type: "date" }, { key: "vehicle_type", label: "Vehicle" }, { key: "status", label: "Status", type: "badge" }]} rows={books.data || []} /></Card>
    </div>}
    {tab === "Invoices" && <Table cols={[{ key: "invoice_no", label: "Invoice" }, { key: "doc_type", label: "Type" }, { key: "date", label: "Date", type: "date" }, { key: "due_date", label: "Due", type: "date" }, { key: "total", label: "Total", type: "money" }, { key: "balance", label: "Balance", type: "money" }, { key: "status", label: "Status", type: "badge" }, { key: "x", label: "", render: (i) => <Btn small onClick={() => download(`/api/portal/invoices/${i.id}/pdf`)}>PDF</Btn> }]} rows={invs.data || []} />}
    {tab === "Payments" && <Table cols={[{ key: "date", label: "Date", type: "date" }, { key: "receipt_no", label: "Receipt" }, { key: "amount", label: "Amount", type: "money" }, { key: "reference", label: "Reference" }, { key: "status", label: "Status", type: "badge" }]} rows={pays.data || []} />}
    {tab === "Statement" && <Card title="Account statement" actions={<><Btn small onClick={() => download(`/api/portal/statement${qs({ ...st, format: "pdf" })}`)}>PDF</Btn><Btn small onClick={() => download(`/api/portal/statement${qs({ ...st, format: "xlsx" })}`)}>Excel</Btn></>}>
      <div className="row gap"><Field label="From"><input type="date" value={st.start} onChange={(e) => setSt({ ...st, start: e.target.value })} /></Field><Field label="To"><input type="date" value={st.end} onChange={(e) => setSt({ ...st, end: e.target.value })} /></Field></div>
      {stmt.data && <Table dense cols={stmt.data.columns} rows={stmt.data.rows} totals={stmt.data.totals} />}
    </Card>}
    {tab === "Complaints" && <div className="grid2">
      <Card title="Raise a complaint"><Field label="Subject"><input value={cp.subject || ""} onChange={(e) => setCp({ ...cp, subject: e.target.value })} /></Field><Field label="Details"><textarea rows={4} value={cp.description || ""} onChange={(e) => setCp({ ...cp, description: e.target.value })} /></Field>
        <Btn kind="primary" onClick={async () => { const r: any = await run(() => api.post("/api/portal/complaints", cp)); if (r) { toast.ok(`Complaint ${r.complaint_no} registered`); setCp({}); comps.reload(); } }}>Submit</Btn></Card>
      <Card title="My complaints"><Table dense cols={[{ key: "complaint_no", label: "No" }, { key: "subject", label: "Subject" }, { key: "status", label: "Status", type: "badge" }, { key: "response", label: "Response" }]} rows={comps.data || []} /></Card>
    </div>}
  </Shell>;
}

// ------------------------------------------------------------------ driver app
function useLocationSharing(enabled: boolean) {
  const watch = useRef<number | null>(null);
  const last = useRef(0);
  useEffect(() => {
    if (!enabled || !("geolocation" in navigator)) return;
    watch.current = navigator.geolocation.watchPosition((p) => {
      if (Date.now() - last.current < 120000) return; // at most every 2 minutes
      last.current = Date.now();
      api.post("/api/driver/location", { lat: p.coords.latitude, lng: p.coords.longitude, accuracy: p.coords.accuracy }).catch(() => {});
    }, () => {}, { enableHighAccuracy: true, maximumAge: 60000 });
    return () => { if (watch.current !== null) navigator.geolocation.clearWatch(watch.current); };
  }, [enabled]);
}

export function DriverApp() {
  const me = useLoad<any>("/api/driver/me");
  const trips = useLoad<any[]>("/api/driver/trips");
  const [open, setOpen] = useState<number | null>(null);
  const active = (trips.data || []).some((t) => ["Loading", "Dispatched", "In Transit"].includes(t.stage));
  useLocationSharing(!!me.data?.gps_consent && active);
  return <Shell title={t("My trips")}>
    {me.data && <Card>
      <div className="row between"><div><b>{me.data.name}</b><div className="small muted">DL {me.data.licence_no} · valid till {dt(me.data.licence_expiry)}</div></div>
        <label className="row gap small"><input type="checkbox" checked={!!me.data.gps_consent} onChange={async (e) => { if (await run(() => api.post("/api/driver/consent", { consent: e.target.checked }), e.target.checked ? "Location sharing on during trips" : "Location sharing off")) me.reload(); }} />Share my location during trips</label></div>
      <p className="tiny muted">Location is sent only while a trip is active and only if you tick this box. You can switch it off any time.</p>
    </Card>}
    <div className="dcards">{(trips.data || []).map((tr) => <div key={tr.id} className="dcard" onClick={() => setOpen(tr.id)}>
      <div className="row between"><b>{tr.trip_no}</b><Badge v={tr.stage} /></div><div>{tr.from_place} → {tr.to_place}</div><div className="small muted">{tr.vehicle_no} · {dt(tr.trip_date)}</div></div>)}
      {trips.data?.length === 0 && <div className="empty-box">No trips assigned</div>}</div>
    {open && <DriverTrip id={open} onClose={() => { setOpen(null); trips.reload(); }} />}
  </Shell>;
}

function DriverTrip({ id, onClose }: { id: number; onClose: () => void }) {
  const { data: tr, reload } = useLoad<any>(`/api/driver/trips/${id}`);
  const [m, setM] = useState<string | null>(null);
  const [f, setF] = useState<any>({});
  if (!tr) return null;
  const pos = (): Promise<any> => new Promise((res) => navigator.geolocation ? navigator.geolocation.getCurrentPosition((p) => res({ lat: p.coords.latitude, lng: p.coords.longitude }), () => res({}), { timeout: 8000 }) : res({}));
  const stage = async (s: string, extra: any = {}) => { const g = await pos(); if (await run(() => api.post(`/api/driver/trips/${id}/stage`, { stage: s, ...extra, ...g }), "Updated")) { setM(null); reload(); } };
  const upload = async (url: string, fields: Record<string, string>, file: File) => {
    const fd = new FormData(); Object.entries(fields).forEach(([k, v]) => fd.append(k, v)); fd.append("file", file);
    if (await run(() => api.form(url, fd), "Uploaded")) reload();
  };
  return <Modal title={tr.trip_no} onClose={onClose}>
    <div className="kv"><div><span>Route</span><b>{tr.from_place} → {tr.to_place}</b></div>{tr.route && <div><span>Via</span><b>{tr.route.via || "-"} · {tr.route.distance_km} km</b></div>}<div><span>Vehicle</span><b>{tr.vehicle_no}</b></div><div><span>Stage</span><b><Badge v={tr.stage} /></b></div><div><span>Customer</span><b>{tr.customer_name}</b></div></div>
    <div className="dactions">
      {["LR Generated", "Driver Allocated"].includes(tr.stage) && <Btn kind="primary" onClick={() => stage("Loading")}>{t("Loading done")}</Btn>}
      {["LR Generated", "Loading"].includes(tr.stage) && <Btn kind="primary" onClick={() => { setF({ start_km: "" }); setM("start"); }}>{t("Start trip")}</Btn>}
      {["Dispatched", "In Transit"].includes(tr.stage) && <Btn kind="primary" onClick={() => { setF({ receiver_name: "" }); setM("deliver"); }}>{t("Delivered")}</Btn>}
      {!["Closed", "Billed", "Settled", "Cancelled"].includes(tr.stage) && <><Btn onClick={() => { setF({ category: "Toll", expense_date: today() }); setM("expense"); }}>{t("Expense")}</Btn><Btn onClick={() => { setF({ category: "Diesel", full_tank: true }); setM("fuel"); }}>Diesel</Btn><Btn kind="danger" onClick={() => { setF({ kind: "Breakdown" }); setM("incident"); }}>{t("Incident")}</Btn>
        <label className="btn">Receipt photo<input hidden type="file" accept="image/*" capture="environment" onChange={(e) => e.target.files?.[0] && upload(`/api/driver/trips/${id}/document`, { kind: "Receipt" }, e.target.files[0])} /></label></>}
    </div>
    <h4>LRs</h4>
    {tr.lrs.map((l: any) => <div key={l.id} className="dcard">
      <div className="row between"><b>{l.lr_no}</b><Badge v={l.status} /></div><div className="small">{l.consignee_name} · {l.delivery_address || l.consignee_address || l.to_place}</div><div className="small">{l.packages} pkgs · {l.weight_kg} kg · {l.consignee_phone && <a href={`tel:${l.consignee_phone}`}>{l.consignee_phone}</a>}</div>
      {!l.pod_received_at && l.status !== "Cancelled" && <label className="btn sm primary">{t("Upload POD")}<input hidden type="file" accept="image/*,application/pdf" capture="environment" onChange={(e) => e.target.files?.[0] && upload(`/api/driver/trips/${id}/pod`, { lr_id: String(l.id), receiver_name: f.receiver_name || "" }, e.target.files[0])} /></label>}
    </div>)}
    {m === "start" && <Modal title={t("Start trip")} onClose={() => setM(null)} footer={<Btn kind="primary" onClick={() => stage("Dispatched", { start_km: f.start_km, odometer: f.start_km })}>Start</Btn>}><Field label={t("Odometer")}><input type="number" inputMode="numeric" value={f.start_km} onChange={(e) => setF({ ...f, start_km: e.target.value })} /></Field></Modal>}
    {m === "deliver" && <Modal title={t("Delivered")} onClose={() => setM(null)} footer={<Btn kind="primary" onClick={() => stage("Delivered", f)}>Confirm</Btn>}><Field label="Received by (name)"><input value={f.receiver_name} onChange={(e) => setF({ ...f, receiver_name: e.target.value })} /></Field><Field label="Receiver phone"><input inputMode="tel" value={f.receiver_phone || ""} onChange={(e) => setF({ ...f, receiver_phone: e.target.value })} /></Field><Field label="Remarks"><textarea value={f.remarks || ""} onChange={(e) => setF({ ...f, remarks: e.target.value })} /></Field></Modal>}
    {m === "expense" && <Modal title={t("Expense")} onClose={() => setM(null)} footer={<Btn kind="primary" onClick={async () => { if (await run(() => api.post(`/api/driver/trips/${id}/expense`, f), "Expense sent for approval")) { setM(null); reload(); } }}>Save</Btn>}>
      <Field label="Type"><select value={f.category} onChange={(e) => setF({ ...f, category: e.target.value })}>{["Toll", "Parking", "RTO / Check Post", "Loading", "Unloading", "Food", "Police / Fine", "Repair on Road", "Tyre Puncture", "Weighbridge", "Phone", "Other"].map((c) => <option key={c}>{c}</option>)}</select></Field>
      <Field label="Amount ₹"><input type="number" inputMode="decimal" value={f.amount || ""} onChange={(e) => setF({ ...f, amount: e.target.value })} /></Field><Field label="Bill no"><input value={f.bill_no || ""} onChange={(e) => setF({ ...f, bill_no: e.target.value })} /></Field><Field label="Remarks"><input value={f.remarks || ""} onChange={(e) => setF({ ...f, remarks: e.target.value })} /></Field></Modal>}
    {m === "fuel" && <Modal title="Diesel" onClose={() => setM(null)} footer={<Btn kind="primary" onClick={async () => { if (await run(() => api.post(`/api/driver/trips/${id}/expense`, f), "Diesel entry saved")) { setM(null); reload(); } }}>Save</Btn>}>
      <Field label="Litres"><input type="number" inputMode="decimal" value={f.litres || ""} onChange={(e) => setF({ ...f, litres: e.target.value })} /></Field><Field label="Amount ₹"><input type="number" inputMode="decimal" value={f.amount || ""} onChange={(e) => setF({ ...f, amount: e.target.value })} /></Field>
      <Field label={t("Odometer")}><input type="number" inputMode="numeric" value={f.odometer || ""} onChange={(e) => setF({ ...f, odometer: e.target.value })} /></Field><Field label="Full tank"><input type="checkbox" checked={f.full_tank} onChange={(e) => setF({ ...f, full_tank: e.target.checked })} /></Field><Field label="Bill no"><input value={f.bill_no || ""} onChange={(e) => setF({ ...f, bill_no: e.target.value })} /></Field></Modal>}
    {m === "incident" && <Modal title={t("Incident")} onClose={() => setM(null)} footer={<Btn kind="danger" onClick={async () => { if (await run(() => api.post(`/api/driver/trips/${id}/incident`, f), "Reported to office")) setM(null); }}>Report</Btn>}>
      <Field label="Type"><select value={f.kind} onChange={(e) => setF({ ...f, kind: e.target.value })}>{["Breakdown", "Accident", "Fine / Challan", "Theft", "Damage", "Other"].map((c) => <option key={c}>{c}</option>)}</select></Field>
      <Field label="Location"><input value={f.location || ""} onChange={(e) => setF({ ...f, location: e.target.value })} /></Field><Field label="Amount ₹ (fine)"><input type="number" value={f.amount || ""} onChange={(e) => setF({ ...f, amount: e.target.value })} /></Field><Field label="What happened"><textarea value={f.description || ""} onChange={(e) => setF({ ...f, description: e.target.value })} /></Field></Modal>}
  </Modal>;
}
