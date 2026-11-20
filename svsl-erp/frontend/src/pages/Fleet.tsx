import React, { useState } from "react";
import { api, can, qs } from "../lib/api";
import { dt, inr, today } from "../lib/format";
import ResourcePage from "../components/ResourcePage";
import { Badge, Btn, Card, Field, Kpi, Modal, Page, RefSelect, Table, Tabs, run, toast, useLoad } from "../components/ui";

export function Fuel() {
  const [tab, setTab] = useState("Diesel entries");
  const [f, setF] = useState<any>(null);
  const [veh, setVeh] = useState<number | null>(null);
  const mil = useLoad<any[]>(veh ? `/api/fuel/mileage/${veh}` : null);
  const [key, setKey] = useState(0);
  return <Page title="Diesel & fuel" actions={can("fuel:write") && <Btn kind="primary" onClick={() => setF({ entry_date: today(), full_tank: true, payment_mode: "Vendor Credit" })}>+ Diesel entry</Btn>}>
    <Tabs tabs={["Diesel entries", "Mileage", "Fuel stations", "Fuel cards"]} value={tab} onChange={setTab} />
    {tab === "Diesel entries" && <ResourcePage key={key} embedded name="fuel_entries" columns={["entry_date", "vehicle_id", "driver_id", "trip_id", "station_id", "litres", "rate", "amount", "odometer", "full_tank", "payment_mode", "entered_via"]} />}
    {tab === "Mileage" && <Card title="Vehicle mileage (full tank to full tank)">
      <Field label="Vehicle"><RefSelect refName="vehicles" value={veh} onChange={setVeh} /></Field>
      <Table dense cols={[{ key: "date", label: "Fill date", type: "date" }, { key: "from_km", label: "From km", type: "number" }, { key: "to_km", label: "To km", type: "number" }, { key: "distance", label: "Distance", type: "number" }, { key: "litres", label: "Litres", type: "number" }, { key: "kmpl", label: "Km/L", type: "number" }, { key: "expected", label: "Expected", type: "number" }, { key: "abnormal", label: "Alert", render: (r) => r.abnormal ? <span className="badge bad">Abnormal</span> : "" }]} rows={mil.data || []} />
    </Card>}
    {tab === "Fuel stations" && <ResourcePage embedded name="fuel_stations" columns={["name", "company", "location", "vendor_id", "credit_account"]} />}
    {tab === "Fuel cards" && <ResourcePage embedded name="fuel_cards" columns={["card_no", "provider", "vehicle_id", "valid_till", "opening_balance"]} />}
    {f && <Modal title="Diesel entry" onClose={() => setF(null)} footer={<Btn kind="primary" onClick={async () => { if (await run(() => api.post("/api/fuel", f), "Diesel entry posted")) { setF(null); setKey(key + 1); } }}>Save</Btn>}>
      <div className="form-grid">
        <Field label="Date"><input type="date" value={f.entry_date} onChange={(e) => setF({ ...f, entry_date: e.target.value })} /></Field>
        <Field label="Vehicle" required><RefSelect refName="vehicles" value={f.vehicle_id} onChange={(v) => setF({ ...f, vehicle_id: v })} /></Field>
        <Field label="Driver"><RefSelect refName="drivers" value={f.driver_id} onChange={(v) => setF({ ...f, driver_id: v })} /></Field>
        <Field label="Fuel station"><RefSelect refName="fuel_stations" value={f.station_id} onChange={(v) => setF({ ...f, station_id: v })} /></Field>
        <Field label="Litres" required><input type="number" value={f.litres || ""} onChange={(e) => setF({ ...f, litres: e.target.value })} /></Field>
        <Field label="Rate ₹/L" required><input type="number" value={f.rate || ""} onChange={(e) => setF({ ...f, rate: e.target.value })} /></Field>
        <Field label="Odometer" required><input type="number" value={f.odometer || ""} onChange={(e) => setF({ ...f, odometer: e.target.value })} /></Field>
        <Field label="Full tank"><input type="checkbox" checked={f.full_tank} onChange={(e) => setF({ ...f, full_tank: e.target.checked })} /></Field>
        <Field label="Payment"><select value={f.payment_mode} onChange={(e) => setF({ ...f, payment_mode: e.target.value })}>{["Vendor Credit", "Cash", "Bank", "Fuel Card", "Driver Cash"].map((x) => <option key={x}>{x}</option>)}</select></Field>
        {f.payment_mode === "Vendor Credit" && <Field label="Vendor (blank = station's vendor)"><RefSelect refName="vendors" value={f.vendor_id} onChange={(v) => setF({ ...f, vendor_id: v })} /></Field>}
        {f.payment_mode === "Fuel Card" && <Field label="Fuel card"><RefSelect refName="fuel_cards" value={f.fuel_card_id} onChange={(v) => setF({ ...f, fuel_card_id: v })} /></Field>}
        <Field label="Bill no"><input value={f.bill_no || ""} onChange={(e) => setF({ ...f, bill_no: e.target.value })} /></Field>
      </div>
      <p className="muted small">Entries linked to a trip are added from the trip screen so they appear in trip profit/loss.</p>
    </Modal>}
  </Page>;
}

