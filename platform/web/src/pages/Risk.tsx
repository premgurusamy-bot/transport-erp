import { useState } from "react";
import { Route, Routes } from "react-router-dom";
import { get, patch, post } from "../api";
import { useAuth } from "../auth";
import { enumOpts, ResourcePage } from "../components/Resource";
import { Badge, Btn, Card, d, dt, Form, inr, Modal, Table, toast, useData } from "../components/ui";
import { SubNav } from "./ErpApp";

export default function Risk() {
  const { can } = useAuth();
  return (
    <div className="stack">
      <SubNav items={[{ to: "/erp/risk", label: "Complaints" }, { to: "/erp/risk/incidents", label: "Incidents & claims" },
        { to: "/erp/risk/insurance", label: "Insurance", show: can("insurance.read") }, { to: "/erp/risk/legal", label: "Legal (restricted)", show: can("legal.read") }]} />
      <Routes>
        <Route index element={<Complaints />} />
        <Route path="incidents" element={<Incidents />} />
        <Route path="insurance" element={<ResourcePage title="Insurance policies" path="/insurance-policies" canWrite={can("insurance.write")}
          note="Never assume a policy covers an incident: the actual wording, exclusions and endorsements must be checked."
          cols={[{ key: "kind", label: "Type" }, { key: "insurer", label: "Insurer" }, { key: "policy_number", label: "Policy" }, { key: "sum_insured", label: "Sum insured", money: true },
            { key: "deductible", label: "Deductible", money: true }, { key: "valid_to", label: "Valid to", render: (r: any) => d(r.valid_to) }, { key: "wording_verified", label: "Wording checked" }]}
          fields={[{ name: "kind", label: "Type", type: "select", required: true, options: enumOpts("motor_tp", "motor_comprehensive", "git_cargo", "liability", "employee", "attached_vehicle", "special_cargo") },
            { name: "insurer", label: "Insurer", required: true }, { name: "policy_number", label: "Policy no.", required: true }, { name: "sum_insured", label: "Sum insured ₹", type: "number" },
            { name: "premium", label: "Premium ₹", type: "number" }, { name: "deductible", label: "Deductible ₹", type: "number" }, { name: "valid_from", label: "From", type: "date", required: true },
            { name: "valid_to", label: "To", type: "date", required: true }, { name: "notification_deadline_hours", label: "Claim notification deadline (h)", type: "number" },
            { name: "exclusions", label: "Exclusions", type: "textarea" }, { name: "wording_verified", label: "Policy wording verified by a person", type: "checkbox" }]} />} />
        <Route path="legal" element={<Legal />} />
      </Routes>
    </div>
  );
}

function Complaints() {
  const { can } = useAuth();
  const { data, reload } = useData(() => get("/complaints"), []);
  const [sel, setSel] = useState<any>(null);
  return (
    <Card title="Complaints" note="Responses about complaints/claims are held for human approval before sending. AI cannot admit liability or promise compensation.">
      <Table rows={data} onRow={can("complaint.write") ? setSel : undefined} cols={[{ key: "code", label: "Ref" }, { key: "category", label: "Category" }, { key: "priority", label: "Priority", badge: true },
        { key: "description", label: "Description" }, { key: "status", label: "Status", badge: true }, { key: "resolve_due_at", label: "Due", date: true },
        { key: "overdue", label: "", render: (r: any) => r.overdue && <Badge v="overdue" /> }]} />
      {sel && <Modal title={`Complaint ${sel.code}`} onClose={() => setSel(null)}>
        <Form fields={[{ name: "status", label: "Status", type: "select", options: enumOpts("open", "investigating", "awaiting_customer", "resolved", "closed") },
          { name: "root_cause", label: "Root cause", type: "textarea" }, { name: "corrective_action", label: "Corrective action", type: "textarea" },
          { name: "resolution", label: "Resolution", type: "textarea" }, { name: "customer_message", label: "Message to customer (held for approval)", type: "textarea" }]}
          initial={sel} onSubmit={async (v) => { await patch(`/complaints/${sel.id}`, v); toast("Updated"); setSel(null); reload(); }} />
      </Modal>}
    </Card>
  );
}

