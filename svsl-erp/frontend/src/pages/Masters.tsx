import React, { useState } from "react";
import { useNavigate } from "react-router-dom";
import { api, can } from "../lib/api";
import { dt, fyStart, inr, today } from "../lib/format";
import ResourcePage from "../components/ResourcePage";
import { Badge, Btn, Card, Field, Kpi, Modal, Page, RefSelect, Table, Tabs, download, run, useLoad } from "../components/ui";

function CustomerDetail({ row }: { row: any }) {
  const s = useLoad<any>(`/api/customers/${row.id}/summary`);
  const nav = useNavigate();
  if (!s.data) return null;
  const d = s.data;
  return <div>
    <div className="kpis small">
      <Kpi label="Outstanding" value={inr(d.outstanding)} tone={Number(d.outstanding) > Number(d.credit_limit || 0) && Number(d.credit_limit) > 0 ? "bad" : undefined} sub={`Limit ${inr(d.credit_limit)}`} />
      <Kpi label="Freight revenue (all time)" value={inr(d.revenue)} />
      <Kpi label="Trip profit" value={inr(d.profit)} tone={Number(d.profit) >= 0 ? "good" : "bad"} />
      <Kpi label="Unbilled LRs" value={d.unbilled_lrs} />
    </div>
    {d.credit_warning && <div className="warn-box">{d.credit_warning}</div>}
    <div className="row gap wrap">
      <Btn small onClick={() => download(`/api/reports/customer_statement?customer_id=${row.id}&start=${fyStart()}&end=${today()}&format=pdf`)}>Statement PDF</Btn>
      <Btn small onClick={() => download(`/api/reports/customer_statement?customer_id=${row.id}&start=${fyStart()}&end=${today()}&format=xlsx`)}>Statement Excel</Btn>
      <Btn small onClick={() => nav(`/documents?entity_type=customer&entity_id=${row.id}`)}>Documents</Btn>
      {can("users:write") && <Btn small onClick={() => nav(`/users?customer_id=${row.id}`)}>Create portal login</Btn>}
    </div>
    <h4>Recent trips</h4>
    <Table dense cols={[{ key: "trip_no", label: "Trip" }, { key: "date", label: "Date", type: "date" }, { key: "route", label: "Route" }, { key: "stage", label: "Stage", type: "badge" }]} rows={d.recent_trips} onRow={(t) => nav(`/trips?id=${t.id}`)} />
  </div>;
}

export function Customers() {
  return <ResourcePage name="customers" columns={["code", "name", "category", "gstin", "billing_city", "mobile", "credit_limit", "credit_days", "contract_end"]} detail={(r) => <CustomerDetail row={r} />} />;
}

function VehicleDetail({ row, reload }: { row: any; reload: () => void }) {
  const s = useLoad<any>(`/api/vehicles/${row.id}/summary`);
  const [ev, setEv] = useState<any>(null);
  const d = s.data;
  return <div>
    {d && <div className="kpis small">
      <Kpi label="Revenue (90 days)" value={inr(d.profit?.revenue)} />
      <Kpi label="Operating profit" value={inr(d.profit?.profit)} tone={Number(d.profit?.profit) >= 0 ? "good" : "bad"} />
      <Kpi label="Utilisation" value={`${d.utilization?.utilization ?? 0}%`} sub={`${d.utilization?.downtime_days ?? 0} downtime days`} />
      <Kpi label="Last km/L" value={d.mileage?.length ? d.mileage[d.mileage.length - 1].kmpl : "-"} />
    </div>}
    {can("vehicles:write") && <div className="row gap wrap">
      {["Transfer", "Sale", "Purchase", "Deactivation", "Reactivation"].map((k) => <Btn small key={k} onClick={() => setEv({ event_type: k, event_date: today(), mode: "Bank" })}>{k}</Btn>)}
    </div>}
    {d && <Tabs2 d={d} />}
    {ev && <Modal title={`Vehicle ${ev.event_type.toLowerCase()} – ${row.registration_no}`} onClose={() => setEv(null)} footer={<Btn kind="primary" onClick={async () => { if (await run(() => api.post(`/api/vehicles/${row.id}/events`, ev), "Recorded")) { setEv(null); reload(); s.reload(); } }}>Save</Btn>}>
      <div className="form-grid">
        <Field label="Date"><input type="date" value={ev.event_date} onChange={(e) => setEv({ ...ev, event_date: e.target.value })} /></Field>
        {ev.event_type === "Transfer" && <Field label="To branch"><RefSelect refName="branches" value={ev.to_branch_id} onChange={(v) => setEv({ ...ev, to_branch_id: v })} /></Field>}
        {["Sale", "Purchase"].includes(ev.event_type) && <>
          <Field label="Amount (₹)"><input type="number" value={ev.amount || ""} onChange={(e) => setEv({ ...ev, amount: e.target.value })} /></Field>
          <Field label={ev.event_type === "Sale" ? "Buyer" : "Seller"}><input value={ev.party || ""} onChange={(e) => setEv({ ...ev, party: e.target.value })} /></Field>
          <Field label={ev.event_type === "Sale" ? "Received by" : "Paid by"}><select value={ev.mode} onChange={(e) => setEv({ ...ev, mode: e.target.value })}><option>Bank</option><option>Cash</option>{ev.event_type === "Purchase" && <><option>Loan</option><option>Vendor Credit</option></>}</select></Field>
          {ev.mode === "Vendor Credit" && <Field label="Vendor"><RefSelect refName="vendors" value={ev.vendor_id} onChange={(v) => setEv({ ...ev, vendor_id: v })} /></Field>}
          {ev.event_type === "Sale" && <Field label="Book value (₹)" help="Defaults to purchase value"><input type="number" value={ev.book_value || ""} onChange={(e) => setEv({ ...ev, book_value: e.target.value })} /></Field>}
        </>}
        <Field label="Odometer"><input type="number" value={ev.odometer || ""} onChange={(e) => setEv({ ...ev, odometer: e.target.value })} /></Field>
        <Field label="Remarks" wide><textarea value={ev.remarks || ""} onChange={(e) => setEv({ ...ev, remarks: e.target.value })} /></Field>
      </div>
    </Modal>}
  </div>;
}