export function Maintenance() {
  const [tab, setTab] = useState("Jobs");
  const jobs = useLoad<any[]>(tab === "Jobs" ? "/api/maintenance/jobs" : null);
  const due = useLoad<any[]>(tab === "Due" ? "/api/maintenance/due" : null);
  const [nj, setNj] = useState<any>(null);
  const [cj, setCj] = useState<any>(null);
  return <Page title="Maintenance" actions={can("maintenance:write") && <Btn kind="primary" onClick={() => setNj({ date_in: today(), category: "Preventive Service", job_type: "Preventive", vehicle_off_road: true })}>+ Job card</Btn>}>
    <Tabs tabs={["Jobs", "Due", "Schedules"]} value={tab} onChange={setTab} />
    {tab === "Jobs" && <Table cols={[{ key: "job_no", label: "Job" }, { key: "vehicle", label: "Vehicle" }, { key: "category", label: "Category" }, { key: "job_type", label: "Type" }, { key: "date_in", label: "In", type: "date" }, { key: "date_out", label: "Out", type: "date" }, { key: "odometer", label: "Km", type: "number" }, { key: "total_amount", label: "Total", type: "money" }, { key: "status", label: "Status", type: "badge" },
      { key: "x", label: "", render: (j) => j.status === "Open" && can("maintenance:write") ? <Btn small kind="primary" onClick={() => setCj({ job: j, parts: [{ name: "", qty: 1, rate: "" }], labour_amount: "", gst_amount: "", date_out: today(), payment_mode: "Vendor Credit" })}>Complete</Btn> : null }]} rows={jobs.data || []} />}
    {tab === "Due" && <Table cols={[{ key: "vehicle", label: "Vehicle" }, { key: "task", label: "Task" }, { key: "due", label: "Due at" }, { key: "overdue", label: "", render: (r) => r.overdue ? <span className="badge bad">Overdue</span> : <span className="badge warn">Due soon</span> }]} rows={due.data || []} empty="No service due" />}
    {tab === "Schedules" && <ResourcePage embedded name="maintenance_schedules" columns={["vehicle_id", "task", "interval_km", "interval_days", "last_done_date", "last_done_km", "is_active"]} />}
    {nj && <Modal title="New job card" onClose={() => setNj(null)} footer={<Btn kind="primary" onClick={async () => { if (await run(() => api.post("/api/maintenance/jobs", nj), "Job card opened")) { setNj(null); jobs.reload(); } }}>Open job</Btn>}>
      <div className="form-grid">
        <Field label="Vehicle"><RefSelect refName="vehicles" value={nj.vehicle_id} onChange={(v) => setNj({ ...nj, vehicle_id: v })} /></Field>
        <Field label="Category"><select value={nj.category} onChange={(e) => setNj({ ...nj, category: e.target.value })}>{["Preventive Service", "Engine Oil", "Tyres", "Battery", "Brake", "Clutch", "Engine Repair", "Gear Box", "Electrical", "Body Work", "Accident Repair", "Suspension", "AC", "Other"].map((x) => <option key={x}>{x}</option>)}</select></Field>
        <Field label="Type"><select value={nj.job_type} onChange={(e) => setNj({ ...nj, job_type: e.target.value })}><option>Preventive</option><option>Breakdown</option><option>Accident</option></select></Field>
        <Field label="Workshop vendor"><RefSelect refName="vendors" value={nj.vendor_id} onChange={(v) => setNj({ ...nj, vendor_id: v })} /></Field>
        <Field label="Date in"><input type="date" value={nj.date_in} onChange={(e) => setNj({ ...nj, date_in: e.target.value })} /></Field>
        <Field label="Odometer"><input type="number" value={nj.odometer || ""} onChange={(e) => setNj({ ...nj, odometer: e.target.value })} /></Field>
        <Field label="Vehicle off road"><input type="checkbox" checked={nj.vehicle_off_road} onChange={(e) => setNj({ ...nj, vehicle_off_road: e.target.checked })} /></Field>
        <Field label="Complaint" wide><textarea value={nj.complaint || ""} onChange={(e) => setNj({ ...nj, complaint: e.target.value })} /></Field>
      </div>
    </Modal>}
    {cj && <Modal wide title={`Complete ${cj.job.job_no}`} onClose={() => setCj(null)} footer={<Btn kind="primary" onClick={async () => { if (await run(() => api.post(`/api/maintenance/jobs/${cj.job.id}/complete`, cj), "Job completed & posted")) { setCj(null); jobs.reload(); } }}>Complete</Btn>}>
      <h4>Spare parts</h4>
      {cj.parts.map((p: any, i: number) => <div className="row gap" key={i}>{["name", "part_no", "qty", "rate"].map((k) => <input key={k} placeholder={k} type={["qty", "rate"].includes(k) ? "number" : "text"} value={p[k] || ""} onChange={(e) => setCj({ ...cj, parts: cj.parts.map((x: any, j: number) => (j === i ? { ...x, [k]: e.target.value } : x)) })} />)}</div>)}
      <Btn small onClick={() => setCj({ ...cj, parts: [...cj.parts, { name: "", qty: 1, rate: "" }] })}>+ Part</Btn>
      <div className="form-grid">
        <Field label="Labour ₹"><input type="number" value={cj.labour_amount} onChange={(e) => setCj({ ...cj, labour_amount: e.target.value })} /></Field>
        <Field label="GST ₹"><input type="number" value={cj.gst_amount} onChange={(e) => setCj({ ...cj, gst_amount: e.target.value })} /></Field>
        <Field label="Date out"><input type="date" value={cj.date_out} onChange={(e) => setCj({ ...cj, date_out: e.target.value })} /></Field>
        <Field label="Bill no"><input value={cj.bill_no || ""} onChange={(e) => setCj({ ...cj, bill_no: e.target.value })} /></Field>
        <Field label="Payment"><select value={cj.payment_mode} onChange={(e) => setCj({ ...cj, payment_mode: e.target.value })}><option>Vendor Credit</option><option>Cash</option><option>Bank</option></select></Field>
        <Field label="Claim GST input credit"><input type="checkbox" checked={!!cj.itc_eligible} onChange={(e) => setCj({ ...cj, itc_eligible: e.target.checked })} /></Field>
        <Field label="Work done" wide><textarea value={cj.work_done || ""} onChange={(e) => setCj({ ...cj, work_done: e.target.value })} /></Field>
      </div>
    </Modal>}
  </Page>;
}

