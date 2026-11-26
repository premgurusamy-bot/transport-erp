import React, { useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { api, can, qs } from "../lib/api";
import { dt, inr, num, today } from "../lib/format";
import { Badge, Btn, Card, Field, Kpi, Modal, Page, Pager, ReasonModal, RefSelect, Search, Table, Tabs, run, useLoad } from "../components/ui";
import { Donut, Icon, Progress, StatCard } from "../components/charts";

export const STAGES = ["Booked", "Vehicle Allocated", "Driver Allocated", "LR Generated", "Loading", "Dispatched", "In Transit", "Delivered", "POD Collected", "Closed", "Billed", "Settled"];
const EXP_CATS = ["Diesel", "Toll", "Parking", "RTO / Check Post", "Loading", "Unloading", "Driver Bata", "Food", "Police / Fine", "Repair on Road", "Weighbridge", "Tyre Puncture", "Phone", "Other"];

function NewTrip({ onDone, onClose }: { onDone: (t: any) => void; onClose: () => void }) {
  const [f, setF] = useState<any>({ trip_date: today() });
  const recent = useLoad<any>("/api/trips?limit=100");
  return <Modal title="New trip" onClose={onClose} footer={<Btn kind="primary" onClick={async () => { const t = await run(() => api.post("/api/trips", f), "Trip created"); if (t) onDone(t); }}>Create trip</Btn>}>
    <div className="form-grid">
      <Field label="Trip date"><input type="date" value={f.trip_date} onChange={(e) => setF({ ...f, trip_date: e.target.value })} /></Field>
      <Field label="Customer"><RefSelect refName="customers" value={f.customer_id} onChange={(v) => setF({ ...f, customer_id: v })} /></Field>
      <Field label="Route"><RefSelect refName="routes" value={f.route_id} onChange={(v) => setF({ ...f, route_id: v })} /></Field>
      <Field label="From"><input value={f.from_place || ""} onChange={(e) => setF({ ...f, from_place: e.target.value })} /></Field>
      <Field label="To"><input value={f.to_place || ""} onChange={(e) => setF({ ...f, to_place: e.target.value })} /></Field>
      <Field label="Vehicle"><RefSelect refName="vehicles" value={f.vehicle_id} onChange={(v) => setF({ ...f, vehicle_id: v })} /></Field>
      <Field label="Driver"><RefSelect refName="drivers" value={f.driver_id} onChange={(v) => setF({ ...f, driver_id: v })} /></Field>
      <Field label="Planned departure"><input type="datetime-local" value={f.planned_departure || ""} onChange={(e) => setF({ ...f, planned_departure: e.target.value })} /></Field>
      <Field label="Expected delivery"><input type="datetime-local" value={f.expected_delivery_at || ""} onChange={(e) => setF({ ...f, expected_delivery_at: e.target.value })} /></Field>
      <Field label="Return trip of"><select value={f.return_of_trip_id || ""} onChange={(e) => setF({ ...f, return_of_trip_id: e.target.value || null })}><option value="">— not a return trip —</option>{(recent.data?.items || []).filter((t: any) => t.stage !== "Cancelled").map((t: any) => <option key={t.id} value={t.id}>{t.trip_no} {t.from_place}→{t.to_place} {t.vehicle_no || ""}</option>)}</select></Field>
      <Field label="Remarks" wide><textarea value={f.remarks || ""} onChange={(e) => setF({ ...f, remarks: e.target.value })} /></Field>
    </div>
  </Modal>;
}

export function TripDetail({ id, onClose }: { id: number; onClose: () => void }) {
  const nav = useNavigate();
  const { data: t, reload } = useLoad<any>(`/api/trips/${id}`);
  const [act, setAct] = useState<any>(null);
  const [tab, setTab] = useState("LRs");
  if (!t) return null;
  const idx = STAGES.indexOf(t.stage);
  const next = STAGES[idx + 1];
  const canWrite = can("trips:write") && !["Closed", "Billed", "Settled", "Cancelled"].includes(t.stage);
  const doStage = (stage: string, extra: any = {}) => run(() => api.post(`/api/trips/${id}/stage`, { stage, ...extra }), `Trip moved to ${stage}`).then((r) => { if (r) { setAct(null); reload(); } });
  return <Modal wide title={`Trip ${t.trip_no}`} onClose={onClose} footer={<Btn onClick={onClose}>Close</Btn>}>
    <div className="stepper">{STAGES.map((s, i) => <div key={s} className={`step ${i <= idx ? "done" : ""} ${i === idx ? "cur" : ""}`}>{s}</div>)}{t.stage === "Cancelled" && <div className="step cur bad">Cancelled</div>}</div>
    {t.delayed && <div className="warn-box">Delivery is delayed (expected {dt(t.expected_delivery_at)})</div>}
    <div className="row gap wrap">
      {canWrite && <>
        {["Booked", "Vehicle Allocated", "Driver Allocated", "LR Generated", "Loading"].includes(t.stage) && <Btn small onClick={() => setAct({ kind: "allocate", vehicle_id: t.vehicle_id, driver_id: t.driver_id })}>Allocate vehicle / driver</Btn>}
        {idx >= 2 && idx < 7 && <Btn small onClick={() => nav(`/lr?new=1&trip_id=${t.id}`)}>+ LR</Btn>}
        {t.stage === "LR Generated" && <Btn small kind="primary" onClick={() => doStage("Loading")}>Loading started</Btn>}
        {["LR Generated", "Loading"].includes(t.stage) && <Btn small kind="primary" onClick={() => setAct({ kind: "dispatch", start_km: t.start_km ?? "", fuel_opening_litres: "" })}>Dispatch</Btn>}
        {t.stage === "Dispatched" && <Btn small onClick={() => doStage("In Transit")}>In transit</Btn>}
        {["Dispatched", "In Transit"].includes(t.stage) && <Btn small kind="primary" onClick={() => setAct({ kind: "deliver", receiver_name: "" })}>Delivered</Btn>}
        {t.stage === "Delivered" && <Btn small kind="primary" onClick={() => doStage("POD Collected")}>POD collected</Btn>}
        {["Delivered", "POD Collected"].includes(t.stage) && <Btn small kind="primary" onClick={() => setAct({ kind: "close", end_km: "", fuel_closing_litres: "", waiting_hours: "", detention_days: "" })}>Close trip</Btn>}
        <Btn small onClick={() => setAct({ kind: "expense", category: "Toll", paid_by: "Driver Cash", expense_date: today() })}>+ Expense</Btn>
        {!t.dispatched_at && <Btn small kind="danger" onClick={() => setAct({ kind: "cancel" })}>Cancel trip</Btn>}
      </>}
    </div>
    <div className="kpis small">
      <Kpi label="Revenue" value={inr(t.pnl.revenue)} /><Kpi label="Expenses" value={inr(t.pnl.expenses)} /><Kpi label="Profit" value={inr(t.pnl.profit)} tone={Number(t.pnl.profit) >= 0 ? "good" : "bad"} sub={t.pnl.margin_pct ? `${t.pnl.margin_pct}%` : ""} />
      <Kpi label="Km" value={num(t.pnl.km)} sub={t.pnl.kmpl ? `${t.pnl.kmpl} km/L` : ""} />
    </div>
    <div className="kv">{[["Customer", t.customer_name], ["Route", `${t.from_place} → ${t.to_place}`], ["Vehicle", t.vehicle_no], ["Driver", `${t.driver_name || ""} ${t.driver_mobile || ""}`], ["Start / end km", `${t.start_km ?? "-"} / ${t.end_km ?? "-"}`], ["Dispatched", dt(t.dispatched_at)], ["Expected", dt(t.expected_delivery_at)], ["Delivered", dt(t.delivered_at)], ["Closed", dt(t.closed_at)], ["Advance to driver", inr(t.advance_to_driver)], ["Return trip", t.is_return ? "Yes" : ""]].filter(([, v]) => v).map(([k, v]) => <div key={k}><span>{k}</span><b>{v}</b></div>)}</div>
    <Tabs tabs={["LRs", "Expenses", "Timeline", "FASTag", "Location"]} value={tab} onChange={setTab} />
    {tab === "LRs" && <Table dense cols={[{ key: "lr_no", label: "LR" }, { key: "consignee_name", label: "Consignee" }, { key: "to_place", label: "To" }, { key: "total_freight", label: "Freight", type: "money" }, { key: "status", label: "Status", type: "badge" }]} rows={t.lrs} onRow={(l) => nav(`/lr?id=${l.id}`)} />}
    {tab === "Expenses" && <Table dense cols={[{ key: "expense_date", label: "Date", type: "date" }, { key: "category", label: "Category" }, { key: "amount", label: "Amount", type: "money" }, { key: "litres", label: "Litres", type: "number" }, { key: "paid_by", label: "Paid by" }, { key: "entered_via", label: "Via" },
      { key: "approved", label: "", render: (e) => e.approved ? "" : <Btn small onClick={async () => { await run(() => api.post(`/api/trips/${id}/approve-expense/${e.id}`), "Approved"); reload(); }}>Approve</Btn> },
      { key: "del", label: "", render: (e) => can("accounts:cancel") && !t.driver_settlement_id ? <Btn small kind="ghost" onClick={async () => { const r = prompt("Reason for removing this expense?"); if (r) { await run(() => api.del(`/api/trips/${id}/expenses/${e.id}?reason=${encodeURIComponent(r)}`), "Removed (voucher reversed)"); reload(); } }}>Remove</Btn> : null }]}
      rows={t.expenses} totals={{ amount: t.pnl.expenses }} />}
    {tab === "Timeline" && <Table dense cols={[{ key: "at", label: "When", type: "datetime" }, { key: "stage", label: "Stage", type: "badge" }, { key: "note", label: "Note" }, { key: "odometer", label: "Km", type: "number" }]} rows={t.events} />}
    {tab === "FASTag" && <Table dense cols={[{ key: "at", label: "When", type: "datetime" }, { key: "plaza", label: "Plaza" }, { key: "amount", label: "Amount", type: "money" }]} rows={t.fastag} empty="No FASTag debits matched to this trip" />}
    {tab === "Location" && <LocationTab id={id} />}
    {act?.kind === "allocate" && <Modal title="Allocate" onClose={() => setAct(null)} footer={<Btn kind="primary" onClick={async () => { if (await run(() => api.put(`/api/trips/${id}`, act), "Allocated")) { setAct(null); reload(); } }}>Save</Btn>}>
      <Field label="Vehicle"><RefSelect refName="vehicles" value={act.vehicle_id} onChange={(v) => setAct({ ...act, vehicle_id: v })} /></Field>
      <Field label="Driver"><RefSelect refName="drivers" value={act.driver_id} onChange={(v) => setAct({ ...act, driver_id: v })} /></Field>
    </Modal>}
    {act?.kind === "dispatch" && <Modal title="Dispatch vehicle" onClose={() => setAct(null)} footer={<Btn kind="primary" onClick={() => doStage("Dispatched", act)}>Dispatch</Btn>}>
      <Field label="Starting km" required><input type="number" value={act.start_km} onChange={(e) => setAct({ ...act, start_km: e.target.value })} /></Field>
      <Field label="Fuel in tank (litres)"><input type="number" value={act.fuel_opening_litres} onChange={(e) => setAct({ ...act, fuel_opening_litres: e.target.value })} /></Field>
    </Modal>}
    {act?.kind === "deliver" && <Modal title="Delivery" onClose={() => setAct(null)} footer={<Btn kind="primary" onClick={() => doStage("Delivered", act)}>Confirm delivery</Btn>}>
      <Field label="Received by"><input value={act.receiver_name} onChange={(e) => setAct({ ...act, receiver_name: e.target.value })} /></Field>
      <Field label="Delivered at"><input type="datetime-local" value={act.at || ""} onChange={(e) => setAct({ ...act, at: e.target.value })} /></Field>
    </Modal>}
    {act?.kind === "close" && <Modal title="Close trip" onClose={() => setAct(null)} footer={<Btn kind="primary" onClick={() => doStage("Closed", act)}>Close trip</Btn>}>
      <div className="form-grid">
        <Field label="Closing km" required><input type="number" value={act.end_km} onChange={(e) => setAct({ ...act, end_km: e.target.value })} /></Field>
        <Field label="Fuel left (litres)"><input type="number" value={act.fuel_closing_litres} onChange={(e) => setAct({ ...act, fuel_closing_litres: e.target.value })} /></Field>
        <Field label="Waiting hours"><input type="number" value={act.waiting_hours} onChange={(e) => setAct({ ...act, waiting_hours: e.target.value })} /></Field>
        <Field label="Detention days"><input type="number" value={act.detention_days} onChange={(e) => setAct({ ...act, detention_days: e.target.value })} /></Field>
        <Field label="POD still pending – close anyway"><input type="checkbox" checked={!!act.pod_all} onChange={(e) => setAct({ ...act, pod_all: e.target.checked })} /></Field>
      </div>
    </Modal>}
    {act?.kind === "expense" && <Modal title="Trip expense" onClose={() => setAct(null)} footer={<Btn kind="primary" onClick={async () => { if (await run(() => api.post(`/api/trips/${id}/expenses`, act), "Expense recorded & posted")) { setAct(null); reload(); } }}>Save</Btn>}>
      <div className="form-grid">
        <Field label="Date"><input type="date" value={act.expense_date} onChange={(e) => setAct({ ...act, expense_date: e.target.value })} /></Field>
        <Field label="Category"><select value={act.category} onChange={(e) => setAct({ ...act, category: e.target.value })}>{EXP_CATS.map((c) => <option key={c}>{c}</option>)}</select></Field>
        {act.category === "Diesel" ? <>
          <Field label="Litres"><input type="number" value={act.litres || ""} onChange={(e) => setAct({ ...act, litres: e.target.value })} /></Field>
          <Field label="Rate / litre"><input type="number" value={act.rate || ""} onChange={(e) => setAct({ ...act, rate: e.target.value })} /></Field>
          <Field label="Odometer"><input type="number" value={act.odometer || ""} onChange={(e) => setAct({ ...act, odometer: e.target.value })} /></Field>
          <Field label="Full tank"><input type="checkbox" checked={act.full_tank !== false} onChange={(e) => setAct({ ...act, full_tank: e.target.checked })} /></Field>
          <Field label="Fuel station"><RefSelect refName="fuel_stations" value={act.station_id} onChange={(v) => setAct({ ...act, station_id: v })} /></Field>
        </> : <Field label="Amount ₹"><input type="number" value={act.amount || ""} onChange={(e) => setAct({ ...act, amount: e.target.value })} /></Field>}
        <Field label="Paid by"><select value={act.paid_by} onChange={(e) => setAct({ ...act, paid_by: e.target.value })}>{["Driver Cash", "Company Cash", "Bank", "Fuel Card", "FASTag", "Vendor Credit"].map((c) => <option key={c}>{c}</option>)}</select></Field>
        {act.paid_by === "Vendor Credit" && <Field label="Vendor"><RefSelect refName="vendors" value={act.vendor_id} onChange={(v) => setAct({ ...act, vendor_id: v })} /></Field>}
        <Field label="Bill no"><input value={act.bill_no || ""} onChange={(e) => setAct({ ...act, bill_no: e.target.value })} /></Field>
        <Field label="Remarks" wide><input value={act.remarks || ""} onChange={(e) => setAct({ ...act, remarks: e.target.value })} /></Field>
      </div>
    </Modal>}
    {act?.kind === "cancel" && <ReasonModal title="Cancel trip" onClose={() => setAct(null)} onSubmit={async (reason) => { const r = await run(() => api.post(`/api/trips/${id}/cancel`, { reason }), "Trip cancelled"); reload(); return r; }} />}
  </Modal>;
}

function LocationTab({ id }: { id: number }) {
  const { data } = useLoad<any[]>(`/api/trips/${id}/locations`);
  const last = data && data[data.length - 1];
  return <div>
    <p className="muted small">Locations are recorded only from drivers who have given consent in the driver app, and only during an active trip.</p>
    {last && <p>Last position {dt(last.at)}: <a target="_blank" rel="noreferrer" href={`https://www.openstreetmap.org/?mlat=${last.lat}&mlon=${last.lng}#map=12/${last.lat}/${last.lng}`}>{last.lat}, {last.lng} (open map)</a></p>}
    <Table dense cols={[{ key: "at", label: "When", type: "datetime" }, { key: "lat", label: "Lat" }, { key: "lng", label: "Lng" }]} rows={data || []} empty="No location data" />
  </div>;
}

/** Trip progress (%) from its stage – used by the progress bars. */
export function tripProgress(stage: string): number {
  const P: Record<string, number> = { Booked: 0, "Vehicle Allocated": 8, "Driver Allocated": 14, "LR Generated": 22, Loading: 32, Dispatched: 45, "In Transit": 65, Delivered: 85, "POD Collected": 92, Closed: 100, Billed: 100, Settled: 100, Cancelled: 0 };
  return P[stage] ?? 0;
}
const stageTone = (r: any) => (r.stage === "Cancelled" ? "bad" : r.delayed ? "bad" : tripProgress(r.stage) >= 100 ? undefined : "info") as any;

/** Expanded trip row: stops from origin through every LR drop to the destination, plus a mini P&L. */
function TripExpand({ id, onOpen }: { id: number; onOpen: () => void }) {
  const nav = useNavigate();
  const { data: t } = useLoad<any>(`/api/trips/${id}`);
  if (!t) return <div className="trip-exp"><div className="skeleton" style={{ height: 140 }} /><div className="skeleton" style={{ height: 140 }} /></div>;
  const delivered = (s: string) => ["Delivered", "POD Received", "Billed"].includes(s);
  const stops: { name: string; place: string; lines: string[]; done: boolean }[] = [
    { name: "Start", place: t.from_place, lines: [t.dispatched_at ? `Dispatched ${dt(t.dispatched_at)}` : t.planned_departure ? `Planned ${dt(t.planned_departure)}` : "Not dispatched", t.start_km != null ? `Odometer ${num(t.start_km)} km` : ""], done: !!t.dispatched_at },
  ];
  for (const l of t.lrs || []) {
    if (l.status === "Cancelled") continue;
    const points = l.delivery_points?.length ? l.delivery_points : [];
    for (const dp of points) stops.push({ name: `Drop · ${l.lr_no}`, place: dp.consignee_name || "", lines: [dp.address, dp.delivered_at ? `Delivered ${dt(dp.delivered_at)}` : `${dp.packages || ""} pkgs ${dp.status}`], done: dp.status === "Delivered" || !!dp.delivered_at });
    stops.push({ name: `Delivery · ${l.lr_no}`, place: l.consignee_name || l.to_place, lines: [l.to_place, delivered(l.status) ? `Delivered ${dt(l.delivered_at)}` : l.status], done: delivered(l.status) });
  }
  if (!(t.lrs || []).length) stops.push({ name: "Destination", place: t.to_place, lines: [t.expected_delivery_at ? `Expected ${dt(t.expected_delivery_at)}` : ""], done: !!t.delivered_at });
  if (t.closed_at) stops.push({ name: "Closed", place: t.from_place === t.to_place ? t.from_place : "", lines: [dt(t.closed_at), t.end_km != null ? `Odometer ${num(t.end_km)} km` : ""], done: true });
  const curIdx = stops.findIndex((s) => !s.done);
  return <div className="trip-exp">
    <div>
      <div className="actions">
        <Btn small kind="primary" onClick={onOpen}>Open trip</Btn>
        {can("trips:write") && !["Closed", "Billed", "Settled", "Cancelled"].includes(t.stage) && <>
          <Btn small onClick={() => nav(`/lr?new=1&trip_id=${t.id}`)}>+ LR</Btn>
          <Btn small onClick={onOpen}>+ Expense</Btn>
          <Btn small onClick={onOpen}>Update stage</Btn></>}
      </div>
      <div className="stops">
        <div className="stops-h"><Badge v={t.stage} />{t.delayed && <span className="badge solid bad">Delayed</span>}<span className="muted">Planned <b>{t.route_km ? `${num(t.route_km)} km` : "–"}</b> · Actual <b>{t.pnl.km ? `${num(t.pnl.km)} km` : "–"}</b> · {(t.lrs || []).length} LR</span></div>
        <div className="stop-line">{stops.map((s, i) => <div key={i} className={`stop ${s.done ? "done" : ""} ${i === curIdx ? "cur" : ""}`}>
          <span className="dot" /><b>{s.name}</b><small><b style={{ fontSize: 12 }}>{s.place}</b>{s.lines.filter(Boolean).map((x, k) => <span key={k} style={{ display: "block" }}>{x}</span>)}</small>
        </div>)}</div>
      </div>
    </div>
    <div className="mini-pnl">
      <b>Trip P&amp;L</b>
      <div className="row"><span>Revenue</span><b>{inr(t.pnl.revenue)}</b></div>
      <div className="row"><span>Expenses</span><b>{inr(t.pnl.expenses)}</b></div>
      <div className="row"><span>Profit</span><b className={Number(t.pnl.profit) >= 0 ? "good" : "bad"}>{inr(t.pnl.profit)}</b></div>
      <Progress pct={Math.max(0, Number(t.pnl.margin_pct || 0))} label={t.pnl.margin_pct ? `${t.pnl.margin_pct}% margin` : "margin –"} tone={Number(t.pnl.profit) < 0 ? "bad" : undefined} />
      <div className="row"><span>Mileage</span><b>{t.pnl.kmpl ? `${t.pnl.kmpl} km/L` : "–"}</b></div>
      <div className="row"><span>Customer</span><b style={{ textAlign: "right" }}>{t.customer_name}</b></div>
    </div>
  </div>;
}

export default function Trips() {
  const [sp, setSp] = useSearchParams();
  const [q, setQ] = useState("");
  const [stage, setStage] = useState("open");
  const [date, setDate] = useState("");
  const [offset, setOffset] = useState(0);
  const [creating, setCreating] = useState(false);
  const [openRow, setOpenRow] = useState<number | null>(null);
  const stats = useLoad<any>("/api/trips/stats");
  const list = useLoad<any>(`/api/trips${qs({ q, offset, limit: 50, ...(stage === "open" ? { open: 1 } : stage === "delayed" ? { open: 1 } : stage ? { stage } : {}), from: date, to: date })}`);
  const rows = (list.data?.items || []).filter((r: any) => stage !== "delayed" || r.delayed);
  const st = stats.data;
  const pick = (v: string) => { setStage(v); setOffset(0); };
  return <Page title="Trips" actions={can("trips:write") && <Btn kind="primary" onClick={() => setCreating(true)}>+ New trip</Btn>}>
    {st && <div className="kpis four">
      <StatCard icon="route" label="Open trips" value={st.open} onClick={() => pick("open")} foot={<>{st.by_stage["Booked"] || 0} booked · {st.by_stage["Loading"] || 0} loading</>} />
      <StatCard icon="truck" label="On the road" value={st.on_road} tone="info" onClick={() => pick("In Transit")} foot={<>{st.by_stage["Dispatched"] || 0} dispatched · {st.by_stage["In Transit"] || 0} in transit</>} />
      <StatCard icon="clock" label="Delayed" value={st.delayed} tone={st.delayed ? "bad" : "good"} onClick={() => pick("delayed")} foot={st.delayed ? "past expected delivery" : "all on schedule"} />
      <StatCard icon="check" label="Completed this month" value={`${st.month_completed} / ${st.month_total}`} tone="good" foot={<>{st.awaiting_pod} awaiting POD</>} onClick={() => pick("Closed")} />
    </div>}
    <div className="toolbar"><Search value={q} onChange={setQ} placeholder="Trip no, place…" />
      <select value={stage} onChange={(e) => pick(e.target.value)}><option value="open">Open trips</option><option value="delayed">Delayed</option><option value="">All</option>{[...STAGES, "Cancelled"].map((s) => <option key={s}>{s}</option>)}</select>
      <label className="row gap small">Daily trip sheet <input type="date" value={date} onChange={(e) => setDate(e.target.value)} /></label>
      <div className="grow" /><span className="muted small">{list.data?.total ?? ""} trip(s)</span></div>
    <div className="table-wrap"><table className="tbl">
      <thead><tr><th style={{ width: 34 }} /><th>Trip</th><th>Status</th><th>Vehicle</th><th>Driver</th><th>Customer</th><th>Route</th><th>Progress</th><th>Date</th><th>ETA</th></tr></thead>
      <tbody>
        {rows.length === 0 && <tr><td colSpan={10} className="empty">{list.loading ? "Loading…" : "No trips"}</td></tr>}
        {rows.map((r: any) => <React.Fragment key={r.id}>
          <tr className={`click ${openRow === r.id ? "open" : ""}`} onClick={() => setOpenRow(openRow === r.id ? null : r.id)}>
            <td><button className={`chev ${openRow === r.id ? "on" : ""}`} aria-label="Show stops"><Icon name="chevron" size={16} /></button></td>
            <td className="nw"><b>{r.trip_no}</b></td>
            <td>{r.delayed ? <span className="badge solid bad">Delayed</span> : <Badge v={r.stage} />}</td>
            <td className="nw">{r.vehicle_no}</td><td>{r.driver_name}</td><td>{r.customer_name}</td>
            <td>{r.from_place} → {r.to_place}</td>
            <td style={{ minWidth: 120 }}><Progress pct={tripProgress(r.stage)} tone={stageTone(r)} /></td>
            <td className="nw">{dt(r.trip_date)}</td><td className="nw">{r.expected_delivery_at ? dt(r.expected_delivery_at).slice(0, 16) : ""}</td>
          </tr>
          {openRow === r.id && <tr><td colSpan={10} className="exp-cell"><TripExpand id={r.id} onOpen={() => setSp({ id: String(r.id) })} /></td></tr>}
        </React.Fragment>)}
      </tbody>
    </table></div>
    <Pager total={list.data?.total || 0} limit={50} offset={offset} onChange={setOffset} />
    {creating && <NewTrip onClose={() => setCreating(false)} onDone={(t) => { setCreating(false); list.reload(); stats.reload(); setSp({ id: String(t.id) }); }} />}
    {sp.get("id") && <TripDetail id={Number(sp.get("id"))} onClose={() => { setSp({}); list.reload(); stats.reload(); }} />}
  </Page>;
}

export function FleetBoard() {
  const { data } = useLoad<any>("/api/fleet/availability");
  const nav = useNavigate();
  if (!data) return null;
  const groups: Record<string, any[]> = {};
  data.vehicles.forEach((v: any) => (groups[v.status] = groups[v.status] || []).push(v));
  const freeDrivers = data.drivers.filter((d: any) => d.status === "Available").length;
  return <Page title="Fleet board">
    <div className="grid2">
      <Card title="Fleet status"><Donut center={data.vehicles.length} centerSub="vehicles" data={Object.entries(groups).map(([s, vs]) => ({ label: s, value: vs.length, color: ({ Available: "var(--c3)", "On Trip": "var(--c1)", Maintenance: "var(--c2)", Breakdown: "var(--bad)" } as any)[s] }))} /></Card>
      <div className="kpis" style={{ gridTemplateColumns: "repeat(2, minmax(0, 1fr))", alignContent: "start", marginBottom: 0 }}>
        <StatCard icon="truck" label="On trip" value={(groups["On Trip"] || []).length} tone="info" foot={data.vehicles.length ? <>{Math.round(100 * (groups["On Trip"] || []).length / data.vehicles.length)}% utilisation</> : null} />
        <StatCard icon="check" label="Available" value={(groups["Available"] || []).length} tone="good" foot="ready for a trip" />
        <StatCard icon="wrench" label="In workshop" value={(groups["Maintenance"] || []).length + (groups["Breakdown"] || []).length} tone="warn" foot={`${(groups["Breakdown"] || []).length} breakdown`} />
        <StatCard icon="user" label="Drivers free" value={`${freeDrivers} / ${data.drivers.length}`} foot="available drivers" />
      </div>
    </div>
    <div className="board">{data.vehicles.map((v: any) => <div key={v.id} className={`vcard ${v.status.replace(/\s/g, "").toLowerCase()}`} onClick={() => v.trip ? nav(`/trips?id=${v.trip.id}`) : nav("/vehicles")}>
      <b>{v.registration_no}</b><small>{v.vehicle_type}</small><Badge v={v.status} />{v.trip && <small>{v.trip.trip_no} · {v.trip.stage} → {v.trip.to}</small>}
    </div>)}</div>
    <Card title="Drivers"><Table dense cols={[{ key: "name", label: "Driver" }, { key: "mobile", label: "Mobile" }, { key: "status", label: "Status", type: "badge" }, { key: "licence_expiry", label: "Licence expiry", type: "date" }]} rows={data.drivers} /></Card>
  </Page>;
}
