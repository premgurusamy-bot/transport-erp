import { useState } from "react";
import { NavLink, Route, Routes, useNavigate, useParams } from "react-router-dom";
import { get, post } from "../api";
import { useAuth } from "../auth";
import { enumOpts, opts } from "../components/Resource";
import { Badge, Btn, Card, d, dt, ErrorBox, Form, inr, Modal, Table, toast, useData } from "../components/ui";
import { AiChat } from "../pages/AiPage";

export function PortalShell({ title, links, children }: { title: string; links: { to: string; label: string }[]; children: React.ReactNode }) {
  const { me, logout } = useAuth();
  const nav = useNavigate();
  return (
    <div className="portal">
      <header className="site-h"><div className="brand">G ROAD LINES · {title}</div>
        <nav className="row gap">{links.map((l) => <NavLink key={l.to} to={l.to} end>{l.label}</NavLink>)}
          <span className="muted small">{me?.name}</span><Btn kind="ghost" onClick={() => { logout(); nav("/login"); }}>Sign out</Btn></nav></header>
      <main className="main">{children}</main>
    </div>
  );
}

export default function CustomerPortal() {
  return (
    <PortalShell title="Customer portal" links={[{ to: "/portal/customer", label: "Bookings" }, { to: "/portal/customer/quotes", label: "Quotes" },
      { to: "/portal/customer/enquiry", label: "New enquiry" }, { to: "/portal/customer/invoices", label: "Invoices" }, { to: "/portal/customer/support", label: "Support" }]}>
      <Routes>
        <Route index element={<MyBookings />} />
        <Route path="bookings/:id" element={<MyBooking />} />
        <Route path="quotes" element={<MyQuotes />} />
        <Route path="enquiry" element={<NewEnquiry />} />
        <Route path="invoices" element={<MyInvoices />} />
        <Route path="support" element={<Support />} />
      </Routes>
    </PortalShell>
  );
}

function MyBookings() {
  const nav = useNavigate();
  const prof = useData(() => get("/portal/customer/profile"), []);
  const { data } = useData(() => get("/portal/customer/bookings"), []);
  return (
    <div className="stack">
      {prof.data && <p>{prof.data.name} · Outstanding {inr(prof.data.outstanding)} · Overdue {inr(prof.data.overdue)}</p>}
      <Card title="My bookings">
        <Table rows={data} onRow={(r: any) => nav(`/portal/customer/bookings/${r.id}`)} cols={[{ key: "code", label: "Booking" }, { key: "lr_number", label: "LR" },
          { key: "service_type", label: "Type" }, { key: "route", label: "Route", render: (r: any) => `${r.origin} → ${r.destination}` }, { key: "status", label: "Status", badge: true },
          { key: "deliver_by", label: "Promised by", date: true }]} />
      </Card>
    </div>
  );
}

