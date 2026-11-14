import { useState } from "react";
import { Route, Routes, useNavigate, useParams } from "react-router-dom";
import { get, post } from "../api";
import { useAuth } from "../auth";
import { enumOpts, opts, useLookup } from "../components/Resource";
import { Badge, Btn, Card, Checks, dt, ErrorBox, Form, inr, Modal, Table, toast, useData } from "../components/ui";

export function Enquiries() {
  const lk = useLookup();
  const { can } = useAuth();
  const { data, reload } = useData(() => get("/enquiries"), []);
  const [creating, setCreating] = useState(false);
  const [quoting, setQuoting] = useState<any>(null);
  const L = lk.data;
  return (
    <Card title="Enquiries" actions={can("crm.write") && <Btn onClick={() => setCreating(true)}>+ Enquiry</Btn>}>
      <Table rows={data} cols={[
        { key: "code", label: "Ref" }, { key: "source", label: "Source" }, { key: "service_type", label: "Type" },
        { key: "prospect_name", label: "Customer/prospect", render: (r: any) => r.prospect_name || L?.customers.find((c: any) => c.id === r.customer_id)?.label || "—" },
        { key: "route", label: "Route", render: (r: any) => `${r.origin_text || L?.locations.find((x: any) => x.id === r.origin_id)?.label || "?"} → ${r.destination_text || L?.locations.find((x: any) => x.id === r.destination_id)?.label || "?"}` },
        { key: "weight_kg", label: "Kg" }, { key: "lead_class", label: "Lead", badge: true },
        { key: "missing_fields", label: "Missing", render: (r: any) => r.missing_fields?.join(", ") || "—" },
        { key: "possible_duplicate_of", label: "Dup?", render: (r: any) => (r.possible_duplicate_of ? <Badge v="warning" /> : "") },
        { key: "status", label: "Status", badge: true }, { key: "created_at", label: "Received", date: true },
        { key: "q", label: "", render: (r: any) => can("quote.write") && <Btn kind="ghost" onClick={() => setQuoting(r)}>Quote</Btn> },
      ]} />
      {creating && L && (
        <Modal title="New enquiry" onClose={() => setCreating(false)}>
          <Form fields={[
            { name: "source", label: "Source", type: "select", options: enumOpts("office", "phone", "whatsapp", "email", "website", "referral"), required: true },
            { name: "customer_id", label: "Existing customer", type: "select", options: opts(L.customers) },
            { name: "prospect_name", label: "Or prospect name" }, { name: "contact_name", label: "Contact" }, { name: "contact_phone", label: "Phone", type: "tel" },
            { name: "service_type", label: "FTL / PTL", type: "select", options: enumOpts("FTL", "PTL"), required: true },
            { name: "service_level", label: "Service level", type: "select", options: enumOpts("standard", "priority", "time_critical") },
            { name: "origin_id", label: "From", type: "select", options: opts(L.locations) }, { name: "destination_id", label: "To", type: "select", options: opts(L.locations) },
            { name: "goods_category_id", label: "Goods category", type: "select", options: opts(L.goods_categories) },
            { name: "goods_description", label: "Goods description" }, { name: "package_count", label: "Packages", type: "number" },
            { name: "weight_kg", label: "Weight (kg)", type: "number" }, { name: "volume_cft", label: "Volume (cft)", type: "number" },
            { name: "declared_value", label: "Declared value ₹", type: "number" }, { name: "pickup_from", label: "Pickup from", type: "datetime-local" },
            { name: "deliver_by", label: "Deliver by", type: "datetime-local" }, { name: "next_action", label: "Next action" },
          ]} initial={{ source: "phone", service_type: "FTL", service_level: "standard" }}
                onSubmit={async (v) => { const e = await post("/enquiries", v); toast(`Enquiry ${e.code} saved`); setCreating(false); reload(); }} />
        </Modal>
      )}
      {quoting && <QuoteModal enquiry={quoting} onClose={() => { setQuoting(null); reload(); }} />}
    </Card>
  );
}

