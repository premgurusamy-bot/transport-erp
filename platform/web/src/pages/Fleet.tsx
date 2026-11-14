import { useState } from "react";
import { Route, Routes } from "react-router-dom";
import { get, post } from "../api";
import { useAuth } from "../auth";
import { enumOpts, opts, ResourcePage, useLookup } from "../components/Resource";
import { Badge, Btn, Card, d, dt, Form, inr, Modal, Table, toast, useData } from "../components/ui";
import { SubNav } from "./ErpApp";

export default function Fleet() {
  const { can } = useAuth();
  return (
    <div className="stack">
      <SubNav items={[{ to: "/erp/fleet", label: "Vehicles" }, { to: "/erp/fleet/compliance", label: "Compliance & renewals" },
        { to: "/erp/fleet/defects", label: "Safety defects" }, { to: "/erp/fleet/fuel", label: "Fuel" }, { to: "/erp/fleet/maintenance", label: "Maintenance" },
        { to: "/erp/fleet/tyres", label: "Tyres" }, { to: "/erp/fleet/drivers", label: "Drivers", show: can("driver.read") },
        { to: "/erp/fleet/owners", label: "Owners & offers", show: can("owner.read") }]} />
      <Routes>
        <Route index element={<Vehicles />} />
        <Route path="compliance" element={<Compliance />} />
        <Route path="defects" element={<Defects />} />
        <Route path="fuel" element={<Fuel />} />
        <Route path="maintenance" element={<Maintenance />} />
        <Route path="tyres" element={<ResourcePage title="Tyres & batteries" path="/tyres" canWrite={can("fleet.write")} cols={[
          { key: "serial", label: "Serial" }, { key: "component", label: "Type" }, { key: "brand", label: "Brand" }, { key: "status", label: "Status", badge: true },
          { key: "position", label: "Position" }, { key: "km_run", label: "Km run" }, { key: "tread_mm", label: "Tread mm" }, { key: "cost", label: "Cost", money: true }]}
          fields={[{ name: "serial", label: "Serial", required: true }, { name: "component", label: "Type", type: "select", options: enumOpts("tyre", "battery") },
            { name: "brand", label: "Brand" }, { name: "size", label: "Size" }, { name: "purchase_date", label: "Purchased", type: "date" }, { name: "cost", label: "Cost ₹", type: "number" }]} />} />
        <Route path="drivers" element={<Drivers />} />
        <Route path="owners" element={<Owners />} />
      </Routes>
    </div>
  );
}

function Vehicles() {
  const { can } = useAuth();
  const lk = useLookup();
  return (
    <ResourcePage title="Vehicles" path="/vehicles" canWrite={can("fleet.write")}
      note="Capacity checks use legal payload and actual body dimensions. The initial 3 own vehicles are editable records, not fixed limits."
      cols={[{ key: "registration", label: "Registration" }, { key: "ownership", label: "Fleet" }, { key: "vehicle_class", label: "Class" },
        { key: "payload_kg", label: "Payload kg" }, { key: "dims", label: "Body (ft)", render: (r: any) => `${r.length_ft} × ${r.width_ft}${r.height_ft ? " × " + r.height_ft : ""}` },
        { key: "odometer_km", label: "Odometer" }, { key: "status", label: "Status", badge: true }]}
      fields={[{ name: "registration", label: "Registration", required: true }, { name: "ownership", label: "Own / attached", type: "select", options: enumOpts("own", "attached"), required: true },
        { name: "owner_id", label: "Owner (attached)", type: "select", options: opts(lk.data?.owners) }, { name: "make", label: "Make" }, { name: "model", label: "Model" },
        { name: "body_type", label: "Body", type: "select", options: enumOpts("open", "closed", "container", "flatbed", "trailer") },
        { name: "vehicle_class", label: "Class (licence match)", type: "select", options: enumOpts("LMV", "MGV", "HGV", "TRANS") },
        { name: "payload_kg", label: "Legal payload kg", type: "number", required: true }, { name: "gvw_kg", label: "GVW kg", type: "number" },
        { name: "length_ft", label: "Body length ft", type: "number", required: true }, { name: "width_ft", label: "Body width ft", type: "number", required: true },
        { name: "height_ft", label: "Usable height ft", type: "number" }, { name: "tank_litres", label: "Tank litres", type: "number" },
        { name: "baseline_kmpl", label: "Baseline km/l", type: "number" }, { name: "odometer_km", label: "Odometer", type: "number" },
        { name: "status", label: "Status", type: "select", options: enumOpts("available", "maintenance", "unavailable") },
        { name: "gps_device_id", label: "GPS tracker ID" }, { name: "dvr_device_id", label: "DVR ID" }, { name: "camera_permission", label: "Owner permits camera (attached)", type: "checkbox" },
        { name: "can_enter_godown", label: "Can enter basement godown", type: "checkbox" }]} />
  );
}

