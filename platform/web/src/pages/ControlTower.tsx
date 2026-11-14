import { useState } from "react";
import { Link } from "react-router-dom";
import { get, post } from "../api";
import { useAuth } from "../auth";
import { Badge, Btn, Card, dt, Kpi, Table, toast, useData } from "../components/ui";

export default function ControlTower() {
  const { can } = useAuth();
  const [view, setView] = useState("owner");
  const ct = useData(() => get(`/control-tower?view=${view}`), [view]);
  const kpis = useData(() => (can("reports.read") ? get("/dashboard/owner") : Promise.resolve({ kpis: [] })), []);
  const plan = useData(() => get("/control-tower/daily-plan"), []);
  const c = ct.data;
  return (
    <div className="stack">
      <div className="row between">
        <h2>Operations Control Tower</h2>
        <div className="row gap">
          <select value={view} onChange={(e) => setView(e.target.value)}>
            {["owner", "operations", "dispatcher", "accounts", "support"].map((v) => <option key={v}>{v}</option>)}
          </select>
          {can("settings.write") && <Btn kind="ghost" onClick={async () => { await post("/jobs/run"); toast("Scheduled checks run"); ct.reload(); }}>Run checks now</Btn>}
          <Btn kind="ghost" onClick={ct.reload}>Refresh</Btn>
        </div>
      </div>
      {c && <p className="small muted">Generated {dt(c.generated_at)} · {c.priority_rule}</p>}
      {kpis.data?.kpis?.length > 0 && <div className="kpis">{kpis.data.kpis.map((k: any) => <Kpi key={k.label} {...k} value={typeof k.value === "string" && /^-?\d+(\.\d+)?$/.test(k.value) && k.label.match(/Revenue|profit|contribution|Receivable|balance/i) ? "₹ " + Number(k.value).toLocaleString("en-IN") : k.value} />)}</div>}
      {c && (
        <div className="kpis">
          <Kpi label="Bookings to plan" value={c.commercial.bookings_to_plan} />
          <Kpi label="Credit holds" value={c.commercial.bookings_on_credit_hold} />
          <Kpi label="Active trips" value={c.operations.active_trips.length} />
          <Kpi label="POD to verify" value={c.operations.pod_pending_verification} />
          <Kpi label="Critical defects" value={c.operations.open_critical_defects} />
          <Kpi label="Compliance expired / due 15d" value={`${c.operations.compliance_expired} / ${c.operations.compliance_due_15d}`} />
          <Kpi label="Approvals pending" value={c.approvals_pending} />
          <Kpi label="Bank unreconciled" value={c.finance.bank_unreconciled} />
          <Kpi label="Open complaints" value={c.customer.open_complaints} />
        </div>
      )}
      {c && (
        <Card title="Live trips" note={c.operations.gps_note}>
          <Table rows={c.operations.active_trips} cols={[
            { key: "trip", label: "Trip", render: (r: any) => <Link to={`/erp/trips/${r.trip_id}`}>{r.trip}</Link> },
            { key: "vehicle", label: "Vehicle" }, { key: "mode", label: "Mode" }, { key: "fleet", label: "Fleet" },
            { key: "gps_state", label: "GPS", badge: true }, { key: "gps_source", label: "Source" }, { key: "last_seen", label: "Last seen", date: true },
            { key: "eta", label: "ETA", render: (r: any) => <>{dt(r.eta)} <span className="muted small">({r.eta_source || "—"})</span></> },
            { key: "delay_minutes", label: "Delay (min)" },
          ]} empty="No trips on the road" />
        </Card>
      )}
      {c && (
        <Card title={`Exceptions (${c.exceptions.length})`} note="Every exception has severity, source, owner, due time and closure reason.">
          <Table rows={c.exceptions} cols={[
            { key: "severity", label: "Severity", badge: true }, { key: "title", label: "Exception" }, { key: "source", label: "Source" },
            { key: "owner_role", label: "Owner" }, { key: "age_hours", label: "Age (h)" },
            { key: "blocking", label: "Blocks", render: (r: any) => (r.blocking ? <Badge v="blocked" /> : "") },
            { key: "act", label: "", render: (r: any) => <Btn kind="ghost" onClick={async () => {
              const reason = prompt("Closure reason (required)"); if (!reason) return;
              try { await post(`/tasks/${r.id}/close`, { reason }); toast("Closed"); ct.reload(); } catch (e: any) { toast(e.message, "red"); }
            }}>Close</Btn> },
          ]} empty="No open exceptions" />
        </Card>
      )}
      {c?.recommendations?.length > 0 && (
        <Card title="Recommendations (advisory)" note="Recommendations never execute anything; an authorised person acts through the normal screens.">
          <Table rows={c.recommendations} cols={[{ key: "title", label: "Recommendation" }, { key: "reasoning", label: "Why" },
            { key: "confidence", label: "Confidence" }, { key: "data_freshness", label: "Data as of", date: true }]} />
        </Card>
      )}
      {plan.data && (
        <Card title="Daily plan">
          <h4>Vehicle / compliance readiness</h4>
          <Table rows={plan.data["2_vehicle_driver_compliance"]} cols={[{ key: "vehicle", label: "Vehicle" }, { key: "status", label: "Status", badge: true },
            { key: "ready", label: "Ready", render: (r: any) => <Badge v={r.ready ? "ok" : "blocked"} /> }, { key: "blocks", label: "Blocks", render: (r: any) => r.blocks.join("; ") }]} />
          <h4>Booking priorities</h4>
          <Table rows={plan.data["3_booking_priorities"]} cols={[{ key: "booking", label: "Booking" }, { key: "service", label: "Service" },
            { key: "level", label: "Level" }, { key: "deliver_by", label: "Deliver by", date: true }, { key: "credit", label: "Credit", badge: true }]} />
        </Card>
      )}
    </div>
  );
}