function Tabs2({ d }: { d: any }) {
  const [tab, setTab] = useState("Trips");
  return <>
    <Tabs tabs={["Trips", "History", "Maintenance", "Tyres", "Mileage", "Documents"]} value={tab} onChange={setTab} />
    {tab === "Trips" && <Table dense cols={[{ key: "trip_no", label: "Trip" }, { key: "date", label: "Date", type: "date" }, { key: "route", label: "Route" }, { key: "stage", label: "Stage", type: "badge" }]} rows={d.trips} />}
    {tab === "History" && <Table dense cols={[{ key: "event_date", label: "Date", type: "date" }, { key: "event_type", label: "Event" }, { key: "amount", label: "Amount", type: "money" }, { key: "party", label: "Party" }, { key: "remarks", label: "Remarks" }]} rows={d.events} />}
    {tab === "Maintenance" && <Table dense cols={[{ key: "job_no", label: "Job" }, { key: "date_in", label: "In", type: "date" }, { key: "category", label: "Category" }, { key: "total_amount", label: "Total", type: "money" }, { key: "status", label: "Status", type: "badge" }]} rows={d.maintenance} />}
    {tab === "Tyres" && <Table dense cols={[{ key: "kind", label: "Type" }, { key: "serial_no", label: "Serial" }, { key: "position", label: "Position" }, { key: "fitted_date", label: "Fitted", type: "date" }, { key: "fitted_km", label: "At km", type: "number" }]} rows={d.tyres} />}
    {tab === "Mileage" && <Table dense cols={[{ key: "date", label: "Fill", type: "date" }, { key: "distance", label: "Km", type: "number" }, { key: "litres", label: "Litres", type: "number" }, { key: "kmpl", label: "Km/L", type: "number" }, { key: "abnormal", label: "Abnormal", type: "bool" }]} rows={d.mileage} />}
    {tab === "Documents" && <Table dense cols={[{ key: "title", label: "Title" }, { key: "doc_type", label: "Type" }, { key: "expiry_date", label: "Expiry", type: "date" }]} rows={d.documents} onRow={(x) => download(`/api/documents/${x.id}/download`)} />}
  </>;
}

export function Vehicles() {
  return <ResourcePage name="vehicles" columns={["registration_no", "vehicle_type", "make", "ownership", "status", "branch_id", "insurance_expiry", "fc_expiry", "national_permit_expiry", "puc_expiry", "current_odometer"]} detail={(r, reload) => <VehicleDetail row={r} reload={reload} />} />;
}