function Compliance() {
  const { can } = useAuth();
  const [days, setDays] = useState("60");
  const { data, reload } = useData(() => get(`/compliance${days ? `?due_in_days=${days}` : ""}`), [days]);
  const vehicles = useData(() => get("/vehicles"), []);
  const [adding, setAdding] = useState(false);
  const [quote, setQuote] = useState<any>(null);
  return (
    <Card title="Compliance documents" note="Renewal expenses always need Owner/Director approval." actions={<>
      <select value={days} onChange={(e) => setDays(e.target.value)}><option value="">All current</option><option value="15">Due ≤ 15 days</option><option value="60">Due ≤ 60 days</option></select>
      {can("compliance.write") && <Btn onClick={() => setAdding(true)}>+ Record</Btn>}</>}>
      <Table rows={data} cols={[{ key: "subject_label", label: "Vehicle/driver" }, { key: "kind", label: "Document" }, { key: "number", label: "Number" },
        { key: "valid_to", label: "Valid to", render: (r: any) => d(r.valid_to) }, { key: "days_left", label: "Days left", render: (r: any) => <span className={r.days_left < 0 ? "red" : r.days_left < 15 ? "amber" : ""}>{r.days_left}</span> },
        { key: "verification", label: "Verified", badge: true },
        { key: "r", label: "", render: (r: any) => can("compliance.write") && <Btn kind="ghost" onClick={async () => { const ren = await post("/compliance/renewals", { compliance_item_id: r.id }); setQuote(ren); }}>Start renewal</Btn> }]} />
      {adding && <Modal title="Record compliance document" onClose={() => setAdding(false)}>
        <Form fields={[{ name: "subject_type", label: "For", type: "select", options: enumOpts("vehicle", "driver"), required: true },
          { name: "subject_id", label: "Vehicle", type: "select", options: (vehicles.data || []).map((v: any) => ({ value: v.id, label: v.registration })), required: true },
          { name: "kind", label: "Document", type: "select", options: enumOpts("insurance", "road_tax", "national_permit", "state_permit", "fitness", "puc", "rc", "licence"), required: true },
          { name: "number", label: "Number" }, { name: "valid_from", label: "Valid from", type: "date" }, { name: "valid_to", label: "Valid to", type: "date", required: true }]}
          initial={{ subject_type: "vehicle" }} onSubmit={async (v) => { await post("/compliance", v); toast("Recorded"); setAdding(false); reload(); }} />
      </Modal>}
      {quote && <Modal title={`Renewal ${quote.code}`} onClose={() => setQuote(null)}>
        {quote.status === "initiated" ? <Form fields={[{ name: "quote_amount", label: "Quoted amount ₹", type: "number", required: true }, { name: "reason", label: "Note" }]}
          onSubmit={async (v) => { setQuote(await post(`/compliance/renewals/${quote.id}/quote`, v)); toast("Sent for Owner/Director approval"); }} /> :
          <p>Status <Badge v={quote.status} />. After approval, complete with payment reference and new validity.</p>}
      </Modal>}
    </Card>
  );
}