export function Tyres() {
  const [act, setAct] = useState<any>(null);
  const [hist, setHist] = useState<any>(null);
  const [k, setK] = useState(0);
  return <Page title="Tyres & batteries">
    <ResourcePage key={k} embedded name="tyres" columns={["kind", "serial_no", "brand", "size", "status", "vehicle_id", "position", "fitted_date", "fitted_km", "total_km", "cost"]}
      rowActions={(r) => <>{can("maintenance:write") && <Btn small onClick={() => setAct({ tyre: r, action: r.status === "Fitted" ? "Removed" : "Fitted", date: today() })}>{r.status === "Fitted" ? "Remove / rotate" : "Fit"}</Btn>}<Btn small kind="ghost" onClick={async () => setHist(await run(() => api.get(`/api/tyres/${r.id}/history`)))}>History</Btn></>} />
    {act && <Modal title={`${act.tyre.serial_no}`} onClose={() => setAct(null)} footer={<Btn kind="primary" onClick={async () => { if (await run(() => api.post(`/api/tyres/${act.tyre.id}/action`, act), "Saved")) { setAct(null); setK(k + 1); } }}>Save</Btn>}>
      <Field label="Action"><select value={act.action} onChange={(e) => setAct({ ...act, action: e.target.value })}>{(act.tyre.status === "Fitted" ? ["Removed", "Rotated", "Retreading", "Scrapped", "Sold"] : ["Fitted", "Scrapped", "Sold"]).map((x) => <option key={x}>{x}</option>)}</select></Field>
      {act.action === "Fitted" && <Field label="Vehicle"><RefSelect refName="vehicles" value={act.vehicle_id} onChange={(v) => setAct({ ...act, vehicle_id: v })} /></Field>}
      {["Fitted", "Rotated"].includes(act.action) && <Field label="Position"><input value={act.position || ""} onChange={(e) => setAct({ ...act, position: e.target.value })} placeholder="FL, FR, RL-O…" /></Field>}
      <Field label="Odometer"><input type="number" value={act.odometer || ""} onChange={(e) => setAct({ ...act, odometer: e.target.value })} /></Field>
      <Field label="Date"><input type="date" value={act.date} onChange={(e) => setAct({ ...act, date: e.target.value })} /></Field>
      <Field label="Cost ₹ (retreading etc.)"><input type="number" value={act.cost || ""} onChange={(e) => setAct({ ...act, cost: e.target.value })} /></Field>
    </Modal>}
    {hist && <Modal title={`History – ${hist.tyre.serial_no}`} onClose={() => setHist(null)}>
      <p>Total km: <b>{hist.tyre.total_km}</b> · Cost: <b>{inr(hist.tyre.cost)}</b> · Cost per km: <b>{hist.cost_per_km ? inr(hist.cost_per_km) : "-"}</b></p>
      <Table dense cols={[{ key: "at", label: "Date", type: "date" }, { key: "event", label: "Event" }, { key: "vehicle_id", label: "Vehicle", type: "ref", ref: "vehicles" }, { key: "position", label: "Pos" }, { key: "odometer", label: "Km", type: "number" }, { key: "km_run", label: "Km run", type: "number" }, { key: "cost", label: "Cost", type: "money" }]} rows={hist.events} />
    </Modal>}
  </Page>;
}

