import { useState } from "react";
import { Route, Routes } from "react-router-dom";
import { get, post } from "../api";
import { useAuth } from "../auth";
import { enumOpts, opts, ResourcePage, useLookup } from "../components/Resource";
import { Btn, Card, Form, Modal, Table, toast, useData } from "../components/ui";
import { SubNav } from "./ErpApp";

export default function Supply() {
  return (
    <div className="stack">
      <SubNav items={[{ to: "/erp/supply", label: "Vendors" }, { to: "/erp/supply/procurement", label: "Procurement" },
        { to: "/erp/supply/inventory", label: "Inventory" }, { to: "/erp/supply/godown", label: "Godown" }]} />
      <Routes>
        <Route index element={<Vendors />} />
        <Route path="procurement" element={<Procurement />} />
        <Route path="inventory" element={<Inventory />} />
        <Route path="godown" element={<Godown />} />
      </Routes>
    </div>
  );
}

function Vendors() {
  const { can } = useAuth();
  return <ResourcePage title="Vendors" path="/masters/vendors" canWrite={can("vendor.write")}
    note="Only approved vendors can be shortlisted for RFQs. Approval/suspension is done by a procurement approver."
    cols={[{ key: "code", label: "Code" }, { key: "name", label: "Name" }, { key: "categories", label: "Categories", render: (r: any) => (r.categories || []).join(", ") },
      { key: "approval_status", label: "Approval", badge: true }, { key: "score", label: "Score", render: (r: any) => r.score?.overall ?? "—" }]}
    fields={[{ name: "name", label: "Name", required: true }, { name: "phone", label: "Phone", type: "tel" }, { name: "email", label: "Email", type: "email" },
      { name: "gstin", label: "GSTIN" }, { name: "pan", label: "PAN" }, { name: "address", label: "Address", type: "textarea" }]} />;
}

function Procurement() {
  const { can } = useAuth();
  const prs = useData(() => get("/procurement/requests"), []);
  const pos = useData(() => get("/procurement/orders"), []);
  const lk = useLookup();
  const [adding, setAdding] = useState(false);
  const [cmp, setCmp] = useState<any>(null);
  const act = async (fn: () => Promise<any>, m: string) => { try { await fn(); toast(m); prs.reload(); pos.reload(); } catch (e: any) { toast(e.message, "red"); } };
  const approvedVendors = (lk.data?.vendors || []).filter((v: any) => v.approved);
  return (
    <div className="stack">
      <Card title="Purchase requests" note="Request → approved shortlist → RFQ → comparison → approval → PO → receipt → invoice (3-way match) → payment."
            actions={can("procurement.write") && <Btn onClick={() => setAdding(true)}>+ Request</Btn>}>
        <Table rows={prs.data} cols={[{ key: "code", label: "Ref" }, { key: "category", label: "Category" }, { key: "description", label: "Need" },
          { key: "estimated_amount", label: "Estimate", money: true }, { key: "emergency", label: "Emergency" }, { key: "status", label: "Status", badge: true },
          { key: "a", label: "", render: (r: any) => <div className="row gap">
            {r.status === "requested" && <Btn kind="ghost" onClick={() => act(() => post(`/procurement/requests/${r.id}/rfq`, { vendor_ids: approvedVendors.map((v: any) => v.id) }), "RFQ sent to approved vendors")}>Send RFQ</Btn>}
            {["rfq", "quotes_received"].includes(r.status) && <Btn kind="ghost" onClick={async () => setCmp(await get(`/procurement/requests/${r.id}/comparison`))}>Compare</Btn>}
            {r.status === "approved" && <Btn kind="ghost" onClick={() => act(() => post(`/procurement/requests/${r.id}/po`), "PO issued")}>Issue PO</Btn>}
          </div> }]} />
      </Card>
      <Card title="Purchase / work orders">
        <Table rows={pos.data} cols={[{ key: "code", label: "PO" }, { key: "kind", label: "Kind" }, { key: "amount", label: "Amount", money: true }, { key: "status", label: "Status", badge: true },
          { key: "vendor_status_note", label: "Vendor note" },
          { key: "g", label: "", render: (r: any) => ["issued", "accepted", "in_progress"].includes(r.status) && <Btn kind="ghost" onClick={() => {
            const amt = prompt("Accepted amount ₹ (service proof / goods received)"); amt && act(() => post(`/procurement/orders/${r.id}/receipt`, { lines: r.lines.map((l: any) => ({ ...l, qty_received: l.qty, qty_accepted: l.qty })), accepted_amount: Number(amt) }), "Receipt recorded");
          }}>Record receipt</Btn> }]} />
      </Card>
      {adding && <Modal title="Purchase request" onClose={() => setAdding(false)}>
        <Form fields={[{ name: "category", label: "Category", type: "select", required: true, options: enumOpts("repair", "tyre", "hamali", "crane", "godown", "overhead", "other") },
          { name: "description", label: "Description", type: "textarea", required: true }, { name: "estimated_amount", label: "Estimate ₹", type: "number" },
          { name: "emergency", label: "Emergency (retrospective review)", type: "checkbox" }, { name: "emergency_reason", label: "Emergency reason" }]}
          onSubmit={async (v) => { await post("/procurement/requests", v); setAdding(false); prs.reload(); }} />
      </Modal>}
      {cmp && <Modal title={`Quotes for ${cmp.request.code}`} onClose={() => setCmp(null)}>
        <Table rows={cmp.quotes} cols={[{ key: "vendor", label: "Vendor" }, { key: "total", label: "Total", money: true }, { key: "delivery_days", label: "Days" },
          { key: "submitted_via", label: "Via" }, { key: "s", label: "", render: (q: any) => <Btn kind="ghost" onClick={() => {
            const reason = prompt("Selection reason"); reason && act(() => post(`/procurement/requests/${cmp.request.id}/select`, { quote_id: q.id, reason }), "Selected (approval if above threshold)").then(() => setCmp(null));
          }}>Select</Btn> }]} empty="No quotes yet" />
        {can("procurement.write") && <Form fields={[{ name: "vendor_id", label: "Vendor", type: "select", options: opts(approvedVendors), required: true },
          { name: "amount", label: "Amount ₹", type: "number", required: true }, { name: "tax_amount", label: "GST ₹", type: "number" }, { name: "delivery_days", label: "Days", type: "number" }]}
          submitLabel="Add quote received by phone/email" onSubmit={async (v) => { await post(`/procurement/requests/${cmp.request.id}/quotes`, v); setCmp(await get(`/procurement/requests/${cmp.request.id}/comparison`)); }} />}
      </Modal>}
    </div>
  );
}