function Defects() {
  const { can } = useAuth();
  const { data, reload } = useData(() => get("/defects"), []);
  return (
    <Card title="Open safety defects" note="A critical defect blocks dispatch until inspected and released by a different authorised person.">
      <Table rows={data} cols={[{ key: "item", label: "Item" }, { key: "severity", label: "Severity", badge: true }, { key: "description", label: "Notes" },
        { key: "created_at", label: "Reported", date: true },
        { key: "r", label: "", render: (r: any) => can("fleet.release_defect") && <Btn kind="ghost" onClick={async () => {
          const note = prompt("Inspection/repair evidence (required)"); if (!note) return;
          try { await post(`/defects/${r.id}/release`, { note }); toast("Released"); reload(); } catch (e: any) { toast(e.message, "red"); } }}>Release</Btn> }]} empty="No open defects" />
    </Card>
  );
}

function Fuel() {
  const { data, reload } = useData(() => get("/fuel"), []);
  return (
    <Card title="Fuel entries" note="Anomalies trigger human review only - never automatic accusation or deduction.">
      <Table rows={data} cols={[{ key: "filled_at", label: "When", date: true }, { key: "odometer_km", label: "Odometer" }, { key: "litres", label: "Litres" },
        { key: "amount", label: "Amount", money: true }, { key: "computed_kmpl", label: "km/l" }, { key: "station", label: "Station" },
        { key: "anomaly_flags", label: "Flags", render: (r: any) => r.anomaly_flags.join("; ") || "—" }, { key: "review_status", label: "Review", badge: true },
        { key: "r", label: "", render: (r: any) => r.review_status === "needs_review" && <Btn kind="ghost" onClick={async () => {
          const note = prompt("Review outcome"); if (note) { await post(`/fuel/${r.id}/review`, { note }); reload(); } }}>Mark reviewed</Btn> }]} />
    </Card>
  );
}

function Maintenance() {
  const { can } = useAuth();
  const jobs = useData(() => get("/job-cards"), []);
  const due = useData(() => get("/maintenance/due"), []);
  const vehicles = useData(() => get("/vehicles"), []);
  const [adding, setAdding] = useState(false);
  return (
    <div className="stack">
      <Card title="Preventive maintenance due"><Table rows={due.data} cols={[{ key: "vehicle", label: "Vehicle" }, { key: "odometer", label: "Odometer" },
        { key: "due_km", label: "Due km" }, { key: "due_date", label: "Due date", render: (r: any) => d(r.due_date) },
        { key: "overdue", label: "Overdue", render: (r: any) => r.overdue ? <Badge v="overdue" /> : "" }, { key: "note", label: "Note" }]} /></Card>
      <Card title="Job cards" actions={can("fleet.write") && <Btn onClick={() => setAdding(true)}>+ Job card</Btn>}>
        <Table rows={jobs.data} cols={[{ key: "code", label: "Job" }, { key: "kind", label: "Kind" }, { key: "description", label: "Work" },
          { key: "estimate", label: "Estimate", money: true }, { key: "status", label: "Status", badge: true }, { key: "opened_at", label: "Opened", date: true },
          { key: "c", label: "", render: (r: any) => ["approved", "in_progress"].includes(r.status) && <Btn kind="ghost" onClick={async () => {
            const parts = prompt("Parts cost ₹") || "0", labour = prompt("Labour cost ₹") || "0";
            try { await post(`/job-cards/${r.id}/complete`, { parts_cost: Number(parts), labour_cost: Number(labour) }); toast("Completed; expense submitted for review"); jobs.reload(); }
            catch (e: any) { toast(e.message, "red"); } }}>Complete</Btn> }]} />
      </Card>
      {adding && <Modal title="New job card" onClose={() => setAdding(false)}>
        <Form fields={[{ name: "vehicle_id", label: "Vehicle", type: "select", options: (vehicles.data || []).map((v: any) => ({ value: v.id, label: v.registration })), required: true },
          { name: "kind", label: "Kind", type: "select", options: enumOpts("preventive", "breakdown", "repair", "accident"), required: true },
          { name: "description", label: "Work required", type: "textarea", required: true }, { name: "estimate", label: "Estimate ₹", type: "number" }, { name: "odometer_km", label: "Odometer", type: "number" }]}
          onSubmit={async (v) => { await post("/job-cards", v); toast("Saved (approval requested above threshold)"); setAdding(false); jobs.reload(); }} />
      </Modal>}
    </div>
  );
}