export function Drivers() {
  const [tab, setTab] = useState("Drivers");
  return <Page title="Drivers">
    <Tabs tabs={["Drivers", "Incidents & fines", "Duty roster"]} value={tab} onChange={setTab} />
    {tab === "Drivers" && <ResourcePage embedded name="drivers" columns={["code", "name", "mobile", "licence_no", "licence_class", "licence_expiry", "employment_status", "status", "gps_consent"]} />}
    {tab === "Incidents & fines" && <ResourcePage embedded name="driver_incidents" columns={["incident_date", "driver_id", "vehicle_id", "kind", "location", "amount", "recover_from_driver", "status", "reported_via"]} defaults={{ incident_date: today() }} />}
    {tab === "Duty roster" && <ResourcePage embedded name="duty_roster" columns={["roster_date", "driver_id", "vehicle_id", "shift", "notes"]} defaults={{ roster_date: today() }} />}
  </Page>;
}

export function Vendors() {
  return <ResourcePage name="vendors" columns={["code", "name", "category", "gstin", "city", "mobile", "credit_days", "tds_section"]} />;
}

export function RoutesPage() {
  const [tab, setTab] = useState("Routes");
  return <Page title="Routes & tolls">
    <Tabs tabs={["Routes", "Toll plazas", "Route toll plazas", "Fuel stations", "Fuel cards"]} value={tab} onChange={setTab} />
    {tab === "Routes" && <ResourcePage embedded name="routes" columns={["code", "origin", "destination", "via", "distance_km", "est_hours", "est_toll"]} />}
    {tab === "Toll plazas" && <ResourcePage embedded name="toll_plazas" columns={["name", "highway", "location", "state", "rate_truck_2axle", "rate_multi_axle"]} />}
    {tab === "Route toll plazas" && <ResourcePage embedded name="route_tolls" columns={["route_id", "toll_plaza_id", "sequence"]} />}
    {tab === "Fuel stations" && <ResourcePage embedded name="fuel_stations" columns={["name", "company", "location", "vendor_id", "credit_account"]} />}
    {tab === "Fuel cards" && <ResourcePage embedded name="fuel_cards" columns={["card_no", "provider", "vehicle_id", "valid_till"]} />}
  </Page>;
}

function RateTools({ row, reload }: { row: any; reload: () => void }) {
  const hist = useLoad<any[]>(`/api/rates/${row.id}/history`);
  const [inp, setInp] = useState<any>({ trips: 1, km: "", weight_kg: "", quantity: "", months: 1, waiting_hours: "", detention_days: "", extra_stops: "" });
  const [res, setRes] = useState<any>(null);
  const [rev, setRev] = useState<any>(null);
  return <div>
    <Card title="Freight calculator">
      <div className="form-grid">{Object.keys(inp).map((k) => <Field key={k} label={k.replace(/_/g, " ")}><input type="number" value={inp[k]} onChange={(e) => setInp({ ...inp, [k]: e.target.value })} /></Field>)}
        <Field label="Return load"><input type="checkbox" checked={!!inp.is_return} onChange={(e) => setInp({ ...inp, is_return: e.target.checked })} /></Field></div>
      <Btn onClick={async () => setRes(await run(() => api.post("/api/freight/calculate", { rate_contract_id: row.id, inputs: inp })))}>Calculate</Btn>
      {res && <Table dense cols={[{ key: "label", label: "Line" }, { key: "amount", label: "Amount", type: "money" }]} rows={res.lines} totals={{ label: "Total", amount: res.total }} />}
    </Card>
    {can("rates:approve") && row.status === "Active" && <Btn kind="primary" onClick={() => setRev({ effective_from: today(), reason: "", changes: { rate: row.rate, min_freight: row.min_freight } })}>Revise rate (new version)</Btn>}
    <h4>Version history</h4>
    <Table dense cols={[{ key: "version", label: "Ver" }, { key: "rate", label: "Rate", type: "money" }, { key: "min_freight", label: "Minimum", type: "money" }, { key: "effective_from", label: "From", type: "date" }, { key: "effective_to", label: "To", type: "date" }, { key: "status", label: "Status", type: "badge" }, { key: "lr_count", label: "LRs", type: "number" }, { key: "revision_reason", label: "Reason" }]} rows={hist.data || []} />
    {rev && <Modal title={`Revise ${row.contract_no}`} onClose={() => setRev(null)} footer={<Btn kind="primary" onClick={async () => { if (await run(() => api.post(`/api/rates/${row.id}/revise`, rev), "New version created")) { setRev(null); reload(); hist.reload(); } }}>Create version</Btn>}>
      <p className="muted small">The current version stays valid until the day before the new effective date. Past LRs and invoices are not changed.</p>
      <div className="form-grid">
        <Field label="Effective from"><input type="date" value={rev.effective_from} onChange={(e) => setRev({ ...rev, effective_from: e.target.value })} /></Field>
        {["rate", "min_freight", "extra_trip_rate", "waiting_rate_per_hour", "detention_rate_per_day", "loading_charge", "unloading_charge", "extra_stop_charge"].map((k) => <Field key={k} label={k.replace(/_/g, " ")}><input type="number" value={rev.changes[k] ?? ""} onChange={(e) => setRev({ ...rev, changes: { ...rev.changes, [k]: e.target.value } })} /></Field>)}
        <Field label="Reason" wide><textarea value={rev.reason} onChange={(e) => setRev({ ...rev, reason: e.target.value })} /></Field>
      </div>
    </Modal>}
  </div>;
}