function Inventory() {
  const { can } = useAuth();
  const [moving, setMoving] = useState<any>(null);
  const vehicles = useData(() => get("/vehicles"), []);
  return (
    <div className="stack">
      <ResourcePage title="Inventory items" path="/inventory-items" canWrite={can("inventory.write")}
        note="Avoid excessive stock: hold only fast-moving items; procure others from approved vendors."
        cols={[{ key: "code", label: "Code" }, { key: "name", label: "Item" }, { key: "category", label: "Category" }, { key: "qty_on_hand", label: "On hand" },
          { key: "min_qty", label: "Min" }, { key: "avg_cost", label: "Avg cost", money: true },
          { key: "m", label: "", render: (r: any) => <Btn kind="ghost" onClick={(e) => { e.stopPropagation(); setMoving(r); }}>Issue / count</Btn> }]}
        fields={[{ name: "name", label: "Item", required: true }, { name: "category", label: "Category", type: "select", options: enumOpts("spare", "tyre", "battery", "lubricant", "packing", "other"), required: true },
          { name: "uom", label: "Unit" }, { name: "min_qty", label: "Min qty", type: "number" }, { name: "max_qty", label: "Max qty", type: "number" }]} />
      {moving && <Modal title={`Stock movement: ${moving.name}`} onClose={() => setMoving(null)}>
        <Form fields={[{ name: "kind", label: "Type", type: "select", options: enumOpts("issue", "return", "damaged", "stocktake", "adjust"), required: true },
          { name: "qty", label: "Quantity", type: "number", required: true }, { name: "counted_qty", label: "Counted qty (stocktake)", type: "number" },
          { name: "vehicle_id", label: "Vehicle (issue)", type: "select", options: (vehicles.data || []).map((v: any) => ({ value: v.id, label: v.registration })) },
          { name: "reason", label: "Reason" }]} initial={{ kind: "issue", qty: 1 }}
          onSubmit={async (v) => { const r = await post("/inventory/movements", { item_id: moving.id, ...v }); toast(r.reorder_alert ? "Saved - below minimum, reorder alert raised" : "Saved"); setMoving(null); }} />
      </Modal>}
    </div>
  );
}

function Godown() {
  const stock = useData(() => get("/godown/stock"), []);
  const fac = useData(() => get("/masters/facilities"), []);
  return (
    <div className="stack">
      <Card title="Facilities" note="Only verified facilities may hold customer goods. The basement godown is NOT verified for commercial use; large lorries are not assumed to access it.">
        <Table rows={fac.data} cols={[{ key: "name", label: "Facility" }, { key: "kind", label: "Kind" }, { key: "area_sqft", label: "Sq ft" },
          { key: "max_vehicle_type", label: "Vehicle access" }, { key: "verified", label: "Verified", render: (r: any) => (r.verified ? "Yes" : "NO") }, { key: "verification_notes", label: "Notes" }]} />
      </Card>
      <Card title="Goods in godown"><Table rows={stock.data} cols={[{ key: "code", label: "GRN" }, { key: "package_count", label: "Pkgs" }, { key: "location", label: "Location" },
        { key: "condition", label: "Condition", badge: true }, { key: "inward_at", label: "In", date: true }]} empty="Nothing in custody" /></Card>
    </div>
  );
}