function Drivers() {
  const { can } = useAuth();
  const lk = useLookup();
  const [sel, setSel] = useState<any>(null);
  return (
    <div className="stack">
      <ResourcePage title="Drivers" path="/drivers" canWrite={can("driver.write")}
        cols={[{ key: "code", label: "Code" }, { key: "name", label: "Name" }, { key: "phone", label: "Phone" }, { key: "category", label: "Category" },
          { key: "licence_valid_to", label: "Licence to", render: (r: any) => d(r.licence_valid_to) }, { key: "status", label: "Status", badge: true },
          { key: "pay", label: "", render: (r: any) => <Btn kind="ghost" onClick={(e) => { e.stopPropagation(); setSel(r); }}>Pay & rules</Btn> }]}
        fields={[{ name: "name", label: "Name", required: true }, { name: "phone", label: "Mobile (OTP login)", type: "tel", required: true },
          { name: "category", label: "Category", type: "select", options: enumOpts("company", "attached", "temporary"), required: true },
          { name: "owner_id", label: "Owner (attached)", type: "select", options: opts(lk.data?.owners) }, { name: "licence_number", label: "Licence no." },
          { name: "licence_valid_to", label: "Licence valid to", type: "date" }, { name: "experience_years", label: "Experience (yrs)", type: "number" },
          { name: "hazmat_endorsement", label: "Hazardous goods endorsement", type: "checkbox" }]} />
      {sel && <DriverPay driver={sel} onClose={() => setSel(null)} />}
    </div>
  );
}

function DriverPay({ driver, onClose }: { driver: any; onClose: () => void }) {
  const { can } = useAuth();
  const { data, reload } = useData(() => get(`/drivers/${driver.id}/remuneration`), [driver.id]);
  return (
    <Modal title={`${driver.name} - remuneration`} onClose={onClose}>
      <p className="small muted">Rules are versioned and prospective. Only approved rules are used. No unapproved deductions.</p>
      {data && <p>Earned {inr(data.summary.earned)} · Pending approval {inr(data.summary.pending_approval)} · Paid {inr(data.summary.paid)} · Advances {inr(data.summary.advances_outstanding)}</p>}
      <Table rows={data?.rules} cols={[{ key: "component", label: "Component" }, { key: "rate", label: "Rate", money: true }, { key: "effective_from", label: "From" },
        { key: "version", label: "v" }, { key: "status", label: "Status", badge: true }]} />
      {can("remuneration.write") && <Form fields={[{ name: "component", label: "Component", type: "select", required: true,
        options: enumOpts("fixed_monthly", "per_trip", "per_km", "duty_day", "night", "waiting_hour", "incentive_on_time") },
        { name: "rate", label: "Rate ₹", type: "number", required: true }, { name: "effective_from", label: "Effective from", type: "date", required: true },
        { name: "reason", label: "Reason", required: true }]} submitLabel="Propose rule (needs approval)"
        onSubmit={async (v) => { await post("/remuneration-rules", { driver_id: driver.id, ...v }); toast("Sent for approval"); reload(); }} />}
      <h4>Advances</h4>
      <Table rows={data?.advances} cols={[{ key: "created_at", label: "Date", date: true }, { key: "amount", label: "Amount", money: true }, { key: "purpose", label: "Purpose" }, { key: "status", label: "Status", badge: true }]} empty="No advances" />
      {can("settlement.prepare") && <Form fields={[{ name: "amount", label: "Advance ₹", type: "number", required: true }, { name: "purpose", label: "Purpose", required: true }]}
        submitLabel="Request advance (needs approval)" onSubmit={async (v) => { await post("/driver-advances", { driver_id: driver.id, ...v }); toast("Sent for approval"); reload(); }} />}
      <h4>Earnings</h4>
      <Table rows={data?.earnings} cols={[{ key: "created_at", label: "Date", date: true }, { key: "gross", label: "Gross", money: true }, { key: "status", label: "Status", badge: true },
        { key: "b", label: "Calculation", render: (r: any) => r.breakdown.map((l: any) => `${l.component}: ${l.formula}`).join("; ") },
        { key: "s", label: "", render: (r: any) => can("settlement.prepare") && r.status === "calculated" && <Btn kind="ghost" onClick={async () => {
          try { await post(`/driver-earnings/${r.id}/submit`, {}); reload(); } catch (e: any) { toast(e.message, "red"); } }}>Submit</Btn> }]} />
    </Modal>
  );
}