export function Tolls() {
  const [veh, setVeh] = useState<number | null>(null);
  const [unmatched, setUnmatched] = useState(false);
  const list = useLoad<any[]>(`/api/fastag${qs({ vehicle_id: veh, unmatched: unmatched || undefined })}`);
  const upload = async (file: File, provider: string) => {
    const fd = new FormData(); fd.append("file", file);
    const r: any = await run(() => api.form(`/api/fastag/import?provider=${encodeURIComponent(provider)}`, fd));
    if (r) { toast.ok(`${r.added} added, ${r.duplicates_skipped} duplicates skipped, ${r.matched_to_trips} matched to trips`); r.errors.slice(0, 3).forEach((e: string) => toast.err(e)); list.reload(); }
  };
  const [prov, setProv] = useState("");
  return <Page title="Tolls & FASTag">
    <Card title="Import FASTag statement">
      <p className="muted small">Download the statement (CSV/Excel) from your FASTag issuer's corporate portal and upload it here. Columns are detected automatically (transaction id, date/time, vehicle number, plaza, amount, type). There is no direct FASTag API connection.</p>
      <div className="row gap"><input placeholder="Issuer (e.g. bank name)" value={prov} onChange={(e) => setProv(e.target.value)} />{can("routes:write") && <label className="btn primary">Upload statement<input hidden type="file" accept=".csv,.xlsx" onChange={(e) => e.target.files?.[0] && upload(e.target.files[0], prov)} /></label>}</div>
    </Card>
    <div className="toolbar"><RefSelect refName="vehicles" value={veh} onChange={setVeh} placeholder="All vehicles" /><label className="row gap small"><input type="checkbox" checked={unmatched} onChange={(e) => setUnmatched(e.target.checked)} />Unmatched only</label></div>
    <Table cols={[{ key: "txn_at", label: "Date / time", type: "datetime" }, { key: "vehicle_no", label: "Vehicle" }, { key: "plaza_name", label: "Plaza" }, { key: "amount", label: "Amount", type: "money" }, { key: "txn_type", label: "Type" }, { key: "trip_no", label: "Trip" }, { key: "match_status", label: "Match", type: "badge" },
      { key: "x", label: "", render: (f) => f.match_status === "Matched" && f.txn_type === "Debit" && can("trips:write") ? <Btn small onClick={async () => { if (await run(() => api.post(`/api/fastag/${f.id}/post-to-trip`), "Booked as trip toll")) list.reload(); }}>Book to trip</Btn> : null }]} rows={list.data || []} />
  </Page>;
}