function QuoteModal({ enquiry, onClose }: { enquiry: any; onClose: () => void }) {
  const { can } = useAuth();
  const [res, setRes] = useState<any>(null);
  return (
    <Modal title={`Quotation for ${enquiry.code}`} onClose={onClose}>
      {!res ? (
        <Form fields={[
          { name: "vehicle_option", label: "Vehicle", type: "select", options: enumOpts("own", "attached"), required: true },
          { name: "distance_km", label: "Distance km (blank = lane master)", type: "number" },
          { name: "owner_quote", label: "Owner quote ₹ (attached)", type: "number" }, { name: "negotiated_owner_rate", label: "Negotiated owner rate ₹", type: "number" },
          { name: "market_rate", label: "Market reference ₹", type: "number" },
          { name: "selling_price", label: "Selling price ₹ (blank = suggested)", type: "number" },
          { name: "validity_days", label: "Validity (days)", type: "number" }, { name: "delivery_window", label: "Delivery window" },
          { name: "payment_terms", label: "Payment terms" }, { name: "exclusions", label: "Exclusions", type: "textarea" },
          { name: "reason", label: "Reason (needed if below floor)" },
        ]} initial={{ vehicle_option: "own" }} onSubmit={async (v) => setRes(await post("/quotations", { enquiry_id: enquiry.id, ...v }))} />
      ) : (
        <div className="stack">
          <p>Quotation <b>{res.number} v{res.version}</b> · status <Badge v={res.status} /></p>
          <p>Selling price: <b>{inr(res.selling_price)}</b></p>
          {can("quote.view_cost") && res.internal_cost && (
            <Card title="Internal (never shown to customer)">
              <p>Internal cost {inr(res.internal_cost)} · Floor {inr(res.floor_price)} · Suggested {inr(res.list_price)} · Contribution {inr(res.expected_contribution)} ({res.margin_pct}%)</p>
              <Table rows={res.cost_breakdown?.lines} cols={[{ key: "label", label: "Cost line" }, { key: "amount", label: "₹", money: true }]} />
            </Card>
          )}
          <Btn onClick={onClose}>Done</Btn>
        </div>
      )}
    </Modal>
  );
}

export function Quotations() {
  const { can } = useAuth();
  const { data, reload } = useData(() => get("/quotations"), []);
  const act = async (q: any, what: string) => {
    try {
      if (what === "accept") await post(`/quotations/${q.id}/accept`, { accepted_by: prompt("Accepted by (name)") || "Customer", channel: "office" });
      else await post(`/quotations/${q.id}/${what}`);
      toast("Done"); reload();
    } catch (e: any) { toast(e.message, "red"); }
  };
  return (
    <Card title="Quotations" note={can("quote.view_cost") ? "Internal cost and margin columns are visible to you only." : undefined}>
      <Table rows={data} cols={[
        { key: "number", label: "Number", render: (r: any) => `${r.number} v${r.version}` }, { key: "service_type", label: "Type" },
        { key: "selling_price", label: "Selling", money: true },
        ...(can("quote.view_cost") ? [{ key: "internal_cost", label: "Cost", money: true }, { key: "floor_price", label: "Floor", money: true },
          { key: "margin_pct", label: "Margin %" }, { key: "below_floor", label: "Below floor" }] : []),
        { key: "valid_until", label: "Valid until", date: true }, { key: "status", label: "Status", badge: true },
        { key: "act", label: "", render: (r: any) => can("quote.write") && <div className="row gap">
          {r.status === "approved" && <Btn kind="ghost" onClick={() => act(r, "send")}>Send</Btn>}
          {["approved", "sent"].includes(r.status) && <Btn kind="ghost" onClick={() => act(r, "accept")}>Record acceptance</Btn>}
        </div> },
      ]} />
    </Card>
  );
}

export function Bookings() {
  return (
    <Routes>
      <Route index element={<BookingList />} />
      <Route path=":id" element={<BookingDetail />} />
    </Routes>
  );
}