function Owners() {
  const { can } = useAuth();
  const offers = useData(() => get("/owner-offers"), []);
  const lk = useLookup();
  const [adding, setAdding] = useState(false);
  return (
    <div className="stack">
      <ResourcePage title="Vehicle owners" path="/masters/owners" canWrite={can("owner.write")}
        note="Suspension/blacklisting only after authorised review. Owners see only their own records in the owner portal."
        cols={[{ key: "code", label: "Code" }, { key: "name", label: "Name" }, { key: "phone", label: "Phone" }, { key: "kyc_status", label: "KYC", badge: true },
          { key: "status", label: "Status", badge: true }, { key: "tds_declaration_received", label: "194C decl." }]}
        fields={[{ name: "name", label: "Name", required: true }, { name: "phone", label: "Phone", type: "tel" }, { name: "pan", label: "PAN" }, { name: "gstin", label: "GSTIN" },
          { name: "address", label: "Address", type: "textarea" }, { name: "kyc_status", label: "KYC", type: "select", options: enumOpts("pending", "verified", "rejected") },
          { name: "tds_declaration_received", label: "TDS 194C(6) declaration received (verify with CA)", type: "checkbox" }]} />
      <Card title="Load requests to owners" actions={can("owner.write") && <Btn onClick={() => setAdding(true)}>+ Request</Btn>}>
        <Table rows={offers.data} cols={[{ key: "code", label: "Ref" }, { key: "lane", label: "Lane" }, { key: "owner_quote", label: "Owner quote", money: true },
          { key: "negotiated_rate", label: "Negotiated", money: true }, { key: "status", label: "Status", badge: true },
          { key: "n", label: "", render: (r: any) => can("owner.write") && ["quoted", "negotiated"].includes(r.status) && <Btn kind="ghost" onClick={async () => {
            const rate = prompt("Negotiated rate ₹"); const adv = prompt("Advance %", "20"); if (rate) { await post(`/owner-offers/${r.id}/negotiate`, { negotiated_rate: Number(rate), advance_pct: Number(adv || 0) }); offers.reload(); } }}>Negotiate</Btn> }]} />
      </Card>
      {adding && <Modal title="Request vehicle from owner" onClose={() => setAdding(false)}>
        <Form fields={[{ name: "owner_id", label: "Owner", type: "select", options: opts(lk.data?.owners), required: true }, { name: "lane", label: "Lane", required: true },
          { name: "vehicle_requirement", label: "Vehicle requirement" }, { name: "required_on", label: "Required on", type: "datetime-local" }]}
          onSubmit={async (v) => { await post("/owner-offers", v); toast("Request sent (MOCK WhatsApp)"); setAdding(false); offers.reload(); }} />
      </Modal>}
    </div>
  );
}

export { dt };