function MyBooking() {
  const { id } = useParams();
  const { data: b, error } = useData(() => get(`/portal/customer/bookings/${id}`), [id]);
  const [req, setReq] = useState(false);
  if (error) return <ErrorBox error={error} />;
  if (!b) return <p>Loading…</p>;
  const tr = b.tracking;
  return (
    <div className="stack">
      <h2>{b.code} <Badge v={b.status} /></h2>
      <Card title="Tracking" note={tr?.shared_transport ? "Shared (PTL) transport - only your consignment's details are shown." : undefined}>
        {!tr ? <p className="muted">Not yet dispatched.</p> : <>
          <p>Vehicle {tr.vehicle} · Trip <Badge v={tr.trip_status} /> · ETA {dt(tr.eta)} ({tr.eta_source || "—"})</p>
          {tr.position && <p className="small">Position: <Badge v={tr.position.state} /> last update {dt(tr.position.recorded_at)} {tr.position.age_minutes != null && `(${tr.position.age_minutes} min ago)`}</p>}
          <Table rows={tr.milestones} cols={[{ key: "at", label: "When", date: true }, { key: "event", label: "Milestone" }]} />
        </>}
      </Card>
      {b.pod && <Card title="Proof of delivery"><p>Delivered {b.pod.delivered_count} package(s) to {b.pod.receiver} at {dt(b.pod.delivered_at)} · <Badge v={b.pod.status} /></p></Card>}
      <Card title="Documents"><Table rows={b.documents} cols={[{ key: "type", label: "Type" }, { key: "filename", label: "File" },
        { key: "o", label: "", render: (r: any) => <Btn kind="ghost" onClick={async () => { const l = await get(`/documents/${r.id}/link`); window.open(l.url, "_blank"); }}>Open</Btn> }]} empty="No documents yet" /></Card>
      {!["delivered", "pod_verified", "invoiced", "closed", "cancelled"].includes(b.status) && <Btn kind="ghost" onClick={() => setReq(true)}>Request change / cancellation</Btn>}
      {req && <Modal title="Request change" onClose={() => setReq(false)}>
        <p className="small muted">A change is only a request until we confirm it is authorised and feasible; charges may apply.</p>
        <Form fields={[{ name: "kind", label: "Request", type: "select", options: enumOpts("modify", "cancel"), required: true }, { name: "deliver_by", label: "New delivery date", type: "datetime-local" },
          { name: "consignee_phone", label: "New consignee phone", type: "tel" }, { name: "reason", label: "Reason", type: "textarea", required: true }]}
          onSubmit={async (v) => { const { kind, reason, ...changes } = v; await post(`/portal/customer/bookings/${id}/requests`, { kind, reason, changes }); toast("Request sent"); setReq(false); }} />
      </Modal>}
    </div>
  );
}

function MyQuotes() {
  const { data, reload } = useData(() => get("/portal/customer/quotations"), []);
  const [booking, setBooking] = useState<any>(null);
  const lk = useData(() => Promise.resolve(null), []);
  return (
    <Card title="Quotations">
      <Table rows={data} cols={[{ key: "number", label: "Quote", render: (r: any) => `${r.number} v${r.version}` }, { key: "service_type", label: "Type" },
        { key: "selling_price", label: "Price (excl. GST)", money: true }, { key: "valid_until", label: "Valid until", date: true }, { key: "delivery_window", label: "Delivery" },
        { key: "status", label: "Status", badge: true }, { key: "ptl_disclosure", label: "Notes", render: (r: any) => <span className="small">{r.ptl_disclosure}</span> },
        { key: "a", label: "", render: (r: any) => <div className="row gap">
          {r.status === "sent" && <Btn onClick={async () => { try { await post(`/portal/customer/quotations/${r.id}/accept`); toast("Accepted"); reload(); } catch (e: any) { toast(e.message, "red"); } }}>Accept</Btn>}
          {r.status === "accepted" && <Btn kind="ghost" onClick={() => setBooking(r)}>Book</Btn>}</div> }]} empty="No quotations yet" />
      {booking && <Modal title={`Book against ${booking.number}`} onClose={() => setBooking(null)}>
        <Form fields={[{ name: "consignor_name", label: "Consignor", required: true }, { name: "consignee_name", label: "Consignee", required: true },
          { name: "consignee_phone", label: "Consignee phone (delivery OTP)", type: "tel" }, { name: "consignee_address", label: "Delivery address", type: "textarea" },
          { name: "goods_description", label: "Goods", required: true }, { name: "package_count", label: "Packages", type: "number", required: true },
          { name: "weight_kg", label: "Weight kg", type: "number", required: true }, { name: "declared_value", label: "Declared value ₹", type: "number" },
          { name: "pickup_from", label: "Pickup from", type: "datetime-local" },
          ...(booking.service_type === "PTL" ? [{ name: "ptl_consent", label: "I understand my goods will travel in a SHARED vehicle", type: "checkbox" as const, required: true }] : [])]}
          initial={{ package_count: 1 }} onSubmit={async (v) => { await post("/portal/customer/bookings", { quotation_id: booking.id, ...v }); toast("Booking request created"); setBooking(null); }} />
      </Modal>}
    </Card>
  );
}