export function DriverOps() {
  const [tab, setTab] = useState("Settlement");
  const [drv, setDrv] = useState<number | null>(null);
  const [upto, setUpto] = useState(today());
  const prev = useLoad<any>(drv && tab === "Settlement" ? `/api/drivers/${drv}/settlement-preview?upto=${upto}` : null);
  const settlements = useLoad<any[]>(tab === "History" ? "/api/driver-settlements" : null);
  const [pay, setPay] = useState({ pay_mode: "Cash", other_deductions: "", remarks: "" });
  const p = prev.data;
  return <Page title="Driver advances & settlement">
    <Tabs tabs={["Settlement", "Advances", "History"]} value={tab} onChange={setTab} />
    {tab === "Settlement" && <>
      <div className="toolbar"><RefSelect refName="drivers" value={drv} onChange={setDrv} placeholder="Select driver" /><Field label="Up to"><input type="date" value={upto} onChange={(e) => setUpto(e.target.value)} /></Field></div>
      {p && <>
        <div className="kpis small"><Kpi label="Bata + allowances" value={inr(p.earnings)} /><Kpi label="Paid by driver (reimburse)" value={inr(p.totals.driver_paid)} /><Kpi label="Advances" value={inr(p.advances_total)} /><Kpi label="Fines to recover" value={inr(p.fines_total)} /><Kpi label="Net payable" value={inr(p.net_payable)} tone={Number(p.net_payable) >= 0 ? "good" : "warn"} sub={Number(p.net_payable) < 0 ? "Driver owes the company" : ""} /></div>
        <Table dense cols={[{ key: "trip_no", label: "Trip" }, { key: "date", label: "Date", type: "date" }, { key: "route", label: "Route" }, { key: "days", label: "Days", type: "number" }, { key: "km", label: "Km", type: "number" }, { key: "bata", label: "Bata", type: "money" }, { key: "food", label: "Food", type: "money" }, { key: "trip_allowance", label: "Trip allow.", type: "money" }, { key: "km_allowance", label: "Km allow.", type: "money" }, { key: "driver_paid", label: "Driver paid", type: "money" }]} rows={p.trips} totals={p.totals} />
        {can("accounts:write") && <div className="row gap wrap">
          <Field label="Other deductions ₹"><input type="number" value={pay.other_deductions} onChange={(e) => setPay({ ...pay, other_deductions: e.target.value })} /></Field>
          <Field label="Pay now by"><select value={pay.pay_mode} onChange={(e) => setPay({ ...pay, pay_mode: e.target.value })}><option value="">Don't pay now</option><option>Cash</option><option>Bank</option></select></Field>
          <Field label="Remarks"><input value={pay.remarks} onChange={(e) => setPay({ ...pay, remarks: e.target.value })} /></Field>
          <Btn kind="primary" onClick={async () => { if (await run(() => api.post(`/api/drivers/${drv}/settle`, { ...pay, upto }), "Settlement posted")) prev.reload(); }}>Post settlement</Btn>
        </div>}
      </>}
    </>}
    {tab === "Advances" && <ResourcePage embedded name="driver_advances" columns={["advance_date", "driver_id", "amount", "trip_id", "mode", "purpose", "settlement_id"]} defaults={{ advance_date: today(), mode: "Cash", purpose: "Trip Advance" }} />}
    {tab === "History" && <Table cols={[{ key: "settlement_no", label: "No" }, { key: "settlement_date", label: "Date", type: "date" }, { key: "driver", label: "Driver" }, { key: "trip_days", label: "Days", type: "number" }, { key: "bata_total", label: "Bata", type: "money" }, { key: "advances_total", label: "Advances", type: "money" }, { key: "net_payable", label: "Net", type: "money" }, { key: "status", label: "Status", type: "badge" }]} rows={settlements.data || []} />}
  </Page>;
}

export { Badge, dt };