export function Rates() {
  return <ResourcePage name="rate_contracts" columns={["contract_no", "version", "name", "customer_id", "route_id", "basis", "rate", "min_freight", "effective_from", "effective_to", "status"]} detail={(r, reload) => <RateTools row={r} reload={reload} />}
    defaults={{ effective_from: today(), status: "Active", basis: "per_trip" }} />;
}

export function Bookings() {
  const nav = useNavigate();
  const [conv, setConv] = useState<any>(null);
  return <>
    <ResourcePage name="bookings" columns={["booking_no", "booking_date", "customer_id", "source", "required_date", "vehicle_type", "goods_description", "status"]} defaults={{ booking_date: today(), required_date: today(), source: "Office", status: "Requested" }}
      rowActions={(r) => ["Requested", "Confirmed"].includes(r.status) && can("trips:write") ? <Btn small kind="primary" onClick={() => setConv({ booking: r, vehicle_id: null, driver_id: null })}>Create trip</Btn> : null} />
    {conv && <Modal title={`Create trip for ${conv.booking.booking_no}`} onClose={() => setConv(null)} footer={<Btn kind="primary" onClick={async () => { const t = await run(() => api.post(`/api/bookings/${conv.booking.id}/convert`, conv), "Trip created"); if (t) nav(`/trips?id=${(t as any).id}`); }}>Create</Btn>}>
      <Field label="Vehicle"><RefSelect refName="vehicles" value={conv.vehicle_id} onChange={(v) => setConv({ ...conv, vehicle_id: v })} /></Field>
      <Field label="Driver"><RefSelect refName="drivers" value={conv.driver_id} onChange={(v) => setConv({ ...conv, driver_id: v })} /></Field>
      <Field label="From (if no route)"><input value={conv.from_place || ""} onChange={(e) => setConv({ ...conv, from_place: e.target.value })} /></Field>
      <Field label="To (if no route)"><input value={conv.to_place || ""} onChange={(e) => setConv({ ...conv, to_place: e.target.value })} /></Field>
    </Modal>}
  </>;
}

export function EwayBills() {
  return <ResourcePage name="eway_bills" title="E-way bills" columns={["ewb_no", "ewb_date", "valid_until", "consignment_id", "vehicle_no", "from_place", "to_place", "goods_value", "source", "status"]} />;
}

export function Complaints() {
  const { data, reload } = useLoad<any[]>("/api/complaints");
  const [c, setC] = useState<any>(null);
  return <Page title="Complaints">
    <Table cols={[{ key: "complaint_no", label: "No" }, { key: "created_at", label: "Date", type: "datetime" }, { key: "customer", label: "Customer" }, { key: "subject", label: "Subject" }, { key: "status", label: "Status", type: "badge" }]} rows={data || []} onRow={setC} />
    {c && <Modal title={c.complaint_no} onClose={() => setC(null)} footer={can("customers:write") && <Btn kind="primary" onClick={async () => { if (await run(() => api.put(`/api/complaints/${c.id}`, c), "Updated")) { setC(null); reload(); } }}>Save</Btn>}>
      <p><b>{c.subject}</b></p><p>{c.description}</p>
      <Field label="Status"><select value={c.status} onChange={(e) => setC({ ...c, status: e.target.value })}>{["Open", "In Progress", "Resolved", "Closed"].map((s) => <option key={s}>{s}</option>)}</select></Field>
      <Field label="Response to customer"><textarea value={c.response || ""} onChange={(e) => setC({ ...c, response: e.target.value })} /></Field>
    </Modal>}
  </Page>;
}

export { Badge, dt };
