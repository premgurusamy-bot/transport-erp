// Driver web app (also used by attached/temporary drivers with trip-scoped OTP access).
// Safety: large one-tap buttons, parked-use reminder, no typing needed for common events.
// Offline: events are queued on the device and replayed idempotently when back online.
import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api, flushQueue, get, post, queueOffline, readQueue } from "../api";
import { useAuth } from "../auth";
import { Badge, Btn, Card, dt, ErrorBox, inr, Table, toast, useData } from "../components/ui";
import { setLang, t, useLang } from "../i18n";
import { AiChat } from "../pages/AiPage";

const CHECK = ["brakes", "steering", "tyres", "lights", "horn", "wipers", "seat_belt", "fire_extinguisher", "leaks", "load_securing", "mirrors", "documents"];

export default function DriverApp() {
  useLang();
  const { me, logout } = useAuth();
  const nav = useNavigate();
  const trips = useData(() => get("/driver/trips"), []);
  const [sel, setSel] = useState<any>(null);
  const [pending, setPending] = useState(readQueue().length);
  const sync = async () => {
    try { const r = await flushQueue(); setPending(readQueue().length); if (r.applied + r.rejected) toast(`Synced ${r.applied}, rejected ${r.rejected}`, r.rejected ? "amber" : "green"); }
    catch { toast("Still offline - will retry", "amber"); }
  };
  useEffect(() => { const on = () => sync(); window.addEventListener("online", on); return () => window.removeEventListener("online", on); }, []);
  const active = sel || trips.data?.find((x: any) => ["planned", "ready", "dispatched", "in_transit", "delivered"].includes(x.status));
  return (
    <div className="driver">
      <header className="site-h"><div className="brand">GRL Driver</div>
        <div className="row gap"><a onClick={() => setLang("en")}>EN</a><a onClick={() => setLang("ta")}>தமிழ்</a>
          <Btn kind="ghost" onClick={() => { logout(); nav("/login"); }}>{t("action.signOut")}</Btn></div></header>
      <div className="alert alert-amber">{t("driver.parkFirst")}</div>
      {pending > 0 && <div className="alert alert-amber">{pending} event(s) saved offline. <Btn kind="ghost" onClick={sync}>Sync now</Btn></div>}
      <p className="small muted">{me?.name}{me?.scope_trip_id ? " · temporary trip access" : ""}</p>
      <Card title={t("driver.myTrips")}>
        <Table rows={trips.data} onRow={setSel} cols={[{ key: "code", label: "Trip" }, { key: "vehicle_registration", label: "Vehicle" },
          { key: "status", label: "Status", badge: true }, { key: "planned_start", label: "Start", date: true }]} empty="No trips assigned" />
      </Card>
      {active && <TripPanel trip={active} onChange={() => { trips.reload(); setPending(readQueue().length); }} />}
      {!me?.scope_trip_id && <Earnings />}
      <AiChat app="driver" fixed="driver" />
    </div>
  );
}

function useGps(trip: any, enabled: boolean) {
  const last = useRef(0);
  useEffect(() => {
    if (!enabled || !("geolocation" in navigator)) return;
    const id = navigator.geolocation.watchPosition((p) => {
      if (Date.now() - last.current < 120000) return; // every 2 minutes during an authorised trip only
      last.current = Date.now();
      const body = { trip_id: trip.id, lat: p.coords.latitude, lng: p.coords.longitude, recorded_at: new Date(p.timestamp).toISOString(), accuracy_m: p.coords.accuracy, speed_kmph: p.coords.speed ? p.coords.speed * 3.6 : null };
      post("/gps/ping", body).catch(() => queueOffline("gps_ping", { trip_id: trip.id, lat: body.lat, lng: body.lng }));
    }, () => {}, { enableHighAccuracy: true, maximumAge: 60000 });
    return () => navigator.geolocation.clearWatch(id);
  }, [enabled, trip.id]);
}

