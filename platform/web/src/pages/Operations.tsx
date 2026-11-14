import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { get, post } from "../api";
import { useAuth } from "../auth";
import { Badge, Btn, Card, Checks, dt, ErrorBox, inr, Modal, Table, toast, useData } from "../components/ui";

export function DispatchBoard() {
  const nav = useNavigate();
  const { data: bookings, reload } = useData(() => get("/bookings?status=confirmed"), []);
  const vehicles = useData(() => get("/vehicles"), []);
  const [sel, setSel] = useState<string[]>([]);
  const [plan, setPlan] = useState<any>(null);
  const [vehicleId, setVehicleId] = useState("");
  const [proposals, setProposals] = useState<any>(null);
  const toggle = (id: string) => setSel((s) => (s.includes(id) ? s.filter((x) => x !== id) : [...s, id]));
  return (
    <div className="stack">
      <Card title="Confirmed bookings awaiting allocation" note="Select one FTL booking, or several PTL bookings to consolidate.">
        <Table rows={bookings} cols={[
          { key: "s", label: "", render: (r: any) => <input type="checkbox" checked={sel.includes(r.id)} onChange={() => toggle(r.id)} /> },
          { key: "code", label: "Booking" }, { key: "service_type", label: "Type" }, { key: "customer_name", label: "Customer" },
          { key: "route", label: "Route", render: (r: any) => `${r.origin} → ${r.destination}` }, { key: "weight_kg", label: "Kg" },
          { key: "deliver_by", label: "Deliver by", date: true }, { key: "credit_status", label: "Credit", badge: true },
        ]} empty="Nothing to allocate" />
        <div className="row gap">
          <Btn disabled={!sel.length} onClick={() => setPlan({ booking_ids: sel })}>Allocate selected</Btn>
          <select value={vehicleId} onChange={(e) => setVehicleId(e.target.value)}>
            <option value="">Vehicle for PTL proposal…</option>
            {(vehicles.data || []).map((v: any) => <option key={v.id} value={v.id}>{v.registration} ({v.payload_kg} kg, {v.ownership})</option>)}
          </select>
          <Btn kind="ghost" disabled={!vehicleId} onClick={async () => setProposals(await post("/consolidation/proposals", { vehicle_id: vehicleId }))}>PTL consolidation proposals</Btn>
        </div>
      </Card>
      {proposals && (
        <Card title={`PTL proposals for ${proposals.vehicle}`} note="PROVISIONAL - requires operations review and physical loading validation.">
          <Table rows={proposals.proposals} cols={[{ key: "bookings", label: "Bookings", render: (r: any) => r.bookings.join(", ") },
            { key: "weight_utilisation_pct", label: "Weight %" }, { key: "floor_utilisation_pct", label: "Floor %" }, { key: "revenue", label: "Revenue", money: true },
            { key: "use", label: "", render: (r: any) => <Btn kind="ghost" onClick={() => setPlan({ booking_ids: r.booking_ids, vehicle_id: proposals_vehicle(proposals, vehicles.data) })}>Plan trip</Btn> }]} />
          {proposals.rejected.length > 0 && <><h4>Not eligible</h4><ul>{proposals.rejected.map((r: any, i: number) => <li key={i}>{r.booking}: {r.reason}</li>)}</ul></>}
        </Card>
      )}
      {plan && <AllocateModal plan={plan} onClose={() => setPlan(null)} onDone={(t: any) => { setPlan(null); setSel([]); reload(); nav(`/erp/trips/${t.id}`); }} />}
    </div>
  );
}
const proposals_vehicle = (p: any, vs: any[] | null) => (vs || []).find((v) => v.registration === p.vehicle)?.id;

