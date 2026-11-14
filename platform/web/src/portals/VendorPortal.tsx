import { useState } from "react";
import { get, post } from "../api";
import { Badge, Btn, Card, Form, Modal, Table, toast, useData } from "../components/ui";
import { PortalShell } from "./CustomerPortal";

export default function VendorPortal() {
  const { data, reload } = useData(() => get("/portal/vendor/summary"), []);
  const [quote, setQuote] = useState<any>(null);
  const [inv, setInv] = useState<any>(null);
  return (
    <PortalShell title="Vendor portal" links={[{ to: "/portal/vendor", label: "Overview" }]}>
      <div className="stack">
        {data && <p>{data.vendor.name} ({data.vendor.code}) · <Badge v={data.vendor.approval_status} /></p>}
        <Card title="Open RFQs"><Table rows={data?.rfqs} cols={[{ key: "code", label: "RFQ" }, { key: "category", label: "Category" }, { key: "description", label: "Requirement" },
          { key: "q", label: "", render: (r: any) => <Btn kind="ghost" onClick={() => setQuote(r)}>Submit quote</Btn> }]} empty="No open RFQs" /></Card>
        <Card title="Work / purchase orders"><Table rows={data?.orders} cols={[{ key: "code", label: "PO" }, { key: "amount", label: "Amount", money: true }, { key: "status", label: "Status", badge: true },
          { key: "a", label: "", render: (r: any) => <div className="row gap">
            {r.status === "issued" && <Btn kind="ghost" onClick={async () => { await post(`/portal/vendor/orders/${r.id}/status`, { status: "accepted" }); reload(); }}>Accept</Btn>}
            {["accepted", "in_progress"].includes(r.status) && <Btn kind="ghost" onClick={async () => { await post(`/portal/vendor/orders/${r.id}/status`, { status: "completed", note: prompt("Completion note") || "" }); toast("Reported - G ROAD LINES will confirm receipt"); reload(); }}>Report done</Btn>}
            {["completed", "in_progress"].includes(r.status) && <Btn kind="ghost" onClick={() => setInv(r)}>Submit invoice</Btn>}</div> }]} /></Card>
        <Card title="Invoices"><Table rows={data?.invoices} cols={[{ key: "invoice_number", label: "Invoice" }, { key: "amount", label: "Amount", money: true }, { key: "status", label: "Status", badge: true }]} /></Card>
        <Card title="Payments"><Table rows={data?.payments} cols={[{ key: "amount", label: "Amount", money: true }, { key: "status", label: "Status", badge: true }, { key: "reference", label: "UTR" }]} empty="No payments yet" /></Card>
      </div>
      {quote && <Modal title={`Quote for ${quote.code}`} onClose={() => setQuote(null)}>
        <Form fields={[{ name: "amount", label: "Amount ₹ (excl. GST)", type: "number", required: true }, { name: "tax_amount", label: "GST ₹", type: "number" },
          { name: "delivery_days", label: "Delivery days", type: "number" }, { name: "notes", label: "Notes", type: "textarea" }]}
          onSubmit={async (v) => { await post(`/portal/vendor/rfqs/${quote.id}/quote`, v); toast("Quote submitted"); setQuote(null); reload(); }} />
      </Modal>}
      {inv && <Modal title={`Invoice for ${inv.code}`} onClose={() => setInv(null)}>
        <Form fields={[{ name: "invoice_number", label: "Invoice no.", required: true }, { name: "invoice_date", label: "Date", type: "date", required: true },
          { name: "amount", label: "Amount ₹", type: "number", required: true }, { name: "tax_amount", label: "GST ₹", type: "number" }]}
          onSubmit={async (v) => { const r = await post("/portal/vendor/invoices", { po_id: inv.id, ...v }); toast(`Invoice ${r.status}`); setInv(null); reload(); }} />
      </Modal>}
    </PortalShell>
  );
}