function NewEnquiry() {
  const [done, setDone] = useState<any>(null);
  const L = useData(() => get("/public/coverage"), []);
  return (
    <Card title="Request a quotation">
      {done ? <p>Thank you. Enquiry {done.code} received.{done.missing_fields?.length ? ` We may ask about: ${done.missing_fields.join(", ")}.` : ""}</p> :
        <Form fields={[{ name: "service_type", label: "FTL / PTL", type: "select", options: enumOpts("FTL", "PTL"), required: true },
          { name: "origin_text", label: "From", required: true }, { name: "destination_text", label: "To", required: true }, { name: "goods_description", label: "Goods", required: true },
          { name: "package_count", label: "Packages", type: "number" }, { name: "weight_kg", label: "Weight kg", type: "number" }, { name: "declared_value", label: "Declared value ₹", type: "number" },
          { name: "pickup_from", label: "Pickup date", type: "datetime-local" }, { name: "deliver_by", label: "Needed by", type: "datetime-local" }]}
          initial={{ service_type: "FTL" }} onSubmit={async (v) => setDone(await post("/portal/customer/enquiries", { source: "portal", ...v }))} />}
      <p className="small muted">Verified coverage: {(L.data || []).map((c: any) => c.city).join(", ")}</p>
    </Card>
  );
}

function MyInvoices() {
  const inv = useData(() => get("/portal/customer/invoices"), []);
  const st = useData(() => get("/portal/customer/statement"), []);
  return (
    <div className="stack">
      <Card title="Invoices" note="Online payment uses an authorised gateway and is confirmed only by the server (currently MOCK).">
        <Table rows={inv.data} cols={[{ key: "number", label: "Invoice" }, { key: "date", label: "Date", render: (r: any) => d(r.date) }, { key: "due_date", label: "Due", render: (r: any) => d(r.due_date) },
          { key: "total", label: "Total", money: true }, { key: "balance", label: "Balance", money: true }, { key: "status", label: "Status", badge: true },
          { key: "p", label: "", render: (r: any) => Number(r.balance) > 0 && <Btn kind="ghost" onClick={async () => { const o = await post("/portal/customer/pay", { invoice_id: r.id }); toast(`${o.note} Order ${o.order_id}`, "amber"); }}>Pay</Btn> }]} />
      </Card>
      <Card title="Statement of account"><Table rows={st.data?.rows} cols={[{ key: "date", label: "Date" }, { key: "type", label: "Type" }, { key: "ref", label: "Ref" },
        { key: "debit", label: "Debit", money: true }, { key: "credit", label: "Credit", money: true }, { key: "balance", label: "Balance", money: true }]} /></Card>
    </div>
  );
}

function Support() {
  const { data, reload } = useData(() => get("/portal/customer/complaints"), []);
  const bk = useData(() => get("/portal/customer/bookings"), []);
  return (
    <div className="stack">
      <Card title="Raise a complaint">
        <Form fields={[{ name: "category", label: "Category", type: "select", options: enumOpts("delay", "damage", "shortage", "billing", "driver_behaviour", "service_quality", "other"), required: true },
          { name: "booking_id", label: "Booking", type: "select", options: (bk.data || []).map((b: any) => ({ value: b.id, label: b.code })) },
          { name: "description", label: "Describe the issue", type: "textarea", required: true }]}
          onSubmit={async (v) => { const r = await post("/portal/customer/complaints", v); toast(`Complaint ${r.code} raised`); reload(); }} />
      </Card>
      <Card title="My complaints"><Table rows={data} cols={[{ key: "code", label: "Ref" }, { key: "category", label: "Category" }, { key: "status", label: "Status", badge: true },
        { key: "resolution", label: "Resolution" }, { key: "created_at", label: "Raised", date: true }]} /></Card>
      <AiChat app="portal" fixed="customer" />
    </div>
  );
}
export { opts };