function BookingList() {
  const { can } = useAuth();
  const nav = useNavigate();
  const lk = useLookup();
  const [status, setStatus] = useState("");
  const { data, reload } = useData(() => get(`/bookings${status ? `?status=${status}` : ""}`), [status]);
  const [creating, setCreating] = useState(false);
  const accepted = useData(() => (can("quote.read") ? get("/quotations") : Promise.resolve([])), []);
  const L = lk.data;
  return (
    <Card title="Bookings" actions={<>
      <select value={status} onChange={(e) => setStatus(e.target.value)}>
        <option value="">All</option>{["draft", "confirmed", "on_hold", "planned", "dispatched", "in_transit", "delivered", "pod_verified", "invoiced", "cancelled"].map((s) => <option key={s}>{s}</option>)}
      </select>
      {can("booking.write") && <Btn onClick={() => setCreating(true)}>+ Booking</Btn>}</>}>
      <Table rows={data} onRow={(r: any) => nav(`/erp/bookings/${r.id}`)} cols={[
        { key: "code", label: "Booking" }, { key: "lr_number", label: "LR" }, { key: "customer_name", label: "Customer" }, { key: "service_type", label: "Type" },
        { key: "route", label: "Route", render: (r: any) => `${r.origin} → ${r.destination}` }, { key: "weight_kg", label: "Kg" },
        { key: "freight_amount", label: "Freight", money: true }, { key: "credit_status", label: "Credit", badge: true }, { key: "status", label: "Status", badge: true },
        { key: "deliver_by", label: "Deliver by", date: true },
      ]} />
      {creating && L && (
        <Modal title="New booking" onClose={() => setCreating(false)}>
          <p className="small muted">Prefer creating bookings from an accepted quotation. Manual bookings need a reason (e.g. contract rate).</p>
          <Form fields={[
            { name: "quotation_id", label: "Accepted quotation", type: "select", options: (accepted.data || []).filter((q: any) => q.status === "accepted").map((q: any) => ({ value: q.id, label: `${q.number} v${q.version} ${inr(q.selling_price)}` })) },
            { name: "customer_id", label: "Customer (manual)", type: "select", options: opts(L.customers) },
            { name: "service_type", label: "FTL/PTL (manual)", type: "select", options: enumOpts("FTL", "PTL") },
            { name: "origin_id", label: "From (manual)", type: "select", options: opts(L.locations) }, { name: "destination_id", label: "To (manual)", type: "select", options: opts(L.locations) },
            { name: "freight_amount", label: "Freight ₹ (manual)", type: "number" }, { name: "manual_price_reason", label: "Manual price reason" },
            { name: "ptl_consent", label: "Customer informed transport is SHARED (PTL)", type: "checkbox" },
            { name: "consignor_name", label: "Consignor", required: true }, { name: "consignee_name", label: "Consignee", required: true },
            { name: "consignee_phone", label: "Consignee phone (for delivery OTP)", type: "tel" }, { name: "consignee_address", label: "Consignee address", type: "textarea" },
            { name: "goods_category_id", label: "Goods category", type: "select", options: opts(L.goods_categories) },
            { name: "goods_description", label: "Goods", required: true }, { name: "package_count", label: "Packages", type: "number" },
            { name: "weight_kg", label: "Weight kg", type: "number", required: true }, { name: "volume_cft", label: "Volume cft", type: "number" },
            { name: "floor_sqft", label: "Floor sqft", type: "number" }, { name: "max_package_length_ft", label: "Longest package ft", type: "number" },
            { name: "declared_value", label: "Declared value ₹", type: "number" }, { name: "fragile", label: "Fragile", type: "checkbox" },
            { name: "pickup_from", label: "Pickup from", type: "datetime-local" }, { name: "deliver_by", label: "Deliver by", type: "datetime-local" },
            { name: "advance_received", label: "Advance received ₹", type: "number" }, { name: "instructions", label: "Instructions", type: "textarea" },
          ]} initial={{ package_count: 1 }} onSubmit={async (v) => { const b = await post("/bookings", v); toast(`Booking ${b.code} created (draft)`); setCreating(false); nav(`/erp/bookings/${b.id}`); }} />
        </Modal>
      )}
    </Card>
  );
}