function TripPanel({ trip, onChange }: { trip: any; onChange: () => void }) {
  const [err, setErr] = useState<any>(null);
  const [check, setCheck] = useState<Record<string, string>>(Object.fromEntries(CHECK.map((c) => [c, "ok"])));
  const [label, setLabel] = useState("");
  const [podFor, setPodFor] = useState<any>(null);
  const onTrip = ["dispatched", "in_transit"].includes(trip.status);
  useGps(trip, onTrip && !!trip.gps_consent_at);
  const act = async (fn: () => Promise<any>, msg: string, offline?: { type: string; payload: any }) => {
    setErr(null);
    try { await fn(); toast(msg); onChange(); }
    catch (e: any) {
      if (offline && (e.status === undefined || e.status >= 500 || !navigator.onLine)) { queueOffline(offline.type, offline.payload); toast("Saved offline", "amber"); onChange(); }
      else setErr(e);
    }
  };
  const ev = (event: string, extra: any = {}) => act(() => post(`/trips/${trip.id}/events`, { event, ...extra }), event.replace(/_/g, " "),
    { type: "trip_event", payload: { trip_id: trip.id, event, ...extra } });
  return (
    <Card title={`${trip.code} · ${trip.vehicle_registration}`}>
      <ErrorBox error={err} />
      <p><Badge v={trip.status} /> {trip.trip_mode === "PTL" ? "Shared load - scan every package" : "Exclusive load"}</p>
      <ol className="small">{trip.loads.map((l: any) => <li key={l.booking_id}>Pickup #{l.pickup_seq} {l.origin} → Drop #{l.drop_seq} {l.destination} · {l.packages} pkg · {l.consignee} {l.consignee_phone}
        {l.instructions && <em> ({l.instructions})</em>}</li>)}</ol>
      {!trip.driver_ack_at && <div className="stack">
        <p className="small">G ROAD LINES will collect your phone location only during this authorised trip.</p>
        <Btn className="big" onClick={() => act(() => post(`/trips/${trip.id}/acknowledge`, { gps_consent: true }), "Trip accepted")}>Accept trip & allow trip GPS</Btn>
      </div>}
      {["planned", "ready"].includes(trip.status) && trip.driver_ack_at && <details open><summary>Pre-trip inspection</summary>
        <div className="grid-form">{CHECK.map((c) => <label key={c} className="row gap"><span>{c.replace(/_/g, " ")}</span>
          <select value={check[c]} onChange={(e) => setCheck({ ...check, [c]: e.target.value })}><option value="ok">OK</option><option value="defect">Defect</option></select></label>)}</div>
        <Btn className="big" onClick={() => act(() => post("/inspections", { vehicle_id: trip.vehicle_id, trip_id: trip.id, kind: "pre_trip", checklist: check }), "Inspection saved",
          { type: "inspection", payload: { vehicle_id: trip.vehicle_id, trip_id: trip.id, kind: "pre_trip", checklist: check } })}>Submit inspection</Btn>
      </details>}
      {["planned", "ready", "dispatched", "in_transit"].includes(trip.status) && <div className="row gap wrap">
        <input placeholder="Package label / QR" value={label} onChange={(e) => setLabel(e.target.value)} />
        <Btn onClick={() => { const cid = crypto.randomUUID(); const stage = onTrip ? "unloaded" : "loaded";
          act(async () => { const r = await post("/scans", { label, trip_id: trip.id, stage, client_event_id: cid }); if (r.result !== "ok") throw { message: `Scan result: ${r.result}` }; }, "Scanned",
            { type: "scan", payload: { label, trip_id: trip.id, stage } }); setLabel(""); }}>Scan</Btn>
      </div>}
      <div className="bigbtns">
        {onTrip && <>
          <Btn className="big" onClick={() => ev("departed")}>Departed</Btn>
          <Btn className="big" onClick={() => ev("arrived_drop")}>Arrived at drop</Btn>
          <Btn className="big" kind="ghost" onClick={() => ev("delay", { delay_minutes: 60, note: "Reported by driver" })}>Delay +1h</Btn>
          <Btn className="big" kind="ghost" onClick={() => ev("rest_start")}>Start rest</Btn>
          <Btn className="big" kind="ghost" onClick={() => ev("rest_end")}>End rest</Btn>
          <Btn className="big" kind="ghost" onClick={() => ev("breakdown", { note: "Breakdown" })}>Breakdown</Btn>
        </>}
        {["planned", "ready"].includes(trip.status) && <Btn className="big" kind="ghost" onClick={() => ev("arrived_pickup")}>Arrived at pickup</Btn>}
        <Btn className="big" kind="danger" onClick={() => {
          if (!confirm("Send SOS to operations? Call 112 for police/ambulance.")) return;
          navigator.geolocation?.getCurrentPosition((p) => ev("sos", { lat: p.coords.latitude, lng: p.coords.longitude, note: "SOS" }), () => ev("sos", { note: "SOS (no location)" }));
        }}>{t("driver.sos")}</Btn>
      </div>
      {onTrip && <div className="stack">
        <h4>Delivery (POD)</h4>
        {trip.loads.filter((l: any) => !["delivered", "partial", "failed"].includes(l.status)).map((l: any) => <Btn key={l.booking_id} kind="ghost" onClick={() => setPodFor(l)}>Deliver {l.booking_code} ({l.destination})</Btn>)}
        {podFor && <Pod trip={trip} load={podFor} onDone={() => { setPodFor(null); onChange(); }} />}
        <h4>Expense</h4>
        <ExpenseQuick trip={trip} onDone={onChange} />
      </div>}
    </Card>
  );
}