function AllocateModal({ plan, onClose, onDone }: { plan: any; onClose: () => void; onDone: (t: any) => void }) {
  const { can } = useAuth();
  const cands = useData(() => get(`/allocation/candidates/${plan.booking_ids[0]}`), []);
  const drivers = useData(() => get("/drivers"), []);
  const [vehicle, setVehicle] = useState(plan.vehicle_id || "");
  const [driver, setDriver] = useState("");
  const [check, setCheck] = useState<any>(null);
  const [err, setErr] = useState<any>(null);
  const [override, setOverride] = useState("");
  const runCheck = async () => setCheck(await post("/allocation/check", { booking_ids: plan.booking_ids, vehicle_id: vehicle, driver_id: driver || null }));
  return (
    <Modal title="Allocate vehicle and driver" onClose={onClose}>
      <ErrorBox error={err} />
      <p className="small muted">Ranked by checks passed (own fleet first). Legal and safety failures can never be overridden.</p>
      <Table rows={cands.data?.slice(0, 8)} cols={[{ key: "registration", label: "Vehicle" }, { key: "ownership", label: "Fleet" }, { key: "payload_kg", label: "Payload" },
        { key: "driver", label: "Suggested driver" }, { key: "eligible", label: "Eligible", render: (r: any) => <Badge v={r.eligible ? "ok" : "blocked"} /> },
        { key: "pick", label: "", render: (r: any) => <Btn kind="ghost" onClick={() => { setVehicle(r.vehicle_id); setDriver(r.driver_id || ""); setCheck(null); }}>Pick</Btn> }]} />
      <div className="row gap">
        <select value={driver} onChange={(e) => setDriver(e.target.value)}><option value="">Driver…</option>
          {(drivers.data || []).map((d: any) => <option key={d.id} value={d.id}>{d.name} ({d.category}, {d.status})</option>)}</select>
        <Btn kind="ghost" disabled={!vehicle} onClick={runCheck}>Run allocation checks</Btn>
      </div>
      {check && <><Checks checks={check.checks} />
        {check.overridable.length > 0 && can("dispatch.override") && <label>Override reason for: {check.overridable.join(", ")}<input value={override} onChange={(e) => setOverride(e.target.value)} /></label>}
        <Btn disabled={!(check.can_allocate || (check.blocking.length === 0 && override))} onClick={async () => {
          try { onDone(await post("/trips", { booking_ids: plan.booking_ids, vehicle_id: vehicle, driver_id: driver || null,
            ...(override ? { override_checks: check.overridable, override_reason: override } : {}) })); toast("Trip planned"); } catch (e) { setErr(e); }
        }}>Create trip</Btn></>}
    </Modal>
  );
}

export function Trips() {
  const nav = useNavigate();
  const [status, setStatus] = useState("planned,ready,dispatched,in_transit,delivered");
  const { data } = useData(() => get(`/trips?status=${status}`), [status]);
  return (
    <Card title="Trips" actions={<select value={status} onChange={(e) => setStatus(e.target.value)}>
      <option value="planned,ready,dispatched,in_transit,delivered">Open</option><option value="closed">Closed</option><option value="cancelled">Cancelled</option></select>}>
      <Table rows={data} onRow={(r: any) => nav(`/erp/trips/${r.id}`)} cols={[
        { key: "code", label: "Trip" }, { key: "trip_mode", label: "Mode" }, { key: "fleet_type", label: "Fleet" }, { key: "vehicle_registration", label: "Vehicle" },
        { key: "driver_name", label: "Driver" }, { key: "loads", label: "Consignments", render: (r: any) => r.loads.map((l: any) => l.booking_code).join(", ") },
        { key: "status", label: "Status", badge: true }, { key: "last_ping_at", label: "Last GPS", date: true }, { key: "eta", label: "ETA", date: true },
      ]} />
    </Card>
  );
}