function BookingDetail() {
  const { id } = useParams();
  const { can } = useAuth();
  const { data: b, reload, error } = useData(() => get(`/bookings/${id}`), [id]);
  const [err, setErr] = useState<any>(null);
  const run = async (fn: () => Promise<any>, msg: string) => { setErr(null); try { await fn(); toast(msg); reload(); } catch (e) { setErr(e); } };
  if (error) return <ErrorBox error={error} />;
  if (!b) return <p>Loading…</p>;
  return (
    <div className="stack">
      <div className="row between"><h2>{b.code} <Badge v={b.status} /> <Badge v={b.service_type} /></h2>
        <div className="row gap">
          {can("booking.write") && ["draft", "on_hold"].includes(b.status) && <Btn onClick={() => run(() => post(`/bookings/${id}/confirm`), "Confirmation attempted - see credit result")}>Confirm</Btn>}
          {can("booking.write") && b.credit_status === "blocked" && <Btn kind="ghost" onClick={() => { const r = prompt("Reason for credit exception"); r && run(() => post(`/bookings/${id}/credit-exception`, { reason: r }), "Exception requested"); }}>Request credit exception</Btn>}
          {can("booking.cancel") && !["cancelled", "dispatched", "in_transit", "delivered", "pod_verified", "invoiced", "closed"].includes(b.status) &&
            <Btn kind="danger" onClick={() => { const r = prompt("Cancellation reason"); r && run(() => post(`/bookings/${id}/cancel`, { reason_code: "CUSTOMER", reason: r }), "Cancelled"); }}>Cancel</Btn>}
        </div>
      </div>
      <ErrorBox error={err} />
      <div className="grid2">
        <Card title="Consignment">
          <dl className="dl">
            <dt>Customer</dt><dd>{b.customer_name}</dd><dt>LR</dt><dd>{b.lr_number || "—"}</dd>
            <dt>Route</dt><dd>{b.origin} → {b.destination}</dd><dt>Consignor</dt><dd>{b.consignor_name}</dd><dt>Consignee</dt><dd>{b.consignee_name} {b.consignee_phone}</dd>
            <dt>Goods</dt><dd>{b.goods_description} · {b.package_count} pkg · {b.weight_kg} kg</dd><dt>Freight</dt><dd>{inr(b.freight_amount)} ({b.gst_mode})</dd>
            <dt>Pickup</dt><dd>{dt(b.pickup_from)}</dd><dt>Deliver by</dt><dd>{dt(b.deliver_by)}</dd><dt>Advance</dt><dd>{inr(b.advance_received)}</dd>
          </dl>
        </Card>
        <Card title="Credit gate">{b.credit ? <>
          <p><Badge v={b.credit.status} /> exposure after booking {inr(b.credit.exposure_after)} / limit {inr(b.credit.limit)}</p>
          <ul>{b.credit.reasons.map((r: string, i: number) => <li key={i}>{r}</li>)}</ul></> : <p className="muted">Not yet checked</p>}
          <h4>Feasibility</h4><p className="small">{b.feasibility.feasible ? `Fits: ${[...b.feasibility.own_vehicles_that_fit, ...b.feasibility.attached_vehicles_that_fit].join(", ")}` : b.feasibility.note}</p>
        </Card>
      </div>
      <Card title={`Packages (${b.packages.length})`} note="Each package has a QR label used for loading and delivery scans.">
        <Table rows={b.packages} cols={[{ key: "label", label: "Label / QR" }, { key: "seq", label: "#" }, { key: "status", label: "Status", badge: true }]} />
      </Card>
      {b.versions.length > 0 && <Card title="Version history"><Table rows={b.versions} cols={[{ key: "version", label: "v" }, { key: "reason", label: "Reason" }, { key: "changed_at", label: "At", date: true }]} /></Card>}
    </div>
  );
}

export { Checks };