function Pod({ trip, load, onDone }: { trip: any; load: any; onDone: () => void }) {
  const [otp, setOtp] = useState("");
  const [count, setCount] = useState(String(load.packages));
  const [receiver, setReceiver] = useState("");
  const [cond, setCond] = useState("good");
  const [err, setErr] = useState<any>(null);
  const [hint, setHint] = useState("");
  return (
    <div className="card">
      <ErrorBox error={err} />
      <Btn kind="ghost" onClick={async () => { try { const r = await post("/pod/otp", { trip_id: trip.id, booking_id: load.booking_id }); setHint(r.dev_otp ? `MOCK SMS OTP (development): ${r.dev_otp}` : "OTP sent to consignee"); } catch (e) { setErr(e); } }}>Send OTP to consignee</Btn>
      {hint && <p className="small">{hint}</p>}
      <div className="grid-form">
        <label><span>OTP from receiver</span><input inputMode="numeric" value={otp} onChange={(e) => setOtp(e.target.value)} /></label>
        <label><span>Packages delivered</span><input type="number" value={count} onChange={(e) => setCount(e.target.value)} /></label>
        <label><span>Receiver name</span><input value={receiver} onChange={(e) => setReceiver(e.target.value)} /></label>
        <label><span>Condition</span><select value={cond} onChange={(e) => setCond(e.target.value)}>{["good", "damaged", "wet", "open", "short"].map((c) => <option key={c}>{c}</option>)}</select></label>
      </div>
      <Btn className="big" disabled={!receiver} onClick={async () => {
        try { await post("/pod", { trip_id: trip.id, booking_id: load.booking_id, delivered_count: Number(count), receiver_name: receiver, otp: otp || null, condition: cond }); toast("POD submitted"); onDone(); }
        catch (e: any) { setErr(e); }
      }}>Submit POD</Btn>
      <p className="small muted">Offline? Take photos and use signature POD; it syncs later (no OTP offline).</p>
    </div>
  );
}

function ExpenseQuick({ trip, onDone }: { trip: any; onDone: () => void }) {
  const [cat, setCat] = useState("toll");
  const [amt, setAmt] = useState("");
  const [file, setFile] = useState<File | null>(null);
  return (
    <div className="row gap wrap">
      <select value={cat} onChange={(e) => setCat(e.target.value)}>{["toll", "parking", "hamali", "loading", "allowance", "repair", "other"].map((c) => <option key={c}>{c}</option>)}</select>
      <input type="number" placeholder="₹" value={amt} onChange={(e) => setAmt(e.target.value)} />
      <input type="file" accept="image/*" capture="environment" onChange={(e) => setFile(e.target.files?.[0] || null)} />
      <Btn disabled={!amt} onClick={async () => {
        const payload: any = { trip_id: trip.id, category: cat, expense_date: new Date().toISOString().slice(0, 10), amount: Number(amt), paid_by: "driver_cash" };
        try {
          if (file) { const f = new FormData(); f.append("file", file); f.append("doc_type", "expense_receipt"); f.append("entity", "trip"); f.append("entity_id", trip.id);
            const doc = await api("/documents", { form: f }); payload.receipt_document_id = doc.id; }
          await post("/finance/expenses", payload); toast("Expense submitted for review"); setAmt(""); onDone();
        } catch { queueOffline("expense", payload); toast("Saved offline", "amber"); onDone(); }
      }}>Add expense</Btn>
    </div>
  );
}

function Earnings() {
  const { data } = useData(() => get("/driver/earnings"), []);
  if (!data) return null;
  return (
    <Card title="My earnings" note="Calculated from your approved pay rules. Disagree? Raise a grievance - a person reviews it.">
      <p>Earned {inr(data.summary.earned)} · Pending approval {inr(data.summary.pending_approval)} · Paid {inr(data.summary.paid)} · Advances {inr(data.summary.advances_outstanding)}</p>
      <Table rows={data.earnings} cols={[{ key: "created_at", label: "Date", date: true }, { key: "gross", label: "Amount", money: true }, { key: "status", label: "Status", badge: true },
        { key: "b", label: "How", render: (r: any) => r.breakdown.map((l: any) => `${l.component}: ${l.formula}`).join("; ") }]} />
      <Btn kind="ghost" onClick={async () => { const d = prompt("Describe the issue"); if (d && d.length >= 5) { await post("/grievances", { topic: "remuneration", description: d }); toast("Grievance raised"); } }}>Raise grievance</Btn>
    </Card>
  );
}
export { dt };