export function TripDetail() {
  const { id } = useParams();
  const { can } = useAuth();
  const { data: t, reload, error } = useData(() => get(`/trips/${id}`), [id]);
  const [err, setErr] = useState<any>(null);
  const [profit, setProfit] = useState<any>(null);
  const [stream, setStream] = useState<any>(null);
  const run = async (fn: () => Promise<any>, msg: string) => { setErr(null); try { await fn(); toast(msg); reload(); } catch (e) { setErr(e); } };
  if (error) return <ErrorBox error={error} />;
  if (!t) return <p>Loading…</p>;
  return (
    <div className="stack">
      <div className="row between">
        <h2>{t.code} <Badge v={t.status} /> <Badge v={t.trip_mode} /> <Badge v={t.fleet_type} /></h2>
        <div className="row gap">
          {can("dispatch.authorize") && ["planned", "ready"].includes(t.status) && <Btn onClick={() => { const o = prompt("Start odometer (km)"); run(() => post(`/trips/${id}/dispatch`, { start_odometer: o ? Number(o) : null }), "Dispatched"); }}>Authorise dispatch</Btn>}
          {can("trip.close") && t.status === "delivered" && <Btn onClick={() => { const o = prompt("End odometer (km, own fleet)"); run(() => post(`/trips/${id}/close`, { end_odometer: o ? Number(o) : null }), "Trip closed"); }}>Close trip</Btn>}
          {can("dispatch.plan") && ["planned", "ready"].includes(t.status) && <Btn kind="danger" onClick={() => { const r = prompt("Reason"); r && run(() => post(`/trips/${id}/cancel`, { reason: r }), "Cancelled"); }}>Cancel</Btn>}
          {can("reports.read") && <Btn kind="ghost" onClick={async () => setProfit(await get(`/finance/reports/trip/${id}/profitability`))}>Profitability</Btn>}
          {can("camera.view") && t.fleet_type === "own" && <Btn kind="ghost" onClick={() => run(async () => setStream(await post(`/vehicles/${t.vehicle_id}/camera/2/live`)), "Stream token issued")}>Cargo camera</Btn>}
        </div>
      </div>
      <ErrorBox error={err} />
      <div className="grid2">
        <Card title="Assignment">
          <dl className="dl"><dt>Vehicle</dt><dd>{t.vehicle_registration}</dd><dt>Driver</dt><dd>{t.driver_name} {t.driver_phone}</dd>
            <dt>Planned start</dt><dd>{dt(t.planned_start)}</dd><dt>Dispatched</dt><dd>{dt(t.actual_start)}</dd><dt>ETA</dt><dd>{dt(t.eta)} ({t.eta_source || "—"})</dd>
            <dt>Driver ack / GPS consent</dt><dd>{dt(t.driver_ack_at)} / {dt(t.gps_consent_at)}</dd>
            {t.fleet_type === "attached" && <><dt>Owner hire / advance</dt><dd>{inr(t.owner_hire_amount)} / {inr(t.owner_advance)}</dd></>}
            {t.override && <><dt>Override</dt><dd>{t.override.reason} ({t.override.checks.join(", ")})</dd></>}</dl>
        </Card>
        <Card title="Position" note="Never estimated: stale or unavailable positions are shown as such with the last timestamp.">
          {t.position ? <dl className="dl"><dt>State</dt><dd><Badge v={t.position.state} /></dd><dt>Source</dt><dd>{t.position.source || "—"}</dd>
            <dt>Last fix</dt><dd>{dt(t.position.recorded_at)} ({t.position.age_minutes ?? "—"} min ago)</dd><dt>Lat/Lng</dt><dd>{t.position.lat ?? "—"}, {t.position.lng ?? "—"}</dd></dl> : <p className="muted">No access</p>}
          {stream && <p className="small"><Badge v="MOCK" /> {stream.label} · expires {dt(stream.expires_at)}</p>}
        </Card>
      </div>
      <Card title="Consignments">
        <Table rows={t.loads} cols={[{ key: "booking_code", label: "Booking", render: (r: any) => <Link to={`/erp/bookings/${r.booking_id}`}>{r.booking_code}</Link> },
          { key: "pickup_seq", label: "Pickup #" }, { key: "drop_seq", label: "Drop #" }, { key: "route", label: "Route", render: (r: any) => `${r.origin} → ${r.destination}` },
          { key: "packages", label: "Pkgs" }, { key: "delivered_count", label: "Delivered" }, { key: "status", label: "Status", badge: true },
          { key: "act", label: "", render: (r: any) => <div className="row gap">
            {can("lr.write") && ["planned", "ready"].includes(t.status) && <Btn kind="ghost" onClick={() => run(() => post(`/trips/${id}/eway`, { booking_id: r.booking_id, use_provider: true }), "E-way bill (MOCK) generated")}>E-way</Btn>}
            {can("trip.close") && r.status !== "planned" && r.booking_status === "delivered" && <Btn kind="ghost" onClick={() => run(() => post(`/pod/${r.booking_id}/verify`, { approve: true }), "POD verified")}>Verify POD</Btn>}
          </div> }]} />
      </Card>
      {t.readiness && <Card title="Dispatch readiness"><Checks checks={t.readiness} /></Card>}
      {t.load_plan && <Card title="Loading plan" note={t.load_plan.status}>
        <p className="small">Utilisation: weight {t.load_plan.utilisation.weight_pct}% · floor {t.load_plan.utilisation.floor_pct ?? "—"}% · {t.load_plan.axle}</p>
        <Table rows={t.load_plan.loading_order} cols={[{ key: "booking", label: "Booking" }, { key: "drop_seq", label: "Drop #" }, { key: "position", label: "Position" },
          { key: "weight_kg", label: "Kg" }, { key: "note", label: "Handling" }]} /></Card>}
      <Card title="Events"><Table rows={t.events} cols={[{ key: "occurred_at", label: "Time", date: true }, { key: "event", label: "Event" }, { key: "source", label: "Source" }, { key: "note", label: "Note" }]} /></Card>
      {profit && <Modal title="Trip profitability" onClose={() => setProfit(null)}>
        <dl className="dl"><dt>Revenue</dt><dd>{inr(profit.revenue)} <span className="muted small">{profit.revenue_basis}</span></dd>
          {Object.entries(profit.direct_costs).map(([k, v]) => <><dt key={k}>{k}</dt><dd>{inr(v)}</dd></>)}
          <dt>Gross contribution</dt><dd><b>{inr(profit.gross_contribution)}</b></dd><dt>Allocated fixed</dt><dd>{inr(profit.allocated_fixed)} <span className="muted small">{profit.allocated_fixed_basis}</span></dd>
          <dt>Fully allocated profit</dt><dd>{inr(profit.fully_allocated_profit)}</dd><dt>Revenue/km · cost/km</dt><dd>{profit.revenue_per_km ?? "—"} · {profit.cost_per_km ?? "—"}</dd></dl>
      </Modal>}
    </div>
  );
}