function Incidents() {
  const { can } = useAuth();
  const inc = useData(() => get("/incidents"), []);
  const claims = useData(() => get("/claims"), []);
  const [adding, setAdding] = useState(false);
  return (
    <div className="stack">
      <Card title="Incident register" actions={can("incident.write") && <Btn onClick={() => setAdding(true)}>+ Incident</Btn>}
            note="Evidence attached to incidents is placed on legal hold automatically.">
        <Table rows={inc.data} cols={[{ key: "code", label: "Ref" }, { key: "kind", label: "Kind" }, { key: "severity", label: "Severity", badge: true },
          { key: "occurred_at", label: "When", date: true }, { key: "description", label: "Description" }, { key: "source", label: "Source" }, { key: "status", label: "Status", badge: true }]} />
      </Card>
      <Card title="Claims" note="Gross loss, insurance receivable, deductible, compensation, recoveries and cash received are tracked separately.">
        <Table rows={claims.data} cols={[{ key: "code", label: "Ref" }, { key: "direction", label: "Direction" }, { key: "gross_loss", label: "Gross loss", money: true },
          { key: "deductible", label: "Deductible", money: true }, { key: "assessed_amount", label: "Assessed", money: true }, { key: "customer_compensation", label: "Compensation", money: true },
          { key: "cash_received", label: "Cash received", money: true }, { key: "notify_deadline", label: "Notify by", date: true }, { key: "status", label: "Status", badge: true }]} />
      </Card>
      {adding && <Modal title="Record incident" onClose={() => setAdding(false)}>
        <Form fields={[{ name: "kind", label: "Kind", type: "select", required: true, options: enumOpts("accident", "injury", "theft", "cargo_damage", "shortage", "fire", "flood", "third_party", "fraud", "cyber", "legal_notice", "breakdown") },
          { name: "severity", label: "Severity", type: "select", options: enumOpts("critical", "high", "medium", "low"), required: true },
          { name: "occurred_at", label: "When", type: "datetime-local", required: true }, { name: "location_text", label: "Where" },
          { name: "description", label: "What happened", type: "textarea", required: true }, { name: "emergency_actions", label: "Emergency actions taken", type: "textarea" },
          { name: "authority_reference", label: "Police / authority ref." }]} onSubmit={async (v) => { await post("/incidents", v); setAdding(false); inc.reload(); }} />
      </Modal>}
    </div>
  );
}

function Legal() {
  const { can } = useAuth();
  const { data, reload } = useData(() => get("/legal-cases"), []);
  const [adding, setAdding] = useState(false);
  return (
    <Card title="Legal cases (privileged - access is audited)" actions={can("legal.write") && <Btn onClick={() => setAdding(true)}>+ Case</Btn>}
          note="AI may flag deadlines but never files responses or gives final legal determinations.">
      <Table rows={data} cols={[{ key: "code", label: "Ref" }, { key: "kind", label: "Kind" }, { key: "title", label: "Matter" }, { key: "forum", label: "Forum" },
        { key: "response_due", label: "Response due", render: (r: any) => d(r.response_due) }, { key: "next_hearing", label: "Next hearing", render: (r: any) => d(r.next_hearing) },
        { key: "exposure", label: "Exposure", money: true }, { key: "status", label: "Status", badge: true }]} />
      {adding && <Modal title="New legal matter" onClose={() => setAdding(false)}>
        <Form fields={[{ name: "kind", label: "Kind", type: "select", required: true, options: enumOpts("notice", "litigation", "arbitration", "consumer", "labour", "tax", "regulatory", "contract") },
          { name: "title", label: "Title", required: true }, { name: "forum", label: "Forum" }, { name: "advocate", label: "Advocate/CA" }, { name: "served_on", label: "Served on", type: "date" },
          { name: "response_due", label: "Response due", type: "date" }, { name: "exposure", label: "Exposure ₹", type: "number" }, { name: "next_action", label: "Next action", type: "textarea" }]}
          onSubmit={async (v) => { await post("/legal-cases", v); setAdding(false); reload(); }} />
      </Modal>}
    </Card>
  );
}
export { dt, inr };
