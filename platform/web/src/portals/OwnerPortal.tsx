import { useState } from "react";
import { Route, Routes } from "react-router-dom";
import { get, post } from "../api";
import { Badge, Btn, Card, d, dt, Form, Modal, Table, toast, useData } from "../components/ui";
import { PortalShell } from "./CustomerPortal";

export default function OwnerPortal() {
  return (
    <PortalShell title="Vehicle owner portal" links={[{ to: "/portal/owner", label: "Vehicles" }, { to: "/portal/owner/offers", label: "Load requests" },
      { to: "/portal/owner/trips", label: "Trips" }, { to: "/portal/owner/settlements", label: "Settlements" }]}>
      <Routes>
        <Route index element={<Vehicles />} />
        <Route path="offers" element={<Offers />} />
        <Route path="trips" element={<Trips />} />
        <Route path="settlements" element={<Settlements />} />
      </Routes>
    </PortalShell>
  );
}

function Vehicles() {
  const { data, reload } = useData(() => get("/portal/owner/summary"), []);
  return (
    <div className="stack">
      {data && <p>{data.owner.name} ({data.owner.code}) · KYC <Badge v={data.owner.kyc_status} /> · <Badge v={data.owner.status} /></p>}
      <Card title="My vehicles">
        <Table rows={data?.vehicles} cols={[{ key: "registration", label: "Vehicle" }, { key: "payload_kg", label: "Payload" }, { key: "status", label: "Status", badge: true },
          { key: "documents", label: "Documents", render: (r: any) => r.documents.map((x: any) => `${x.kind} → ${d(x.valid_to)}`).join(" · ") || "None uploaded" },
          { key: "available_from", label: "Available from", date: true },
          { key: "a", label: "", render: (r: any) => <Btn kind="ghost" onClick={async () => { const v = prompt("Available from (YYYY-MM-DD HH:MM)"); if (v) { await post("/portal/owner/availability", { vehicle_id: r.id, available_from: new Date(v).toISOString() }); reload(); } }}>Set availability</Btn> }]} />
      </Card>
    </div>
  );
}

function Offers() {
  const { data, reload } = useData(() => get("/portal/owner/offers"), []);
  const veh = useData(() => get("/portal/owner/summary"), []);
  const [acc, setAcc] = useState<any>(null);
  return (
    <Card title="Load requests from G ROAD LINES">
      <Table rows={data} cols={[{ key: "code", label: "Ref" }, { key: "lane", label: "Lane" }, { key: "vehicle_requirement", label: "Vehicle" }, { key: "required_on", label: "Required", date: true },
        { key: "owner_quote", label: "My quote", money: true }, { key: "negotiated_rate", label: "Agreed rate", money: true }, { key: "advance_pct", label: "Advance %" },
        { key: "status", label: "Status", badge: true },
        { key: "a", label: "", render: (r: any) => <div className="row gap">
          {["requested", "quoted"].includes(r.status) && <Btn kind="ghost" onClick={async () => { const a = prompt("Your quote ₹"); if (a) { await post(`/portal/owner/offers/${r.id}/quote`, { amount: Number(a) }); reload(); } }}>Quote</Btn>}
          {["quoted", "negotiated"].includes(r.status) && <Btn onClick={() => setAcc(r)}>Accept</Btn>}
          {["requested", "quoted", "negotiated"].includes(r.status) && <Btn kind="danger" onClick={async () => { await post(`/portal/owner/offers/${r.id}/decline`); reload(); }}>Decline</Btn>}</div> }]} />
      {acc && <Modal title={`Accept ${acc.code}`} onClose={() => setAcc(null)}>
        <p className="small muted">Confirm the actual vehicle and driver. G ROAD LINES verifies documents before dispatch.</p>
        <Form fields={[{ name: "vehicle_id", label: "Vehicle", type: "select", required: true, options: (veh.data?.vehicles || []).map((v: any) => ({ value: v.id, label: v.registration })) },
          { name: "driver_id", label: "Driver ID (from G ROAD LINES)", required: true }, { name: "confirm_documents_valid", label: "Vehicle and driver documents are valid", type: "checkbox", required: true }]}
          onSubmit={async (v) => { await post(`/portal/owner/offers/${acc.id}/accept`, v); toast("Accepted"); setAcc(null); reload(); }} />
      </Modal>}
    </Card>
  );
}

function Trips() {
  const { data } = useData(() => get("/portal/owner/trips"), []);
  return <Card title="My vehicles' trips"><Table rows={data} cols={[{ key: "code", label: "Trip" }, { key: "vehicle", label: "Vehicle" }, { key: "status", label: "Status", badge: true },
    { key: "hire", label: "Hire", money: true }, { key: "advance", label: "Advance", money: true }, { key: "started", label: "Started", date: true }, { key: "ended", label: "Ended", date: true }]} /></Card>;
}

function Settlements() {
  const { data } = useData(() => get("/portal/owner/settlements"), []);
  return (
    <Card title="Settlements & payments" note="Gross hire − advances − TDS (if applicable) = net payable. No unapproved deductions.">
      <Table rows={data} cols={[{ key: "code", label: "Ref" }, { key: "gross", label: "Gross", money: true }, { key: "advances", label: "Advances", money: true }, { key: "tds", label: "TDS", money: true },
        { key: "net", label: "Net", money: true }, { key: "paid", label: "Paid", money: true }, { key: "status", label: "Status", badge: true },
        { key: "payments", label: "Payments", render: (r: any) => r.payments.map((p: any) => `${p.amount} ${p.status} ${p.reference || ""} ${dt(p.at)}`).join("; ") }]} />
    </Card>
  );
}
